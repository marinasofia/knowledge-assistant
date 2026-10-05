import concurrent.futures
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.answers import Answer, Reference, admit, generate, reserve_usage, validate_answer
from app.auth import Identity
from app.config import settings
from app.db import run, transaction
from app.ingestion import cleanup, enqueue, process_one, split_passages, validate_file
from app.main import app
from app.seed import seed


@pytest.fixture(scope="module", autouse=True)
def setup():
    settings.dev_auth = True
    settings.user_daily_limit = 1000
    settings.workspace_daily_limit = 1000
    settings.daily_limit = 2000
    seed()


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers["origin"] = settings.origin
        c.headers["X-Workspace-ID"] = "northstar"
        assert c.post("/api/auth/development", json={"role": "admin"}).status_code == 200
        c.headers["X-CSRF-Token"] = c.get("/api/session").json()["csrf"]
        yield c


def test_runtime_rls_and_pool_context():
    with transaction() as conn:
        assert run(conn, "SELECT count(*) FROM documents").scalar() == 0
        row = run(
            conn, "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).one()
        assert not row.rolsuper and not row.rolbypassrls
    with transaction("northstar") as conn:
        assert run(conn, "SELECT count(*) FROM documents").scalar() >= 6
    with transaction() as conn:
        assert run(conn, "SELECT count(*) FROM documents").scalar() == 0


def test_cross_workspace_insert_blocked():
    with pytest.raises(DBAPIError), transaction("northstar") as conn:
        run(conn, "INSERT INTO documents(id,workspace_id,title) VALUES('attack','other','Secret')")


def test_anonymous_denied():
    with TestClient(app) as c:
        for route in [
            "/api/documents",
            "/api/conversations",
            "/api/reviews",
            "/api/settings",
            "/api/sources/fake",
        ]:
            assert c.get(route).status_code == 401


def test_workspace_spoof_and_csrf(client):
    assert client.get("/api/documents", headers={"X-Workspace-ID": "other"}).status_code == 404
    assert (
        client.post(
            "/api/query", json={"question": "equipment"}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/query", json={"question": "equipment"}, headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )


def test_member_cannot_manage(client):
    client.post("/api/auth/development", json={"role": "member"})
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf"]
    assert client.post("/api/documents", files={"file": ("x.txt", b"policy")}).status_code == 403
    assert client.delete("/api/documents/fake").status_code == 403
    claim = {"action": "claim", "revision": 0}
    assert client.post("/api/reviews/fake/transitions", json=claim).status_code == 403


def test_upload_answer_source_and_delete(client):
    marker = "orchid" + uuid4().hex
    response = client.post(
        "/api/documents",
        files={"file": ("Policy.md", f"# Supplies\nThe {marker} allowance is $42.".encode())},
    )
    assert response.status_code == 202, response.text
    document = response.json()["id"]
    while process_one("northstar"):
        pass
    response = client.post("/api/query", json={"question": marker})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["status"] == "answer"
    citation = answer["citations"][0]
    assert "$42" in citation["quote"]
    assert client.get("/api/sources/" + citation["source_id"]).status_code == 200
    assert client.delete("/api/documents/" + document).status_code == 200
    assert client.get("/api/sources/" + citation["source_id"]).status_code == 404
    assert client.post("/api/query", json={"question": marker}).json()["status"] == "abstain"


def test_atomic_replacement_and_deleted_queue(client):
    doc = client.post(
        "/api/documents", files={"file": ("Policy.txt", b"oldzephyr wording")}
    ).json()["id"]
    while process_one("northstar"):
        pass
    old = client.post("/api/query", json={"question": "oldzephyr"}).json()["citations"][0][
        "source_id"
    ]
    client.post(
        "/api/documents/" + doc + "/versions", files={"file": ("new.txt", b"newzephyr wording")}
    )
    assert client.get("/api/sources/" + old).status_code == 200
    while process_one("northstar"):
        pass
    assert client.get("/api/sources/" + old).status_code == 404
    client.post(
        "/api/documents/" + doc + "/versions", files={"file": ("new.txt", b"queueddeleted wording")}
    )
    client.delete("/api/documents/" + doc)
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        assert run(conn, "SELECT active_version FROM documents WHERE id=:i", i=doc).scalar() is None


def test_explicit_review_and_private_conversation(client):
    answer = client.post("/api/query", json={"question": "equipment allowance"}).json()
    before = len(client.get("/api/reviews").json())
    assert (
        client.post(
            "/api/messages/" + answer["message_id"] + "/feedback", json={"helpful": True}
        ).status_code
        == 200
    )
    assert len(client.get("/api/reviews").json()) == before
    review = client.post(
        "/api/reviews", json={"question": "Contractor eligibility?", "note": "Please clarify."}
    )
    assert review.status_code == 201
    claimed = client.post(
        "/api/reviews/" + review.json()["id"] + "/transitions",
        json={"action": "claim", "revision": 0},
    )
    assert claimed.status_code == 200
    client.post("/api/auth/development", json={"role": "member"})
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf"]
    assert client.get("/api/conversations/" + answer["conversation_id"]).status_code == 404
    assert (
        client.post(
            "/api/query",
            json={"question": "equipment", "conversation_id": answer["conversation_id"]},
        ).status_code
        == 404
    )


def test_invented_citations_rejected():
    evidence = [{"source_id": "allowed", "content": "approved words"}]
    for ref in [
        Reference(source_id="invented", quote="approved"),
        Reference(source_id="allowed", quote="fabricated"),
    ]:
        with pytest.raises(ValueError):
            validate_answer(
                Answer(status="answer", text="Claim", citations=[ref], gaps=[]), evidence
            )


def test_evidence_mode_abstains_below_coverage():
    weak = [{"source_id": "s1", "content": "Company laptops are encrypted.", "coverage": 0.25}]
    answer = validate_answer(generate("Does the company offer dental insurance?", weak), weak)
    assert answer.status == "abstain" and answer.citations and answer.gaps
    strong = [{"source_id": "s1", "content": "The equipment allowance is $500.", "coverage": 1.0}]
    assert generate("What is the equipment allowance?", strong).status == "answer"


def test_query_abstains_on_unanswerable_question(client):
    def status(question):
        return client.post("/api/query", json={"question": question}).json()["status"]

    assert status("What is the equipment allowance?") == "answer"
    assert status("Does the company offer dental insurance?") == "abstain"


@pytest.mark.parametrize(
    "name,data",
    [
        ("x.pdf", b"%PDF"),
        ("x.txt", b"\x00binary"),
        ("x.md", b"\xff"),
        ("x.txt", b" "),
        ("x.txt", b"a" * 500001),
    ],
)
def test_adversarial_uploads(name, data):
    with pytest.raises(HTTPException):
        validate_file(name, data)


def test_provenance():
    passages = split_passages("# Travel\nMeal allowance.\n# Equipment\nDesk allowance.")
    assert [(p.section, p.text) for p in passages] == [
        ("Travel", "Meal allowance."),
        ("Equipment", "Desk allowance."),
    ]


def test_concurrent_cap(monkeypatch):
    who = Identity("cap-" + uuid4().hex, "Cap test", "northstar", "member", "x")
    monkeypatch.setattr(settings, "user_daily_limit", 3)

    def reserve(_):
        try:
            reserve_usage(who)
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(12))) == 3


def test_kill_switch(client, monkeypatch):
    monkeypatch.setattr(settings, "generation_enabled", False)
    assert client.post("/api/query", json={"question": "equipment"}).status_code == 503
    assert client.get("/api/documents").status_code == 200


def test_evidence_mode_skips_paid_quota(client, monkeypatch):
    monkeypatch.setattr(settings, "user_daily_limit", 2)
    statuses = [
        client.post("/api/query", json={"question": "equipment allowance"}).status_code
        for _ in range(4)
    ]
    assert statuses == [200] * 4


def test_provider_mode_enforces_paid_quota(monkeypatch):
    who = Identity("quota-" + uuid4().hex, "Quota test", "northstar", "member", "x")
    monkeypatch.setattr(settings, "generation_mode", "anthropic")
    monkeypatch.setattr(settings, "user_daily_limit", 1)
    admit(who)
    with pytest.raises(HTTPException) as exc:
        admit(who)
    assert exc.value.status_code == 429


def test_slow_question_does_not_block_other_requests(monkeypatch):
    import asyncio
    import time

    import httpx

    import app.main as main_module

    real_retrieve = main_module.retrieve

    def slow_retrieve(conn, question):
        time.sleep(1.0)
        return real_retrieve(conn, question)

    monkeypatch.setattr(main_module, "retrieve", slow_retrieve)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.headers["origin"] = settings.origin
            await c.post("/api/auth/development", json={"role": "member"})
            c.headers["X-CSRF-Token"] = (await c.get("/api/session")).json()["csrf"]
            started = time.monotonic()
            slow = asyncio.create_task(c.post("/api/query", json={"question": "equipment"}))
            await asyncio.sleep(0.2)
            assert (await c.get("/api/health/live")).status_code == 200
            elapsed = time.monotonic() - started
            assert (await slow).status_code == 200
            return elapsed

    # A blocked event loop would delay the health check until the slow retrieval ends.
    assert asyncio.run(scenario()) < 0.8


def test_cleanup_runs_once_per_deleted_version(monkeypatch):
    import app.ingestion as ingestion

    with transaction("northstar") as conn:
        result = enqueue(conn, "northstar", "Cleanup once", "x.txt", b"cleanup once")
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        run(conn, "UPDATE documents SET deleted=true WHERE id=:i", i=result["id"])
    cleanup("northstar")
    with transaction("northstar") as conn:
        version = run(
            conn,
            """SELECT cleaned_at,(SELECT count(*) FROM chunks WHERE version_id=:v) AS chunks
          FROM document_versions WHERE id=:v""",
            v=result["version_id"],
        ).one()
    assert version.cleaned_at is not None and version.chunks == 0

    def fail(key):
        raise AssertionError("cleaned version was processed again")

    monkeypatch.setattr(ingestion, "object_path", fail)
    cleanup("northstar")


def test_configuration_error_not_masked_as_provider_outage(client, monkeypatch):
    import app.main as main_module

    def refuse(question, evidence, conflicts):
        raise HTTPException(503, "model_requires_budget_review")

    monkeypatch.setattr(main_module, "generate", refuse)
    response = client.post("/api/query", json={"question": "equipment allowance"})
    assert response.status_code == 503
    assert response.json()["error"] == "model_requires_budget_review"


def test_retries_bounded():
    with transaction("northstar") as conn:
        result = enqueue(conn, "northstar", "Missing file", "x.txt", b"missing file")
        run(
            conn,
            "UPDATE document_versions SET storage_key=:k WHERE id=:i",
            k=str(uuid4()),
            i=result["version_id"],
        )
    statuses = []
    for _ in range(4):
        process_one("northstar")
        with transaction("northstar") as conn:
            run(
                conn,
                "UPDATE ingestion_jobs SET available_at=now() WHERE version_id=:i",
                i=result["version_id"],
            )
            statuses.append(
                run(
                    conn,
                    "SELECT status FROM document_versions WHERE id=:i",
                    i=result["version_id"],
                ).scalar()
            )
    # Queued while retries remain, failed only once they are exhausted.
    assert statuses[:2] == ["queued", "queued"] and statuses[2:] == ["failed", "failed"]
    with transaction("northstar") as conn:
        job = run(
            conn,
            "SELECT attempts,status FROM ingestion_jobs WHERE version_id=:i",
            i=result["version_id"],
        ).one()
        assert job.attempts == 3 and job.status == "failed"
        run(conn, "UPDATE documents SET deleted=true WHERE id=:i", i=result["id"])


def test_workspace_header_required_when_ambiguous(client):
    del client.headers["X-Workspace-ID"]
    assert client.get("/api/documents").status_code == 200
    with transaction() as conn:
        run(
            conn,
            "INSERT INTO workspaces(id,name) VALUES('ambiguous','Second') ON CONFLICT DO NOTHING",
        )
        run(
            conn,
            """INSERT INTO memberships(user_id,workspace_id,role)
          VALUES('demo-admin','ambiguous','member') ON CONFLICT DO NOTHING""",
        )
    try:
        missing = client.get("/api/documents")
        assert missing.status_code == 400 and missing.json()["error"] == "workspace_required"
        chosen = client.get("/api/documents", headers={"X-Workspace-ID": "northstar"})
        assert chosen.status_code == 200
    finally:
        with transaction() as conn:
            run(conn, "DELETE FROM memberships WHERE workspace_id='ambiguous'")
            run(conn, "DELETE FROM workspaces WHERE id='ambiguous'")


def test_global_concurrency_leases():
    from app.budgets import acquire_slot, release_slot

    keys = []
    try:
        for _ in range(5):
            keys.append(acquire_slot())
        with pytest.raises(HTTPException) as exc:
            acquire_slot()
        assert exc.value.status_code == 429
    finally:
        for key in keys:
            release_slot(key)


def test_rank_fusion_combines_independent_rankings():
    from app.embeddings import fuse_ranks

    a, b, c = ({"source_id": key} for key in ["a", "b", "c"])
    assert [r["source_id"] for r in fuse_ranks([a, b], [c, b])] == ["b", "a", "c"]


def test_second_workspace_ids_cannot_cross_endpoints(client):
    workspace = "isolation-" + uuid4().hex
    with transaction() as conn:
        run(conn, "INSERT INTO workspaces VALUES(:w,:n)", w=workspace, n="Isolation fixture")
        run(conn, "INSERT INTO memberships VALUES('demo-admin',:w,'admin')", w=workspace)
    headers = {"X-Workspace-ID": workspace}
    try:
        doc = client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("isolation.txt", b"isolatedorchid passage")},
        ).json()["id"]
        while process_one(workspace):
            pass
        answer = client.post(
            "/api/query", headers=headers, json={"question": "isolatedorchid"}
        ).json()
        source = answer["citations"][0]["source_id"]
        review = client.post(
            "/api/reviews", headers=headers, json={"question": "Private review?", "note": ""}
        ).json()["id"]
        assert client.get("/api/sources/" + source).status_code == 404
        assert client.get("/api/conversations/" + answer["conversation_id"]).status_code == 404
        assert client.delete("/api/documents/" + doc).status_code == 404
        assert client.post("/api/documents/" + doc + "/retry").status_code == 404
        claim = {"action": "claim", "revision": 0}
        assert client.post("/api/reviews/" + review + "/transitions", json=claim).status_code == 404
        assert (
            client.post(
                "/api/messages/" + answer["message_id"] + "/feedback", json={"helpful": True}
            ).status_code
            == 404
        )
        # Revoke membership and verify that the previously authorized source is denied.
        with transaction() as conn:
            run(conn, "DELETE FROM memberships WHERE workspace_id=:w", w=workspace)
        assert client.get("/api/sources/" + source, headers=headers).status_code == 404
    finally:
        # Runs even when an assertion fails, so no fixture leaks into later tests.
        with transaction() as conn:
            run(conn, "DELETE FROM memberships WHERE workspace_id=:w", w=workspace)
        with transaction(workspace) as conn:
            run(conn, "UPDATE documents SET deleted=true,active_version=NULL,latest_version=NULL")
        from app.ingestion import cleanup

        cleanup(workspace)
        # Review history is append-only for the runtime role, so the owner role removes it.
        from sqlalchemy import create_engine, text

        with create_engine(settings.migration_url).begin() as owner:
            owner.execute(text("SELECT set_config('app.workspace', :w, true)"), {"w": workspace})
            owner.execute(text("DELETE FROM review_events"))
        with transaction(workspace) as conn:
            for table in [
                "review_citations",
                "audit_events",
                "review_requests",
                "feedback",
                "citations",
                "messages",
                "conversations",
                "ingestion_jobs",
                "chunks",
                "document_versions",
                "documents",
            ]:
                run(conn, f"DELETE FROM {table}")
        with transaction() as conn:
            run(conn, "DELETE FROM workspaces WHERE id=:w", w=workspace)
