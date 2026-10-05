import { useState } from "react";
import { api, post, type Answer, type PrecedenceRule } from "./api";

type Act = (fn: () => Promise<unknown>, success: string) => void;

export function ConflictResolver({
  answer,
  busy,
  action,
}: {
  answer: Answer;
  busy: boolean;
  action: Act;
}) {
  const conflict = answer.conflicts?.find((c) => !c.prevailing_title);
  const documents = [
    ...new Map(
      answer.sources
        .filter((s) => conflict?.source_ids.includes(s.source_id))
        .map((s) => [s.document_id, s.title]),
    ),
  ];
  const [prevailing, setPrevailing] = useState(documents[0]?.[0] || ""),
    [note, setNote] = useState("");
  if (!conflict || documents.length < 2) return null;
  return (
    <form
      className="conflict-resolver"
      onSubmit={(e) => {
        e.preventDefault();
        const yielding = documents.filter(([id]) => id !== prevailing);
        action(
          () =>
            Promise.all(
              yielding.map(([id]) =>
                post("/precedence", {
                  prevailing_document_id: prevailing,
                  yielding_document_id: id,
                  section: conflict.section,
                  note,
                }),
              ),
            ),
          "Precedence saved. Ask again to see the governing policy.",
        );
      }}
    >
      <p className="eyebrow">DECIDE WHICH POLICY GOVERNS</p>
      <fieldset>
        <legend>For {conflict.section}, follow</legend>
        {documents.map(([id, title]) => (
          <label key={id} className="check">
            <input
              type="radio"
              name={"prevailing-" + answer.message_id}
              checked={prevailing === id}
              onChange={() => setPrevailing(id)}
            />
            {title}
          </label>
        ))}
      </fieldset>
      <label htmlFor={"note-" + answer.message_id}>
        Reason, shown to readers
      </label>
      <input
        id={"note-" + answer.message_id}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        minLength={3}
        maxLength={1000}
        required
      />
      <button className="primary" disabled={busy || note.trim().length < 3}>
        Save precedence
      </button>
    </form>
  );
}

export function PrecedenceList({
  rules,
  isAdmin,
  busy,
  action,
}: {
  rules: PrecedenceRule[];
  isAdmin: boolean;
  busy: boolean;
  action: Act;
}) {
  if (!rules.length) return null;
  return (
    <section className="precedence-list">
      <h2>Precedence between policies</h2>
      {rules.map((r) => (
        <div key={r.id} className="precedence-row">
          <p>
            <strong>{r.prevailing_title}</strong> governs over{" "}
            <strong>{r.yielding_title}</strong> for {r.section}.{" "}
            <span className="muted">{r.note}</span>
          </p>
          {isAdmin && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                action(
                  () => api("/precedence/" + r.id, { method: "DELETE" }),
                  "Precedence removed.",
                )
              }
            >
              Remove
            </button>
          )}
        </div>
      ))}
    </section>
  );
}
