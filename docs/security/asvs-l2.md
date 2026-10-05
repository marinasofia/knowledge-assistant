# Security verification against OWASP ASVS level 2

Scope: the backend API, worker, and React client in this repository, running locally. Mapped by ASVS 4.0 chapter and described in plain terms. Confirm exact requirement numbers against the published ASVS 4.0.3 text before citing them externally.

Status values:
* **Met:** implemented, with the evidence listed.
* **Partial:** implemented in part; the gap is stated.
* **Not met:** missing.
* **Deployment:** can only be verified on real infrastructure.

No independent security review has been performed.

## V1 Architecture and threat modeling

| Control | Status | Evidence |
|---|---|---|
| Documented trust boundaries and threat model | Met | `docs/threat-model.md`, `docs/architecture.md` |
| Authorization enforced server side at a trusted layer | Met | `auth.identity`, `auth.admin`, PostgreSQL RLS policies in `migrations/versions/001_initial.py` |
| Least privilege for the runtime database role | Met | Role is `NOSUPERUSER NOBYPASSRLS` and not the table owner; `/api/health/ready` refuses an unsafe role; `test_runtime_rls_and_pool_context` |
| Security decisions not delegated to a model | Met | Precedence, abstention and conflict rules in `answers.generate`; `test_unresolved_conflict_never_reaches_the_model`, `test_uncovered_question_never_reaches_the_model` |

## V2 Authentication

| Control | Status | Evidence |
|---|---|---|
| Delegated authentication through OIDC with state and nonce | Partial | Authlib OIDC flow in `main.py`; never exercised against a real provider |
| Development login cannot run in production | Met | `config.Settings.validate_mode`; `test_production_rejects_demo_identity` |
| Rate limiting on authentication endpoints | Met | `limits.hit` on development and OIDC routes; `test_routes_enforce_rate_limits` |
| Multi-factor authentication | Deployment | Delegated to the identity provider's policy |

## V3 Session management

| Control | Status | Evidence |
|---|---|---|
| Opaque, high-entropy session tokens, stored only as hashes | Met | `secrets.token_urlsafe(32)`, SHA-256 in `auth.create_session` |
| Cookie flags HttpOnly, SameSite=Lax, Secure in production | Met | `auth.create_session` |
| Absolute session timeout | Met | 8 hours, enforced in the session query |
| Idle timeout | Met | Sessions end after 30 minutes without activity (`auth.IDLE_MINUTES`); `test_idle_session_expires` |
| CSRF token rotation | Accepted | One synchronizer token per session, bound to the server session and replaced at every sign in |
| Logout invalidates the server session | Met | `DELETE FROM sessions` in `/api/auth/logout` |

## V4 Access control

| Control | Status | Evidence |
|---|---|---|
| Deny by default, every route checks membership | Met | `identity` dependency on every workspace route; `test_anonymous_denied` |
| Tenant isolation even if a route forgets a filter | Met | FORCE RLS on all tenant tables; `test_second_workspace_ids_cannot_cross_endpoints`, `test_cross_workspace_insert_blocked` |
| Admin functions restricted | Met | `admin()` checks; `test_member_cannot_manage`, review transition tests |
| CSRF protection on state-changing requests | Met | Per-session token plus exact Origin check; `test_workspace_spoof_and_csrf` |
| Global tables outside RLS | Partial | `sessions`, `memberships`, `usage_buckets`, `rate_limits` are readable by the runtime role across tenants; isolation there relies on application queries |

## V5 Validation, sanitization and encoding

| Control | Status | Evidence |
|---|---|---|
| Typed request validation with bounds | Met | Pydantic models with lengths and limits in `main.py` |
| Parameterized SQL everywhere | Met | All queries use bound parameters; the only interpolated SQL fragments are code constants (`COVERAGE`, table names in fixed lists) |
| Output encoding for model and document text | Met | React renders text, never HTML; CSP `default-src 'self'`; `test_security_headers_on_every_response` |
| Upload type, size, encoding and control character checks | Met | `ingestion.validate_file`; `test_adversarial_uploads` |
| Structured model output validated before use | Met | `answer_schema.validate_answer`, `extra="forbid"`; `test_invalid_provider_output_rejected` |
| Indirect prompt injection in retrieved documents | Partial | Evidence passed as data, model output schema checked, fabricated sources rejected; `test_injection_inside_a_document_stays_quoted_data`. Free text inside a valid claim is not checked for entailment |

## V7 Errors and logging

| Control | Status | Evidence |
|---|---|---|
| Generic error responses with a request ID | Met | `guard` middleware and exception handlers in `main.py` |
| Logs avoid secrets and content | Met | Provider errors log only the exception class |
| Security events recorded | Met | `audit_events` for administrative actions; append-only `review_events` (`test_review_history_is_append_only`) |
| Centralized monitoring and alerting | Deployment | Structured JSON logs only |

## V8 Data protection

| Control | Status | Evidence |
|---|---|---|
| Retention for conversations and audit data | Met | `maintenance.maintain`; `test_retention_removes_old_messages` |
| No caching of sensitive responses | Met | `Cache-Control: no-store` on every response |
| Encryption at rest for database and objects | Deployment | Depends on the managed database and storage |
| Review request retention | Met | Resolved reviews removed 365 days after resolution with citations and history; open work never expires; `test_resolved_reviews_expire_after_a_year` |

## V9 Communications

| Control | Status | Evidence |
|---|---|---|
| TLS for all traffic | Deployment | Production startup requires an `https://` origin and OIDC discovery URL |

## V10 Malicious code and dependencies

| Control | Status | Evidence |
|---|---|---|
| Locked dependencies and audit in CI | Met | `uv.lock`, `package-lock.json`, `pip-audit` and `npm audit` in `.github/workflows/ci.yml` |
| Model weights loaded without remote code | Met | `trust_remote_code=False`, pinned revision in `embeddings.py` |

## V11 Business logic

| Control | Status | Evidence |
|---|---|---|
| Limits on expensive operations | Met | Daily paid quota, five global generation slots, per-user query and upload rate limits; `test_concurrent_cap`, `test_global_concurrency_leases` |
| Replay-safe writes | Met | Idempotency keys on uploads and review creation; `test_retried_upload_is_applied_once` |
| Concurrent updates cannot overwrite each other | Met | Revision compare-and-set on reviews; `test_concurrent_claims_have_one_winner` |

## V12 Files and resources

| Control | Status | Evidence |
|---|---|---|
| Server-generated storage names, no user paths | Met | UUID keys validated in `ingestion.object_path` |
| Files outside the web root with restrictive permissions | Met | Private storage directory, mode 0600 files |
| Orphaned files cleaned up | Met | `maintenance.sweep_orphans` with a one-hour quarantine; `test_orphan_sweeper_respects_references_and_quarantine` |
| Malware scanning of uploads | Not met | Plain text and Markdown only; required before external uploads |

## V13 API

| Control | Status | Evidence |
|---|---|---|
| Request size limits | Met | `guard` middleware rejects bodies over the limit or without a length |
| Consistent authorization on every method | Met | Covered by the V4 tests |

## V14 Configuration

| Control | Status | Evidence |
|---|---|---|
| Production refuses unsafe configuration | Met | `Settings.validate_mode` fails closed; release gate in `docs/release.md` |
| Security headers | Met | CSP, `nosniff`, `Referrer-Policy`, `frame-ancestors 'none'` |
| Secrets outside the repository | Met | `.env` ignored; `scripts/check_repository.py` in CI |

## Open items, in priority order

1. Row-level security or a separate schema for global tables (V4).
2. Malware scanning or content disarm before accepting external uploads (V12).
3. Real OIDC provider integration test, TLS, encryption at rest and alerting (V2, V7, V8, V9), which need a deployment.
