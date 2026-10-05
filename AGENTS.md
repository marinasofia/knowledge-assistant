# Working agreement

Use plain punctuation, never em or en dashes. Keep changes small and test behavior with the change. Do not introduce attribution trailers in commits.

## Commands

- Backend: `cd backend && uv sync --frozen && uv run pytest -q`
- Format: `cd backend && uv run ruff format . && uv run ruff check .`
- UI: `cd frontend && npm ci && npm run build`
- Browser: start API, worker, and Vite, then `cd frontend && npm test`

## Trust boundaries

Never commit credentials, environment files, personal documents, local database contents, or machine-specific paths. Fictional fixtures only. Runtime database credentials must not own tables or bypass row security. Every source and workspace route must enforce access independently. Never allow model output to perform writes. Do not bypass a release gate or claim a test ran when it did not. Do not spawn additional agents without authorization.

## Security

Follow [SECURITY-RULES.md](SECURITY-RULES.md) for every change. Before this repo goes public, run the security kit scan and its publish checklist.
