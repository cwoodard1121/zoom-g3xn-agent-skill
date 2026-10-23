// Where the band is in the song, in the recording's seconds, so the words, the cues and the
// backing track can all follow it. Hands free: the band starts, you listen for a bar, then tap two
// bars on the pedal (hold FS3 for its tap tempo, then tap it) or with T. The first bar of taps only
// finds the beat; the second sets the band's tempo. The song is three bars in by the last tap, so
// the clock starts there, running that much faster or slower than the recording. Tapping again
// later follows the band.
import { useEffect, useRef, useState } from "react";
import type { GigEntry } from "./api";
import { usePedal } from "./pedal";

const TAP_RESET_MS = 2500; // a gap this long starts a new count
const LISTEN = 4; // beats the band plays before the first tap
export const WARM_UP = 4; // the first bar of taps: only finding the beat
export const TAPS = 8; // two bars of taps, then the clock runs

interface Tap {
  t: number; // ms (Date.now)
  bpm?: number; // from the gap since the tap before (the pedal measures its own)
}

const average = (taps: Tap[]) => {
  const bpms = taps.map((x) => x.bpm).filter((b): b is number => !!b);
  return bpms.length ? bpms.reduce((a, b) => a + b, 0) / bpms.length : null;
};

interface Clock {
  base: number; // song seconds at `since`
  since: number; // performance.now()
  rate: number; // the band's tempo over the recording's
  running: boolean;
  beat: number; // one beat, in the recording's seconds
}
const STOPPED: Clock = { base: 0, since: 0, rate: 1, running: false, beat: 0.5 };

export interface SongClock {
  time: () => number; // where the song is now
  running: boolean;
  rate: number;
  beat: number;
  bpm: number | null; // the band's tempo, once tapped
  taps: number; // taps in the count so far
  moved: number; // goes up whenever the clock jumps, starts, stops or changes speed
  tap: () => void;
  jump: (at: number) => void; // carry on from `at` seconds (and run)
  toggle: () => void; // pause or carry on
  reset: () => void; // back to the top, stopped
}

export function useSongClock(entry: GigEntry | undefined): SongClock {
  const clock = useRef<Clock>(STOPPED);
  const [running, setRunning] = useState(false);
  const [moved, setMoved] = useState(0);
  const [taps, setTaps] = useState<Tap[]>([]);
  const [bpm, setBpm] = useState<number | null>(null);
  const tempo = entry?.tempo;

  const time = () => {
    const c = clock.current;
    return c.running ? c.base + ((performance.now() - c.since) / 1000) * c.rate : c.base;
  };
  const set = (patch: Partial<Clock>) => {
    clock.current = { ...clock.current, base: time(), since: performance.now(), ...patch };
    setRunning(clock.current.running);
    setMoved((m) => m + 1);
  };

  // A new song: back to the top, stopped.
  useEffect(() => {
    clock.current = STOPPED;
    setRunning(false);
    setMoved((m) => m + 1);
    setTaps([]);
    setBpm(null);
  }, [entry?.song]);

  // Every tap, from here or the pedal, lands here.
  const tapsRef = useRef(taps);
  tapsRef.current = taps;
  const counted = (series: Tap[]) => {
    setTaps(series);
    if (!clock.current.running) {
      if (series.length < TAPS) return;
      const live = average(series.slice(WARM_UP)); // the second bar only
      if (!live) return;
      const rate = tempo ? live / tempo : 1;
      const beat = 60 / (tempo || live);
      const last = series[series.length - 1].t;
      const since = Math.max(0, Date.now() - last) / 1000; // how long ago the last tap was
      setBpm(Math.round(live));
      set({ rate, beat, running: true, base: (LISTEN + TAPS - 1) * beat + since * rate });
    } else if (series.length >= WARM_UP) {
      const live = average(series.slice(-WARM_UP)); // the last bar: follow the band
      if (!live) return;
      setBpm(Math.round(live));
      if (tempo) set({ rate: live / tempo });
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

  return {
    time,
    running,
    rate: clock.current.rate,
    beat: clock.current.beat,
    bpm,
    taps: taps.length,
    moved,
    tap,
    jump: (at) => set({ base: Math.max(0, at), running: true }),
    toggle: () => set({ running: !clock.current.running }),
    reset: () => {
      set({ base: 0, running: false });
      setTaps([]);
    },
  };
}

/** The song's time, every frame while the clock runs. */
export function useSongTime(clock: SongClock) {
  const [now, setNow] = useState(clock.time());
  useEffect(() => {
    setNow(clock.time());
    if (!clock.running) return;
    let id = 0;
    const tick = () => {
      setNow(clock.time());
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [clock.running, clock.moved]);
  return now;
}

export const mmss = (s: number) => {
  const t = Math.max(0, s);
  return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
};
