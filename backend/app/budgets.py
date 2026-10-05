from fastapi import Depends, HTTPException

from .auth import identity
from .db import run, transaction
from .ingestion import new_id


def acquire_slot():
    key = new_id()
    with transaction() as conn:
        run(conn, "SELECT pg_advisory_xact_lock(73592401)")
        run(conn, "DELETE FROM generation_leases WHERE expires_at<now()")
        if run(conn, "SELECT count(*) FROM generation_leases").scalar() >= 5:
            raise HTTPException(429, "too_many_concurrent_questions")
        run(conn, "INSERT INTO generation_leases VALUES(:i,now()+interval '40 seconds')", i=key)
    return key


def release_slot(key):
    with transaction() as conn:
        run(conn, "DELETE FROM generation_leases WHERE id=:i", i=key)


# A sync dependency runs in the threadpool, keeping lease queries off the event loop.
def query_slot(who=Depends(identity)):
    key = acquire_slot()
    try:
        yield key
    finally:
        release_slot(key)
