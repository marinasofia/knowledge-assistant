# Architecture decisions

## 001: Modular monolith

The browser calls a same-origin API. The API verifies identity, selects an authorized membership, and sets transaction-local tenant context. PostgreSQL RLS provides a second boundary. The runtime role is neither the table owner nor a bypass role. A separate worker leases ingestion jobs and activates complete document versions atomically.

## 002: Identity

Hosted identity uses a managed OIDC provider with authorization code flow, state and nonce, server-side token validation, and an opaque server-side session. Auth0 is the reference provider, configured through discovery. Cookies are HttpOnly, SameSite=Lax, and Secure in production. Cookie mutations require a per-session CSRF token and same-origin checks. Local demo login is explicitly enabled only in development and selects fictional seeded users. It is forbidden in production.

## 003: Retrieval and generation

The first runnable mode uses PostgreSQL full-text retrieval and verbatim evidence extraction. It is explicitly labeled as local evidence mode. It makes no paid calls and does not claim semantic reasoning. The live adapter uses Anthropic with validated source IDs and exact quotes. No model tools or model-initiated writes exist. Generation requires explicit configuration and capped reservations before calls.

Local sentence-transformers embeddings are an optional extra because model weights and a machine-learning runtime materially increase installation size. The pinned all-MiniLM-L6-v2 model produces 384-dimensional vectors, uses an Apache-2.0 license, and must run with remote code disabled. Reserve at least 1 GB for the worker; measure actual peak memory before hosting. Hybrid search requires vectors from the same revision at query and ingestion time. Keyword mode remains a labeled baseline, never a fake vector implementation.

## 004: Hosting and storage

The Python API and worker require a container host with PostgreSQL and private storage. A frontend-only Worker host cannot run this backend. No hosting registration or deployment is required to save this application to GitHub. Development uses private local storage. External uploads and PDF parsing remain disabled unless the documented parser sandbox and storage requirements are satisfied.

## 005: Retention

Deletion removes documents from retrieval and source viewing immediately. Physical cleanup is retryable. Old versions stay inactive. Historical answer text may retain excerpts; conversation retention is separate, defaults to 30 days, and must be included in erasure procedures. No shared answer cache.

## Sources

- https://ui.shadcn.com/blocks?category=dashboard
- https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- https://github.com/pgvector/pgvector
- https://platform.claude.com/docs/en/models/overview
- https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2

## 006: Keep keyword retrieval as the default

The actual local embedding run did not improve the small draft development set: keyword passage recall was 37/39 versus 36/39 for hybrid. Both reached 16/16 on the separate held-out subset. Retain semantic retrieval as an explicit optional mode and keep keyword default. Do not infer human grounding quality from these draft-label retrieval scores.

Update, Sep 28 2026: with deterministic tie-breaks and nDCG, hybrid scores slightly higher on both splits, but a paired randomization test gives p = 0.19 and 0.25, so there is no demonstrated difference. Keyword stays the default because it matches quality within measurement error while avoiding a machine-learning runtime, model download, and vector maintenance. Revisit when the labeled set is large enough to detect a difference of this size.

## 007: Human review is a state machine

Review requests move `open` to `claimed`, then to `answered` or `declined`; a claimer can `release` back to `open`. The allowed transitions live in one table in `backend/app/reviews.py`, so an illegal move is a lookup failure, not a scattered conditional. Only admins claim, and only the claimer resolves, which gives each answer one accountable author.

Every transition is a compare-and-set: the client sends the `revision` it saw, and the update matches only if the row still has it. Two admins who claim at once both read revision 0; PostgreSQL serializes their updates on the row lock, the second update rechecks its `WHERE` clause against the committed row, matches nothing, and returns 409. This is optimistic concurrency (Kung and Robinson, 1981): no lock is held while a person reads and types, and conflicts are detected at write time. A pessimistic lock would hold a database lock for minutes of human thinking.

Answers cite passages only if they are active at answer time, and each citation stores the version ID, section, and quote as a snapshot. Cleanup deletes passages of deleted documents, so citations must not depend on `chunks` rows to stay readable. The version ID is what lets a later change mark a published answer as resting on superseded policy.

Not yet built: published answers are not shown to future askers, and a superseded citation is displayed but does not reopen the review. Review requests still need a retention rule.

## 008: Passages follow document structure and keep their identity

Passages are paragraphs under their full heading path. A paragraph longer than 1,200 characters is packed from whole sentences, and only a single sentence longer than the limit is cut, at a space. The earlier fixed 1,200 character windows could split a rule mid-sentence and made quotes arbitrary.

Each passage has a content key: a hash of its section path and whitespace-normalized text. The same paragraph under the same heading has the same key in every version, which makes a version diff a set comparison per section (added, removed, changed, unchanged) instead of a text diff over the whole file. The key includes the section path on purpose: identical words under a different heading can mean a different rule. Chunk IDs stay per version, because citations must name the exact text that was shown.

## 009: Policy metadata and precedence are data, not model judgment

Owner and effective date come from an optional front matter header, validated at upload so a bad date is rejected before any work is queued. A version effective in the future is processed but stored as `scheduled`; the worker activates it when the date arrives, or marks it `superseded` if a newer upload overtook it. Dates use the database's `current_date`, so one clock decides.

A conflict is two active documents giving different figures under the same section title, and it only decides the outcome when the best matching passage is one of them. The result is `conflict` in every mode and no model is called. An administrator can declare which document prevails for a section, with a reason; answers then lead with the governing passage and state the rule. Precedence is never inferred, because choosing which policy governs is an organizational decision with an accountable owner, and a model's choice would be neither auditable nor stable. The rule is narrow by design: it misses disagreements under different titles or without figures, and those still reach human review.

## 010: Two replaceable interfaces around fixed decision rules

`generators.py` defines a relevance gate (does the evidence cover the question) and a generator (turn evidence into an answer). The coverage rule and evidence mode are one implementation each; Claude is a second generator, and a Jev relevance gate would be a second gate, selected by configuration and compared on the same evaluation cases. The decision order stays in `answers.generate`: no evidence, not covered, unresolved conflict, then the generator. Adapters cannot skip a step, so a new model can change wording but not whether the system abstains or reports a conflict. The gate runs in every mode, so an uncovered question never becomes a paid call.

In Claude mode an answer is a list of claims, each citing at least one exact quote, and every quote must support some claim. This is structural attribution: it proves each sentence points at real approved text, not that the text entails the sentence (Rashkin et al., 2023, separate these). Entailment still needs human review or a separately measured judge.
