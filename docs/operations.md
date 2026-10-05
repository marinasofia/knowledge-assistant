# Local operations and release preparation

## Start and stop

Install Docker, Node 22, Python 3.12, and uv 0.12.3. From the repository root, run `./scripts/dev.sh`. Open http://127.0.0.1:5173 and enter the fictional member or administrator workspace. Ctrl+C stops the application processes. The named local database container retains data. Use `docker stop knowledge-assistant-db` to stop it. Never use demo database passwords on a network-accessible database.

Manual commands are listed in README.md. Docker Compose is an alternative database launcher; do not start both launchers on the same port. Health routes: `/api/health/live` and `/api/health/ready`. Interactive typed API documentation: `/docs` on the backend port.

## Optional semantic retrieval

From backend, run `uv sync --frozen --extra semantic`, then `uv run --extra semantic python -m app.reindex`. This downloads the pinned Apache-2.0 MiniLM model and embeds the approved fictional corpus. Set `KA_SEMANTIC_SEARCH=true` for both API and worker. Every new document version records its embedding model revision. Retrieval uses exact pgvector distance and reciprocal rank fusion with the keyword baseline. No approximate index exists. Never mix incompatible vector models.

## Provider mode and budgets

Set `KA_GENERATION_MODE=anthropic`, `KA_ANTHROPIC_API_KEY`, and the reviewed model ID in an ignored environment file. The supported budget-reviewed model is `claude-haiku-4-5-20251001`. Local evidence mode is the default. It is passage extraction, not a simulated provider response.

Per request: one generation call, no SDK retries, 1500 output tokens, at most five passages totaling at most 8000 UTF-8 content bytes, 25-second provider timeout, and 28-second generation deadline. A five-slot PostgreSQL lease semaphore bounds concurrent workflows across API processes. Slots expire after 40 seconds for crash recovery. DB statements time out at five seconds. These are component budgets; the entire HTTP lifecycle still needs a deployment-level deadline.

Atomic daily reservations cap 30 user, 100 workspace, and 200 global attempts by default. Failed calls consume reservations. At the verified model price of $1 per million input tokens and $5 per million output tokens, a conservative $0.10 upper reservation per bounded call yields a $20 daily ceiling at default settings. This is a conservative bound, not a provider billing reconciliation. Changes to pricing, model, prompt size, tokenization, or limits require a new budget review. Actual provider usage reconciliation and live cost measurement are not release-verified. Set `KA_GENERATION_ENABLED=false` and restart the API to pause answers while keeping document operations available.

Reference: https://platform.claude.com/docs/en/models/overview

## Backup and restore

Back up PostgreSQL with the migration/operator role and private object storage together. Encrypt backups and keep credentials out of command logs. Example for fictional local data:

```sh
docker exec knowledge-assistant-db pg_dump -U knowledge_owner -d knowledge -Fc > knowledge.dump
docker exec -i knowledge-assistant-db pg_restore -U knowledge_owner -d knowledge_restore < knowledge.dump
```

Create an empty restore database first, restore into it, compare record counts and exact sample passages, then run the tenant and deletion invariants under the runtime role. Do not overwrite the live database while rehearsing recovery. Object backups must match each version's content hash. Database-only recovery does not recover stored uploads.

## Migrations and rollback

Use separate operator credentials in `KA_MIGRATION_URL`. Run `uv run alembic upgrade head` before API startup. The application role must never run migrations or own tables. Back up before migration. On a release failure, stop traffic and the worker, restore the prior compatible application image, and verify the schema is compatible. Prefer a forward repair; downgrades can delete application data and require a reviewed backup and restore plan.

## Retention and deletion

Run `uv run python -m app.maintenance` daily through the operator scheduler. It removes expired sessions, messages older than 30 days with their citations and feedback, empty expired conversations, audit records older than 90 days, and deleted-document objects/chunks. The worker also retries physical document cleanup. Review requests currently require an explicit operator retention policy before production use. The document version metadata and tombstones are intentionally retained. Historical answer text can retain excerpts until message retention or a scoped erasure action.

An upload file may be orphaned if the database commit fails after its object is written. Before external uploads, add a reconciler that safely removes objects not referenced by any version after a quarantine interval. The local adapter is development-only. Hosted private S3 storage, parser isolation, malware policy, and operational alerting remain release work.
