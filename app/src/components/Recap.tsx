// After the show (or any time during it): the songs played, how the band's tapped tempo sat
// against the record, and which patches were changed on the pedal (autosave keeps a knob turned
// mid-song), with the panic button that puts them all back as the gig loaded them.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Gig, GigChange } from "../api";
import { usePedal } from "../pedal";

export interface Played {
  song: string;
  album?: number; // the record's tempo
  tempos: number[]; // the band's, each time it was tapped
}

export function Recap({ gig, played, onClose }: { gig: Gig; played: Played[]; onClose: () => void }) {
  const { act } = usePedal();
  const [changed, setChanged] = useState<GigChange[] | null>(null);
  const [putting, setPutting] = useState(false);

  useEffect(() => {
    act(() => api.checkGig(gig.id!)).then((r) => setChanged(r?.changed ?? []));
  }, [gig.id]);

  const putBack = async () => {
    if (!window.confirm(`Put ${changed!.length} patch${changed!.length === 1 ? "" : "es"} back the way ${gig.name} loaded them? The changed versions are backed up first.`)) return;
    setPutting(true);
    const r = await act(() => api.restoreGig(gig.id!), (r) => `Put back ${r.restored.length} patch${r.restored.length === 1 ? "" : "es"}`);
    setPutting(false);
    if (r) setChanged([]);
  };

  const tapped = played.filter((p) => p.tempos.length);
  const drift = (p: Played) => (p.album ? (avg(p.tempos) - p.album) / p.album : 0);
  const fastest = tapped.length ? tapped.reduce((a, b) => (drift(b) > drift(a) ? b : a)) : null;

  return (
    <div className="recap-scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="recap" role="dialog" aria-modal="true" aria-labelledby="recap-title">
        <header className="recap-head">
          <p className="recap-kicker">{gig.name}</p>
          <h2 id="recap-title" className="recap-title">Show recap</h2>
          <button className="button" onClick={onClose}>Close</button>
        </header>

        <div className="recap-stats">
          <p><b>{played.length}</b><span>songs played</span></p>
          <p><b>{tapped.length}</b><span>tapped in</span></p>
          {fastest?.album && (
            <p>
              <b>{fmt(drift(fastest))}</b>
              <span>{drift(fastest) > 0 ? "rushed most" : "dragged most"}: {fastest.song}</span>
            </p>
          )}
          <p><b>{changed === null ? "…" : changed.length}</b><span>patches changed on the pedal</span></p>
        </div>

        {played.length > 0 && (
          <ol className="recap-songs">
            {played.map((p, i) => {
              const d = drift(p);
              return (
                <li key={i}>
                  <span className="recap-song">{p.song}</span>
                  {p.tempos.length ? (
                    <>
                      <span className="recap-tempo"><b>{Math.round(avg(p.tempos))}</b>{p.album ? ` / ${p.album}` : ""} BPM</span>
                      {p.album ? (
                        <span className={`recap-drift${Math.abs(d) < 0.02 ? " steady" : d > 0 ? " fast" : " slow"}`} title="Against the record">
                          <span style={{ width: `${Math.min(50, Math.abs(d) * 500)}%`, [d >= 0 ? "left" : "right"]: "50%" }} />
                          {fmt(d)}
                        </span>
                      ) : <span />}
                    </>
                  ) : (
                    <span className="recap-tempo dim">not tapped</span>
                  )}
                </li>
              );
            })}
          </ol>
        )}

        <div className="recap-changed">
          <h3>Changed on the pedal</h3>
          {changed === null ? (
            <p className="dim">Checking the pedal…</p>
          ) : changed.length === 0 ? (
            <p className="dim">Every patch is as the gig loaded it.</p>
          ) : (
            <>
              <ul>
                {changed.map((c) => (
                  <li key={c.slot}><b>{c.song}</b> <span className="dim">slot {c.slot}</span> {c.change ?? `now ${c.now}`}</li>
                ))}
              </ul>
              <button className="button danger" disabled={putting} onClick={putBack}>
                {putting ? "Putting them back…" : "Put them all back"}
              </button>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
const fmt = (d: number) => `${d >= 0 ? "+" : "−"}${Math.abs(d * 100).toFixed(1)}%`;
