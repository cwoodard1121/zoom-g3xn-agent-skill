// Macro knobs: one knob that moves several real knobs together, from wherever they are now.
// Turn it and every knob it covers moves up or down; let go and it springs back to the
// middle, ready to go further. Gain also eases the patch volume the other way.
import { useEffect, useRef, useState } from "react";
import type { EffectInfo, Tone } from "../api";
import { Knob } from "./Knob";

const REACH = 0.45; // a full turn moves each knob by up to 45% of its range
const SPRING_MS = 1200;

interface Target {
  index: number; // 0-based chain position in the tone
  effect: string;
  knob: string;
  max: number;
  weight: number;
}

interface Macro {
  name: string;
  targets: Target[];
  volumeWeight: number;
}

const RULES: { name: string; volumeWeight: number; match: (group: string, knob: string) => number }[] = [
  {
    name: "Gain",
    volumeWeight: -0.3,
    match: (g, k) =>
      (g === "DRIVE" && /^(gain|drive|dist|distortion|fuzz|sustain|sus)$/i.test(k)) || (g === "AMP" && /^gain$/i.test(k)) ? 1 : 0,
  },
  {
    name: "Brightness",
    volumeWeight: 0,
    match: (g, k) => ((g === "DRIVE" || g === "AMP") && /^(tone|treble|treb|pres|presence|high|hi|brght|bright)$/i.test(k) ? 1 : 0),
  },
  {
    name: "Space",
    volumeWeight: 0,
    match: (g, k) =>
      (g === "DELAY" || g === "REVERB") && /^mix$/i.test(k) ? 1 : g === "DELAY" && /^(f\.b|fb|feedback)$/i.test(k) ? 0.5 : 0,
  },
];

export function buildMacros(tone: Tone, infos: Record<string, EffectInfo>): Macro[] {
  return RULES.map((rule) => {
    const targets: Target[] = [];
    tone.chain.forEach((fx, index) => {
      const info = infos[fx.effect];
      if (!info) return;
      for (const p of info.params) {
        const weight = rule.match(info.group, p.name);
        if (weight && !p.shown_as?.options && p.name in fx.knobs) {
          targets.push({ index, effect: fx.effect, knob: p.name, max: p.max, weight });
        }
      }
    });
    return { name: rule.name, targets, volumeWeight: rule.volumeWeight };
  }).filter((m) => m.targets.length > 0);
}

export interface MacroMove {
  knobs: { index: number; knob: string; value: number }[];
  volume?: number;
}

export function Macros({ tone, infos, onMove }: { tone: Tone; infos: Record<string, EffectInfo>; onMove: (m: MacroMove) => void }) {
  const macros = buildMacros(tone, infos);
  if (macros.length === 0) return null;
  return (
    <div className="macros" aria-label="Macro knobs">
      <span className="macros-label">Macros</span>
      {macros.map((m) => (
        <MacroKnob key={m.name} macro={m} tone={tone} onMove={onMove} />
      ))}
    </div>
  );
}

function MacroKnob({ macro, tone, onMove }: { macro: Macro; tone: Tone; onMove: (m: MacroMove) => void }) {
  const [value, setValue] = useState(50);
  const base = useRef<Tone | null>(null);
  const held = useRef(false);
  const spring = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(spring.current), []);

  const springBack = (ms: number) => {
    window.clearTimeout(spring.current);
    spring.current = window.setTimeout(() => {
      base.current = null;
      setValue(50);
    }, ms);
  };

  const change = (v: number) => {
    base.current ??= tone; // turning starts from the tone as it is now
    setValue(v);
    const t = (v - 50) / 50;
    const from = base.current;
    onMove({
      knobs: macro.targets.map((tg) => {
        const start = from.chain[tg.index]?.knobs[tg.knob] ?? 0;
        return { index: tg.index, knob: tg.knob, value: clamp(start + tg.weight * t * REACH * tg.max, tg.max) };
      }),
      volume: macro.volumeWeight ? clamp(from.volume + macro.volumeWeight * t * REACH * 120, 120) : undefined,
    });
    if (held.current) window.clearTimeout(spring.current);
    else springBack(SPRING_MS); // scroll wheel or arrow keys: no release to wait for
  };

  const moves = macro.targets.map((t) => `${t.effect} ${t.knob}`).join(", ");
  const hint = `Moves ${moves}${macro.volumeWeight ? ", and eases the patch volume the other way" : ""}. Springs back to the middle when you let go.`;
  const shown = value === 50 ? "0" : value > 50 ? `+${value - 50}` : String(value - 50);
  return (
    <Knob
      label={macro.name}
      value={value}
      max={100}
      text={shown}
      hint={hint}
      onChange={change}
      onGrab={(h) => {
        held.current = h;
        if (!h) springBack(350);
      }}
    />
  );
}

function clamp(v: number, max: number) {
  return Math.max(0, Math.min(max, Math.round(v)));
}
