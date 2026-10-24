// The song as a strip of its parts (songmap.ts), with where the clock is running across it: the
// part you're in, big, and the next one coming. Click a part to carry on from its start. Cues and
// reminders show as ticks along the strip; a reminder pops up as it comes round.
import type React from "react";
import type { Cue, Note } from "../cues";
import { mmss, useSongTime } from "../songclock";
import type { SongClock } from "../songclock";
import { partAt } from "../songmap";
import type { Part } from "../songmap";

export function SongMap({ parts, total, clock, cues, notes }: { parts: Part[]; total: number; clock: SongClock; cues: Cue[]; notes: Note[] }) {
  const now = useSongTime(clock);
  const here = partAt(parts, now);
  const next = parts[parts.indexOf(here) + 1];
  const pct = (at: number) => `${Math.min(100, Math.max(0, (at / total) * 100))}%`;
  const inPart = here ? Math.min(1, Math.max(0, (now - here.at) / Math.max(1, here.end - here.at))) : 0;
  const started = clock.running || now > 0;

  return (
    <div className={`songmap${started ? " started" : ""}`}>
      <div className="songmap-head" aria-live="polite">
        <span className={`songmap-now kind-${here?.kind ?? "part"}`} key={here?.label}>
          {started ? here?.label : "Ready"}
        </span>
        <span className="songmap-progress" aria-hidden="true">
          <span style={{ width: `${started ? inPart * 100 : 0}%` }} />
        </span>
        {started && next && (
          <span className="songmap-next">
            {next.label} in <b>{mmss((next.at - now) / (clock.rate || 1))}</b>
          </span>
        )}
      </div>
      <div className="songmap-strip" role="group" aria-label="Parts of the song: carry on from one">
        {parts.map((p, i) => (
          <button
            key={i}
            className={`songmap-part kind-${p.kind}${p === here && started ? " here" : ""}${started && p.end <= now ? " past" : ""}`}
            style={{ flexGrow: Math.max(1, p.end - p.at) } as React.CSSProperties}
            onClick={() => clock.jump(p.at)}
            title={`Carry on from ${p.label} (${mmss(p.at)})`}
          >
            <span>{p.label}</span>
          </button>
        ))}
        {cues.map((c, i) => (
          <span key={`c${i}`} className={`songmap-tick cue${c.on ? " on" : ""}`} style={{ left: pct(c.at) }} title={`${mmss(c.at)} ${c.effect} ${c.on ? "on" : "off"}`} />
        ))}
        {notes.map((n, i) => (
          <span key={`n${i}`} className="songmap-tick note" style={{ left: pct(n.at) }} title={`${mmss(n.at)} ${n.text}`} />
        ))}
        <span className="songmap-head-line" style={{ left: pct(now) }} aria-hidden="true" />
      </div>
    </div>
  );
}

/** A reminder, from a few seconds before its time until a few after. */
export function StageNote({ notes, clock }: { notes: Note[]; clock: SongClock }) {
  const now = useSongTime(clock);
  if (!clock.running) return null;
  const rate = clock.rate || 1;
  const note = notes.filter((n) => now >= n.at - 4 * rate && now < n.at + 6 * rate).pop();
  if (!note) return null;
  const soon = now < note.at;
  return (
    <p className={`stage-note${soon ? " soon" : ""}`} role="status" key={note.at}>
      <span className="stage-note-when">{soon ? `in ${Math.ceil((note.at - now) / rate)}` : "now"}</span>
      {note.text}
    </p>
  );
}
