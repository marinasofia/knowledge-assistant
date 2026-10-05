import asyncio
import hashlib
import json
import logging
import time
from typing import Annotated, Literal
from uuid import uuid4

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import policy, reviews
from .answers import admit, generate, retrieve, validate_answer
from .auth import admin, check_origin, create_session, digest, identity, session_user
from .budgets import query_slot
from .config import settings
from .db import run, transaction
from .idempotency import fingerprint, once
from .ingestion import MAX_BYTES, diff_versions, enqueue, new_id
from .limits import client_ip, hit

app = FastAPI(title="Knowledge Assistant", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.env == "production",
    same_site="lax",
    max_age=600,
)
logger = logging.getLogger("knowledge")
oauth = OAuth()
if settings.oidc_discovery_url:
    oauth.register(
        "provider",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_discovery_url,
        client_kwargs={"scope": "openid profile email"},
    )
Who = Annotated[object, Depends(identity)]


@app.middleware("http")
async def guard(request, call_next):
    request_id = str(uuid4())
    started = time.monotonic()
    if request.method in {"POST", "PUT", "PATCH"}:
        try:
            length = int(request.headers.get("content-length", "-1"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BYTES + 65536:
            return JSONResponse({"error": "request_size_limit", "request_id": request_id}, 413)
    try:
        response = await call_next(request)
    except Exception:
        logger.error(json.dumps({"request_id": request_id, "error": "internal_error"}))
        response = JSONResponse({"error": "internal_error", "request_id": request_id}, 500)
    response.headers.update(
        {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; object-src 'none'",
        }
    )
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    )
    return response


@app.exception_handler(HTTPException)
async def api_error(request, exc):
    return JSONResponse({"error": exc.detail}, exc.status_code)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({"error": "invalid_request"}, 422)


@app.get("/api/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready():
    with transaction() as conn:
        run(conn, "SELECT 1")
        role = run(
            conn, "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).one()
        if role.rolsuper or role.rolbypassrls:
            raise HTTPException(503, "unsafe_database_role")
    return {"status": "ready"}


@app.get("/api/auth/config")
def auth_config():
    return {
        "development_login": settings.dev_auth,
        "oidc_enabled": bool(settings.oidc_discovery_url),
    }


class DevLogin(BaseModel):
    role: Literal["admin", "member"] = "member"


@app.post("/api/auth/development")
def development_login(body: DevLogin, request: Request):
    if not settings.dev_auth or settings.env != "development":
        raise HTTPException(404, "not_found")
    hit("auth:" + client_ip(request), settings.auth_rate_per_minute)
    check_origin(request)
    response = JSONResponse({"status": "signed_in"})
    create_session(response, "demo-" + body.role)
    return response


@app.get("/api/auth/login")
async def login(request: Request):
    if not settings.oidc_discovery_url:
        raise HTTPException(503, "identity_provider_not_configured")
    await run_in_threadpool(hit, "auth:" + client_ip(request), settings.auth_rate_per_minute)
    return await oauth.provider.authorize_redirect(request, settings.origin + "/api/auth/callback")


@app.get("/api/auth/callback")
async def callback(request: Request):
    if not settings.oidc_discovery_url:
        raise HTTPException(404, "not_found")
    await run_in_threadpool(hit, "auth:" + client_ip(request), settings.auth_rate_per_minute)
    try:
        token = await oauth.provider.authorize_access_token(request)
        user = token["userinfo"]
        subject = hashlib.sha256((user["iss"] + "|" + user["sub"]).encode()).hexdigest()
    except Exception:
        raise HTTPException(401, "identity_verification_failed") from None
    response = RedirectResponse(settings.origin)
    # Database work in the threadpool: this route is async because Authlib's calls are awaited.
    await run_in_threadpool(start_member_session, response, subject)
    request.session.clear()
    return response


def start_member_session(response, subject):
    with transaction() as conn:
        member = run(conn, "SELECT 1 FROM memberships WHERE user_id=:u", u=subject).first()
    if not member:
        raise HTTPException(403, "workspace_invitation_required")
    create_session(response, subject)


@app.get("/api/session")
def current_session(request: Request):
    user = session_user(request)
    with transaction() as conn:
        workspaces = [
            dict(r)
            for r in run(
                conn,
                """SELECT w.id,w.name,m.role FROM workspaces w
          JOIN memberships m ON m.workspace_id=w.id WHERE m.user_id=:u""",
                u=user["id"],
            ).mappings()
        ]
    return {
        "user": {"id": user["id"], "name": user["name"]},
        "csrf": user["csrf"],
        "workspaces": workspaces,
        "mode": settings.generation_mode,
    }


@app.post("/api/auth/logout")
def logout(request: Request, who: Who):
    with transaction() as conn:
        run(
            conn,
            "DELETE FROM sessions WHERE token_hash=:t",
            t=digest(request.cookies.get("ka_session", "")),
        )
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie("ka_session", path="/")
    return response


def audit(conn, who, action, target):
    run(
        conn,
        """INSERT INTO audit_events(id,workspace_id,user_id,action,target_id)
      VALUES(:i,:w,:u,:a,:t)""",
        i=new_id(),
        w=who.workspace,
        u=who.user_id,
        a=action,
        t=target,
    )


@app.get("/api/documents")
def documents(who: Who, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    with transaction(who.workspace) as conn:
        return [
            dict(r)
            for r in run(
                conn,
                """SELECT d.id,d.title,d.active_version,d.created_at,
          v.id AS version_id,v.number AS version,v.status,v.error,v.owner,v.effective_from,
          (SELECT count(*) FROM chunks c WHERE c.version_id=d.active_version) AS passages
          FROM documents d LEFT JOIN document_versions v ON v.workspace_id=d.workspace_id
          AND v.id=d.latest_version WHERE NOT d.deleted ORDER BY d.created_at DESC LIMIT :l OFFSET :o""",
                l=limit,
                o=offset,
            ).mappings()
        ]


IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


@app.post("/api/documents", status_code=202)
def upload(who: Who, key: IdempotencyKey = None, file: UploadFile = File(...)):
    admin(who)
    hit("upload:" + who.user_id, settings.upload_rate_per_minute)
    data = file.file.read(MAX_BYTES + 1)
    filename = file.filename or "untitled.txt"

    def operation(conn):
        result = enqueue(conn, who.workspace, filename, filename, data)
        audit(conn, who, "document.upload", result["id"])
        return result

    with transaction(who.workspace) as conn:
        return once(conn, who, key, fingerprint("upload", filename, data), operation)


@app.post("/api/documents/{document_id}/versions", status_code=202)
def replace(document_id: str, who: Who, key: IdempotencyKey = None, file: UploadFile = File(...)):
    admin(who)
    hit("upload:" + who.user_id, settings.upload_rate_per_minute)
    data = file.file.read(MAX_BYTES + 1)
    filename = file.filename or "untitled.txt"

    def operation(conn):
        result = enqueue(conn, who.workspace, filename, filename, data, document_id)
        audit(conn, who, "document.replace", document_id)
        return result

    request_hash = fingerprint("replace", document_id, filename, data)
    with transaction(who.workspace) as conn:
        return once(conn, who, key, request_hash, operation)


@app.post("/api/documents/{document_id}/retry")
def retry(document_id: str, who: Who):
    admin(who)
    with transaction(who.workspace) as conn:
        row = run(
            conn,
            """SELECT latest_version FROM documents WHERE id=:d AND NOT deleted
          FOR UPDATE""",
            d=document_id,
        ).first()
        if not row:
            raise HTTPException(404, "document_not_found")
        updated = run(
            conn,
            """UPDATE ingestion_jobs SET status='queued',attempts=0,
          available_at=now(),lease_token=NULL,lease_until=NULL WHERE version_id=:v AND status='failed'
          RETURNING id""",
            v=row.latest_version,
        ).first()
        if not updated:
            raise HTTPException(409, "job_not_failed")
        run(
            conn,
            "UPDATE document_versions SET status='queued',error=NULL WHERE id=:v",
            v=row.latest_version,
        )
        audit(conn, who, "document.retry", document_id)
    return {"status": "queued"}


@app.delete("/api/documents/{document_id}")
def delete(document_id: str, who: Who):
    admin(who)
    with transaction(who.workspace) as conn:
        row = run(
            conn,
            """UPDATE documents SET deleted=true,active_version=NULL WHERE id=:d
          AND NOT deleted RETURNING id""",
            d=document_id,
        ).first()
        if not row:
            raise HTTPException(404, "document_not_found")
        reviews.outdate_for_document(conn, who.workspace, document_id)
        audit(conn, who, "document.delete", document_id)
    return {"status": "deleted"}


@app.get("/api/documents/{document_id}/diff")
def document_diff(
    document_id: str,
    who: Who,
    from_version: int = Query(..., alias="from", ge=1),
    to_version: int = Query(..., alias="to", ge=1),
):
    with transaction(who.workspace) as conn:
        if not run(
            conn, "SELECT 1 FROM documents WHERE id=:d AND NOT deleted", d=document_id
        ).first():
            raise HTTPException(404, "document_not_found")
        return diff_versions(conn, document_id, from_version, to_version)


class Precedence(BaseModel):
    prevailing_document_id: str
    yielding_document_id: str
    section: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=3, max_length=1000)


@app.get("/api/precedence")
def precedence_rules(who: Who):
    with transaction(who.workspace) as conn:
        return [
            dict(r)
            for r in run(
                conn,
                """SELECT p.id,p.section,p.note,p.created_at,p.prevailing_document_id,
              p.yielding_document_id,a.title AS prevailing_title,b.title AS yielding_title
              FROM document_precedence p
              JOIN documents a ON a.workspace_id=p.workspace_id AND a.id=p.prevailing_document_id
              JOIN documents b ON b.workspace_id=p.workspace_id AND b.id=p.yielding_document_id
              ORDER BY p.created_at DESC LIMIT 100""",
            ).mappings()
        ]


@app.post("/api/precedence", status_code=201)
def declare_precedence(body: Precedence, who: Who):
    admin(who)
    with transaction(who.workspace) as conn:
        key = policy.declare(
            conn,
            who,
            body.prevailing_document_id,
            body.yielding_document_id,
            body.section,
            body.note,
        )
        audit(conn, who, "precedence.declare", key)
    return {"id": key}


@app.delete("/api/precedence/{rule_id}")
def remove_precedence(rule_id: str, who: Who):
    admin(who)
    with transaction(who.workspace) as conn:
        if not run(
            conn, "DELETE FROM document_precedence WHERE id=:i RETURNING id", i=rule_id
        ).first():
            raise HTTPException(404, "precedence_not_found")
        audit(conn, who, "precedence.remove", rule_id)
    return {"status": "removed"}


@app.get("/api/sources/{source_id}")
def source(source_id: str, who: Who):
    with transaction(who.workspace) as conn:
        row = (
            run(
                conn,
                """SELECT c.id,c.content,c.section,c.section_path,c.version_id,d.title,
          v.number AS version,v.owner,v.effective_from
          FROM chunks c JOIN document_versions v ON v.workspace_id=c.workspace_id AND v.id=c.version_id
          JOIN documents d ON d.workspace_id=v.workspace_id AND d.id=v.document_id
          WHERE c.id=:i AND NOT d.deleted AND d.active_version=v.id""",
                i=source_id,
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(404, "source_unavailable")
        # The whole section, so a reader sees the cited passage in its context.
        section = [
            {"id": p.id, "content": p.content, "cited": p.id == source_id}
            for p in run(
                conn,
                """SELECT id,content FROM chunks WHERE version_id=:v AND section_path=:s
              ORDER BY ordinal""",
                v=row["version_id"],
                s=row["section_path"],
            )
        ]
        paragraph = next(i for i, p in enumerate(section, 1) if p["cited"])
        return {**dict(row), "section_passages": section, "paragraph": paragraph}


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: str | None = None


@app.post("/api/query", dependencies=[Depends(query_slot)])
async def query(body: Question, who: Who):
    # Database work runs in the threadpool so a slow question never blocks the event loop.
    await run_in_threadpool(hit, "query:" + who.user_id, settings.query_rate_per_minute)
    evidence, reviewed, conflicts = await run_in_threadpool(find_evidence, body, who)
    await run_in_threadpool(admit, who)
    started = time.monotonic()
    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(generate, body.question, evidence, conflicts), timeout=28
        )
        validate_answer(answer, evidence)
    except HTTPException:
        raise
    except (TimeoutError, ValueError) as exc:
        # Log the error class only; messages can echo model output or policy text.
        logger.warning(json.dumps({"event": "answer_rejected", "error": type(exc).__name__}))
        raise HTTPException(502, "answer_validation_or_timeout") from None
    except Exception as exc:
        logger.warning(json.dumps({"event": "provider_error", "error": type(exc).__name__}))
        raise HTTPException(502, "provider_unavailable") from None
    return await run_in_threadpool(
        save_answer, body, who, answer, evidence, reviewed, conflicts, started
    )


def find_evidence(body, who):
    # Single-turn evidence: previous answer text never becomes an authoritative source.
    with transaction(who.workspace) as conn:
        if body.conversation_id:
            existing = run(
                conn,
                "SELECT id FROM conversations WHERE id=:i AND user_id=:u",
                i=body.conversation_id,
                u=who.user_id,
            ).first()
            if not existing:
                raise HTTPException(404, "conversation_not_found")
        evidence = retrieve(conn, body.question)
        return (
            evidence,
            reviews.published_matches(conn, body.question),
            policy.find_conflicts(conn, evidence),
        )


def save_answer(body, who, answer, evidence, reviewed, conflicts, started):
    conversation_id = body.conversation_id or new_id()
    message_id = new_id()
    with transaction(who.workspace) as conn:
        if not run(
            conn,
            "SELECT 1 FROM memberships WHERE user_id=:u AND workspace_id=:w",
            u=who.user_id,
            w=who.workspace,
        ).first():
            raise HTTPException(404, "workspace_not_found")
        for citation in answer.citations:
            row = run(
                conn,
                """SELECT c.id FROM chunks c JOIN document_versions v
              ON v.workspace_id=c.workspace_id AND v.id=c.version_id JOIN documents d
              ON d.workspace_id=v.workspace_id AND d.id=v.document_id
              WHERE c.id=:i AND NOT d.deleted AND d.active_version=v.id FOR SHARE OF d""",
                i=citation.source_id,
            ).first()
            if not row:
                raise HTTPException(409, "evidence_changed_please_retry")
        if not body.conversation_id:
            run(
                conn,
                "INSERT INTO conversations(id,workspace_id,user_id,title) VALUES(:i,:w,:u,:t)",
                i=conversation_id,
                w=who.workspace,
                u=who.user_id,
                t=body.question[:100],
            )
        result = answer.model_dump()
        result.update(
            {
                "mode": settings.generation_mode,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "reviewed_answers": reviewed,
                "conflicts": [
                    {k: c[k] for k in ("section", "source_ids", "prevailing_title", "note")}
                    for c in conflicts
                ],
                "sources": [
                    {k: v for k, v in e.items() if k not in {"content", "rank", "coverage"}}
                    for e in evidence
                ],
            }
        )
        run(
            conn,
            """INSERT INTO messages(id,workspace_id,conversation_id,question,answer)
          VALUES(:i,:w,:c,:q,CAST(:a AS jsonb))""",
            i=message_id,
            w=who.workspace,
            c=conversation_id,
            q=body.question,
            a=json.dumps(result),
        )
        for citation in answer.citations:
            run(
                conn,
                """INSERT INTO citations(id,workspace_id,message_id,chunk_id,quote)
              VALUES(:i,:w,:m,:c,:q)""",
                i=new_id(),
                w=who.workspace,
                m=message_id,
                c=citation.source_id,
                q=citation.quote,
            )
    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "question": body.question,
        **result,
    }


@app.get("/api/conversations")
def conversations(who: Who, offset: int = Query(0, ge=0)):
    with transaction(who.workspace) as conn:
        return [
            dict(r)
            for r in run(
                conn,
                """SELECT id,title,created_at FROM conversations
          WHERE user_id=:u ORDER BY created_at DESC LIMIT 50 OFFSET :o""",
                u=who.user_id,
                o=offset,
            ).mappings()
        ]


@app.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str, who: Who):
    with transaction(who.workspace) as conn:
        if not run(
            conn,
            "SELECT 1 FROM conversations WHERE id=:i AND user_id=:u",
            i=conversation_id,
            u=who.user_id,
        ).first():
            raise HTTPException(404, "conversation_not_found")
        return [
            {
                "message_id": r["id"],
                "question": r["question"],
                "conversation_id": conversation_id,
                **r["answer"],
            }
            for r in run(
                conn,
                """SELECT id,question,answer FROM messages WHERE conversation_id=:i
                  ORDER BY created_at LIMIT 100""",
                i=conversation_id,
            ).mappings()
        ]


class Feedback(BaseModel):
    helpful: bool


@app.post("/api/messages/{message_id}/feedback")
def feedback(message_id: str, body: Feedback, who: Who):
    with transaction(who.workspace) as conn:
        if not run(
            conn,
            """SELECT 1 FROM messages m JOIN conversations c
          ON c.workspace_id=m.workspace_id AND c.id=m.conversation_id
          WHERE m.id=:i AND c.user_id=:u""",
            i=message_id,
            u=who.user_id,
        ).first():
            raise HTTPException(404, "message_not_found")
        run(
            conn,
            """INSERT INTO feedback(id,workspace_id,message_id,user_id,helpful)
          VALUES(:i,:w,:m,:u,:h) ON CONFLICT(workspace_id,message_id,user_id)
          DO UPDATE SET helpful=excluded.helpful""",
            i=new_id(),
            w=who.workspace,
            m=message_id,
            u=who.user_id,
            h=body.helpful,
        )
    return {"status": "saved"}


class Review(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    note: str = Field(max_length=2000)
    message_id: str | None = None


@app.post("/api/reviews", status_code=201)
def create_review(body: Review, who: Who, key: IdempotencyKey = None):
    def operation(conn):
        review_id = reviews.create(conn, who, body.question, body.note, body.message_id)
        audit(conn, who, "review.create", review_id)
        return {"id": review_id, "status": "open"}

    with transaction(who.workspace) as conn:
        return once(conn, who, key, fingerprint("review", body.model_dump()), operation)


@app.get("/api/reviews")
def review_queue(who: Who, offset: int = Query(0, ge=0)):
    with transaction(who.workspace) as conn:
        return reviews.listing(conn, who, offset)


class Transition(BaseModel):
    action: Literal["claim", "release", "answer", "decline"]
    revision: int = Field(ge=0)
    resolution: str | None = Field(None, max_length=4000)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    publish: bool = False


@app.post("/api/reviews/{review_id}/transitions")
def review_transition(review_id: str, body: Transition, who: Who):
    with transaction(who.workspace) as conn:
        result = reviews.transition(
            conn,
            who,
            review_id,
            body.action,
            body.revision,
            body.resolution,
            body.source_ids,
            body.publish,
        )
        audit(conn, who, "review." + body.action, review_id)
    return result


@app.get("/api/settings")
def workspace_settings(who: Who):
    with transaction() as conn:
        used = (
            run(
                conn,
                "SELECT used FROM usage_buckets WHERE key=:k AND day=current_date",
                k="user:" + who.user_id,
            ).scalar()
            or 0
        )
    return {
        "role": who.role,
        "generation_mode": settings.generation_mode,
        "generation_enabled": settings.generation_enabled,
        "daily_used": used,
        "daily_limit": settings.user_daily_limit,
        "file_limit_mb": 10,
        "document_limit": 100,
        "supported_types": [".txt", ".md"],
        "retention_days": 30,
        "environment": settings.env,
    }
