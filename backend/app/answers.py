from fastapi import HTTPException

from .answer_schema import Answer, Reference, validate_answer
from .config import settings
from .db import run, transaction
from .generators import MIN_COVERAGE, cite, gate, generator

# Re-exported for callers that import them from here.
__all__ = ["MIN_COVERAGE", "Answer", "Reference", "generate", "retrieve", "validate_answer"]


COVERAGE = """(SELECT count(*) FROM unnest(tsvector_to_array(to_tsvector('english',:q))) t
  WHERE t = ANY(tsvector_to_array(c.search)))::float
  / greatest(cardinality(tsvector_to_array(to_tsvector('english',:q))),1) AS coverage"""


def retrieve(conn, question):
    results = [
        dict(row)
        for row in run(
            conn,
            f"""SELECT c.id AS source_id,c.content,c.section,c.section_path,
      d.title,d.id AS document_id,v.number AS version,
      {COVERAGE},
      ts_rank_cd(c.search,replace(plainto_tsquery('english',:q)::text, '&', '|')::tsquery) AS rank
      FROM chunks c JOIN document_versions v ON v.workspace_id=c.workspace_id AND v.id=c.version_id
      JOIN documents d ON d.workspace_id=v.workspace_id AND d.id=v.document_id
      WHERE NOT d.deleted AND d.active_version=v.id AND v.status='ready'
      AND c.search @@ replace(plainto_tsquery('english',:q)::text, '&', '|')::tsquery
      ORDER BY rank DESC,d.title,c.ordinal,c.id LIMIT 5""",
            q=question,
        ).mappings()
    ]

    if settings.semantic_search:
        from .embeddings import IDENTIFIER, encode, fuse_ranks

        vector = encode([question])[0]
        semantic = [
            dict(row)
            for row in run(
                conn,
                f"""SELECT c.id AS source_id,c.content,c.section,c.section_path,
          d.title,d.id AS document_id,v.number AS version,
          {COVERAGE},
          1-(c.embedding <=> CAST(:e AS vector)) AS rank
          FROM chunks c JOIN document_versions v ON v.workspace_id=c.workspace_id AND v.id=c.version_id
          JOIN documents d ON d.workspace_id=v.workspace_id AND d.id=v.document_id
          WHERE NOT d.deleted AND d.active_version=v.id AND v.status='ready'
          AND v.embedding_model=:m AND c.embedding IS NOT NULL
          ORDER BY c.embedding <=> CAST(:e AS vector),d.title,c.ordinal,c.id LIMIT 5""",
                e=vector,
                m=IDENTIFIER,
                q=question,
            ).mappings()
        ]
        results = fuse_ranks(results, semantic)
    bounded = []
    evidence_bytes = 0
    for item in results:
        size = len(item["content"].encode("utf-8"))
        if evidence_bytes + size <= 8000:
            bounded.append(item)
            evidence_bytes += size
    return bounded


def admit(who):
    # The kill switch covers every mode; the paid quota only covers provider calls.
    if not settings.generation_enabled:
        raise HTTPException(503, "generation_disabled")
    if generator().paid:
        reserve_usage(who)


def reserve_usage(who):
    # Lock buckets in a stable order. Committed reservations are never refunded on failure.
    buckets = [
        ("global", settings.daily_limit),
        ("user:" + who.user_id, settings.user_daily_limit),
        ("workspace:" + who.workspace, settings.workspace_daily_limit),
    ]
    with transaction() as conn:
        for key, limit in sorted(buckets):
            run(
                conn,
                """INSERT INTO usage_buckets(key,day,used) VALUES(:k,current_date,0)
              ON CONFLICT(key) DO NOTHING""",
                k=key,
            )
            row = (
                run(conn, "SELECT * FROM usage_buckets WHERE key=:k FOR UPDATE", k=key)
                .mappings()
                .one()
            )
            used = (
                row["used"]
                if str(row["day"]) == str(run(conn, "SELECT current_date").scalar())
                else 0
            )
            if used >= limit:
                raise HTTPException(429, "daily_usage_limit")
            run(
                conn,
                "UPDATE usage_buckets SET day=current_date,used=:u WHERE key=:k",
                k=key,
                u=used + 1,
            )


def generate(question, evidence, conflicts=()):
    """Decide the outcome in a fixed order: no evidence, not covered, conflict, then answer."""
    if not evidence:
        return Answer(
            status="abstain",
            text="I could not find an approved passage that answers this question.",
            citations=[],
            gaps=["Try different wording or send this question for human review."],
        )
    if not gate().covers(question, evidence):
        # Applies in every mode, so an uncovered question never reaches a paid model.
        return Answer(
            status="abstain",
            text="No approved passage clearly covers this question. The closest passages are below.",
            citations=cite(evidence[:3]),
            gaps=["Check these passages or send this question for human review."],
        )
    by_id = {e["source_id"]: e for e in evidence}
    # Only a disagreement about the best matching passage decides the outcome. Chosen on the
    # development split: counting any disagreement in the evidence flagged side topics.
    conflicts = [c for c in conflicts if evidence[0]["source_id"] in c["source_ids"]]
    unresolved = [c for c in conflicts if not c["prevailing_document_id"]]
    if unresolved:
        # Deterministic in every mode: no model is asked which policy wins.
        conflict = unresolved[0]
        return Answer(
            status="conflict",
            text=f"Approved policies disagree on {conflict['section']}, and no administrator has "
            "set which one takes precedence.",
            citations=cite(by_id[i] for i in conflict["source_ids"]),
            gaps=["Send this question for human review so an administrator can decide."],
        )
    resolved = [c for c in conflicts if c["prevailing_document_id"]]
    if resolved:
        # Prevailing passages first, so both readers and the model see the governing text first.
        prevailing = {c["prevailing_document_id"] for c in resolved}
        evidence = sorted(evidence, key=lambda e: e["document_id"] not in prevailing)
    precedence = [{k: c[k] for k in ("section", "prevailing_title", "note")} for c in resolved]
    return generator().answer(question, evidence, precedence)
