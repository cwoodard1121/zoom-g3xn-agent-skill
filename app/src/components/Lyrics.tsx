// The song's words on the stage view, roughly in time with the band, hands free: tap two bars on
// the pedal (hold FS3 for its tap tempo, then tap it) or with Tap / T here. The first bar is just
// for finding the beat; the second sets the band's tempo, and the words start on the next downbeat,
// running that much faster or slower than the recording. Tapping again later follows the band.
// Scroll starts them straight away; clicking a line carries on from there. With timed lyrics the
// line being sung lights up.
import { useEffect, useMemo, useRef, useState } from "react";
import type { GigEntry } from "../api";
import { length, lines } from "../lyrics";
import { usePedal } from "../pedal";

const TAP_RESET_MS = 2500; // a gap this long starts a new count
const WARM_UP = 4; // the first bar: taps that only find the beat
const START = 8; // two bars of taps, then the song

interface Tap {
  t: number; // ms (Date.now)
  bpm?: number; // from the gap since the tap before (the pedal measures its own)
}

const average = (taps: Tap[]) => {
  const bpms = taps.map((x) => x.bpm).filter((b): b is number => !!b);
  return bpms.length ? bpms.reduce((a, b) => a + b, 0) / bpms.length : null;
};

export function Lyrics({ entry }: { entry: GigEntry }) {
  const all = useMemo(() => lines(entry), [entry]);
  const timed = all.some((l) => l.time !== null);
  const total = length(entry, all);

  // Song time = base + (now - since) * rate while running, in the recording's seconds.
  const clock = useRef({ base: 0, since: 0, rate: 1, running: false, beat: 0.5 });
  const [running, setRunning] = useState(false);
  const [taps, setTaps] = useState<Tap[]>([]);
  const [bpm, setBpm] = useState<number | null>(null);
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
    setBpm(null);
    setNow(0);
    box.current?.scrollTo({ top: 0 });
  }, [entry.song]);

  // Every tap, from here or the pedal, lands here.
  const tapsRef = useRef(taps);
  tapsRef.current = taps;
  const counted = (series: Tap[]) => {
    setTaps(series);
    if (!clock.current.running) {
      if (series.length < START) return;
      const live = average(series.slice(WARM_UP));            // the second bar only
      if (!live) return;
      const beat = 60 / (entry.tempo || live);                 // one beat, in the recording's seconds
      setBpm(Math.round(live));
      setClock({ rate: entry.tempo ? live / entry.tempo : 1, beat, running: true, base: -beat });   // in on the next 1
      setNow(-beat);
    } else if (series.length >= WARM_UP) {
      const live = average(series.slice(-WARM_UP));             // the last bar: follow the band
      if (!live) return;
      setBpm(Math.round(live));
      if (entry.tempo) setClock({ rate: live / entry.tempo });
    }
  };
  const fresh = (t: number) => {
    const last = tapsRef.current[tapsRef.current.length - 1];
    return !last || t - last.t > TAP_RESET_MS;
  };

  const tap = () => {
    const t = Date.now();
    const series = tapsRef.current;
    counted(fresh(t) ? [{ t }] : [...series, { t, bpm: 60000 / (t - series[series.length - 1].t) }]);
  };

  // The pedal's own tap tempo: it reports from the second tap on, with the tempo it measured.
  const { pedalTempo } = usePedal();
  const seenTempo = useRef(pedalTempo?.at);
  useEffect(() => {
    if (!pedalTempo || pedalTempo.at === seenTempo.current) return;
    seenTempo.current = pedalTempo.at;
    const t = pedalTempo.at;
    const step = { t, bpm: pedalTempo.bpm };
    counted(fresh(t) ? [{ t: t - 60000 / pedalTempo.bpm }, step] : [...tapsRef.current, step]);
  });

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

  // Tick every frame while running.
  useEffect(() => {
    if (!running) return;
    let id = 0;
    const tick = () => {
      setNow(songTime());
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [running]);

  const current = timed ? all.reduce((at, l, i) => (l.time !== null && l.time <= now ? i : at), -1) : -1;

  // Keep the words moving: the sung line a third of the way down, or an even scroll.
  useEffect(() => {
    const el = box.current;
    if (!el || !running || now < 0) return;
    if (timed) {
      const line = el.querySelectorAll<HTMLElement>(".lyric")[Math.max(current, 0)];
      if (line) el.scrollTo({ top: line.offsetTop - el.clientHeight * 0.35, behavior: "smooth" });
    } else {
      el.scrollTo({ top: (el.scrollHeight - el.clientHeight) * Math.min(1, now / total) });
    }
  }, [timed ? current : Math.round(now * 4), running]);

  // Click a line: the words carry on from there (and start, if they were stopped).
  const jump = (i: number) => {
    const at = all[i].time ?? (i / Math.max(1, all.length)) * total;
    setClock({ base: Math.max(0, at - 0.2), running: true });
    setNow(clock.current.base);
  };

  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  // The eight lights: taps filling two bars, then the beat going round them.
  const beatNow = running ? Math.floor(now / clock.current.beat) : null;
  const lit = (i: number) => (beatNow !== null ? ((beatNow % START) + START) % START === i : i < taps.length);
  const tapHint = running
    ? "Tap again any time to follow the band"
    : taps.length === 0
      ? "Tap two bars: FS3 (hold it first) or T"
      : taps.length < WARM_UP
        ? "Finding the beat…"
        : "Counting in…";

  return (
    <div className="stage-lyrics-wrap" style={{ viewTransitionName: "stage-words" }}>
      <div className="lyrics-bar">
        <button className="button lyrics-tap" onClick={tap} title="Tap two bars with the band (or press T, or tap FS3 on the pedal). The first bar is ignored; the words start on the next downbeat.">
          Tap
        </button>
        <span className={`tap-lights${running ? " running" : ""}`} aria-hidden="true">
          {Array.from({ length: START }, (_, i) => (
            <span key={i} className={`tap-light${i < WARM_UP ? " warm" : ""}${i % 4 === 0 ? " one" : ""}${lit(i) ? " lit" : ""}`} />
          ))}
        </span>
        <span className="lyrics-tempo">
          {bpm ? <><b>{bpm}</b> BPM{entry.tempo ? ` · album ${entry.tempo}` : ""}</> : entry.tempo ? <>album <b>{entry.tempo}</b> BPM</> : "no tempo yet"}
        </span>
        <span className="lyrics-time">{now < 0 ? "in on 1…" : `${mmss(now)} / ${mmss(total / (clock.current.rate || 1))}`}</span>
        <span className="stage-spacer" />
        <button className="button" aria-pressed={running} onClick={() => setClock({ running: !running })}>
          {running ? "Pause" : now > 0 ? "Resume" : "Scroll"}
        </button>
        <button
          className="button"
          onClick={() => {
            setClock({ base: 0, running: false });
            setTaps([]);
            setNow(0);
            box.current?.scrollTo({ top: 0, behavior: "smooth" });
          }}
          disabled={now === 0 && !taps.length}
        >
          Top
        </button>
      </div>
      <p className="tap-hint" aria-live="polite">{tapHint}</p>
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
