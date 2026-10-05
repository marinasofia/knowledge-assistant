"""Backfill local embeddings on approved versions, with per-workspace isolation."""

from .db import run, transaction
from .embeddings import IDENTIFIER, encode


def reindex():
    with transaction() as conn:
        workspaces = list(run(conn, "SELECT id FROM workspaces").scalars())
    count = 0
    for workspace in workspaces:
        with transaction(workspace) as conn:
            versions = list(
                run(
                    conn,
                    """SELECT active_version FROM documents WHERE NOT deleted
              AND active_version IS NOT NULL""",
                ).scalars()
            )
        for version in versions:
            with transaction(workspace) as conn:
                chunks = [
                    dict(r)
                    for r in run(
                        conn,
                        "SELECT id,content FROM chunks WHERE version_id=:v ORDER BY ordinal",
                        v=version,
                    ).mappings()
                ]
            vectors = encode([c["content"] for c in chunks])
            with transaction(workspace) as conn:
                if not run(
                    conn,
                    "SELECT id FROM documents WHERE active_version=:v AND NOT deleted FOR UPDATE",
                    v=version,
                ).first():
                    continue
                for chunk, vector in zip(chunks, vectors, strict=True):
                    run(
                        conn,
                        "UPDATE chunks SET embedding=CAST(:e AS vector) WHERE id=:i",
                        e=vector,
                        i=chunk["id"],
                    )
                    count += 1
                run(
                    conn,
                    "UPDATE document_versions SET embedding_model=:m WHERE id=:v",
                    m=IDENTIFIER,
                    v=version,
                )
    print(f"Indexed {count} passages with {IDENTIFIER}")


if __name__ == "__main__":
    reindex()
