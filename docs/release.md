# Release evidence

## Verified locally

- 23 pytest checks passed, including real PostgreSQL RLS under a non-owner runtime role, pool context isolation, actual second-workspace source/conversation/document/review/feedback denial, revoked membership, CSRF, member restrictions, citation rejection, atomic versions, deletion, three-attempt retries, concurrent daily caps, and a five-slot global lease limit.
- Four Playwright workflows passed: member questions and source viewing, explicit review submission, administrator upload/replacement/deletion, narrow layout navigation, and keyboard abstention. Desktop and mobile screenshots were inspected.
- TypeScript checks and the Vite production build passed. Python lint and formatting passed.
- Frontend and backend dependency audits, including the optional semantic runtime, reported no known vulnerabilities at build time. A tracked-file credential-pattern scan passed. This is not a comprehensive secret-detection guarantee.
- The actual pinned MiniLM model indexed 22 passages. Development recall was 37/39 labeled passages for keyword and 36/39 for hybrid. Held-out recall was 16/16 for both. Labels are draft and not human-reviewed. No tuning followed the held-out run. Keyword remains the default.
- A five-client, 20-request in-process ASGI load smoke test against PostgreSQL had 0 errors, p50 63.585 ms and p95 117.33 ms on arm64 macOS. It excludes HTTP network and live provider latency and is not a service guarantee.
- Alembic migrated an empty PostgreSQL database through revision 003. A custom-format dump restored into a new disposable database with six active documents and 22 chunks. The runtime role saw six workspace documents inside trusted context and zero after the transaction. The disposable restore database was removed. Object-storage recovery and full deployment rollback were not exercised.

## Unverified release gates

Production startup intentionally fails closed. Before a private hosted pilot:

1. Configure and test managed OIDC against the chosen real tenant, provision memberships out of band, and exercise secure cookies and CSRF on the actual HTTPS origin.
2. Add and test private hosted object storage, orphan reconciliation, parser isolation, and a malware/content-disarm decision before external uploads. PDF remains disabled.
3. Run the live Anthropic suite with approved credentials and budget. Measure claim support, abstention, conflict handling, actual token usage, cost reconciliation, and deployment latency. No paid model calls were made during this build.
4. Human-review the 60-case corpus and expected evidence. Draft retrieval scores cannot satisfy human grounding gates.
5. Exercise full object plus database restore, deletion verification, retention scheduling, deployment rollback, and operational alerting. Set a retention policy for review requests.
6. Add deployment-level HTTP deadlines and enforce streaming-body limits independent of Content-Length. The local server currently relies on a bounded Content-Length plus file read validation.
7. Provision least-privilege production credentials, replace all local-only passwords, review migration privileges, pin deployment image digests, and perform an independent security review.

GitHub publication is source-code delivery. It does not deploy the application or certify these gates.
