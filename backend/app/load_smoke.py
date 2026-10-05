"""Five-client local evidence smoke test using a temporary fictional identity."""

import json
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from pathlib import Path
from uuid import uuid4

from fastapi import Response
from fastapi.testclient import TestClient

from .auth import create_session
from .config import settings
from .db import run, transaction
from .main import app


def smoke():
    if settings.env != "development" or settings.generation_mode != "evidence":
        raise RuntimeError("This smoke test is only for local evidence mode")
    uid = "load-" + uuid4().hex
    with transaction() as conn:
        run(conn, "INSERT INTO users VALUES(:i,:n)", i=uid, n="Load fixture")
        run(conn, "INSERT INTO memberships VALUES(:i,'northstar','member')", i=uid)
    response = Response()
    csrf = create_session(response, uid)
    cookie = SimpleCookie(response.headers["set-cookie"])["ka_session"].value

    def request(_):
        started = time.perf_counter()
        with TestClient(app) as client:
            client.cookies.set("ka_session", cookie)
            result = client.post(
                "/api/query",
                json={"question": "equipment allowance"},
                headers={"origin": settings.origin, "X-CSRF-Token": csrf},
            )
        return {
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "status": result.status_code,
        }

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(request, range(20)))
    durations = sorted(r["duration_ms"] for r in results)
    report = {
        "mode": "local_evidence",
        "transport": "in-process ASGI with real PostgreSQL",
        "hardware_arch": platform.machine(),
        "os": platform.system(),
        "concurrency": 5,
        "corpus_documents": 6,
        "requests": len(results),
        "errors": sum(r["status"] != 200 for r in results),
        "p50_ms": statistics.median(durations),
        "p95_ms": durations[18],
        "limitations": "Small local smoke test, excludes network and live provider latency.",
    }
    root = Path(__file__).resolve().parents[2]
    (root / "evaluations/load-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    with transaction("northstar") as conn:
        for table in ["citations", "feedback"]:
            run(
                conn,
                f"""DELETE FROM {table} WHERE message_id IN (SELECT m.id FROM messages m
              JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=:u)""",
                u=uid,
            )
        run(
            conn,
            "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=:u)",
            u=uid,
        )
        run(conn, "DELETE FROM conversations WHERE user_id=:u", u=uid)
    with transaction() as conn:
        run(conn, "DELETE FROM sessions WHERE user_id=:u", u=uid)
        run(conn, "DELETE FROM memberships WHERE user_id=:u", u=uid)
        run(conn, "DELETE FROM users WHERE id=:u", u=uid)


if __name__ == "__main__":
    smoke()
