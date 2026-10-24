// Where things are in a song: its parts (verses, choruses, the solo...) and what someone means by
// "chorus", "you're two bars behind" or a line of the words.
//
// The parts come from the gig's cues when it has "1:05 part Chorus" lines; otherwise they're worked
// out from the words: lines that come back are the chorus, the rest are verses (a one-off after the
// second chorus is the bridge), and a long gap with no words is the intro, a solo or the outro.
import type { GigEntry } from "./api";
import type { Line } from "./lyrics";

export type Kind = "intro" | "verse" | "pre" | "chorus" | "bridge" | "solo" | "outro" | "part";

export interface Part {
  kind: Kind;
  label: string; // "Verse 2", "Chorus", "Solo"
  n: number; // which one of its kind, from 1
  at: number; // seconds into the recording
  end: number;
}

const GAP = 8; // seconds without words that count as a part of their own

const words = (s: string) =>
  s
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/[^a-z0-9 ]+/g, " ")
    .split(" ")
    .filter(Boolean);
const key = (s: string) => words(s).join(" ");

const KINDS: Record<string, Kind> = {
  intro: "intro", verse: "verse", pre: "pre", "pre chorus": "pre", prechorus: "pre", chorus: "chorus", hook: "chorus",
  refrain: "chorus", bridge: "bridge", middle: "bridge", "middle eight": "bridge", solo: "solo", break: "solo",
  instrumental: "solo", outro: "outro", ending: "outro", end: "outro", coda: "outro",
};
const NAMES: Record<Kind, string> = {
  intro: "Intro", verse: "Verse", pre: "Pre-chorus", chorus: "Chorus", bridge: "Bridge", solo: "Solo", outro: "Outro", part: "Part",
};

/** Part markers written in the cues: "1:05 part Chorus", "2:40 section solo". */
function markedParts(cues: string | undefined, total: number): Part[] {
  const marks = (cues ?? "").split("\n").flatMap((line) => {
    const m = /^(\d+):(\d{1,2}(?:\.\d+)?)\s+(?:part|section)\s+(.+)$/i.exec(line.trim());
    return m ? [{ at: Number(m[1]) * 60 + Number(m[2]), name: m[3].trim() }] : [];
  });
  marks.sort((a, b) => a.at - b.at);
  const seen: Partial<Record<Kind, number>> = {};
  return marks.map((m, i) => {
    const bare = key(m.name).replace(/\s*\d+$/, "");
    const kind = KINDS[bare] ?? "part";
    const n = (seen[kind] = (seen[kind] ?? 0) + 1);
    return { kind, label: m.name, n, at: m.at, end: marks[i + 1]?.at ?? total };
  });
}

/** The song's parts, in order, covering it from 0 to `total`. */
export function partsOf(entry: GigEntry, all: Line[], total: number): Part[] {
  const marked = markedParts(entry.cues, total);
  if (marked.length) return marked;

  // Each line's time (an even spread when the words aren't timed).
  const t = (i: number) => all[i].time ?? (i / Math.max(1, all.length)) * total;
  const sung = all.flatMap((l, i) => (l.text.trim() ? [{ i, key: key(l.text) }] : []));
  if (!sung.length) return [{ kind: "part", label: "Song", n: 1, at: 0, end: total }];
  const gaps = sung.map((l, j) => (j ? t(l.i) - t(sung[j - 1].i) : 0)).filter((g) => g > 0).sort((x, y) => x - y);
  const usual = gaps[Math.floor(gaps.length / 2)] ?? 4;

  // A line sung more than once is a chorus line. One odd line out in a run of the other kind goes
  // with the run (a chorus with one line that changes; a verse that ends on the hook).
  const count = new Map<string, number>();
  for (const l of sung) count.set(l.key, (count.get(l.key) ?? 0) + 1);
  const again = sung.map((l) => (count.get(l.key) ?? 0) > 1 && l.key.split(" ").length >= 2);
  const smooth = again.map((r, j) => (j > 0 && j < again.length - 1 && again[j - 1] === again[j + 1] && r !== again[j - 1] ? again[j - 1] : r));

  // Blocks: runs of chorus lines and runs of the rest, also broken by a blank line or a long gap.
  const blocks: { from: number; to: number; chorus: boolean }[] = [];
  sung.forEach((l, j) => {
    const prev = sung[j - 1];
    const blankBefore = prev && all.slice(prev.i + 1, l.i).some((x) => !x.text.trim());
    const gapBefore = prev && t(l.i) - t(prev.i) > Math.max(usual * 2.2, 5);
    const last = blocks[blocks.length - 1];
    if (!last || last.chorus !== smooth[j] || gapBefore || (blankBefore && !smooth[j])) blocks.push({ from: l.i, to: l.i, chorus: smooth[j] });
    else last.to = l.i;
  });

  const parts: Part[] = [];
  const seen: Partial<Record<Kind, number>> = {};
  const add = (kind: Kind, at: number, end: number) => {
    const n = (seen[kind] = (seen[kind] ?? 0) + 1);
    parts.push({ kind, label: kind === "verse" || kind === "chorus" || kind === "solo" ? `${NAMES[kind]}${n > 1 || kind === "verse" ? ` ${n}` : ""}` : NAMES[kind], n, at, end });
  };
  const firstAt = t(blocks[0].from);
  if (firstAt > GAP) add("intro", 0, firstAt - 0.5);
  blocks.forEach((s, i) => {
    const at = Math.max(0, t(s.from) - 0.5);
    const lastLine = all[s.to].time !== null ? t(s.to) + Math.min(usual * 1.5, 6) : t(s.to) + usual;
    const next = blocks[i + 1] ? Math.max(0, t(blocks[i + 1].from) - 0.5) : total;
    const choruses = blocks.slice(0, i).filter((x) => x.chorus).length;
    const kind: Kind = s.chorus ? "chorus" : choruses >= 2 && blocks.slice(i + 1).some((x) => x.chorus) ? "bridge" : "verse";
    // The words stop well before the next part starts: what's between is a solo (or the outro).
    if (next - lastLine > GAP) {
      add(kind, at, lastLine);
      add(i === blocks.length - 1 ? "outro" : "solo", lastLine, next);
    } else {
      add(kind, at, next);
    }
  });
  // "Chorus 1" reads oddly when there's only one.
  for (const p of parts) if (p.kind === "chorus" && seen.chorus === 1) p.label = "Chorus";
  if (seen.solo === 1) for (const p of parts) if (p.kind === "solo") p.label = "Solo";
  return parts;
}

export const partAt = (parts: Part[], at: number) => parts.find((p) => at >= p.at && at < p.end) ?? parts[parts.length - 1];

// --- what was said ---

export type Heard =
  | { do: "jump"; at: number; said: string; live: boolean } // live: it's happening now (allow for the delay hearing it)
  | { do: "nudge"; by: number; said: string } // seconds of the recording, + is later in the song
  | { do: "pause" | "go" | "top"; said: string };

const NUMBERS: Record<string, number> = {
  a: 1, an: 1, one: 1, two: 2, to: 2, too: 2, couple: 2, three: 3, four: 4, for: 4, five: 5, six: 6,
  seven: 7, eight: 8, half: 0.5,
};
// Which one ("second verse", "verse 2"): no "to" or "for" here, so "go to verse" is just a verse.
const ORDINALS: Record<string, number> = {
  one: 1, first: 1, "1st": 1, two: 2, second: 2, "2nd": 2, three: 3, third: 3, "3rd": 3, four: 4, fourth: 4,
  "4th": 4, five: 5, fifth: 5,
};
const num = (w?: string) => (w === undefined ? undefined : /^\d+(\.\d+)?$/.test(w) ? Number(w) : NUMBERS[w]);
const ordinal = (w?: string) => (w === undefined ? undefined : /^\d+$/.test(w) ? Number(w) : ORDINALS[w]);

const GEAR = /\b(gain|delay|reverb|overdrive|distortion|fuzz|volume|treble|bass|mids|patch|effect|amp|tremolo|flanger|phaser|octave|wah|knob|fizzy|pedal|tuner)\b/;
const TONE = /\b(on|off|turn|make|more|less|louder|quieter|tone|drive|level)\b/;
const PART_TALK = new Set(("skip jump go to the a we re were are in at its it s now this is here thats back take me start from of " +
  "into lets let next last final first second third fourth fifth 1st 2nd 3rd 4th 1 2 3 4 5 one two three four five part the into ok okay").split(" "));
const SKIP = /\b(skip|jump|go to|back to|next|take me|start (at|from)|from the)\b/;

interface Where {
  now: number; // where the clock is
  beat: number; // a beat, in the recording's seconds
  parts: Part[];
  lines: Line[];
  total: number;
}

/** What someone said, as something for the song clock to do, or null if it's not about where the
 * song is (then it goes on to Claude). */
export function understand(text: string, w: Where): Heard | null {
  const said = text.trim();
  const ws = words(said);
  const s = ws.join(" ");
  if (!s) return null;

  if (/^(stop|pause|hold on|wait)( (it|the words|the lyrics|scrolling))?$/.test(s)) return { do: "pause", said };
  if (/^(go|resume|carry on|keep going|play|start|unpause)( (it|the words|the lyrics|scrolling))?$/.test(s)) return { do: "go", said };
  if (/^(from the top|top|start over|restart|again from the top|back to the (top|start|beginning))$/.test(s)) return { do: "top", said };

  // Tone talk is for Claude, even when it names a part ("more gain on the solo", "chorus on").
  if (GEAR.test(s)) return null;
  const toneish = TONE.test(s);

  // A part named with no amount ("go back to the chorus") is a jump, not a nudge.
  const partWord = /\b(intro|verse|pre chorus|prechorus|chorus|hook|refrain|bridge|middle eight|solo|break|instrumental|outro|ending|coda)\b/.exec(s);

  // Nudges: "you're two bars behind", "we're ahead a bit", "move up a bit", "back a bar".
  const bar = 4 * w.beat;
  const amount = (() => {
    const m = /(\d+(?:\.\d+)?|a|an|one|two|to|too|three|four|for|five|six|seven|eight|half|couple)(?: of)? (bars?|beats?|seconds?|secs?|measures?|lines?)/.exec(s);
    if (m) {
      const n = num(m[1]) ?? 1;
      const unit = m[2];
      if (unit.startsWith("beat")) return n * w.beat;
      if (unit.startsWith("sec")) return n;
      if (unit.startsWith("line")) return n * 2 * bar;
      return n * bar;
    }
    if (/\b(a lot|way|loads|heaps|lots)\b/.test(s)) return 4 * bar;
    if (/\b(a (little|tiny|touch|smidge)|slightly|a bit|bit)\b/.test(s)) return bar / 2;
    return null;
  })();
  const behind = /\b(behind|late|slow|lagging|catch up|move up|skip ahead|jump ahead|go forward|forward|faster)\b/.test(s);
  const ahead = /\b(ahead|early|too fast|go back|back up|move back|backwards?|rewind|back)\b/.test(s.replace(/\b(skip|jump) ahead\b/g, ""));
  if (!toneish && !(partWord && amount === null) && (behind || ahead) && (amount !== null || /\b(behind|ahead|early|late|move up|go back|back up)\b/.test(s))) {
    // "We're" means the band: the band behind the words means the words go back.
    const band = /^(we re|we are|were|the band|band|the band s|we)\b/.test(s);
    let sign = behind && !ahead ? 1 : ahead && !behind ? -1 : /\bbehind\b/.test(s) ? 1 : -1;
    if (band && /\b(behind|ahead|early|late)\b/.test(s)) sign = -sign;
    return { do: "nudge", by: sign * (amount ?? bar), said };
  }

  // A part: "chorus", "second verse", "skip to the solo", "last chorus", "we're in the bridge".
  if (partWord && !toneish && ws.every((x) => PART_TALK.has(x) || x === partWord[1] || partWord[1].split(" ").includes(x))) {
    const kind = KINDS[partWord[1]];
    const ofKind = w.parts.filter((p) => p.kind === kind);
    if (!ofKind.length) return null;
    const before = s.slice(0, partWord.index).split(" ").filter(Boolean);
    const after = s.slice(partWord.index + partWord[1].length).split(" ").filter(Boolean);
    const which = ordinal(before[before.length - 1]) ?? ordinal(after[0]);
    let part: Part | undefined;
    if (/\b(last|final)\b/.test(s)) part = ofKind[ofKind.length - 1];
    else if (/\bnext\b/.test(s)) part = ofKind.find((p) => p.at > w.now + 1) ?? ofKind[ofKind.length - 1];
    else if (which && which >= 1) part = ofKind[Math.min(ofKind.length, which) - 1];
    else part = ofKind.reduce((best, p) => (Math.abs(p.at - w.now) < Math.abs(best.at - w.now) ? p : best)); // the nearest one
    // "We're in the chorus" is now; "skip to the chorus" is its start.
    return { do: "jump", at: part.at, said: part.label, live: !SKIP.test(s) };
  }

  // A line of the words: the closest match, the nearest one to now when it comes back.
  const sung = ws.filter((x) => !["skip", "go", "jump", "to", "the", "line", "where", "its", "we", "re", "at", "were"].includes(x) || ws.length < 4);
  if (sung.length >= 2) {
    const bag = new Set(sung);
    const scored = w.lines.flatMap((l, i) => {
      const lw = words(l.text);
      if (lw.length < 2) return [];
      const hits = lw.filter((x) => bag.has(x)).length;
      const score = hits / Math.max(sung.length, Math.min(lw.length, 6));
      const at = l.time ?? (i / Math.max(1, w.lines.length)) * w.total;
      return hits >= 2 && score >= 0.5 ? [{ score, at, text: l.text }] : [];
    });
    if (scored.length) {
      const best = Math.max(...scored.map((x) => x.score));
      const hit = scored.filter((x) => x.score >= best - 0.1).reduce((a, b) => (Math.abs(b.at - w.now) < Math.abs(a.at - w.now) ? b : a));
      return { do: "jump", at: Math.max(0, hit.at - 0.2), said: "that line", live: !SKIP.test(s) };
    }
  }
  return null;
}

/** For a continuous listener (the singer, heard by the browser): the line just sung, near where
 * the clock thinks the song is, or null. Stricter than `understand`: it only ever nudges. */
export function followLine(heard: string, w: Where, window = 25): number | null {
  const got = words(heard);
  if (got.length < 3) return null;
  const tail = got.slice(-8);
  const bag = new Set(tail);
  let best: { score: number; at: number } | null = null;
  w.lines.forEach((l, i) => {
    const at = l.time ?? (i / Math.max(1, w.lines.length)) * w.total;
    if (Math.abs(at - w.now) > window) return;
    const lw = words(l.text);
    if (lw.length < 3) return;
    const hits = lw.filter((x) => bag.has(x)).length;
    const score = hits / Math.min(lw.length, tail.length);
    if (hits >= 3 && score >= 0.6 && (!best || score > best.score || (score === best.score && Math.abs(at - w.now) < Math.abs(best.at - w.now)))) best = { score, at };
  });
  return best ? (best as { at: number }).at : null;
}
