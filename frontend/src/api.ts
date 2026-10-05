export type Session = {
  user: { id: string; name: string };
  csrf: string;
  workspaces: { id: string; name: string; role: string }[];
  mode: string;
};
export type Document = {
  id: string;
  title: string;
  version: number;
  status: string;
  error: string | null;
  passages: number;
  created_at: string;
  active_version: string | null;
  owner: string | null;
  effective_from: string | null;
};
export type PrecedenceRule = {
  id: string;
  section: string;
  note: string;
  prevailing_title: string;
  yielding_title: string;
};
export type Conflict = {
  section: string;
  source_ids: string[];
  prevailing_title: string | null;
  note: string | null;
};
export type Source = {
  source_id: string;
  section: string;
  title: string;
  version: number;
  document_id: string;
};
export type Answer = {
  message_id: string;
  conversation_id: string;
  question: string;
  status: "answer" | "abstain" | "conflict";
  text: string;
  citations: { source_id: string; quote: string }[];
  gaps: string[];
  claims?: { text: string; citations: number[] }[];
  sources: Source[];
  reviewed_answers?: ReviewedAnswer[];
  conflicts?: Conflict[];
  mode: string;
  duration_ms: number;
};
export type Conversation = { id: string; title: string };
export type ReviewSource = {
  source_id: string;
  title: string;
  section: string;
  version: number;
};
export type ReviewCitation = ReviewSource & { quote: string; current: boolean };
export type ReviewedAnswer = {
  review_id: string;
  question: string;
  resolution: string;
  resolved_at: string;
  citations: ReviewCitation[];
};
export type Review = {
  id: string;
  question: string;
  note: string;
  status: "open" | "claimed" | "answered" | "declined" | "outdated";
  published: boolean;
  history: {
    action: string;
    resolution: string | null;
    created_at: string;
    actor_name: string | null;
  }[];
  created_at: string;
  revision: number;
  message_id: string | null;
  requested_by_name: string | null;
  claimed_by: string | null;
  claimed_by_name: string | null;
  resolution: string | null;
  resolved_at: string | null;
  resolved_by_name: string | null;
  citations: ReviewCitation[];
  candidate_sources: ReviewSource[];
};
export type Settings = {
  role: string;
  generation_mode: string;
  generation_enabled: boolean;
  daily_used: number;
  daily_limit: number;
  file_limit_mb: number;
  document_limit: number;
  supported_types: string[];
  retention_days: number;
  environment: string;
};
let csrf = "";
let workspace = "";
export function configure(session: Session) {
  csrf = session.csrf;
  workspace = session.workspaces[0]?.id || "";
}
const errors: Record<string, string> = {
  sign_in_required: "Your session has ended. Please sign in again.",
  daily_usage_limit:
    "Your daily question limit has been reached. Please try again tomorrow.",
  source_unavailable:
    "This source was removed or replaced. Ask the question again for current evidence.",
  admin_required: "Only workspace administrators can make this change.",
  text_or_markdown_required_pdf_not_enabled:
    "Choose a text or Markdown file. PDF uploads are not available yet.",
  rate_limited:
    "Too many requests in a short time. Wait a minute and try again.",
  idempotency_key_reused:
    "This request changed while being retried. Please submit again.",
  workspace_required: "Choose a workspace and try again.",
  generation_disabled:
    "Answers are temporarily paused. Your documents are still available.",
  answer_validation_or_timeout:
    "The answer could not be verified in time. Please try again.",
  evidence_changed_please_retry:
    "A source changed while answering. Please ask again.",
  provider_unavailable: "The answer service is unavailable. Please try again.",
  file_size_limit: "Choose a nonempty file smaller than 10 MB.",
  review_changed:
    "Someone else updated this review. The queue has been refreshed.",
  invalid_transition: "This review has already moved on.",
  claimed_by_another_reviewer: "Another administrator is handling this review.",
  precedence_already_declared:
    "A precedence rule for this section already exists. Remove it first.",
  contradicts_existing_precedence:
    "The opposite precedence is already set for this section. Remove it first.",
  invalid_front_matter:
    "The document header must use only owner and effective lines.",
  invalid_effective_date: "Write the effective date as YYYY-MM-DD.",
  extracted_text_limit: "This document exceeds the 500,000-character limit.",
};
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "X-CSRF-Token": csrf,
    "X-Workspace-ID": workspace,
  };
  if (init.body && !(init.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch("/api" + path, {
    ...init,
    headers: { ...headers, ...init.headers },
    credentials: "same-origin",
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(
      errors[body.error] ||
        "Something went wrong. Please try again. (" + response.status + ")",
    );
  return body as T;
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
// Retrying with the same key cannot apply a write twice; the server replays the first result.
export const postOnce = <T>(path: string, body: unknown, key: string) =>
  api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Idempotency-Key": key },
  });
