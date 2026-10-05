"""Fixed-window rate limits stored in PostgreSQL, so every API process shares one count."""

from fastapi import HTTPException

from .db import run, transaction


def hit(key, limit, window_seconds=60):
    """Count one request against key; raise 429 once the window's limit is passed."""
    with transaction() as conn:
        count = run(
            conn,
            """INSERT INTO rate_limits(key,window_start,count) VALUES(:k,now(),1)
          ON CONFLICT(key) DO UPDATE SET
            count=CASE WHEN rate_limits.window_start <= now()-make_interval(secs=>:w)
              THEN 1 ELSE rate_limits.count+1 END,
            window_start=CASE WHEN rate_limits.window_start <= now()-make_interval(secs=>:w)
              THEN now() ELSE rate_limits.window_start END
          RETURNING count""",
            k=key,
            w=window_seconds,
        ).scalar()
    if count > limit:
        raise HTTPException(429, "rate_limited")


def client_ip(request):
    # The direct peer address. Forwarded headers are not trusted until a known proxy is set.
    return request.client.host if request.client else "unknown"
