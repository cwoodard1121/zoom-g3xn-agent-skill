// Fill in a gig's lyrics from LRCLIB (through the daemon), for the songs that have none,
// or just one song. Throws if LRCLIB can't be reached.
import { api } from "./api";
import type { Gig } from "./api";

export async function fillLyrics(gig: Gig, only?: number): Promise<{ gig: Gig; found: number; missing: string[] }> {
  let patches = gig.patches;
  let found = 0;
  const missing: string[] = [];
  for (let i = 0; i < patches.length; i++) {
    const e = patches[i];
    if ((only !== undefined && i !== only) || (only === undefined && e.lyrics) || !e.song.trim()) continue;
    const hit = await api.lyrics(e.song, e.artist);
    if (hit.found && hit.lyrics) {
      patches = patches.map((x, j) => (j === i ? { ...x, lyrics: hit.lyrics, artist: x.artist || hit.artist } : x));
      found++;
    } else missing.push(e.song);
  }
  return { gig: { ...gig, patches }, found, missing };
}

export function lyricsMessage(found: number, missing: string[]): string {
  if (found) return `Found lyrics for ${found} song${found === 1 ? "" : "s"}${missing.length ? `. None for ${missing.join(", ")}` : ""}`;
  return missing.length ? `No lyrics found for ${missing.join(", ")}` : "Every song already has lyrics";
}
