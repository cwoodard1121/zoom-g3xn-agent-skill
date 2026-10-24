// Shaping a set: an order for the songs that flows. Retuning between songs costs the most (a dead
// minute on stage), then a jarring key change, then a big tempo jump. "Build" also wants the tempo
// to climb through the set. The opener and the closer can stay put.
import type { GigEntry } from "./api";
import { sameTuning, tuningOf } from "./tuning";

export type Shape = "smooth" | "build";

const PITCH: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

/** A key ("E", "C#m", "Bb minor") as its place on the circle of fifths, minor keys at their relative major. */
function fifths(key?: string): number | null {
  const m = /^\s*([A-Ga-g])\s*([#♯b♭]?)\s*(m(?!aj)|min(?:or)?|-)?/.exec(key ?? "");
  if (!m) return null;
  let pc = PITCH[m[1].toUpperCase()] + (m[2] === "#" || m[2] === "♯" ? 1 : m[2] ? -1 : 0);
  if (m[3]) pc += 3;                                    // A minor sits with C major
  pc = ((pc % 12) + 12) % 12;
  return (pc * 7) % 12;                                 // semitones to steps round the circle
}

const keyGap = (a?: string, b?: string) => {
  const x = fifths(a), y = fifths(b);
  if (x === null || y === null) return 1;
  const d = Math.abs(x - y) % 12;
  return Math.min(d, 12 - d);                           // 0 same key ... 6 the far side
};

/** What moving from song a to song b costs. */
export function step(a: GigEntry, b: GigEntry, shape: Shape): number {
  let cost = sameTuning(tuningOf(a.tuning), tuningOf(b.tuning)) ? 0 : 100;
  cost += keyGap(a.key, b.key) * 3;
  if (a.tempo && b.tempo) {
    const jump = b.tempo - a.tempo;
    cost += Math.abs(jump) / 8;
    if (shape === "build" && jump < 0) cost += -jump / 3;
  }
  return cost;
}

const total = (order: GigEntry[], shape: Shape) => order.slice(1).reduce((c, e, i) => c + step(order[i], e, shape), 0);

/** The songs in a better order (and how many retunes it saves). `keepEnds`: the first and last stay put. */
export function shapeSet(songs: GigEntry[], shape: Shape, keepEnds = true) {
  const n = songs.length;
  if (n < 3) return { order: songs, before: retunes(songs), after: retunes(songs) };
  const fixedFirst = keepEnds ? songs[0] : null;
  const fixedLast = keepEnds ? songs[n - 1] : null;
  const middle = songs.filter((s) => s !== fixedFirst && s !== fixedLast);

  // Nearest next song from each possible start, then untangle with 2-opt.
  let best: GigEntry[] = songs;
  let bestCost = total(songs, shape);
  const starts = fixedFirst ? [fixedFirst] : songs;
  for (const start of starts) {
    const left = (fixedFirst ? middle : songs.filter((s) => s !== start && s !== fixedLast)).slice();
    const order = [start];
    while (left.length) {
      const here = order[order.length - 1];
      let k = 0;
      for (let j = 1; j < left.length; j++) if (step(here, left[j], shape) < step(here, left[k], shape)) k = j;
      order.push(left.splice(k, 1)[0]);
    }
    if (fixedLast) order.push(fixedLast);
    const lo = 1, hi = order.length - (fixedLast ? 2 : 1);
    for (let better = true; better; ) {
      better = false;
      for (let i = lo; i < hi; i++) {
        for (let j = i + 1; j <= hi; j++) {
          const tried = [...order.slice(0, i), ...order.slice(i, j + 1).reverse(), ...order.slice(j + 1)];
          if (total(tried, shape) + 1e-9 < total(order, shape)) {
            order.splice(0, order.length, ...tried);
            better = true;
          }
        }
      }
    }
    const cost = total(order, shape);
    if (cost < bestCost - 1e-9) {
      best = order;
      bestCost = cost;
    }
  }
  return { order: best, before: retunes(songs), after: retunes(best) };
}

export function retunes(songs: GigEntry[]) {
  return songs.slice(1).filter((e, i) => !sameTuning(tuningOf(songs[i].tuning), tuningOf(e.tuning))).length;
}
