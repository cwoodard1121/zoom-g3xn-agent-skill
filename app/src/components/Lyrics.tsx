// The song's words on the stage view, scrolling roughly with the band. A bar of taps (in the app
// or on the pedal) sets the band's tempo and starts a two-bar count-off on screen; the words start
// with the song, then run that much faster or slower than the recording. Scroll starts them at once.
// With timed lyrics the line being sung lights up.
import { useEffect, useMemo, useRef, useState } from "react";
import type { GigEntry } from "../api";
import { length, lines, tapped } from "../lyrics";
import { usePedal } from "../pedal";

const TAP_RESET_MS = 2500; // a gap this long starts a new count
const BAR = 4; // taps that start the count-off: one bar of 4/4
const COUNT_BEATS = 8; // the count-off: two bars, from the downbeat after the taps

export function Lyrics({ entry }: { entry: GigEntry }) {
  const all = useMemo(() => lines(entry), [entry]);
  const timed = all.some((l) => l.time !== null);
  const total = length(entry, all);

  // Song time = base + (now - since) * rate while running.
  const clock = useRef({ base: 0, since: 0, rate: 1, running: false, beat: 0.5 });   // beat: in song seconds
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
    clock.current = { base: 0, since: 0, rate: 1, running: false, beat: 0.5 };
    setRunning(false);
    setTaps([]);
    setNow(0);
    box.current?.scrollTo({ top: 0 });
  }, [entry.song]);

  // A tempo tapped on the pedal itself (hold FS3, then tap it) counts like taps here.
  const { pedalTempo } = usePedal();
  const [pedalBpm, setPedalBpm] = useState<number | null>(null);
  const seenTempo = useRef(pedalTempo?.at);
  const pedalTaps = useRef(0);       // taps on the pedal in this count (it reports from the second tap on)
  useEffect(() => {
    if (!pedalTempo || pedalTempo.at === seenTempo.current) return;
    const gap = pedalTempo.at - (seenTempo.current ?? 0);
    seenTempo.current = pedalTempo.at;
    pedalTaps.current = gap > TAP_RESET_MS ? 2 : pedalTaps.current + 1;
    setPedalBpm(pedalTempo.bpm);
    const rate = entry.tempo ? pedalTempo.bpm / entry.tempo : clock.current.rate;
    if (!clock.current.running && pedalTaps.current >= BAR) countOff(rate, pedalTempo.bpm);
    else setClock({ rate });
  });
  useEffect(() => setPedalBpm(null), [entry.song]);

  const bpm = tapped(taps) ?? pedalBpm;
  const tap = () => {
    const t = performance.now();
    const fresh = taps.length && t - taps[taps.length - 1] > TAP_RESET_MS ? [t] : [...taps, t];
    setTaps(fresh);
    const live = tapped(fresh);
    const rate = live && entry.tempo ? live / entry.tempo : clock.current.rate;
    if (!clock.current.running && fresh.length >= BAR) countOff(rate, live);   // a bar of taps starts the count
    else setClock({ rate });
  };

  // Two bars counted on screen, starting a beat after the last tap; the words start with the song.
  function countOff(rate: number, live: number | null) {
    const beat = 60 / (entry.tempo || live || 120);
    setClock({ rate, beat, running: true, base: -(COUNT_BEATS + 1) * beat });
    setNow(clock.current.base);
  }

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
    const id = window.setInterval(() => setNow(songTime()), 100);
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

  // Click a line: the words carry on from there (and start, if they were stopped).
  const jump = (i: number) => {
    const at = all[i].time ?? (i / Math.max(1, all.length)) * total;
    setClock({ base: Math.max(0, at - 0.2), running: true });
    setNow(clock.current.base);
  };

  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  // During the count-off: which beat of which bar (null before the first one, and after).
  const counted = now < 0 ? COUNT_BEATS + 1 - Math.ceil(-now / clock.current.beat) : null;
  const count = counted !== null && counted >= 1 ? { bar: Math.ceil(counted / 4), beat: ((counted - 1) % 4) + 1 } : null;

  return (
    <div className="stage-lyrics-wrap">
      <div className="lyrics-bar">
        <button className="button lyrics-tap" onClick={tap} title="Tap a bar along with the band (or press T): two bars are counted off, then the words start with the song.">
          Tap
        </button>
        <span className="lyrics-tempo">
          {bpm ? <><b>{bpm}</b> BPM{entry.tempo ? ` · album ${entry.tempo}` : ""}</> : entry.tempo ? <>album <b>{entry.tempo}</b> BPM</> : "tap for tempo"}
        </span>
        {now < 0 ? (
          <span className="lyrics-count" aria-live="off">
            {count ? <>Count-off <b>{count.bar}</b> bar · beat <b>{count.beat}</b></> : "Count-off…"}
          </span>
        ) : (
          <span className="lyrics-time">{mmss(now)} / {mmss(total / (clock.current.rate || 1))}</span>
        )}
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
          <p
            key={i}
            className={`lyric${i === current ? " now" : ""}${current >= 0 && i < current ? " sung" : ""}`}
            onClick={() => jump(i)}
            title="Carry on from here"
          >
            {l.text || " "}
          </p>
        ))}
      </section>
    </div>
  );
}
