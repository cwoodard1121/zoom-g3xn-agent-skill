// Stage: the gig that's on the pedal, readable from where you stand.
// It follows the pedal: stomp to the next patch and the next song comes up.
// Arrow keys, space and Page Up/Down (what Bluetooth page-turner pedals send) step through the set.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Gig, GigEntry } from "../api";
import { usePedal } from "../pedal";

const SEGMENTS = Array.from({ length: 15 }, (_, i) => i - 7);

export function Stage() {
  const { gigs, status, names, tuner, act } = usePedal();
  const [gig, setGig] = useState<Gig | null>(null);
  const stageRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!gigs.active) return setGig(null);
    api.gig(gigs.active).then(setGig, () => setGig(null));
  }, [gigs.active, gigs.list]);

  const slots = gig?.loaded?.slots ?? [];
  const current = status?.current_slot ?? null;
  const index = slots.findIndex((s) => s.slot === current);
  const song = index >= 0 ? slots[index] : null;
  const next = slots[index + 1];
  // Notes, tempo and key can change after loading; match them by song title.
  const info: GigEntry | undefined = song
    ? gig!.patches.find((p) => p.song === song.song) ?? gig!.patches[index]
    : undefined;

  const goTo = (i: number) => {
    const s = slots[i];
    if (s) act(() => api.select(s.slot));
  };

  const stepRef = useRef((_d: number) => {});
  stepRef.current = (d: number) => goTo(index < 0 ? 0 : Math.min(slots.length - 1, Math.max(0, index + d)));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement).closest("input, textarea, select")) return;
      const d = { ArrowRight: 1, ArrowDown: 1, PageDown: 1, " ": 1, ArrowLeft: -1, ArrowUp: -1, PageUp: -1 }[e.key];
      if (d) {
        e.preventDefault();
        stepRef.current(d);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The tuner turns off again when you leave the stage view.
  const tunerOn = !!status?.tuner;
  const tunerOnRef = useRef(tunerOn);
  tunerOnRef.current = tunerOn;
  useEffect(() => () => {
    if (tunerOnRef.current) api.tuner(false).catch(() => {});
  }, []);

  if (!gig || !slots.length) {
    return (
      <section className="stage stage-empty">
        <h1 className="view-title">Stage</h1>
        <p className="empty">
          Load a gig to the pedal and it shows up here, one song at a time. <a href="#gigs">Go to Gigs</a>
        </p>
      </section>
    );
  }

  const meter = tuner?.note ? tuner.meter : null;

  return (
    <section className="stage" ref={stageRef} aria-labelledby="stage-song">
      <div className="stage-now">
        <p className="stage-where">
          {gig.name} · {song ? `song ${index + 1} of ${slots.length}` : `${slots.length} songs`}
        </p>
        {song ? (
          <>
            <h1 id="stage-song" className="stage-song">{song.song}</h1>
            <div className="stage-patch">
              <span className="stage-lcd" aria-label={`Slot ${song.slot}, ${song.patch}`}>
                <span className="stage-lcd-slot">{String(song.slot).padStart(3, "0")}</span>
                <span>{song.patch}</span>
              </span>
              {info?.tempo && <span className="stage-fact"><b>{info.tempo}</b> BPM</span>}
              {info?.key && <span className="stage-fact">Key <b>{info.key}</b></span>}
            </div>
            {info?.notes && <p className="stage-notes">{info.notes}</p>}
          </>
        ) : (
          <>
            <h1 id="stage-song" className="stage-song off-set">Not in the set</h1>
            <p className="stage-notes">
              The pedal is on slot {current}{current && names[current] ? `, ${names[current]}` : ""}.
              Press Next to start at {slots[0].song}.
            </p>
          </>
        )}

        {tunerOn && (
          <div className="stage-tuner" aria-live="polite">
            <span className={`stage-tuner-note${meter === 0 ? " in-tune" : ""}`}>{tuner?.note ?? "–"}</span>
            <span className="tuner-meter compact" aria-hidden="true">
              {SEGMENTS.map((s) => (
                <span key={s} className={`seg${s === 0 ? " center" : ""}${meter !== null && s === meter ? " lit" : ""}`} />
              ))}
            </span>
          </div>
        )}

        <div className="stage-next">
          {next ? (
            <p><span className="stage-next-label">Next</span> {next.song} <span className="stage-next-slot">slot {next.slot}</span></p>
          ) : song ? (
            <p><span className="stage-next-label">Next</span> That's the last song.</p>
          ) : null}
        </div>

        <div className="stage-controls">
          <button className="stage-step" onClick={() => stepRef.current(-1)} disabled={index <= 0}>Previous</button>
          <button className="stage-step primary" onClick={() => stepRef.current(1)} disabled={index >= slots.length - 1}>
            {song ? "Next" : "Start"}
          </button>
          <span className="stage-spacer" />
          <button className="button" aria-pressed={tunerOn} onClick={() => act(() => api.tuner(!tunerOn))}>
            Tuner
          </button>
          <button
            className="button"
            onClick={() => {
              if (document.fullscreenElement) document.exitFullscreen();
              else stageRef.current?.requestFullscreen().catch(() => {});
            }}
          >
            Full screen
          </button>
        </div>
      </div>

      <ol className="setlist" aria-label="Setlist">
        {slots.map((s, i) => (
          <li key={s.slot}>
            <button
              className={`setlist-song${index >= 0 && i < index ? " played" : ""}`}
              aria-current={i === index ? "true" : undefined}
              onClick={() => goTo(i)}
            >
              <span className="setlist-n">{i + 1}</span>
              <span className="setlist-title">{s.song}</span>
              <span className="setlist-slot">{s.slot}</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
