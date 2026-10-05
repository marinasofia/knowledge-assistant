#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .data
if ! docker inspect knowledge-assistant-db >/dev/null 2>&1; then
  docker run -d --name knowledge-assistant-db -e POSTGRES_DB=knowledge -e POSTGRES_USER=knowledge_owner -e POSTGRES_PASSWORD=local-owner-only -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16
else
  docker start knowledge-assistant-db >/dev/null
fi
for attempt in {1..30}; do
  if docker exec knowledge-assistant-db pg_isready -U knowledge_owner -d knowledge >/dev/null; then break; fi
  sleep 1
done
(cd backend && uv sync --frozen && uv run alembic upgrade head && uv run python -m app.seed)
(cd frontend && npm ci)
(cd backend && KA_DEV_AUTH=true uv run uvicorn app.main:app --host 127.0.0.1 --port 8000) &
api_pid=$!
(cd backend && uv run python -m app.worker) &
worker_pid=$!
(cd frontend && npm run dev) &
ui_pid=$!
trap 'kill "$api_pid" "$worker_pid" "$ui_pid" 2>/dev/null || true' EXIT INT TERM
printf 'Workspace: http://127.0.0.1:5173\nPress Ctrl+C to stop the application.\n'
wait
