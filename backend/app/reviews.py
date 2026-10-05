"""Human review as an explicit state machine with optimistic concurrency."""

import json

from fastapi import HTTPException

from .db import run
from .ingestion import new_id

# Share of the asker's question terms that a published question must contain to be offered.
# Not validated on labeled data yet; see evaluations/README.md.
REUSE_COVERAGE = 0.6

# action: (states it may start from, state it leads to)
TRANSITIONS = {
    "claim": ({"open", "outdated"}, "claimed"),
    "release": ({"claimed"}, "open"),
    "answer": ({"claimed"}, "answered"),
    "decline": ({"claimed"}, "declined"),
}


def create(conn, who, question, note, message_id=None):
    if (
        message_id
        and not run(
            conn,
            """SELECT 1 FROM messages m JOIN conversations c
      ON c.workspace_id=m.workspace_id AND c.id=m.conversation_id
      WHERE m.id=:m AND c.user_id=:u""",
            m=message_id,
            u=who.user_id,
        ).first()
    ):
        raise HTTPException(404, "message_not_found")
    key = new_id()
    run(
        conn,
        """INSERT INTO review_requests(id,workspace_id,user_id,question,note,message_id)
      VALUES(:i,:w,:u,:q,:n,:m)""",
        i=key,
        w=who.workspace,
        u=who.user_id,
        q=question,
        n=note,
        m=message_id,
    )
    record(conn, who.workspace, key, "create", who.user_id)
    return key


def record(conn, workspace, review_id, action, actor, resolution=None, citations=()):
    # Append-only: the runtime role may insert and read events, never change them.
    run(
        conn,
        """INSERT INTO review_events(id,workspace_id,review_id,action,actor_id,resolution,citations)
      VALUES(:i,:w,:r,:a,:u,:res,CAST(:c AS jsonb))""",
        i=new_id(),
        w=workspace,
        r=review_id,
        a=action,
        u=actor,
        res=resolution,
        c=json.dumps(list(citations)),
    )


def transition(
    conn, who, review_id, action, revision, resolution=None, source_ids=(), publish=False
):
    if who.role != "admin":
        raise HTTPException(403, "admin_required")
    starts, target = TRANSITIONS[action]
    review = run(
        conn,
        "SELECT status,claimed_by,revision FROM review_requests WHERE id=:i",
        i=review_id,
    ).first()
    if not review:
        raise HTTPException(404, "review_not_found")
    if review.revision != revision:
        raise HTTPException(409, "review_changed")
    if review.status not in starts:
        raise HTTPException(409, "invalid_transition")
    if action != "claim" and review.claimed_by != who.user_id:
        raise HTTPException(403, "claimed_by_another_reviewer")
    if action in {"answer", "decline"} and not (resolution or "").strip():
        raise HTTPException(422, "resolution_required")
    if action != "answer" and (source_ids or publish):
        raise HTTPException(422, "citations_only_on_answer")
    citations = [active_passage(conn, source_id) for source_id in dict.fromkeys(source_ids)]
    # Compare and set: a concurrent change bumps the revision and this update matches nothing.
    updated = run(
        conn,
        """UPDATE review_requests SET status=:s, revision=revision+1,
      claimed_by=CASE WHEN :s='claimed' THEN :u WHEN :s='open' THEN NULL ELSE claimed_by END,
      resolved_by=CASE WHEN :s IN ('answered','declined') THEN :u ELSE resolved_by END,
      resolved_at=CASE WHEN :s IN ('answered','declined') THEN now() ELSE resolved_at END,
      resolution=CASE WHEN :s IN ('answered','declined') THEN :r ELSE resolution END,
      published=CASE WHEN :s='answered' THEN :p WHEN :s='declined' THEN false ELSE published END
      WHERE id=:i AND revision=:v RETURNING revision""",
        s=target,
        u=who.user_id,
        r=resolution,
        i=review_id,
        v=revision,
        p=publish,
    ).first()
    if not updated:
        raise HTTPException(409, "review_changed")
    if action == "answer":
        # Only the latest answer's citations are live; earlier ones stay in the event history.
        run(conn, "DELETE FROM review_citations WHERE review_id=:r", r=review_id)
    for passage in citations:
        run(
            conn,
            """INSERT INTO review_citations(id,workspace_id,review_id,chunk_id,version_id,section,quote)
          VALUES(:i,:w,:r,:c,:v,:s,:q)""",
            i=new_id(),
            w=who.workspace,
            r=review_id,
            c=passage.id,
            v=passage.version_id,
            s=passage.section,
            q=passage.content,
        )
    snapshot = [
        {"source_id": p.id, "version_id": p.version_id, "section": p.section, "quote": p.content}
        for p in citations
    ]
    record(conn, who.workspace, review_id, action, who.user_id, resolution, snapshot)
    return {"status": target, "revision": updated.revision}


def outdate_for_document(conn, workspace, document_id):
    """Reopen answers whose quoted text is no longer in the document's active version."""
    reopened = run(
        conn,
        """UPDATE review_requests r SET status='outdated', revision=revision+1
      WHERE r.status='answered' AND EXISTS (
        SELECT 1 FROM review_citations rc JOIN document_versions v
        ON v.workspace_id=rc.workspace_id AND v.id=rc.version_id
        WHERE rc.review_id=r.id AND v.document_id=:d AND NOT EXISTS (
          SELECT 1 FROM documents d JOIN chunks c
          ON c.workspace_id=d.workspace_id AND c.version_id=d.active_version
          WHERE d.id=:d AND NOT d.deleted AND strpos(c.content, rc.quote) > 0))
      RETURNING r.id""",
        d=document_id,
    ).scalars()
    ids = list(reopened)
    for review_id in ids:
        record(conn, workspace, review_id, "outdate", None)
    return ids


def citations_for(conn, review_id):
    return [
        dict(c)
        for c in run(
            conn,
            # Snapshots, not a join to chunks: cleanup removes passages of deleted documents.
            """SELECT rc.chunk_id AS source_id,rc.quote,rc.section,d.title,v.number AS version,
          (NOT d.deleted AND d.active_version=v.id) AS current
          FROM review_citations rc JOIN document_versions v
          ON v.workspace_id=rc.workspace_id AND v.id=rc.version_id
          JOIN documents d ON d.workspace_id=v.workspace_id AND d.id=v.document_id
          WHERE rc.review_id=:r ORDER BY rc.id""",
            r=review_id,
        ).mappings()
    ]


def published_matches(conn, question, limit=2):
    """Published answers whose original question shares most of this question's terms."""
    matches = [
        dict(r)
        for r in run(
            conn,
            """SELECT r.id AS review_id,r.question,r.resolution,r.resolved_at FROM (
            SELECT r.*,
              (SELECT count(*) FROM unnest(tsvector_to_array(to_tsvector('english',:q))) t
               WHERE t = ANY(tsvector_to_array(to_tsvector('english',r.question))))::float
              / greatest(cardinality(tsvector_to_array(to_tsvector('english',:q))),1) AS coverage
            FROM review_requests r WHERE r.status='answered' AND r.published) r
          WHERE r.coverage >= :m ORDER BY r.coverage DESC,r.resolved_at DESC LIMIT :l""",
            q=question,
            m=REUSE_COVERAGE,
            l=limit,
        ).mappings()
    ]
    for match in matches:
        # Stored inside the message JSON, so values must be JSON native.
        match["resolved_at"] = match["resolved_at"].isoformat()
        match["citations"] = citations_for(conn, match["review_id"])
    return matches


def active_passage(conn, source_id):
    passage = run(
        conn,
        """SELECT c.id,c.version_id,c.section,c.content FROM chunks c JOIN document_versions v
      ON v.workspace_id=c.workspace_id AND v.id=c.version_id JOIN documents d
      ON d.workspace_id=v.workspace_id AND d.id=v.document_id
      WHERE c.id=:i AND NOT d.deleted AND d.active_version=v.id FOR SHARE OF d""",
        i=source_id,
    ).first()
    if not passage:
        raise HTTPException(409, "evidence_changed_please_retry")
    return passage


def listing(conn, who, offset):
    reviews = [
        dict(r)
        for r in run(
            conn,
            """SELECT r.id,r.question,r.note,r.status,r.created_at,r.revision,r.message_id,
          r.published,
          r.resolution,r.resolved_at,claimer.name AS claimed_by_name,r.claimed_by,
          resolver.name AS resolved_by_name,requester.name AS requested_by_name
          FROM review_requests r LEFT JOIN users claimer ON claimer.id=r.claimed_by
          LEFT JOIN users resolver ON resolver.id=r.resolved_by
          LEFT JOIN users requester ON requester.id=r.user_id
          WHERE (:admin OR r.user_id=:u) ORDER BY r.created_at DESC LIMIT 50 OFFSET :o""",
            admin=who.role == "admin",
            u=who.user_id,
            o=offset,
        ).mappings()
    ]
    for review in reviews:
        review["citations"] = citations_for(conn, review["id"])
        review["history"] = [
            dict(e)
            for e in run(
                conn,
                """SELECT e.action,e.resolution,e.created_at,u.name AS actor_name
              FROM review_events e LEFT JOIN users u ON u.id=e.actor_id
              WHERE e.review_id=:r ORDER BY e.created_at,e.id""",
                r=review["id"],
            ).mappings()
        ]
        review["candidate_sources"] = []
        if who.role == "admin" and review["message_id"]:
            review["candidate_sources"] = [
                dict(c)
                for c in run(
                    conn,
                    """SELECT ci.chunk_id AS source_id,d.title,c.section,v.number AS version
                  FROM citations ci JOIN chunks c ON c.workspace_id=ci.workspace_id
                  AND c.id=ci.chunk_id JOIN document_versions v
                  ON v.workspace_id=c.workspace_id AND v.id=c.version_id JOIN documents d
                  ON d.workspace_id=v.workspace_id AND d.id=v.document_id
                  WHERE ci.message_id=:m AND NOT d.deleted AND d.active_version=v.id""",
                    m=review["message_id"],
                ).mappings()
            ]
    return reviews
