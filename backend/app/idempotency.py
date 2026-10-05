"""Replay-safe writes: the same Idempotency-Key and body returns the first result.

Follows the pattern of storing the key and request fingerprint in the same transaction as the
write, so a retried request can never apply the write twice."""

import hashlib
import json

from fastapi import HTTPException

from .db import run


def fingerprint(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(
            part if isinstance(part, bytes) else json.dumps(part, sort_keys=True).encode()
        )
        digest.update(b"\0")
    return digest.hexdigest()


def once(conn, who, key, request_hash, operation):
    """Run operation(conn) at most once per (workspace, user, key)."""
    if not key:
        return operation(conn)
    if len(key) > 200:
        raise HTTPException(422, "idempotency_key_too_long")
    claimed = run(
        conn,
        """INSERT INTO idempotency_keys(workspace_id,user_id,key,request_hash)
      VALUES(:w,:u,:k,:h) ON CONFLICT DO NOTHING RETURNING key""",
        w=who.workspace,
        u=who.user_id,
        k=key,
        h=request_hash,
    ).first()
    if not claimed:
        # A concurrent first attempt holds the row lock until it commits, so this read sees it.
        prior = run(
            conn,
            """SELECT request_hash,response FROM idempotency_keys
          WHERE user_id=:u AND key=:k""",
            u=who.user_id,
            k=key,
        ).one()
        if prior.request_hash != request_hash:
            raise HTTPException(422, "idempotency_key_reused")
        if prior.response is None:
            raise HTTPException(409, "request_in_progress")
        return prior.response
    result = operation(conn)
    run(
        conn,
        """UPDATE idempotency_keys SET response=CAST(:r AS jsonb),status_code=200
      WHERE user_id=:u AND key=:k""",
        r=json.dumps(result),
        u=who.user_id,
        k=key,
    )
    return result
