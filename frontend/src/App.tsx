import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileText,
  FolderOpen,
  Inbox,
  LoaderCircle,
  Menu,
  MessageSquare,
  Plus,
  Search,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  api,
  configure,
  post,
  postOnce,
  type Answer,
  type Conversation,
  type Document,
  type PrecedenceRule,
  type Review,
  type Session,
  type Settings,
} from "./api";
import { Sidebar, type View } from "./Sidebar";
import { ReviewCard } from "./ReviewCard";
import { ConflictResolver, PrecedenceList } from "./PolicyPanels";
import { VersionDiff, type Diff } from "./VersionDiff";

const starters = [
  {
    topic: "WORKPLACE",
    question: "What is the home office equipment allowance?",
    query: "home office equipment allowance",
    icon: FolderOpen,
  },
  {
    topic: "PEOPLE",
    question: "How much annual leave can I carry over?",
    query: "annual leave carryover",
    icon: Clock3,
  },
  {
    topic: "EXPENSES",
    question: "What is the daily meal allowance?",
    query: "meal allowance",
    icon: FileText,
  },
];
const date = (value: string) =>
  new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

export default function App() {
  const [session, setSession] = useState<Session | null>(null),
    [loading, setLoading] = useState(true),
    [dev, setDev] = useState(false),
    [oidc, setOidc] = useState(false);
  const [view, setView] = useState<View>("Ask"),
    [mobile, setMobile] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [history, setHistory] = useState<Conversation[]>([]),
    [documents, setDocuments] = useState<Document[]>([]),
    [reviews, setReviews] = useState<Review[]>([]),
    [rules, setRules] = useState<PrecedenceRule[]>([]),
    [diff, setDiff] = useState<{ title: string; data: Diff } | null>(null),
    [settings, setSettings] = useState<Settings | null>(null);
  const [question, setQuestion] = useState(""),
    [answers, setAnswers] = useState<Answer[]>([]),
    [busy, setBusy] = useState(false),
    [filter, setFilter] = useState("");
  const [source, setSource] = useState<{
      title: string;
      section: string;
      section_path: string;
      content: string;
      version: number;
      owner: string | null;
      effective_from: string | null;
      paragraph: number;
      section_passages: { id: string; content: string; cited: boolean }[];
    } | null>(null),
    [sourceError, setSourceError] = useState(""),
    [sourceBusy, setSourceBusy] = useState(false);
  const [reviewDraft, setReviewDraft] = useState<string | null>(null),
    [reviewMessage, setReviewMessage] = useState<string | null>(null),
    [reviewKey, setReviewKey] = useState(""),
    [reviewNote, setReviewNote] = useState(""),
    [deleteId, setDeleteId] = useState<string | null>(null),
    [replacement, setReplacement] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null),
    questionInput = useRef<HTMLTextAreaElement>(null),
    reviewDialog = useRef<HTMLDialogElement>(null);
  const isAdmin = session?.workspaces[0]?.role === "admin";
  async function loadSession() {
    const s = await api<Session>("/session");
    configure(s);
    setSession(s);
    return s;
  }
  async function refresh() {
    const [h, d, r, s, p] = await Promise.all([
      api<Conversation[]>("/conversations"),
      api<Document[]>("/documents"),
      api<Review[]>("/reviews"),
      api<Settings>("/settings"),
      api<PrecedenceRule[]>("/precedence"),
    ]);
    setRules(p);
    setHistory(h);
    setDocuments(d);
    setReviews(r);
    setSettings(s);
  }
  useEffect(() => {
    Promise.all([
      api<{ development_login: boolean; oidc_enabled: boolean }>(
        "/auth/config",
      ).then((c) => {
        setDev(c.development_login);
        setOidc(c.oidc_enabled);
      }),
      loadSession().catch(() => {}),
    ])
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (session) refresh().catch((e) => setError(e.message));
  }, [session]);
  useEffect(() => {
    if (
      !session ||
      !documents.some((d) => d.status === "queued" || d.status === "processing")
    )
      return;
    const timer = setInterval(
      () =>
        api<Document[]>("/documents")
          .then(setDocuments)
          .catch((e) => setError(e.message)),
      2000,
    );
    return () => clearInterval(timer);
  }, [session, documents]);
  const reviewOpen = reviewDraft !== null;
  useEffect(() => {
    // One key per opened dialog: double submits and retries create a single request.
    if (reviewOpen) setReviewKey(crypto.randomUUID());
  }, [reviewOpen]);
  useEffect(() => {
    if (reviewDraft !== null) reviewDialog.current?.showModal();
    else reviewDialog.current?.close();
  }, [reviewDraft]);
  function navigate(next: View) {
    setView(next);
    setMobile(false);
    setError("");
    setNotice("");
    if (next === "Ask") {
      setAnswers([]);
      setSource(null);
      setSourceError("");
      setQuestion("");
    }
    if (session) refresh().catch((e) => setError(e.message));
  }
  async function login(role: string) {
    setBusy(true);
    setError("");
    try {
      await post("/auth/development", { role });
      await loadSession();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    try {
      await post("/auth/logout");
      setSession(null);
      setAnswers([]);
      setHistory([]);
      setSource(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function ask(value = question) {
    if (value.trim().length < 3 || busy) return;
    setBusy(true);
    setError("");
    setSource(null);
    setSourceError("");
    try {
      const answer = await post<Answer>("/query", {
        question: value.trim(),
        conversation_id: answers[0]?.conversation_id,
      });
      setAnswers((old) => [...old, answer]);
      setQuestion("");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openConversation(id: string) {
    setError("");
    setView("Ask");
    setMobile(false);
    setSource(null);
    setSourceError("");
    try {
      setAnswers(await api<Answer[]>("/conversations/" + id));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function openSource(id: string) {
    setSource(null);
    setSourceError("");
    setSourceBusy(true);
    try {
      setSource(await api("/sources/" + id));
    } catch (e) {
      setSourceError((e as Error).message);
    } finally {
      setSourceBusy(false);
    }
  }
  async function upload(file: File) {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      await api(
        replacement ? "/documents/" + replacement + "/versions" : "/documents",
        {
          method: "POST",
          body: form,
          headers: { "Idempotency-Key": crypto.randomUUID() },
        },
      );
      setNotice("Document received. Ingestion is queued.");
      setReplacement(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function action(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    try {
      await fn();
      setNotice(success);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (loading)
    return (
      <div className="loading-screen">
        <LoaderCircle className="spin" />
        <p>Opening your workspace...</p>
      </div>
    );
  if (!session)
    return (
      <div className="login-shell">
        <div className="login-story">
          <div className="brand">
            <BookOpen /> Knowledge Assistant
          </div>
          <div>
            <p className="eyebrow">YOUR TEAM'S KNOWLEDGE, CONNECTED</p>
            <h1>
              Good answers.
              <br />
              Clear sources.
            </h1>
            <p>
              Find what you need in the policies your team has approved. Keep
              the evidence close.
            </p>
          </div>
          <small>Northstar Studio is a fictional company.</small>
        </div>
        <main className="login-panel">
          <span className="login-symbol">
            <BookOpen size={28} />
          </span>
          <h2>Welcome to your workspace</h2>
          <p>Policies, procedures, and the answers behind them.</p>
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          {oidc && (
            <a className="primary" href="/api/auth/login">
              Sign in with your organization <ArrowUpRight size={18} />
            </a>
          )}
          {dev && (
            <>
              <button
                className="primary"
                disabled={busy}
                onClick={() => login("member")}
              >
                Explore demo workspace <ArrowUpRight size={18} />
              </button>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => login("admin")}
              >
                Enter as demo administrator
              </button>
              <p className="small muted">
                Local development access. Uses fictional policies and makes no
                paid calls in evidence mode.
              </p>
            </>
          )}
          {!dev && !oidc && (
            <p className="alert">
              Sign-in is not configured. Follow the local setup instructions to
              enable development access.
            </p>
          )}
          <div className="login-trust">
            <ShieldCheck size={17} /> Sources stay within your workspace
          </div>
        </main>
      </div>
    );
  return (
    <div className="app-shell">
      <Sidebar
        view={view}
        navigate={navigate}
        history={history}
        openConversation={openConversation}
        session={session}
        logout={logout}
        open={mobile}
        close={() => setMobile(false)}
      />
      <div className="workspace-main">
        <header className="topbar">
          <div>
            <button
              className="mobile-toggle icon-button"
              aria-label="Open navigation"
              onClick={() => setMobile(true)}
            >
              <Menu size={20} />
            </button>
            <span className="muted">Workspace</span>
            <ChevronRight size={14} />
            <strong>{view}</strong>
          </div>
          <span className="mode-pill">
            <ShieldCheck size={14} />
            {session.mode === "evidence"
              ? "Local evidence mode"
              : "Grounded answers"}
          </span>
        </header>
        {error && (
          <div role="alert" className="alert global-alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div role="status" className="notice">
            {" "}
            <Check size={16} />
            {notice}
            <button
              aria-label="Dismiss notification"
              onClick={() => setNotice("")}
            >
              <X size={16} />
            </button>
          </div>
        )}
        {view === "Ask" && (
          <div className="ask-layout">
            <main className="ask-main">
              <div className="page-heading">
                <div>
                  <p className="eyebrow">ASK YOUR KNOWLEDGE BASE</p>
                  <h1>Answers you can trace.</h1>
                  <p>Start with a question. Follow it to the source.</p>
                </div>
                <span className="heading-symbol">
                  <MessageSquare size={24} />
                </span>
              </div>
              <div className="conversation-space" aria-live="polite">
                {answers.length === 0 ? (
                  <>
                    <div className="welcome-note">
                      <span className="welcome-icon">
                        <BookOpen size={23} />
                      </span>
                      <h2>What would you like to know?</h2>
                      <p>
                        Ask about your team's policies and everyday procedures.
                      </p>
                    </div>
                    <div className="starter-grid">
                      {starters.map((s) => (
                        <button
                          className="starter"
                          key={s.topic}
                          disabled={busy}
                          onClick={() => {
                            setQuestion(s.question);
                            questionInput.current?.focus();
                          }}
                        >
                          <s.icon size={20} />
                          <span className="eyebrow">{s.topic}</span>
                          <strong>{s.question}</strong>
                          <ArrowUpRight size={17} />
                        </button>
                      ))}
                    </div>
                    <div className="knowledge-caption">
                      <ShieldCheck size={16} />
                      {documents.filter((d) => d.active_version).length}{" "}
                      approved documents in your workspace
                      <ChevronRight size={14} />
                    </div>
                  </>
                ) : (
                  answers.map((a, index) => (
                    <article key={a.message_id} className="answer-thread">
                      <div className="question-line">
                        <span className="user-label">QUESTION</span>
                        <h2>{a.question}</h2>
                      </div>
                      <div className="answer-card">
                        <div className="answer-header">
                          <strong className="verdict">
                            {a.status === "abstain"
                              ? "Not covered by approved policy"
                              : a.status === "conflict"
                                ? "Policies conflict"
                                : "Covered by approved policy"}
                          </strong>
                          <span className="status method">
                            {a.mode === "evidence"
                              ? "Exact passages"
                              : "Model answer, citations checked"}
                          </span>
                        </div>
                        {a.reviewed_answers?.map((ra) => (
                          <section
                            className="reviewed-answer"
                            key={ra.review_id}
                          >
                            <p className="eyebrow">REVIEWED ANSWER</p>
                            <p>
                              <strong>{ra.question}</strong>
                            </p>
                            <p>{ra.resolution}</p>
                            {ra.citations.map((c) => (
                              <small key={c.source_id} className="muted">
                                {c.title}, {c.section}, v{c.version}.{" "}
                              </small>
                            ))}
                            <small className="muted">
                              Reviewed {date(ra.resolved_at)}
                            </small>
                          </section>
                        ))}
                        {a.claims?.length ? (
                          <ol className="claims">
                            {a.claims.map((c, i) => (
                              <li key={i}>
                                {c.text}{" "}
                                {c.citations.map((n) => (
                                  <sup key={n}>[{n + 1}]</sup>
                                ))}
                              </li>
                            ))}
                          </ol>
                        ) : (
                          <p>{a.text}</p>
                        )}
                        {a.citations.map((c, i) => {
                          const meta = a.sources.find(
                            (s) => s.source_id === c.source_id,
                          );
                          return (
                            <button
                              className="citation"
                              key={c.source_id}
                              onClick={() => openSource(c.source_id)}
                            >
                              <span className="citation-number">{i + 1}</span>
                              <span>
                                <span className="citation-title">
                                  {meta?.title || "Approved source"}
                                  <span>v{meta?.version}</span>
                                </span>
                                <span className="quote">{c.quote}</span>
                                <span className="citation-link">
                                  View exact source <ArrowUpRight size={13} />
                                </span>
                              </span>
                            </button>
                          );
                        })}
                        {isAdmin && a.status === "conflict" && (
                          <ConflictResolver
                            answer={a}
                            busy={busy}
                            action={action}
                          />
                        )}
                        {a.gaps.length > 0 && (
                          <div className="evidence-note">
                            <CircleHelp size={16} />
                            <div>
                              {a.gaps.map((g) => (
                                <p key={g}>{g}</p>
                              ))}
                            </div>
                          </div>
                        )}
                        <div className="answer-footer">
                          <span>Was this useful?</span>
                          <button
                            title="Helpful"
                            aria-label={
                              "Mark answer " + (index + 1) + " helpful"
                            }
                            onClick={() =>
                              action(
                                () =>
                                  post(
                                    "/messages/" + a.message_id + "/feedback",
                                    { helpful: true },
                                  ),
                                "Feedback saved.",
                              )
                            }
                          >
                            <ThumbsUp size={15} />
                          </button>
                          <button
                            title="Not helpful"
                            aria-label={
                              "Mark answer " + (index + 1) + " not helpful"
                            }
                            onClick={() =>
                              action(
                                () =>
                                  post(
                                    "/messages/" + a.message_id + "/feedback",
                                    { helpful: false },
                                  ),
                                "Feedback saved.",
                              )
                            }
                          >
                            <ThumbsDown size={15} />
                          </button>
                          <button
                            className="review-link"
                            onClick={() => {
                              setReviewDraft(a.question);
                              setReviewMessage(a.message_id);
                              setReviewNote("");
                            }}
                          >
                            Request human review <ArrowUpRight size={14} />
                          </button>
                        </div>
                      </div>
                    </article>
                  ))
                )}
                {busy && (
                  <div className="thinking" role="status">
                    <LoaderCircle className="spin" size={17} /> Finding and
                    checking approved passages...
                  </div>
                )}
              </div>
              <form
                className="composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  ask();
                }}
              >
                <label htmlFor="question" className="sr-only">
                  Ask a question
                </label>
                <textarea
                  ref={questionInput}
                  id="question"
                  placeholder="Ask a question about your team's policies..."
                  value={question}
                  maxLength={2000}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      ask();
                    }
                  }}
                />
                <div className="composer-bottom">
                  <span>
                    <BookOpen size={14} /> Workspace documents only
                  </span>
                  <button
                    className="send-button"
                    type="submit"
                    disabled={busy || question.trim().length < 3}
                    aria-label="Send question"
                  >
                    {busy ? (
                      <LoaderCircle size={19} className="spin" />
                    ) : (
                      <ArrowUp size={20} />
                    )}
                  </button>
                </div>
              </form>
              <p className="composer-hint">
                Answers depend on available evidence. Always check the source.
              </p>
            </main>
            <aside className="source-panel" aria-label="Source passages">
              <div className="source-heading">
                <h2>
                  <BookOpen size={18} /> Sources
                </h2>
                <span>
                  {source ? "1 OPEN" : answers.at(-1)?.citations.length || 0}
                </span>
              </div>
              {sourceBusy ? (
                <div className="source-empty">
                  <LoaderCircle className="spin" />
                  <p>Loading source...</p>
                </div>
              ) : sourceError ? (
                <div role="alert" className="source-empty">
                  <CircleHelp />
                  <h3>Source unavailable</h3>
                  <p>{sourceError}</p>
                </div>
              ) : source ? (
                <div className="source-detail">
                  <span className="file-type">APPROVED DOCUMENT</span>
                  <h3>{source.title}</h3>
                  <p className="pinpoint">
                    {source.section_path.split(" > ").join(" › ")}, version{" "}
                    {source.version}, paragraph {source.paragraph}
                  </p>
                  <dl className="provenance">
                    <dt>Owner</dt>
                    <dd>{source.owner || "Not declared"}</dd>
                    <dt>Effective</dt>
                    <dd>
                      {source.effective_from
                        ? date(source.effective_from)
                        : "Not declared"}
                    </dd>
                  </dl>
                  <hr />
                  <h4>{source.section}</h4>
                  <div className="section-text">
                    {source.section_passages.map((p) =>
                      p.cited ? (
                        <mark key={p.id} className="cited">
                          {p.content}
                        </mark>
                      ) : (
                        <p key={p.id}>{p.content}</p>
                      ),
                    )}
                  </div>
                  <div className="source-assurance">
                    <ShieldCheck size={16} /> Access checked when opened
                  </div>
                </div>
              ) : (
                <>
                  <div className="source-empty">
                    <div className="source-empty-icon">
                      <FileText size={28} />
                    </div>
                    <h3>See where answers come from</h3>
                    <p>
                      Open a citation to read its exact passage and document
                      version.
                    </p>
                  </div>
                  <div className="source-principles">
                    <p className="eyebrow">BUILT AROUND EVIDENCE</p>
                    <div>
                      <Check size={15} />
                      <span>Approved workspace documents</span>
                    </div>
                    <div>
                      <Check size={15} />
                      <span>Exact, verifiable passages</span>
                    </div>
                    <div>
                      <Check size={15} />
                      <span>Missing evidence made visible</span>
                    </div>
                  </div>
                </>
              )}
            </aside>
          </div>
        )}
        {view === "Documents" && (
          <main className="content-page">
            <div className="page-heading">
              <div>
                <p className="eyebrow">YOUR SOURCE OF TRUTH</p>
                <h1>Documents</h1>
                <p>Keep your team's approved knowledge in one place.</p>
              </div>
              {isAdmin && (
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => {
                    setReplacement(null);
                    fileInput.current?.click();
                  }}
                >
                  <Plus size={18} /> Upload document
                </button>
              )}
            </div>
            <input
              ref={fileInput}
              type="file"
              accept=".txt,.md"
              className="sr-only"
              aria-label="Upload document file"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload(file);
              }}
            />
            <div className="document-summary">
              <div>
                <FolderOpen size={22} />
                <strong>{documents.length}</strong>
                <span>documents</span>
              </div>
              <div>
                <ShieldCheck size={22} />
                <strong>
                  {documents.filter((d) => d.active_version).length}
                </strong>
                <span>available to your team</span>
              </div>
              <div>
                <Clock3 size={22} />
                <strong>
                  {
                    documents.filter((d) =>
                      ["queued", "processing"].includes(d.status),
                    ).length
                  }
                </strong>
                <span>processing</span>
              </div>
            </div>
            <div className="list-toolbar">
              <h2>
                Document library <span>{documents.length}</span>
              </h2>
              <label className="search-box">
                <Search size={17} />
                <input
                  aria-label="Search documents"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder="Find a document..."
                />
              </label>
            </div>
            <div className="document-list">
              <div className="document-columns">
                <span>DOCUMENT NAME</span>
                <span>STATUS</span>
                <span>VERSION</span>
                <span>ADDED</span>
                <span />
              </div>
              {documents
                .filter((d) =>
                  d.title.toLowerCase().includes(filter.toLowerCase()),
                )
                .map((d) => (
                  <div className="document-row" key={d.id}>
                    <div className="document-title">
                      <span className="document-icon">
                        <FileText size={20} />
                      </span>
                      <div>
                        <strong>{d.title}</strong>
                        <small>
                          {d.owner && d.owner + " · "}
                          {d.effective_from &&
                            "effective " + date(d.effective_from) + " · "}
                          {d.passages} passages
                          {d.error ? " · " + d.error.replaceAll("_", " ") : ""}
                        </small>
                      </div>
                    </div>
                    <span className={"status " + d.status}>
                      {d.status === "ready"
                        ? "Ready"
                        : d.status === "scheduled"
                          ? "Scheduled"
                          : d.status}
                    </span>
                    <span className="version-tag">v{d.version}</span>
                    {d.version > 1 && (
                      <button
                        className="secondary compact"
                        onClick={() =>
                          api<Diff>(
                            `/documents/${d.id}/diff?from=${d.version - 1}&to=${d.version}`,
                          )
                            .then((data) => setDiff({ title: d.title, data }))
                            .catch((e) => setError(e.message))
                        }
                      >
                        Compare with previous
                      </button>
                    )}
                    <span className="muted document-date">
                      {date(d.created_at)}
                    </span>
                    <div className="row-actions">
                      {isAdmin && (
                        <>
                          {d.status === "failed" && (
                            <button
                              onClick={() =>
                                action(
                                  () => post("/documents/" + d.id + "/retry"),
                                  "Retry queued.",
                                )
                              }
                              disabled={busy}
                            >
                              Retry
                            </button>
                          )}
                          <button
                            className="icon-button"
                            aria-label={"Replace " + d.title}
                            title="Replace document"
                            disabled={busy}
                            onClick={() => {
                              setReplacement(d.id);
                              fileInput.current?.click();
                            }}
                          >
                            <Upload size={16} />
                          </button>
                          {deleteId === d.id ? (
                            <>
                              <button
                                className="danger-text"
                                onClick={() =>
                                  action(async () => {
                                    await api("/documents/" + d.id, {
                                      method: "DELETE",
                                    });
                                    setDeleteId(null);
                                  }, "Document deleted. Sources are no longer accessible.")
                                }
                                disabled={busy}
                              >
                                Confirm delete
                              </button>
                              <button
                                aria-label="Cancel delete"
                                onClick={() => setDeleteId(null)}
                              >
                                <X size={15} />
                              </button>
                            </>
                          ) : (
                            <button
                              className="icon-button"
                              aria-label={"Delete " + d.title}
                              title="Delete document"
                              onClick={() => setDeleteId(d.id)}
                            >
                              <Trash2 size={16} />
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                ))}
              {documents.filter((d) =>
                d.title.toLowerCase().includes(filter.toLowerCase()),
              ).length === 0 && (
                <div className="empty-state">
                  <FolderOpen />
                  <h3>No documents found</h3>
                  <p>
                    {filter
                      ? "Try a different document name."
                      : "Upload a text or Markdown policy to get started."}
                  </p>
                </div>
              )}
            </div>
            {diff && (
              <VersionDiff
                title={diff.title}
                diff={diff.data}
                onClose={() => setDiff(null)}
              />
            )}
            <PrecedenceList
              rules={rules}
              isAdmin={isAdmin}
              busy={busy}
              action={action}
            />
            <div className="subtle-note">
              <ShieldCheck size={17} />
              <p>
                All workspace members can read approved documents.{" "}
                {isAdmin
                  ? "Text and Markdown files, up to 10 MB each. Replacements become available after processing."
                  : "Only administrators can upload, replace, or delete documents."}
              </p>
            </div>
          </main>
        )}
        {view === "Review queue" && (
          <main className="content-page">
            <div className="page-heading">
              <div>
                <p className="eyebrow">CLOSE THE KNOWLEDGE GAPS</p>
                <h1>Review queue</h1>
                <p>
                  {isAdmin
                    ? "Help your team resolve questions that need a human answer."
                    : "Track the questions you have sent for human review."}
                </p>
              </div>
              <button
                className="primary"
                onClick={() => {
                  setReviewDraft("");
                  setReviewMessage(null);
                  setReviewNote("");
                }}
              >
                <Plus size={18} /> New review request
              </button>
            </div>
            <div className="queue-heading">
              <span className="queue-tab">
                All requests <b>{reviews.length}</b>
              </span>
              <span className="muted">
                {reviews.filter((r) => r.status === "open").length} awaiting
                review, {reviews.filter((r) => r.status === "answered").length}{" "}
                answered
              </span>
            </div>
            {reviews.length ? (
              reviews.map((r) => (
                <ReviewCard
                  key={r.id + ":" + r.revision}
                  review={r}
                  isAdmin={isAdmin}
                  userId={session?.user.id || ""}
                  busy={busy}
                  action={action}
                  openSource={openSource}
                  when={date}
                />
              ))
            ) : (
              <div className="empty-state queue-empty">
                <Inbox size={32} />
                <h2>No questions waiting here</h2>
                <p>
                  When the documents don't have an answer, send a question for
                  human review.
                </p>
              </div>
            )}
          </main>
        )}
        {view === "Settings" && settings && (
          <main className="content-page settings-page">
            <div className="page-heading">
              <div>
                <p className="eyebrow">WORKSPACE PREFERENCES</p>
                <h1>Settings</h1>
                <p>Understand your access, evidence, and operating limits.</p>
              </div>
            </div>
            <section className="settings-card">
              <h2>Workspace</h2>
              <div>
                <span>Name</span>
                <strong>{session.workspaces[0]?.name}</strong>
              </div>
              <div>
                <span>Your role</span>
                <strong className="capitalize">{settings.role}</strong>
              </div>
              <div>
                <span>Document access</span>
                <strong>All approved workspace documents</strong>
              </div>
            </section>
            <section className="settings-card">
              <h2>Answers & usage</h2>
              <div>
                <span>Answer mode</span>
                <strong>
                  {settings.generation_mode === "evidence"
                    ? "Local evidence extraction"
                    : "Anthropic generation"}
                </strong>
              </div>
              <div>
                <span>Availability</span>
                <strong>
                  {settings.generation_enabled ? "Enabled" : "Paused"}
                </strong>
              </div>
              <div>
                <span>Questions today</span>
                <strong>
                  {settings.daily_used} of {settings.daily_limit}
                </strong>
              </div>
              <progress
                aria-label="Daily question usage"
                value={settings.daily_used}
                max={settings.daily_limit}
              />
              <p>
                {settings.generation_mode === "evidence"
                  ? "Local evidence mode returns exact passages without sending content to an external model. It does not interpret policy or detect conflicts."
                  : "Questions and retrieved passages are sent to the configured model provider. Do not upload private data until your organization approves this use."}
              </p>
            </section>
            <section className="settings-card">
              <h2>Documents & retention</h2>
              <div>
                <span>Supported formats</span>
                <strong>Text and Markdown</strong>
              </div>
              <div>
                <span>Limits</span>
                <strong>
                  {settings.file_limit_mb} MB per file ·{" "}
                  {settings.document_limit} documents
                </strong>
              </div>
              <div>
                <span>Conversation retention target</span>
                <strong>{settings.retention_days} days</strong>
              </div>
              <p>
                Deleting a document immediately removes source access. Previous
                answers may still contain excerpts. Operators must run the
                retention procedure to remove old conversations.
              </p>
            </section>
          </main>
        )}
      </div>
      <dialog
        ref={reviewDialog}
        onCancel={() => setReviewDraft(null)}
        className="review-dialog"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              await postOnce(
                "/reviews",
                {
                  question: reviewDraft,
                  note: reviewNote,
                  message_id: reviewMessage,
                },
                reviewKey,
              );
              setReviewDraft(null);
            }, "Review request submitted.");
          }}
        >
          <div className="dialog-heading">
            <h2>Request human review</h2>
            <button
              type="button"
              className="icon-button"
              aria-label="Close review request"
              onClick={() => setReviewDraft(null)}
            >
              <X size={19} />
            </button>
          </div>
          <p>
            Check the question and add any context before submitting it to your
            workspace queue.
          </p>
          <label htmlFor="review-question">Question</label>
          <textarea
            id="review-question"
            value={reviewDraft || ""}
            onChange={(e) => setReviewDraft(e.target.value)}
            required
            minLength={3}
            maxLength={2000}
          />
          <label htmlFor="review-note">
            Additional context <span className="muted">(optional)</span>
          </label>
          <textarea
            id="review-note"
            value={reviewNote}
            onChange={(e) => setReviewNote(e.target.value)}
            maxLength={2000}
            placeholder="What needs clarification?"
          />
          <div className="dialog-actions">
            <button
              type="button"
              className="secondary"
              onClick={() => setReviewDraft(null)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="primary"
              disabled={busy || !reviewDraft || reviewDraft.trim().length < 3}
            >
              Submit for review
            </button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
