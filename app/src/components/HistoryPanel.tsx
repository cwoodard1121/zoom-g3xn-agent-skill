// The time machine: every version of the tone being tried, newest first.
// Click one to hear it again; Claude's changes say why they were made.
import { api } from "../api";
import { usePedal } from "../pedal";
import { Drawer } from "./Drawer";

export function HistoryPanel({ onClose }: { onClose: () => void }) {
  const { history, act } = usePedal();
  const entries = history.entries.map((e, i) => ({ ...e, index: i })).reverse();

  return (
    <Drawer title="History" onClose={onClose}>
      {entries.length === 0 ? (
        <p className="drawer-note">Every change to the tone you're trying shows up here, so you can go back to any of them.</p>
      ) : (
        <ol className="history">
          {entries.map((e) => (
            <li key={e.id}>
              <button
                className={[
                  "history-item",
                  e.index === history.position ? "is-current" : "",
                  e.index > history.position ? "is-undone" : "",
                ].join(" ")}
                aria-current={e.index === history.position ? "true" : undefined}
                onClick={() => act(() => api.goTo(e.id))}
              >
                <span className="history-label">{e.label}</span>
                {e.reason && <span className="history-reason">“{e.reason}”</span>}
                <span className="history-meta">
                  {e.source === "claude" ? <span className="badge">Claude</span> : null}
                  <time dateTime={new Date(e.time * 1000).toISOString()}>{ago(e.time)}</time>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Drawer>
  );
}

function ago(seconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 50) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}
