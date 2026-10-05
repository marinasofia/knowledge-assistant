import concurrent.futures

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import reviews
from app.auth import Identity
from app.config import settings
from app.db import run, transaction
from app.ingestion import enqueue, process_one
from app.main import app
from app.seed import seed


@pytest.fixture(scope="module", autouse=True)
def setup():
    settings.dev_auth = True
    seed()
    with transaction() as conn:
        run(
            conn,
            "INSERT INTO users(id,name) VALUES('second-admin','Sam Rivera') ON CONFLICT DO NOTHING",
        )
        run(
            conn,
            """INSERT INTO memberships(user_id,workspace_id,role)
          VALUES('second-admin','northstar','admin') ON CONFLICT DO NOTHING""",
        )


def signed_in(role):
    client = TestClient(app)
    client.headers["origin"] = settings.origin
    assert client.post("/api/auth/development", json={"role": role}).status_code == 200
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf"]
    return client


def find(client, review_id):
    return next(r for r in client.get("/api/reviews").json() if r["id"] == review_id)


def move(client, review_id, action, revision, **body):
    return client.post(
        f"/api/reviews/{review_id}/transitions",
        json={"action": action, "revision": revision, **body},
    )


def new_review(conn=None):
    with transaction("northstar") as conn:
        member = Identity("demo-member", "Jordan Lee", "northstar", "member", "x")
        return reviews.create(conn, member, "Is there a pension match?", "Not in policy.")


def test_member_request_answered_with_cited_policy():
    member, admin = signed_in("member"), signed_in("admin")
    answer = member.post("/api/query", json={"question": "What is the equipment allowance?"})
    message_id = answer.json()["message_id"]
    created = member.post(
        "/api/reviews",
        json={"question": "Equipment allowance?", "note": "Unclear.", "message_id": message_id},
    )
    review_id = created.json()["id"]

    queued = find(admin, review_id)
    assert queued["status"] == "open" and queued["candidate_sources"]
    source_id = queued["candidate_sources"][0]["source_id"]
    assert move(admin, review_id, "claim", 0).json() == {"status": "claimed", "revision": 1}
    answered = move(
        admin, review_id, "answer", 1, resolution="See the allowance.", source_ids=[source_id]
    )
    assert answered.json() == {"status": "answered", "revision": 2}

    seen = find(member, review_id)
    assert seen["status"] == "answered" and seen["resolution"] == "See the allowance."
    assert seen["resolved_by_name"] == "Alex Morgan"
    assert seen["citations"][0]["current"] is True and seen["candidate_sources"] == []


def test_rules_of_the_state_machine():
    member, admin = signed_in("member"), signed_in("admin")
    review_id = new_review()
    assert move(member, review_id, "claim", 0).status_code == 403
    assert move(admin, review_id, "answer", 0, resolution="x").status_code == 409
    assert move(admin, review_id, "claim", 5).status_code == 409
    assert move(admin, review_id, "claim", 0).status_code == 200
    assert move(admin, review_id, "decline", 1).status_code == 422
    assert move(admin, review_id, "release", 1, source_ids=["x"]).status_code == 422
    assert move(admin, review_id, "release", 1).json()["status"] == "open"
    assert move(admin, review_id, "claim", 2).status_code == 200
    declined = move(admin, review_id, "decline", 3, resolution="Policy is silent.")
    assert declined.json()["status"] == "declined"
    assert move(admin, review_id, "claim", 4).status_code == 409


def test_only_the_claiming_reviewer_resolves():
    review_id = new_review()
    first = Identity("demo-admin", "Alex Morgan", "northstar", "admin", "x")
    second = Identity("second-admin", "Sam Rivera", "northstar", "admin", "x")
    with transaction("northstar") as conn:
        reviews.transition(conn, first, review_id, "claim", 0)
    with pytest.raises(HTTPException) as exc, transaction("northstar") as conn:
        reviews.transition(conn, second, review_id, "answer", 1, "Mine now.")
    assert exc.value.status_code == 403


def test_concurrent_claims_have_one_winner():
    review_id = new_review()
    admins = [
        Identity("demo-admin", "Alex Morgan", "northstar", "admin", "x"),
        Identity("second-admin", "Sam Rivera", "northstar", "admin", "x"),
    ]

    def claim(who):
        try:
            with transaction("northstar") as conn:
                reviews.transition(conn, who, review_id, "claim", 0)
            return True
        except HTTPException as exc:
            assert exc.status_code == 409
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, admins)) == [False, True]


def test_cannot_link_another_users_message():
    admin, member = signed_in("admin"), signed_in("member")
    message_id = admin.post("/api/query", json={"question": "equipment allowance"}).json()[
        "message_id"
    ]
    linked = member.post(
        "/api/reviews", json={"question": "Whose?", "note": "", "message_id": message_id}
    )
    assert linked.status_code == 404


def test_citation_keeps_provenance_after_policy_replacement():
    admin = signed_in("admin")
    with transaction("northstar") as conn:
        doc = enqueue(conn, "northstar", "Provenance", "p.md", b"# Rule\nProvenance passage one.")
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        chunk = run(conn, "SELECT id FROM chunks WHERE version_id=:v", v=doc["version_id"]).scalar()
    review_id = new_review()
    move(admin, review_id, "claim", 0)
    move(admin, review_id, "answer", 1, resolution="Per the rule.", source_ids=[chunk])
    with transaction("northstar") as conn:
        enqueue(
            conn, "northstar", "Provenance", "p.md", b"# Rule\nProvenance passage two.", doc["id"]
        )
    while process_one("northstar"):
        pass

    citation = find(admin, review_id)["citations"][0]
    assert citation["current"] is False and citation["version"] == 1
    assert citation["quote"] == "Provenance passage one." and citation["section"] == "Rule"
    with transaction("northstar") as conn:
        run(conn, "UPDATE documents SET deleted=true WHERE id=:i", i=doc["id"])


def answered_about(admin, body, publish=False, question="Is there a pension match?"):
    """Upload a one-section policy, then answer a new review citing its passage."""
    with transaction("northstar") as conn:
        doc = enqueue(conn, "northstar", "Pension " + body[:12], "p.md", body.encode())
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        chunk = run(
            conn, "SELECT id FROM chunks WHERE version_id=:v ORDER BY ordinal", v=doc["version_id"]
        ).scalar()
        member = Identity("demo-member", "Jordan Lee", "northstar", "member", "x")
        review_id = reviews.create(conn, member, question, "")
    move(admin, review_id, "claim", 0)
    move(
        admin,
        review_id,
        "answer",
        1,
        resolution="Covered by the pension rule.",
        source_ids=[chunk],
        publish=publish,
    )
    return doc, review_id


def replace_with(doc, body):
    with transaction("northstar") as conn:
        enqueue(conn, "northstar", "Pension", "p.md", body.encode(), doc["id"])
    while process_one("northstar"):
        pass


def delete(doc):
    with transaction("northstar") as conn:
        run(conn, "UPDATE documents SET deleted=true WHERE id=:i", i=doc["id"])


def test_answer_outdated_when_quoted_text_changes():
    admin = signed_in("admin")
    doc, review_id = answered_about(admin, "# Pension\nThe match is three percent.")
    replace_with(doc, "# Pension\nThe match is five percent.")
    review = find(admin, review_id)
    assert review["status"] == "outdated"
    assert review["resolution"] == "Covered by the pension rule."
    assert [e["action"] for e in review["history"]] == ["create", "claim", "answer", "outdate"]
    assert review["history"][-1]["actor_name"] is None

    assert move(admin, review_id, "claim", review["revision"]).status_code == 200
    with transaction("northstar") as conn:
        chunk = run(
            conn,
            """SELECT c.id FROM chunks c JOIN documents d ON d.active_version=c.version_id
          WHERE d.id=:d""",
            d=doc["id"],
        ).scalar()
    move(
        admin,
        review_id,
        "answer",
        review["revision"] + 1,
        resolution="Now five percent.",
        source_ids=[chunk],
    )
    review = find(admin, review_id)
    assert review["status"] == "answered" and len(review["citations"]) == 1
    assert review["citations"][0]["quote"] == "The match is five percent."
    delete(doc)


def test_answer_kept_when_other_sections_change():
    admin = signed_in("admin")
    doc, review_id = answered_about(admin, "# Pension\nThe match is two percent.")
    replace_with(doc, "# Pension\nThe match is two percent.\n# Parking\nParking is free.")
    assert find(admin, review_id)["status"] == "answered"
    delete(doc)


def test_deleting_cited_document_outdates_answer():
    admin = signed_in("admin")
    doc, review_id = answered_about(admin, "# Pension\nThe match is one percent.")
    admin.delete("/api/documents/" + doc["id"])
    assert find(admin, review_id)["status"] == "outdated"


def test_published_answers_offered_to_later_askers():
    admin, member = signed_in("admin"), signed_in("member")
    question = "Is there a pension contribution match for contractors?"
    doc, published = answered_about(
        admin, "# Pension\nContractors get no match.", publish=True, question=question
    )
    private_doc, private = answered_about(
        admin, "# Pension\nContractors are excluded.", publish=False, question=question
    )
    offered = member.post("/api/query", json={"question": question}).json()["reviewed_answers"]
    ids = [a["review_id"] for a in offered]
    assert published in ids and private not in ids
    assert offered[ids.index(published)]["citations"][0]["current"] is True

    unrelated = member.post("/api/query", json={"question": "Who approves annual leave?"})
    assert published not in [a["review_id"] for a in unrelated.json()["reviewed_answers"]]

    replace_with(doc, "# Pension\nContractors now get a match.")
    after = member.post("/api/query", json={"question": question}).json()["reviewed_answers"]
    assert published not in [a["review_id"] for a in after]
    delete(doc)
    delete(private_doc)


def test_review_history_is_append_only():
    review_id = new_review()
    with pytest.raises(Exception) as exc, transaction("northstar") as conn:
        run(conn, "UPDATE review_events SET action='forged' WHERE review_id=:r", r=review_id)
    assert "permission denied" in str(exc.value)
