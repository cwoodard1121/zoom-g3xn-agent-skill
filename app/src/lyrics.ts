// Lyrics: fill a gig's in from LRCLIB (through the daemon), and the timing the stage view
// scrolls them by.
import { api } from "./api";
import type { Gig, GigEntry } from "./api";

/** Look up words for the songs with none (or just song `only`). Songs that already have words
 * keep them; they only gain the timing (when LRCLIB's words are the same ones). Throws offline. */
export async function fillLyrics(gig: Gig, only?: number): Promise<{ gig: Gig; found: number; missing: string[] }> {
  let patches = gig.patches;
  let found = 0;
  const missing: string[] = [];
  for (let i = 0; i < patches.length; i++) {
    const e = patches[i];
    const wanted = only !== undefined ? i === only : !e.lyrics || e.duration === undefined;
    if (!wanted || !e.song.trim()) continue;
    const hit = await api.lyrics(e.song, e.artist);
    if (!hit.found || !hit.lyrics) {
      if (!e.lyrics) missing.push(e.song);
      continue;
    }
    const replace = only !== undefined || !e.lyrics;
    const same = replace || e.lyrics!.trim() === hit.lyrics.trim();
    const next: GigEntry = {
      ...e,
      artist: e.artist || hit.artist,
      lyrics: replace ? hit.lyrics : e.lyrics,
      synced: same ? hit.synced ?? undefined : e.synced,
      duration: hit.duration ?? undefined,
    };
    patches = patches.map((x, j) => (j === i ? next : x));
    if (replace) found++;
  }
  return { gig: { ...gig, patches }, found, missing };
}

export function lyricsMessage(found: number, missing: string[]): string {
  if (found) return `Found lyrics for ${found} song${found === 1 ? "" : "s"}${missing.length ? `. None for ${missing.join(", ")}` : ""}`;
  return missing.length ? `No lyrics found for ${missing.join(", ")}` : "Every song has lyrics";
}

export interface Line {
  time: number | null; // seconds into the recording, when the lyrics are timed
  text: string;
}

/** The lines to show: timed ones from `synced` when there are any, else the plain words. */
export function lines(entry: GigEntry): Line[] {
  const timed: Line[] = [];
  for (const raw of (entry.synced ?? "").split("\n")) {
    const m = raw.match(/^\[(\d+):(\d+(?:\.\d+)?)\]\s?(.*)$/);
    if (m) timed.push({ time: Number(m[1]) * 60 + Number(m[2]), text: m[3] });
  }
  if (timed.length) return timed;
  return (entry.lyrics ?? "").split("\n").map((text) => ({ time: null, text }));
}

/** How long the song runs at the album's tempo, in seconds: the recording's length, or a guess. */
export function length(entry: GigEntry, all: Line[]): number {
  if (entry.duration) return entry.duration;
  const last = all[all.length - 1]?.time;
  return last ? last + 15 : Math.max(120, all.filter((l) => l.text.trim()).length * 4);
}

/** Beats per minute from tap times (ms): the average of the last few gaps, or null. */
export function tapped(taps: number[]): number | null {
  const recent = taps.slice(-6);
  if (recent.length < 3) return null;
  const gap = (recent[recent.length - 1] - recent[0]) / (recent.length - 1);
  return Math.round(60000 / gap);
}
