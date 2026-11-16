// A/B: keep two versions of the tone and flip between them by ear.
// The A or B key plays it; "Set" stores what you hear now. Snapshots stay on this device.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Tone } from "../api";
import { usePedal } from "../pedal";

type Side = "A" | "B";
type Snaps = Partial<Record<Side, Tone>>;
const KEY = "g3xn.ab";

export function ABSwitch({ tone }: { tone: Tone }) {
  const { act, say } = usePedal();
  const [snaps, setSnaps] = useState<Snaps>(load);
  const current = plain(tone);
  const matches = (side: Side) => !!snaps[side] && same(snaps[side]!, current);

  const store = (side: Side) => {
    const next = { ...snaps, [side]: current };
    setSnaps(next);
    save(next);
    say(`Saved what you hear as ${side}`);
  };
  const play = (side: Side) => {
    const snap = snaps[side];
    if (!snap) store(side);
    else if (!matches(side)) act(() => api.play(snap));
  };

  // The A and B keys, except while typing.
  const playRef = useRef(play);
  playRef.current = play;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement).closest("input, textarea")) return;
      const side = e.key.toUpperCase();
      if (side === "A" || side === "B") playRef.current(side);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="toolbar-group ab" aria-label="A/B compare">
      {(["A", "B"] as const).map((side) => (
        <div className="ab-side" key={side}>
          <button
            className={`ab-key${snaps[side] ? "" : " empty"}`}
            aria-pressed={matches(side)}
            onClick={() => play(side)}
            title={snaps[side] ? `Play ${side} (key ${side})` : `Save what you hear as ${side}`}
          >
            {side}
          </button>
          {snaps[side] && !matches(side) && (
            <button className="ab-set" onClick={() => store(side)} title={`Replace ${side} with what you hear now`}>
              Set {side}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function plain(t: Tone): Tone {
  return {
    name: t.name, volume: t.volume, dsp_percent: t.dsp_percent,
    chain: t.chain.map((fx) => ({ effect: fx.effect, on: fx.on, knobs: { ...fx.knobs } })),
  };
}

function same(a: Tone, b: Tone): boolean {
  return a.volume === b.volume && JSON.stringify(a.chain) === JSON.stringify(b.chain);
}

function load(): Snaps {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "{}");
  } catch {
    return {};
  }
}

function save(s: Snaps) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // private window or storage blocked: A/B still works until the app closes
  }
}
