// The song clock's bar on the stage view (tap in, the band's tempo, where the song is) and the
// song's words moving with it (songclock.ts has how the tapping works). With timed lyrics the
// three lines around the one being sung light up (the clock is only roughly with the band), held
// near the top; otherwise they scroll evenly. Clicking a line carries on from there.
import { useEffect, useMemo, useRef } from "react";
import type { GigEntry } from "../api";
import { length, lines } from "../lyrics";
import { mmss, TAPS, useSongTime, WARM_UP } from "../songclock";
import type { SongClock } from "../songclock";

export function ClockBar({ entry, clock }: { entry: GigEntry; clock: SongClock }) {
  const now = useSongTime(clock);
  const all = useMemo(() => lines(entry), [entry]);
  const total = length(entry, all);

  // The eight lights: taps filling two bars, then the beat going round them.
  const beatNow = clock.running ? Math.floor(now / clock.beat + 1e-6) : null;
  const lit = (i: number) => (beatNow !== null ? beatNow % TAPS === i : i < clock.taps);
  const hint = clock.running
    ? "Tap again any time to follow the band"
    : clock.taps === 0
      ? "Listen for a bar, then tap two: FS3 (hold it first) or T"
      : clock.taps < WARM_UP
        ? "Finding the beat…"
        : "Setting the tempo…";

  return (
    <>
      <div className="lyrics-bar">
        <button
          className="button lyrics-tap"
          onClick={clock.tap}
          title="Listen for a bar, then tap two bars with the band (or press T, or tap FS3 on the pedal). The first bar of taps only finds the beat; the song carries on from three bars in."
        >
          Tap
        </button>
        <span className={`tap-lights${clock.running ? " running" : ""}`} aria-hidden="true">
          {Array.from({ length: TAPS }, (_, i) => (
            <span key={i} className={`tap-light${i < WARM_UP ? " warm" : ""}${i % 4 === 0 ? " one" : ""}${lit(i) ? " lit" : ""}`} />
          ))}
        </span>
        <span className="lyrics-tempo">
          {clock.bpm ? (
            <><b>{clock.bpm}</b> BPM{entry.tempo ? ` · album ${entry.tempo}` : ""}</>
          ) : entry.tempo ? (
            <>album <b>{entry.tempo}</b> BPM</>
          ) : (
            "no tempo yet"
          )}
        </span>
        <span className="lyrics-time">{`${mmss(now)} / ${mmss(total / (clock.rate || 1))}`}</span>
        <span className="stage-spacer" />
        <button className="button" aria-pressed={clock.running} onClick={clock.toggle}>
          {clock.running ? "Pause" : now > 0 ? "Resume" : "Scroll"}
        </button>
        <button className="button" onClick={clock.reset} disabled={now === 0 && !clock.taps}>
          Top
        </button>
      </div>
      <p className="tap-hint" aria-live="polite">{hint}</p>
    </>
  );
}

export function Lyrics({ entry, clock }: { entry: GigEntry; clock: SongClock }) {
  const all = useMemo(() => lines(entry), [entry]);
  const timed = all.some((l) => l.time !== null);
  const total = length(entry, all);
  const now = useSongTime(clock);
  const box = useRef<HTMLElement>(null);

  const current = timed ? all.reduce((at, l, i) => (l.time !== null && l.time <= now ? i : at), -1) : -1;

  // Back at the top (a new song, or Top): the words are too.
  useEffect(() => {
    if (!clock.running && clock.time() === 0) box.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [entry.song, clock.moved]);

  // Keep the words moving: the lit lines near the top, or an even scroll.
  useEffect(() => {
    const el = box.current;
    if (!el || !clock.running) return;
    if (timed) {
      const line = el.querySelectorAll<HTMLElement>(".lyric")[Math.max(current - 1, 0)];
      if (line) el.scrollTo({ top: line.offsetTop - el.clientHeight * 0.12, behavior: "smooth" });
    } else {
      el.scrollTo({ top: (el.scrollHeight - el.clientHeight) * Math.min(1, now / total) });
    }
  }, [timed ? current : Math.round(now * 4), clock.running]);

  // Click a line: the words carry on from there (and start, if they were stopped).
  const jump = (i: number) => clock.jump(Math.max(0, (all[i].time ?? (i / Math.max(1, all.length)) * total) - 0.2));

  return (
    <section ref={box} className={`stage-lyrics${timed ? " timed" : ""}`} aria-label={`Lyrics for ${entry.song}`} tabIndex={0}>
      {all.map((l, i) => (
        <p
          key={i}
          className={`lyric${current >= 0 && Math.abs(i - current) <= 1 ? " now" : ""}${current >= 0 && i < current - 1 ? " sung" : ""}`}
          onClick={() => jump(i)}
          title="Carry on from here"
        >
          {l.text || " "}
        </p>
      ))}
    </section>
  );
}
