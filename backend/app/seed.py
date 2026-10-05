from pathlib import Path

from .config import settings
from .db import run, transaction
from .ingestion import enqueue
from .worker import tick


def seed():
    if settings.env != "development":
        raise RuntimeError("Demo seed only works in development")
    with transaction() as conn:
        for uid, name in [("demo-admin", "Alex Morgan"), ("demo-member", "Jordan Lee")]:
            run(
                conn,
                "INSERT INTO users(id,name) VALUES(:i,:n) ON CONFLICT DO NOTHING",
                i=uid,
                n=name,
            )
        run(
            conn,
            "INSERT INTO workspaces(id,name) VALUES('northstar','Northstar Studio') ON CONFLICT DO NOTHING",
        )
        for uid, role in [("demo-admin", "admin"), ("demo-member", "member")]:
            run(
                conn,
                """INSERT INTO memberships(user_id,workspace_id,role)
              VALUES(:i,'northstar',:r) ON CONFLICT DO NOTHING""",
                i=uid,
                r=role,
            )
    with transaction("northstar") as conn:
        for path in sorted((Path(__file__).resolve().parents[2] / "corpus").glob("*.md")):
            if not run(
                conn, "SELECT 1 FROM documents WHERE title=:t", t=path.stem.replace("_", " ")
            ).first():
                enqueue(
                    conn, "northstar", path.stem.replace("_", " "), path.name, path.read_bytes()
                )
    while tick():
        pass


if __name__ == "__main__":
    seed()
