import { useState } from "react";
import { Inbox } from "lucide-react";
import { post, type Review } from "./api";

const labels: Record<Review["status"], string> = {
  open: "Needs review",
  claimed: "In review",
  answered: "Answered",
  declined: "Closed without answer",
  outdated: "Policy changed, needs re-review",
};

type Props = {
  review: Review;
  isAdmin: boolean;
  userId: string;
  busy: boolean;
  action: (fn: () => Promise<unknown>, success: string) => void;
  openSource: (id: string) => void;
  when: (value: string) => string;
};

export function ReviewCard({
  review: r,
  isAdmin,
  userId,
  busy,
  action,
  openSource,
  when,
}: Props) {
  const [resolution, setResolution] = useState(""),
    [chosen, setChosen] = useState<string[]>([]),
    [publish, setPublish] = useState(r.published);
  const move = (verb: string, success: string, body = {}) =>
    action(
      () =>
        post("/reviews/" + r.id + "/transitions", {
          action: verb,
          revision: r.revision,
          ...body,
        }),
      success,
    );
  const mine = r.status === "claimed" && r.claimed_by === userId;
  return (
    <article className="review-card">
      <span className="review-icon">
        <Inbox size={21} />
      </span>
      <div>
        <span className={"status " + r.status}>{labels[r.status]}</span>
        {r.published && r.status === "answered" && (
          <span className="status published">Shared with workspace</span>
        )}
        <h2>{r.question}</h2>
        {r.note && <p>{r.note}</p>}
        <small className="muted">
          {isAdmin && r.requested_by_name && `From ${r.requested_by_name}. `}
          Submitted {when(r.created_at)}
          {r.status === "claimed" && `. Claimed by ${r.claimed_by_name}`}
        </small>
        {r.resolution && (
          <section className="review-resolution">
            <p>{r.resolution}</p>
            {r.status === "answered" && !r.citations.length && (
              <p className="muted">Approved policy does not cover this.</p>
            )}
            {r.citations.map((c) => (
              <button
                key={c.source_id}
                className="citation"
                disabled={!c.current}
                onClick={() => openSource(c.source_id)}
              >
                <span>
                  <span className="citation-title">
                    {c.title}, {c.section}
                    <span>
                      v{c.version}
                      {!c.current && ", since replaced"}
                    </span>
                  </span>
                  <span className="quote">{c.quote}</span>
                </span>
              </button>
            ))}
            <small className="muted">
              {r.resolved_by_name}, {r.resolved_at && when(r.resolved_at)}
            </small>
          </section>
        )}
        {isAdmin && mine && (
          <form
            className="review-form"
            onSubmit={(e) => {
              e.preventDefault();
              move("answer", "Answer published.", {
                resolution,
                source_ids: chosen,
                publish,
              });
            }}
          >
            <label htmlFor={"resolution-" + r.id}>Answer or reason</label>
            <textarea
              id={"resolution-" + r.id}
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              maxLength={4000}
              required
            />
            {r.candidate_sources.length > 0 && (
              <fieldset>
                <legend>Cite passages from the original answer</legend>
                {r.candidate_sources.map((s) => (
                  <label key={s.source_id} className="check">
                    <input
                      type="checkbox"
                      checked={chosen.includes(s.source_id)}
                      onChange={(e) =>
                        setChosen(
                          e.target.checked
                            ? [...chosen, s.source_id]
                            : chosen.filter((id) => id !== s.source_id),
                        )
                      }
                    />
                    {s.title}, {s.section} (v{s.version})
                  </label>
                ))}
              </fieldset>
            )}
            <label className="check">
              <input
                type="checkbox"
                checked={publish}
                onChange={(e) => setPublish(e.target.checked)}
              />
              Share this answer with anyone who asks a similar question
            </label>
            <div className="dialog-actions">
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => move("release", "Returned to the queue.")}
              >
                Release
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || !resolution.trim()}
                onClick={() =>
                  move("decline", "Closed without an answer.", { resolution })
                }
              >
                Close without answer
              </button>
              <button
                type="submit"
                className="primary"
                disabled={busy || !resolution.trim()}
              >
                Publish answer
              </button>
            </div>
          </form>
        )}
        {r.history.length > 1 && (
          <details className="review-history">
            <summary>History ({r.history.length} events)</summary>
            <ol>
              {r.history.map((e, i) => (
                <li key={i}>
                  {when(e.created_at)}: {e.action}
                  {e.actor_name ? " by " + e.actor_name : " (policy change)"}
                  {e.resolution && <q>{e.resolution}</q>}
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
      {isAdmin && (r.status === "open" || r.status === "outdated") && (
        <button
          className="secondary"
          disabled={busy}
          onClick={() => move("claim", "Review claimed.")}
        >
          Claim
        </button>
      )}
    </article>
  );
}
