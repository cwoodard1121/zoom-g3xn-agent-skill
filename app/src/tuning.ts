// Guitar tunings: what a song's "tuning" says, as six strings (low to high) in the tuner's note
// names, so the stage view can say what to retune between songs and watch the tuner do it.
// A tuning is a name from the list ("Eb", "Drop D"…) or six notes ("D A D G B E", "DADGAD").

export const TUNINGS: { name: string; about: string; strings: string[] }[] = [
  { name: "Standard", about: "Standard", strings: ["E", "A", "D", "G", "B", "E"] },
  { name: "Eb", about: "Half step down", strings: ["D#", "G#", "C#", "F#", "A#", "D#"] },
  { name: "Drop D", about: "Low E down to D", strings: ["D", "A", "D", "G", "B", "E"] },
  { name: "D", about: "Whole step down", strings: ["D", "G", "C", "F", "A", "D"] },
  { name: "Drop C#", about: "Half step down, low string to C#", strings: ["C#", "G#", "C#", "F#", "A#", "D#"] },
  { name: "Drop C", about: "Whole step down, low string to C", strings: ["C", "G", "C", "F", "A", "D"] },
  { name: "Open G", about: "Open G", strings: ["D", "G", "D", "G", "B", "D"] },
  { name: "Open D", about: "Open D", strings: ["D", "A", "D", "F#", "A", "D"] },
  { name: "Open E", about: "Open E", strings: ["E", "B", "E", "G#", "B", "E"] },
  { name: "DADGAD", about: "DADGAD", strings: ["D", "A", "D", "G", "A", "D"] },
];

// Other ways of writing the same tunings.
const ALSO: Record<string, string> = {
  "": "Standard", e: "Standard", estandard: "Standard",
  "d#": "Eb", "e♭": "Eb", ebstandard: "Eb", "d#standard": "Eb", halfstepdown: "Eb", halfstep: "Eb", eflat: "Eb",
  dstandard: "D", wholestepdown: "D", wholestep: "D",
  dropdb: "Drop C#",
};

// The tuner names notes with sharps.
const FLATS: Record<string, string> = { Cb: "B", Db: "C#", Eb: "D#", Fb: "E", Gb: "F#", Ab: "G#", Bb: "A#" };
const note = (n: string) => {
  const plain = n.replace("♯", "#").replace("♭", "b");
  return FLATS[plain] ?? plain;
};

const squash = (s: string) => s.toLowerCase().replace(/[\s()_-]+/g, "").replace("flat", "b").replace("sharp", "#");

export interface Tuning {
  name: string; // "Eb", "Drop D", "D A D G B E"…
  about: string | null; // "Half step down"
  strings: string[] | null; // low to high; null when it isn't one we know
}

/** What a song's tuning field means (empty is standard). */
export function tuningOf(text?: string): Tuning {
  const t = (text ?? "").trim();
  const key = squash(t);
  const known = TUNINGS.find((x) => squash(x.name) === key || squash(x.about) === key) ??
    TUNINGS.find((x) => x.name === ALSO[key]);
  if (known) return { name: known.name, about: known.about === known.name ? null : known.about, strings: known.strings };
  const notes = /^[A-G#b♯♭\s,/-]+$/.test(t) ? t.match(/[A-G][#b♯♭]?/g) : null;
  if (notes?.length === 6) {
    const strings = notes.map(note);
    const same = TUNINGS.find((x) => x.strings.join() === strings.join());
    return same ? tuningOf(same.name) : { name: notes.join(" "), about: null, strings };
  }
  return { name: t, about: null, strings: null };
}

/** Whether going from one tuning to the other means retuning. */
export function sameTuning(a: Tuning, b: Tuning) {
  return a.strings && b.strings ? a.strings.join() === b.strings.join() : squash(a.name) === squash(b.name);
}
