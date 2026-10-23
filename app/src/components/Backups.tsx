// Whole-pedal backups (one is kept each time the pedal is plugged in and something changed), each
// with the slots that changed since the one before, and a way to put a slot back how it was.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Backup } from "../api";
import { usePedal } from "../pedal";
import { Icon } from "./Icon";

const when = (t: number) =>
  new Date(t * 1000).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export function Backups({ onClose }: { onClose: () => void }) {
  const { act, names } = usePedal();
  const [list, setList] = useState<Backup[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const load = () => api.backups().then((r) => setList(r.backups), (e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const putBack = async (from: Backup, slot: number, patch: string | null) => {
    const ok = window.confirm(
      `Put slot ${slot} back to “${patch ?? "Empty"}” from ${when(from.time)}?\n\nIt holds “${names[slot] ?? "?"}” now; that's saved first.`,
    );
    if (ok && (await act(() => api.restoreSlot(from.name, slot), (r) => `Slot ${slot} is ${r.patch} again`))) load();
  };

  return (
    <aside className="detail backups" aria-labelledby="backups-title">
      <button className="detail-close" onClick={onClose} aria-label="Close"><Icon name="close" size={20} /></button>
      <h2 id="backups-title" className="detail-name">Backups</h2>
      <p className="detail-note">One is kept every time the pedal is plugged in and something changed.</p>
      {error && <p className="detail-note error">{error}</p>}
      {list === null && !error && <p className="detail-note">Reading the backups…</p>}
      {list?.length === 0 && <p className="detail-note">No backups yet. One is made the next time the pedal connects.</p>}
      <ol className="backup-list">
        {list?.map((b, i) => {
          const before = list[i + 1];          // newest first: the one before is next
          const shown = open === b.name;
          return (
            <li key={b.name} className="backup">
              <button className="backup-head" aria-expanded={shown} onClick={() => setOpen(shown ? null : b.name)} disabled={!b.changed.length}>
                <span className="backup-when">{when(b.time)}</span>
                <span className="backup-what">
                  {b.first ? `${b.slots} slots` : b.changed.length ? `${b.changed.length} changed` : "no changes"}
                  {b.auto ? "" : " · saved"}
                </span>
              </button>
              {shown && (
                <ul className="backup-changes">
                  {b.changed.map((c) => (
                    <li key={c.slot}>
                      <span className="backup-slot vfd">{String(c.slot).padStart(3, "0")}</span>
                      <span className="backup-names">
                        {c.was ?? "Empty"} <span aria-hidden="true">→</span><span className="visually-hidden"> became </span> {c.now ?? "Empty"}
                      </span>
                      {before && c.was !== null && (
                        <button className="link-button" onClick={() => putBack(before, c.slot, c.was)}>
                          Put back
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
