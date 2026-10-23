// Cues: effects a song switches as it goes, a line each in the gig: "1:05 Octave on", "2:30 3 off"
// (an effect by name, the start of its name, or its number in the chain; then on or off). The stage
// view runs them off the song clock.
import { mmss } from "./songclock";

export interface Cue {
  at: number; // seconds into the recording
  effect: string;
  on: boolean;
}

export function parseCues(text?: string): Cue[] {
  return (text ?? "")
    .split("\n")
    .flatMap((line) => {
      const m = /^(\d+):(\d{1,2}(?:\.\d+)?)\s+(.+?)\s+(on|off)$/i.exec(line.trim());
      return m ? [{ at: Number(m[1]) * 60 + Number(m[2]), effect: m[3], on: m[4].toLowerCase() === "on" }] : [];
    })
    .sort((a, b) => a.at - b.at);
}

/** Which effect in `chain` a cue means, the way the daemon finds one (-1 if none). */
export function effectIndex(chain: { effect: string }[], which: string): number {
  const want = which.trim().toLowerCase();
  if (/^\d+$/.test(want)) return Number(want) >= 1 && Number(want) <= chain.length ? Number(want) - 1 : -1;
  for (const match of [(n: string) => n === want, (n: string) => n.startsWith(want), (n: string) => n.includes(want)]) {
    const i = chain.findIndex((c) => match(c.effect.toLowerCase()));
    if (i >= 0) return i;
  }
  return -1;
}

export const cueLine = (at: number, effect: string, on: boolean) => `${mmss(at)} ${effect} ${on ? "on" : "off"}`;

/** A song's cues with a new one added, in time order. */
export function addCue(text: string | undefined, at: number, effect: string, on: boolean) {
  const all = [...(text ?? "").split("\n").filter((l) => l.trim()), cueLine(at, effect, on)];
  const time = (l: string) => parseCues(l)[0]?.at ?? Infinity;
  return all.sort((a, b) => time(a) - time(b)).join("\n");
}
