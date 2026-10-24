// Keep the tone being tried: store it in a slot. A slot that holds a patch is only
// replaced after ticking the box that names it.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Tone } from "../api";
import { usePedal } from "../pedal";
import type { CopyOf } from "../pedal";

/** over: the stored patch this tone is a copy of, when the user asked to save over it. */
export function SaveDialog({ tone, over, onClose }: { tone: Tone; over?: CopyOf; onClose: () => void }) {
  const { names, status, act, setCopyOf, guitars, setGuitar } = usePedal();
  const scratch = status?.scratch_slot ?? 150;
  const firstEmpty = Object.entries(names).find(([n, name]) => name === "Empty" && Number(n) !== scratch)?.[0];
  const [slot, setSlot] = useState(over?.slot ?? (firstEmpty ? Number(firstEmpty) : 1));
  const [name, setName] = useState(tone.name);
  const [replace, setReplace] = useState(!!over);
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  const holds = names[slot];
  const taken = holds !== undefined && holds !== "Empty";
  const valid = slot >= 1 && slot <= 150 && slot !== scratch && name.trim().length > 0;

  const save = async () => {
    const done = await act(
      () => api.save(slot, name.trim(), taken && replace),
      (r) => `Kept ${r.saved} in slot ${r.slot}${r.kept ? ". The old patch is in a file, just in case" : ""}`,
    );
    if (done) {
      const scratchGuitar = scratch ? guitars.slots[scratch] : undefined;
      if (scratchGuitar && guitars.slots[done.slot] !== scratchGuitar) setGuitar(done.slot, scratchGuitar);
      setCopyOf(null);
      onClose();
    }
  };

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} aria-labelledby="save-title">
      <form method="dialog" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <h2 id="save-title">{over ? `Save over ${over.name}` : "Keep this tone"}</h2>
        <label className="field">
          <span>Name</span>
          <input value={name} maxLength={10} onChange={(e) => setName(e.target.value)} spellCheck={false} />
        </label>
        <label className="field">
          <span>Slot</span>
          <input
            type="number"
            min={1}
            max={150}
            value={slot}
            onChange={(e) => { setSlot(Number(e.target.value)); setReplace(false); }}
          />
        </label>
        <p className="field-note">
          {slot === scratch
            ? `Slot ${scratch} is where tones are tried out. Pick another slot.`
            : taken
              ? `Slot ${slot} holds ${holds}.`
              : `Slot ${slot} is empty.`}
        </p>
        {taken && slot !== scratch && (
          <label className="check">
            <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
            <span>Replace {holds}. A copy of it is kept in a file, just in case.</span>
          </label>
        )}
        <div className="dialog-actions">
          <button type="button" className="button" onClick={onClose}>Cancel</button>
          <button type="submit" className="button primary" disabled={!valid || (taken && !replace)}>
            Keep in slot {slot}
          </button>
        </div>
      </form>
    </dialog>
  );
}
