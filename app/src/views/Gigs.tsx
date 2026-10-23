// Gigs: setlists of songs, each with a patch, loaded onto a run of slots in order
// so the pedal's own footswitches step through the set.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Gig, GigEntry, PlanStep } from "../api";
import { Icon } from "../components/Icon";
import { fillLyrics, lyricsMessage } from "../lyrics";
import { usePedal } from "../pedal";

const BLANK: Gig = { name: "New gig", start_slot: 100, patches: [] };
// Strat five-way, then Les Paul three-way; anything else can be typed.
const PICKUPS = ["Neck", "Neck + middle", "Middle", "Middle + bridge", "Bridge", "Rhythm", "Both", "Treble"];

export function Gigs({ onStage }: { onStage: () => void }) {
  const { gigs, names, act } = usePedal();
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Gig | null>(null);

  useEffect(() => {
    if (!openId) return;
    api.gig(openId).then(setDraft, () => setDraft(null));
  }, [openId]);

  const create = async (gig: Gig) => {
    const saved = await act(() => api.saveGig(gig));
    if (saved?.id) {
      setOpenId(saved.id);
      setDraft(saved);
    }
  };

  return (
    <section className="gigs" aria-labelledby="gigs-title">
      <div className="gigs-list">
        <h1 id="gigs-title" className="view-title">Gigs</h1>
        <p className="view-sub">Setlists that load onto the pedal in order.</p>
        <ul className="gig-items">
          {gigs.list.map((g) => (
            <li key={g.id}>
              <button className={`gig-item${g.id === openId ? " is-open" : ""}`} onClick={() => setOpenId(g.id)}>
                <span className="gig-item-name">{g.name}</span>
                <span className="gig-item-meta">
                  {g.songs} song{g.songs === 1 ? "" : "s"} · from slot {g.start_slot}
                  {g.id === gigs.active && <span className="badge on-pedal">On the pedal</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <div className="gig-new">
          <button className="button primary" onClick={() => create({ ...BLANK, start_slot: firstEmpty(names) })}>New gig</button>
          <ImportFromSlots onImport={create} />
        </div>
      </div>
      {draft ? (
        <GigEditor
          key={draft.id}
          gig={draft}
          active={draft.id === gigs.active}
          onSaved={setDraft}
          onDeleted={() => { setOpenId(null); setDraft(null); }}
          onStage={onStage}
        />
      ) : (
        <p className="empty gig-empty">
          {gigs.list.length ? "Pick a gig to edit it, or start a new one." : "No gigs yet. Start one, or make one from a run of slots already on the pedal."}
        </p>
      )}
    </section>
  );
}

function ImportFromSlots({ onImport }: { onImport: (g: Gig) => void }) {
  const { act } = usePedal();
  const [open, setOpen] = useState(false);
  const [first, setFirst] = useState(1);
  const [last, setLast] = useState(10);
  if (!open) return <button className="button" onClick={() => setOpen(true)}>From slots on the pedal…</button>;
  return (
    <form
      className="import-slots"
      onSubmit={async (e) => {
        e.preventDefault();
        const gig = await act(() => api.exportGig(first, last, `Slots ${first}-${last}`));
        // Keep the tones but not their slot numbers, so the set can be loaded anywhere.
        if (gig) onImport({ ...gig, start_slot: first, patches: gig.patches.map(({ slot: _slot, ...entry }) => entry) });
        setOpen(false);
      }}
    >
      <label>Slots <input type="number" min={1} max={150} value={first} onChange={(e) => setFirst(Number(e.target.value))} /></label>
      <label>to <input type="number" min={1} max={150} value={last} onChange={(e) => setLast(Number(e.target.value))} /></label>
      <button className="button primary" type="submit">Make gig</button>
      <button className="button" type="button" onClick={() => setOpen(false)}>Cancel</button>
    </form>
  );
}

interface EditorProps {
  gig: Gig;
  active: boolean;
  onSaved: (g: Gig) => void;
  onDeleted: () => void;
  onStage: () => void;
}

function GigEditor({ gig, active, onSaved, onDeleted, onStage }: EditorProps) {
  const { names, live, act, say } = usePedal();
  const [g, setG] = useState<Gig>(gig);
  const [dirty, setDirty] = useState(false);
  const [plan, setPlan] = useState<PlanStep[] | null>(null);
  const [replaceOk, setReplaceOk] = useState(false);

  const update = (next: Gig) => {
    setG(next);
    setDirty(true);
    setPlan(null);
  };
  const setEntry = (i: number, entry: GigEntry) => update({ ...g, patches: g.patches.map((e, j) => (j === i ? entry : e)) });
  const [words, setWords] = useState<number | null>(null);    // the song whose lyrics are open
  const [finding, setFinding] = useState(false);

  // Look up the words for the songs that have none (or just one), on LRCLIB, and keep them.
  const findLyrics = async (only?: number) => {
    setFinding(true);
    const r = await act(() => fillLyrics(g, only));
    setFinding(false);
    if (!r) return;
    if (r.found) {
      setG(r.gig);
      await save(true, r.gig);
    }
    say(lyricsMessage(r.found, r.missing), !r.found && r.missing.length > 0);
  };
  const moveEntry = (i: number, d: number) => {
    const patches = [...g.patches];
    const [e] = patches.splice(i, 1);
    patches.splice(i + d, 0, e);
    update({ ...g, patches });
  };
  const save = async (quiet = false, gig: Gig = g) => {
    const saved = await act(() => api.saveGig(gig), () => (quiet ? undefined : `Saved ${gig.name}`));
    if (saved) {
      setDirty(false);
      onSaved(saved);
    }
    return saved;
  };
  const checkPlan = async () => {
    if (dirty && !(await save(true))) return;
    const r = await act(() => api.planGig(g.id!));
    if (r) {
      setPlan(r.plan);
      setReplaceOk(false);
    }
  };
  const load = async () => {
    const r = await act(() => api.loadGig(g.id!), (r) => `Loaded ${r.written.length} songs. Every slot was backed up first.`);
    if (r) setPlan(null);
  };
  const overwrites = plan?.filter((s) => s.overwrites_real_patch) ?? [];
  const slotOptions = Object.entries(names).filter(([, n]) => n !== "Empty");

  return (
    <div className="gig-editor">
      <div className="gig-head">
        <label className="field grow">
          <span>Gig</span>
          <input className="gig-name" value={g.name} onChange={(e) => update({ ...g, name: e.target.value })} />
        </label>
        <label className="field">
          <span>First slot</span>
          <input type="number" min={1} max={149} value={g.start_slot} onChange={(e) => update({ ...g, start_slot: Number(e.target.value) })} />
        </label>
      </div>

      <ol className="songs">
        {g.patches.length > 0 && (
          <li className="song song-head" aria-hidden="true">
            <span />
            <span>Song</span>
            <span>Patch</span>
            <span>BPM</span>
            <span>Key</span>
            <span>Pickup</span>
            <span>Notes</span>
          </li>
        )}
        {g.patches.map((entry, i) => (
          <li className="song" key={i}>
            <span className="song-number">{i + 1}</span>
            <input
              className="song-title"
              placeholder="Song"
              aria-label={`Song ${i + 1}`}
              value={entry.song}
              onChange={(e) => setEntry(i, { ...entry, song: e.target.value })}
            />
            <select
              aria-label={`Patch for song ${i + 1}`}
              value={entry.tone ? "tone" : String(entry.from_slot ?? "")}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "live" && live) setEntry(i, { ...entry, tone: stripTone(live), from_slot: undefined });
                else if (v !== "tone") setEntry(i, { ...entry, tone: undefined, from_slot: Number(v) });
              }}
            >
              {entry.tone && <option value="tone">Tone: {entry.tone.name}</option>}
              {!entry.tone && entry.from_slot === undefined && <option value="">Pick a patch…</option>}
              {live && <option value="live">The tone playing now ({live.name})</option>}
              {slotOptions.map(([n, name]) => (
                <option key={n} value={n}>Slot {n} · {name}</option>
              ))}
            </select>
            <input
              className="song-small"
              placeholder="BPM"
              aria-label={`Tempo for song ${i + 1}`}
              inputMode="numeric"
              value={entry.tempo ?? ""}
              onChange={(e) => setEntry(i, { ...entry, tempo: e.target.value ? Number(e.target.value) || undefined : undefined })}
            />
            <input
              className="song-small"
              placeholder="Key"
              aria-label={`Key for song ${i + 1}`}
              value={entry.key ?? ""}
              onChange={(e) => setEntry(i, { ...entry, key: e.target.value || undefined })}
            />
            <input
              className="song-pickup"
              placeholder="Pickup"
              aria-label={`Pickup for song ${i + 1}`}
              list="pickups"
              value={entry.pickup ?? ""}
              onChange={(e) => setEntry(i, { ...entry, pickup: e.target.value || undefined })}
            />
            <input
              className="song-notes"
              placeholder="Notes for the stage view"
              aria-label={`Notes for song ${i + 1}`}
              value={entry.notes ?? ""}
              onChange={(e) => setEntry(i, { ...entry, notes: e.target.value || undefined })}
            />
            <span className="song-tools">
              <button
                className={`song-words${entry.lyrics ? " has" : ""}`}
                onClick={() => setWords(words === i ? null : i)}
                aria-expanded={words === i}
                aria-label={`Lyrics for song ${i + 1}`}
                title={entry.lyrics ? "Lyrics" : "No lyrics yet"}
              >
                Aa
              </button>
              <button onClick={() => moveEntry(i, -1)} disabled={i === 0} aria-label={`Move song ${i + 1} up`}><Icon name="up" /></button>
              <button onClick={() => moveEntry(i, 1)} disabled={i === g.patches.length - 1} aria-label={`Move song ${i + 1} down`}><Icon name="down" /></button>
              <button onClick={() => update({ ...g, patches: g.patches.filter((_, j) => j !== i) })} aria-label={`Remove song ${i + 1}`}><Icon name="close" /></button>
            </span>
            {words === i && (
              <div className="song-lyrics">
                <div className="song-lyrics-head">
                  <input
                    placeholder="Artist (helps find the right words)"
                    aria-label={`Artist for song ${i + 1}`}
                    value={entry.artist ?? ""}
                    onChange={(e) => setEntry(i, { ...entry, artist: e.target.value || undefined })}
                  />
                  <button className="button" disabled={finding || !entry.song.trim()} onClick={() => findLyrics(i)}>
                    {finding ? "Looking…" : entry.lyrics ? "Find them again" : "Find lyrics"}
                  </button>
                </div>
                <textarea
                  aria-label={`Lyrics for ${entry.song || `song ${i + 1}`}`}
                  placeholder="Paste or type the words. They scroll under the song on the stage view."
                  rows={10}
                  value={entry.lyrics ?? ""}
                  onChange={(e) => setEntry(i, { ...entry, lyrics: e.target.value || undefined })}
                />
              </div>
            )}
          </li>
        ))}
      </ol>
      <datalist id="pickups">
        {PICKUPS.map((p) => <option key={p} value={p} />)}
      </datalist>
      <div className="songs-actions">
        <button
          className="button"
          onClick={() => update({ ...g, patches: [...g.patches, { song: "", tone: live ? stripTone(live) : undefined }] })}
        >
          Add a song
        </button>
        <button className="button" disabled={finding || g.patches.every((e) => (e.lyrics && e.duration !== undefined) || !e.song.trim())} onClick={() => findLyrics()}>
          {finding ? "Finding lyrics…" : "Find lyrics for every song"}
        </button>
      </div>

      <div className="gig-actions">
        <button className="button" onClick={() => save()} disabled={!dirty}>{dirty ? "Save" : "Saved"}</button>
        <button className="button" onClick={checkPlan} disabled={g.patches.length === 0 || g.patches.some((e) => !e.tone && e.from_slot === undefined)}>
          Check where it goes
        </button>
        {active && <button className="button" onClick={onStage}>Stage view</button>}
        <button
          className="button danger"
          onClick={async () => {
            if (window.confirm(`Delete ${g.name}? The patches on the pedal stay as they are.`)) {
              if (await act(() => api.deleteGig(g.id!), () => `Deleted ${g.name}`)) onDeleted();
            }
          }}
        >
          Delete gig
        </button>
      </div>

      {plan && (
        <div className="plan">
          <h2 className="plan-title">Where it goes</h2>
          <table className="plan-table">
            <thead>
              <tr><th>#</th><th>Song</th><th>Slot</th><th>Replaces</th></tr>
            </thead>
            <tbody>
              {plan.map((s) => (
                <tr key={s.order} className={s.overwrites_real_patch ? "overwrites" : ""}>
                  <td>{s.order}</td>
                  <td>{s.song}</td>
                  <td>{s.slot}</td>
                  <td>{s.replaces === "Empty" ? "empty slot" : s.replaces_own ? `${s.replaces} (this gig's own)` : s.replaces}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {overwrites.length > 0 && (
            <label className="check">
              <input type="checkbox" checked={replaceOk} onChange={(e) => setReplaceOk(e.target.checked)} />
              <span>
                Replace {overwrites.length} patch{overwrites.length === 1 ? "" : "es"} ({overwrites.map((s) => s.replaces).join(", ")}).
                Every slot is backed up first.
              </span>
            </label>
          )}
          <button className="button primary" disabled={overwrites.length > 0 && !replaceOk} onClick={load}>
            Load to pedal
          </button>
        </div>
      )}
    </div>
  );
}

/** The first Empty slot, where a new gig starts unless you pick another. */
function firstEmpty(names: Record<number, string>): number {
  const n = Object.entries(names).find(([slot, name]) => name === "Empty" && Number(slot) < 150);
  return n ? Number(n[0]) : BLANK.start_slot;
}

function stripTone(t: { name: string; volume: number; dsp_percent: number; chain: { effect: string; on: boolean; knobs: Record<string, number> }[] }) {
  return { name: t.name, volume: t.volume, dsp_percent: t.dsp_percent, chain: t.chain.map((f) => ({ effect: f.effect, on: f.on, knobs: f.knobs })) };
}
