// The song's words on the stage view, scrolling roughly with the band. The clock starts on the
// first tap (or Scroll); tapping along sets the band's real tempo, and the words run that much
// faster or slower than the recording. With timed lyrics the line being sung lights up.
import { useEffect, useMemo, useRef, useState } from "react";
import type { GigEntry } from "../api";
import { length, lines, tapped } from "../lyrics";
import { usePedal } from "../pedal";

const TAP_RESET_MS = 2500; // a gap this long starts a new count

export function Lyrics({ entry }: { entry: GigEntry }) {
  const all = useMemo(() => lines(entry), [entry]);
  const timed = all.some((l) => l.time !== null);
  const total = length(entry, all);

  // Song time = base + (now - since) * rate while running.
  const clock = useRef({ base: 0, since: 0, rate: 1, running: false });
  const [running, setRunning] = useState(false);
  const [taps, setTaps] = useState<number[]>([]);
  const [now, setNow] = useState(0);
  const box = useRef<HTMLElement>(null);

  const songTime = () => {
    const c = clock.current;
    return c.running ? c.base + ((performance.now() - c.since) / 1000) * c.rate : c.base;
  };
  const setClock = (patch: Partial<typeof clock.current>) => {
    clock.current = { ...clock.current, base: songTime(), since: performance.now(), ...patch };
    setRunning(clock.current.running);
  };

  // A new song: back to the top, stopped.
  useEffect(() => {
    clock.current = { base: 0, since: 0, rate: 1, running: false };
    setRunning(false);
    setTaps([]);
    setNow(0);
    box.current?.scrollTo({ top: 0 });
  }, [entry.song]);

  // A tempo tapped on the pedal itself (hold FS3, then tap it) counts like taps here.
  const { pedalTempo } = usePedal();
  const [pedalBpm, setPedalBpm] = useState<number | null>(null);
  const seenTempo = useRef(pedalTempo?.at);
  useEffect(() => {
    if (!pedalTempo || pedalTempo.at === seenTempo.current) return;
    seenTempo.current = pedalTempo.at;
    setPedalBpm(pedalTempo.bpm);
    const rate = entry.tempo ? pedalTempo.bpm / entry.tempo : clock.current.rate;
    setClock({ running: true, rate });
  });
  useEffect(() => setPedalBpm(null), [entry.song]);

  const bpm = tapped(taps) ?? pedalBpm;
  const tap = () => {
    const t = performance.now();
    const fresh = taps.length && t - taps[taps.length - 1] > TAP_RESET_MS ? [t] : [...taps, t];
    setTaps(fresh);
    const live = tapped(fresh);
    const rate = live && entry.tempo ? live / entry.tempo : clock.current.rate;
    if (!clock.current.running) setClock({ running: true, rate });     // the first tap starts it
    else setClock({ rate });
  };

  // "T" taps, from anywhere on the stage.
  const tapRef = useRef(tap);
  tapRef.current = tap;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "t" && e.key !== "T") return;
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement).closest("input, textarea, select")) return;
      e.preventDefault();
      tapRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Tick while running.
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => setNow(songTime()), 200);
    return () => window.clearInterval(id);
  }, [running]);

  const current = timed ? all.reduce((at, l, i) => (l.time !== null && l.time <= now ? i : at), -1) : -1;

  // Keep the words moving.
  useEffect(() => {
    const el = box.current;
    if (!el || !running) return;
    if (timed) {
      const line = el.querySelectorAll<HTMLElement>(".lyric")[Math.max(current, 0)];
      if (line) el.scrollTo({ top: line.offsetTop - el.clientHeight * 0.35, behavior: "smooth" });
    } else {
      el.scrollTo({ top: (el.scrollHeight - el.clientHeight) * Math.min(1, now / total) });
    }
  }, [now, current, running, timed, total]);

  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  return (
    <div className="stage-lyrics-wrap">
      <div className="lyrics-bar">
        <button className="button lyrics-tap" onClick={tap} title="Tap along with the band (or press T). The first tap starts the words.">
          Tap
        </button>
        <span className="lyrics-tempo">
          {bpm ? <><b>{bpm}</b> BPM{entry.tempo ? ` · album ${entry.tempo}` : ""}</> : entry.tempo ? <>album <b>{entry.tempo}</b> BPM</> : "tap for tempo"}
        </span>
        <span className="lyrics-time">{mmss(now)} / {mmss(total / (clock.current.rate || 1))}</span>
        <span className="stage-spacer" />
        <button className="button" aria-pressed={running} onClick={() => setClock({ running: !running })}>
          {running ? "Pause" : now > 0 ? "Resume" : "Scroll"}
        </button>
        <button
          className="button"
          onClick={() => {
            setClock({ base: 0, running: false });
            setNow(0);
            box.current?.scrollTo({ top: 0, behavior: "smooth" });
          }}
          disabled={now === 0}
        >
          Top
        </button>
      </div>
      <section ref={box} className={`stage-lyrics${timed ? " timed" : ""}`} aria-label={`Lyrics for ${entry.song}`} tabIndex={0}>
        {all.map((l, i) => (
          <p key={i} className={`lyric${i === current ? " now" : ""}${current >= 0 && i < current ? " sung" : ""}`}>
            {l.text || " "}
          </p>
        ))}
      </section>
    </div>
  );
}
