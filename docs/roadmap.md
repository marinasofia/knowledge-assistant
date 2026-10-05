# Development roadmap

1. Architecture: follow a question from browser to evidence. Exercise: identify each trust boundary. Interview question: why is a prompt not an authorization boundary?
2. Services and isolation: run migrations and tenant tests. Exercise: add a member fixture. Interview question: why use transaction-local database settings?
3. Ingestion: trace queued, processing, ready, and failed states. Exercise: test a replacement failure. Interview question: how can a stale worker corrupt a newer version?
4. Retrieval and answers: compare exact passages to generated claims. Exercise: add an unanswered question. Interview question: what does citation validation actually prove?
5. Interface and review: submit an explicit review request. Exercise: add a keyboard shortcut. Interview question: why must model output never submit that action?
6. Release: evaluate held-out data and operational recovery. Exercise: rehearse restore in a disposable database. Interview question: why is a successful build insufficient release evidence?
