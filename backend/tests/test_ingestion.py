import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import run, transaction
from app.ingestion import MAX_PASSAGE, Passage, enqueue, pack, process_one, split_passages
from app.main import app
from app.seed import seed


@pytest.fixture(scope="module", autouse=True)
def setup():
    settings.dev_auth = True
    seed()


def test_paragraphs_become_passages_under_their_heading_path():
    text = "# Travel\nIntro line.\n\n## Meals\nFirst rule.\n\nSecond rule.\n### Field\nField rule.\n## Hotels\nHotel rule."
    passages = split_passages(text)
    assert [(p.section_path, p.text) for p in passages] == [
        ("Travel", "Intro line."),
        ("Travel > Meals", "First rule."),
        ("Travel > Meals", "Second rule."),
        ("Travel > Meals > Field", "Field rule."),
        ("Travel > Hotels", "Hotel rule."),
    ]
    assert passages[3].section == "Field"


def test_long_paragraphs_split_only_between_sentences():
    sentences = [f"Rule {i} applies to every employee in every office." for i in range(60)]
    pieces = pack(" ".join(sentences))
    assert len(pieces) > 1 and all(len(p) <= MAX_PASSAGE for p in pieces)
    assert all(p.endswith(".") for p in pieces)
    assert " ".join(pieces) == " ".join(sentences)


def test_oversized_sentence_is_cut_at_a_space():
    pieces = pack("word " * 400)
    assert all(len(p) <= MAX_PASSAGE for p in pieces) and all(p for p in pieces)
    assert " ".join(pieces).split() == ["word"] * 400


def test_content_key_ignores_whitespace_but_not_section():
    a = Passage("Meals", "Travel > Meals", "The allowance is $75.")
    assert a.key == Passage("Meals", "Travel > Meals", "The  allowance\nis $75.").key
    assert a.key != Passage("Meals", "Field > Meals", "The allowance is $75.").key
    assert a.key != Passage("Meals", "Travel > Meals", "The allowance is $90.").key


def test_version_diff_by_section():
    client = TestClient(app)
    client.headers["origin"] = settings.origin
    client.post("/api/auth/development", json={"role": "member"})
    v1 = b"# Policy\n## Kept\nSame words.\n## Edited\nOld rule.\n## Dropped\nGone soon."
    v2 = b"# Policy\n## Kept\nSame   words.\n## Edited\nNew rule.\n## Added\nBrand new."
    with transaction("northstar") as conn:
        doc = enqueue(conn, "northstar", "Diff policy", "d.md", v1)
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        enqueue(conn, "northstar", "Diff policy", "d.md", v2, doc["id"])
    while process_one("northstar"):
        pass

    diff = client.get(f"/api/documents/{doc['id']}/diff?from=1&to=2").json()
    by_path = {s["section_path"]: s for s in diff["sections"]}
    assert by_path["Policy > Kept"]["status"] == "unchanged"
    assert by_path["Policy > Edited"] == {
        "section_path": "Policy > Edited",
        "status": "changed",
        "removed": ["Old rule."],
        "added": ["New rule."],
    }
    assert by_path["Policy > Added"]["status"] == "added"
    assert by_path["Policy > Dropped"]["status"] == "removed"
    assert client.get(f"/api/documents/{doc['id']}/diff?from=1&to=9").status_code == 404
    with transaction("northstar") as conn:
        version = run(
            conn,
            "SELECT extraction_version FROM document_versions WHERE id=:v",
            v=doc["version_id"],
        ).scalar()
        run(conn, "UPDATE documents SET deleted=true WHERE id=:i", i=doc["id"])
    assert version == "markdown-paragraphs-v2"


def test_source_shows_the_cited_passage_in_its_section():
    client = TestClient(app)
    client.headers["origin"] = settings.origin
    client.post("/api/auth/development", json={"role": "member"})
    body = b"---\nowner: Finance\neffective: 2026-01-01\n---\n# Rules\n## Meals\nFirst.\n\nSecond.\n## Hotels\nOther."
    with transaction("northstar") as conn:
        doc = enqueue(conn, "northstar", "Context policy", "c.md", body)
    while process_one("northstar"):
        pass
    with transaction("northstar") as conn:
        second = run(
            conn,
            "SELECT id FROM chunks WHERE version_id=:v AND content='Second.'",
            v=doc["version_id"],
        ).scalar()
    source = client.get("/api/sources/" + second).json()
    assert source["section_path"] == "Rules > Meals" and source["paragraph"] == 2
    assert [(p["content"], p["cited"]) for p in source["section_passages"]] == [
        ("First.", False),
        ("Second.", True),
    ]
    assert source["owner"] == "Finance" and source["effective_from"] == "2026-01-01"
    with transaction("northstar") as conn:
        run(conn, "UPDATE documents SET deleted=true WHERE id=:i", i=doc["id"])
