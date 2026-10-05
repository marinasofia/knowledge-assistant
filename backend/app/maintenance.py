"""Run retention cleanup explicitly from the operator scheduler."""

import time
from pathlib import Path

from .config import settings
from .db import run, transaction
from .ingestion import cleanup

# An upload writes its object before its transaction commits. Younger files may belong to a
# commit still in flight, so only older unreferenced files are treated as orphans.
ORPHAN_QUARANTINE_SECONDS = 3600


def sweep_orphans(workspaces, quarantine=ORPHAN_QUARANTINE_SECONDS):
    root = Path(settings.storage_dir).resolve()
    if not root.exists():
        return []
    referenced = set()
    for workspace in workspaces:
        with transaction(workspace) as conn:
            referenced.update(run(conn, "SELECT storage_key FROM document_versions").scalars())
    cutoff = time.time() - quarantine
    removed = []
    for path in root.iterdir():
        if path.is_file() and path.name not in referenced and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def maintain():
    with transaction() as conn:
        workspaces = list(run(conn, "SELECT id FROM workspaces").scalars())
        run(conn, "DELETE FROM sessions WHERE expires_at<now()")
        run(conn, "DELETE FROM rate_limits WHERE window_start<now()-interval '1 day'")
    for workspace in workspaces:
        cleanup(workspace)
        with transaction(workspace) as conn:
            for table in ["citations", "feedback"]:
                run(
                    conn,
                    f"""DELETE FROM {table} WHERE message_id IN
                  (SELECT id FROM messages WHERE created_at<now()-interval '30 days')""",
                )
            run(conn, "DELETE FROM messages WHERE created_at<now()-interval '30 days'")
            run(
                conn,
                """DELETE FROM conversations WHERE NOT EXISTS
              (SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id)
              AND created_at<now()-interval '30 days' """,
            )
            run(conn, "DELETE FROM audit_events WHERE created_at<now()-interval '90 days'")
            run(conn, "DELETE FROM idempotency_keys WHERE created_at<now()-interval '24 hours'")
            # Resolved reviews are kept for a year after resolution, then removed with their
            # citations and history. Open, claimed and outdated reviews are never expired.
            expired = """SELECT id FROM review_requests WHERE status IN ('answered','declined')
              AND resolved_at<now()-interval '365 days'"""
            for table in ["review_citations", "review_events"]:
                run(conn, f"DELETE FROM {table} WHERE review_id IN ({expired})")
            run(conn, f"DELETE FROM review_requests WHERE id IN ({expired})")
    sweep_orphans(workspaces)


if __name__ == "__main__":
    maintain()
