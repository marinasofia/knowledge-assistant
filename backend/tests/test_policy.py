from datetime import date

import anthropic
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.db import run, transaction
from app.ingestion import activate_due, enqueue, process_one
from app.main import app
from app.policy import figures, parse_front_matter
from app.seed import seed


@pytest.fixture(scope="module", autouse=True)
def setup():
    settings.dev_auth = True
    seed()


def signed_in(role):
    client = TestClient(app)
    client.headers["origin"] = settings.origin
    client.post("/api/auth/development", json={"role": role})
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf"]
    return client


def doc_id(title):
    with transaction("northstar") as conn:
        return run(
            conn, "SELECT id FROM documents WHERE title=:t AND NOT deleted", t=title
        ).scalar()


def test_front_matter_parsing():
    meta, body = parse_front_matter("---\nowner: Finance\neffective: 2026-08-15\n---\n# T\nx")
    assert meta == {"owner": "Finance", "effective": date(2026, 8, 15)} and body == "# T\nx"
    assert parse_front_matter("# No header\n") == ({}, "# No header\n")
    for bad in ["---\ncolor: red\n---\n", "---\neffective: soon\n---\n", "---\nowner:\n---\n"]:
        with pytest.raises(HTTPException) as exc:
            parse_front_matter(bad)
        assert exc.value.status_code == 422


def test_invalid_front_matter_rejected_at_upload():
    admin = signed_in("admin")
    bad = b"---\neffective: next week\n---\n# Policy\nText."
    response = admin.post("/api/documents", files={"file": ("bad.md", bad)})
    assert response.status_code == 422 and response.json()["error"] == "invalid_effective_date"


def test_future_version_waits_for_its_effective_date():
    v1 = b"---\neffective: 2026-01-01\n---\n# Parking\nParking costs $5."
    v2 = b"---\nowner: Facilities\neffective: 2099-01-01\n---\n# Parking\nParking costs $9."
    with transaction("northstar") as conn:
        doc = enqueue(conn, "northstar", "Parking", "p.md", v1)
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        second = enqueue(conn, "northstar", "Parking", "p.md", v2, doc["id"])
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        state = run(
            conn,
            """SELECT d.active_version,v.status,v.owner FROM documents d
          JOIN document_versions v ON v.id=:v WHERE d.id=:d""",
            v=second["version_id"],
            d=doc["id"],
        ).one()
    assert state.active_version == doc["version_id"]
    assert state.status == "scheduled" and state.owner == "Facilities"

    with transaction("northstar") as conn:
        run(
            conn,
            "UPDATE document_versions SET effective_from=current_date WHERE id=:v",
            v=second["version_id"],
        )
    assert activate_due("northstar") == 1
    with transaction("northstar") as conn:
        assert (
            run(conn, "SELECT active_version FROM documents WHERE id=:d", d=doc["id"]).scalar()
            == second["version_id"]
        )
        run(conn, "UPDATE documents SET deleted=true WHERE id=:d", d=doc["id"])


def test_scheduled_version_overtaken_by_newer_upload_is_superseded():
    future = b"---\neffective: 2099-01-01\n---\n# Lockers\nLockers are free."
    now = b"# Lockers\nLockers cost $2."
    with transaction("northstar") as conn:
        doc = enqueue(conn, "northstar", "Lockers", "l.md", future)
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        latest = enqueue(conn, "northstar", "Lockers", "l.md", now, doc["id"])
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        run(
            conn,
            "UPDATE document_versions SET effective_from=current_date WHERE id=:v",
            v=doc["version_id"],
        )
    activate_due("northstar")
    with transaction("northstar") as conn:
        status = run(
            conn, "SELECT status FROM document_versions WHERE id=:v", v=doc["version_id"]
        ).scalar()
        active = run(conn, "SELECT active_version FROM documents WHERE id=:d", d=doc["id"]).scalar()
        run(conn, "UPDATE documents SET deleted=true WHERE id=:d", d=doc["id"])
    assert status == "superseded" and active == latest["version_id"]


def test_figures_ignore_formatting():
    assert figures("Pay $1,500 within 30 days or 5%.") == {"$1500", "30", "5%"}


def test_meal_allowance_conflict_then_declared_precedence():
    admin, member = signed_in("admin"), signed_in("member")
    question = {"question": "Is the meal allowance $75 or $90?"}
    conflict = member.post("/api/query", json=question).json()
    assert conflict["status"] == "conflict" and len(conflict["citations"]) == 2
    assert conflict["conflicts"][0]["prevailing_title"] is None

    travel, field = doc_id("Travel and expenses"), doc_id("Field team handbook")
    rule = {
        "prevailing_document_id": travel,
        "yielding_document_id": field,
        "section": "Meal reimbursement",
        "note": "Finance sets allowances.",
    }
    assert member.post("/api/precedence", json=rule).status_code == 403
    created = admin.post("/api/precedence", json=rule)
    assert created.status_code == 201
    assert admin.post("/api/precedence", json=rule).status_code == 409
    reverse = {**rule, "prevailing_document_id": field, "yielding_document_id": travel}
    assert admin.post("/api/precedence", json=reverse).status_code == 409
    same = {**rule, "yielding_document_id": travel}
    assert admin.post("/api/precedence", json=same).status_code == 422

    resolved = member.post("/api/query", json=question).json()
    assert resolved["status"] == "answer"
    assert resolved["gaps"] == [
        "Travel and expenses takes precedence for Meal reimbursement: Finance sets allowances."
    ]
    first = next(
        s for s in resolved["sources"] if s["source_id"] == resolved["citations"][0]["source_id"]
    )
    assert first["title"] == "Travel and expenses"
    assert admin.delete("/api/precedence/" + created.json()["id"]).status_code == 200


def test_unresolved_conflict_never_reaches_the_model(monkeypatch):
    class Refuse:
        def __init__(self, **_):
            raise AssertionError("model called for an unresolved conflict")

    monkeypatch.setattr(anthropic, "Anthropic", Refuse)
    monkeypatch.setattr(settings, "generation_mode", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "stub-key")
    member = signed_in("member")
    answer = member.post("/api/query", json={"question": "Is the meal allowance $75 or $90?"})
    assert answer.json()["status"] == "conflict"
