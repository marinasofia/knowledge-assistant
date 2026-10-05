import { X } from "lucide-react";

export type Diff = {
  document_id: string;
  from: number;
  to: number;
  sections: {
    section_path: string;
    status: "added" | "removed" | "changed" | "unchanged";
    removed: string[];
    added: string[];
  }[];
};

const labels = {
  added: "Added",
  removed: "Removed",
  changed: "Changed",
  unchanged: "Unchanged",
};

export function VersionDiff({
  title,
  diff,
  onClose,
}: {
  title: string;
  diff: Diff;
  onClose: () => void;
}) {
  const changed = diff.sections.filter((s) => s.status !== "unchanged");
  return (
    <section className="version-diff" aria-label="Version comparison">
      <div className="dialog-heading">
        <h2>
          {title}: version {diff.from} to {diff.to}
        </h2>
        <button
          className="icon-button"
          aria-label="Close comparison"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <p className="muted">
        {changed.length} of {diff.sections.length} sections changed. Unchanged
        paragraphs keep their identity across versions.
      </p>
      {diff.sections.map((s) => (
        <div key={s.section_path} className={"diff-section " + s.status}>
          <h3>
            <span className={"status " + s.status}>{labels[s.status]}</span>{" "}
            {s.section_path.split(" > ").join(" › ")}
          </h3>
          {s.removed.map((t) => (
            <del key={"r" + t}>{t}</del>
          ))}
          {s.added.map((t) => (
            <ins key={"a" + t}>{t}</ins>
          ))}
        </div>
      ))}
    </section>
  );
}
