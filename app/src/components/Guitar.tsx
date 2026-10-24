// Which guitar a tone is for. The pedal can't keep it, so the daemon does, by slot; these name it
// (with the guitars used before as suggestions) and show it.
import { useEffect, useState } from "react";
import { usePedal } from "../pedal";

/** The guitars named so far, for any guitar box on the page (rendered once, in the shell). */
export function GuitarNames() {
  const { guitars } = usePedal();
  return (
    <datalist id="guitars">
      {guitars.names.map((g) => <option key={g} value={g} />)}
    </datalist>
  );
}

/** A box naming the guitar for `slot`'s tone; it's kept when you leave the box or press Enter. */
export function GuitarField({ slot, className = "" }: { slot: number; className?: string }) {
  const { guitars, setGuitar } = usePedal();
  const kept = guitars.slots[slot] ?? "";
  const [text, setText] = useState(kept);
  useEffect(() => setText(kept), [kept, slot]);
  const commit = () => {
    if (text.trim() !== kept) setGuitar(slot, text.trim());
  };
  return (
    <label className={`guitar-field ${className}`}>
      <span>Guitar</span>
      <input
        list="guitars"
        placeholder="Which guitar?"
        maxLength={40}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") setText(kept);
        }}
      />
    </label>
  );
}

export function GuitarTag({ name }: { name?: string | null }) {
  return name ? <span className="guitar-tag" title={`For the ${name}`}>{name}</span> : null;
}
