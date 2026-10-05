import hashlib
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request

from .config import settings
from .db import run, transaction

# Sessions end after this much inactivity, and in any case after 8 hours.
IDLE_MINUTES = 30


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Identity:
    user_id: str
    name: str
    workspace: str
    role: str
    csrf: str


def session_user(request: Request):
    token = request.cookies.get("ka_session", "")
    with transaction() as conn:
        row = (
            run(
                conn,
                """SELECT u.id, u.name, s.csrf FROM sessions s JOIN users u ON
          u.id=s.user_id WHERE s.token_hash=:token AND expires_at>now()
          AND last_seen_at>now()-make_interval(mins=>:idle)""",
                token=digest(token),
                idle=IDLE_MINUTES,
            )
            .mappings()
            .first()
        )
        if row:
            # Touch at most once a minute, so activity tracking is not a write per request.
            run(
                conn,
                """UPDATE sessions SET last_seen_at=now() WHERE token_hash=:token
              AND last_seen_at<now()-interval '1 minute'""",
                token=digest(token),
            )
    if not row:
        raise HTTPException(401, "sign_in_required")
    return row


def identity(request: Request):
    user = session_user(request)
    workspace = request.headers.get("X-Workspace-ID")
    with transaction() as conn:
        if not workspace:
            # Without a header, fall back only when the choice is unambiguous.
            only = (
                run(conn, "SELECT workspace_id FROM memberships WHERE user_id=:u", u=user["id"])
                .scalars()
                .all()
            )
            if len(only) != 1:
                raise HTTPException(400, "workspace_required")
            workspace = only[0]
        membership = run(
            conn,
            "SELECT role FROM memberships WHERE user_id=:u AND workspace_id=:w",
            u=user["id"],
            w=workspace,
        ).scalar()
    if not membership:
        raise HTTPException(404, "workspace_not_found")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), user["csrf"]):
            raise HTTPException(403, "csrf_failed")
    return Identity(user["id"], user["name"], workspace, membership, user["csrf"])


def check_origin(request):
    if request.headers.get("origin") != settings.origin:
        raise HTTPException(403, "origin_not_allowed")


def admin(who):
    if who.role != "admin":
        raise HTTPException(403, "admin_required")


def create_session(response, user_id):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with transaction() as conn:
        run(
            conn,
            """INSERT INTO sessions(token_hash,user_id,csrf,expires_at)
          VALUES(:t,:u,:c,now()+interval '8 hours')""",
            t=digest(token),
            u=user_id,
            c=csrf,
        )
    response.set_cookie(
        "ka_session",
        token,
        httponly=True,
        secure=settings.env == "production",
        samesite="lax",
        max_age=28800,
        path="/",
    )
    return csrf
