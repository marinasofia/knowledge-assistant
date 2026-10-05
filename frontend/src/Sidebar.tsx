// Adapted from shadcn sidebar-07. License and source are recorded in docs.
import {
  BookOpen,
  MessageSquare,
  Files,
  Inbox,
  Settings2,
  Plus,
  LogOut,
  X,
  ChevronDown,
} from "lucide-react";
import type { Conversation, Session } from "./api";
export type View = "Ask" | "Documents" | "Review queue" | "Settings";
const navigation = [
  { title: "Ask", icon: MessageSquare },
  { title: "Documents", icon: Files },
  { title: "Review queue", icon: Inbox },
  { title: "Settings", icon: Settings2 },
] as const;
export function Sidebar({
  view,
  navigate,
  history,
  openConversation,
  session,
  logout,
  open,
  close,
}: {
  view: View;
  navigate: (v: View) => void;
  history: Conversation[];
  openConversation: (id: string) => void;
  session: Session;
  logout: () => void;
  open: boolean;
  close: () => void;
}) {
  return (
    <>
      <button
        className={"sidebar-backdrop " + (open ? "visible" : "")}
        aria-label="Close navigation"
        onClick={close}
      />
      <aside
        className={"sidebar " + (open ? "mobile-open" : "")}
        aria-label="Workspace navigation"
      >
        <div className="sidebar-header">
          <div className="brand">
            <span className="brand-mark">
              <BookOpen size={21} />
            </span>
            <span>
              Knowledge<span className="brand-small">ASSISTANT</span>
            </span>
            <button
              className="mobile-close icon-button"
              onClick={close}
              aria-label="Close navigation"
            >
              <X size={18} />
            </button>
          </div>
          <div className="workspace-card">
            <span className="workspace-avatar">N</span>
            <span>
              <strong>{session.workspaces[0]?.name}</strong>
              <small>Team workspace</small>
            </span>
            <ChevronDown size={16} />
          </div>
        </div>
        <div className="sidebar-content">
          <button className="new-question" onClick={() => navigate("Ask")}>
            <Plus size={17} /> New question
          </button>
          <nav>
            {navigation.map(({ title, icon: Icon }) => (
              <button
                key={title}
                aria-current={view === title ? "page" : undefined}
                className={"nav-item " + (view === title ? "active" : "")}
                onClick={() => navigate(title)}
              >
                <Icon size={19} />
                {title}
              </button>
            ))}
          </nav>
          <div className="history">
            <p className="eyebrow">RECENT QUESTIONS</p>
            {history.length ? (
              history.slice(0, 7).map((c) => (
                <button
                  title={c.title}
                  key={c.id}
                  onClick={() => openConversation(c.id)}
                >
                  <MessageSquare size={14} />
                  <span>{c.title}</span>
                </button>
              ))
            ) : (
              <p className="history-empty">Your questions will appear here.</p>
            )}
          </div>
        </div>
        <div className="sidebar-footer">
          <div className="demo-note">
            <span className="tiny-square" />
            Fictional company demo<small>Explore with sample policies.</small>
          </div>
          <div className="profile">
            <span className="avatar">
              {session.user.name
                .split(" ")
                .map((n) => n[0])
                .join("")}
            </span>
            <span>
              <strong>{session.user.name}</strong>
              <small>
                {session.workspaces[0]?.role === "admin"
                  ? "Administrator"
                  : "Workspace member"}
              </small>
            </span>
            <button
              className="icon-button"
              title="Sign out"
              aria-label="Sign out"
              onClick={logout}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
