// The tone playing now: its chain as a row of stompboxes you can tweak, rearrange and
// add to, live. Tweaks only ever happen on the scratch slot; a stored patch is copied there first.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, effectInfo } from "../api";
import type { ChainEffect, EffectInfo, Tone, TweakChange } from "../api";
import { ABSwitch } from "../components/ABSwitch";
import { EffectBrowser, MAX_POSITIONS } from "../components/EffectBrowser";
import { Enclosure } from "../components/Enclosure";
import { HistoryPanel } from "../components/HistoryPanel";
import { Knob } from "../components/Knob";
import { usePedal } from "../pedal";
import { SaveDialog } from "./SaveDialog";

const MAX_VOLUME = 120;
const NEW_TONE: Tone = { name: "NEW TONE", volume: 100, dsp_percent: 0, chain: [] };

type Panel = { kind: "add" } | { kind: "swap"; index: number } | { kind: "history" } | null;

export function ToneView() {
  const pedal = usePedal();
  const { live, status, onScratch, act, setLive, refreshLive, history } = pedal;
  const infos = useEffectInfos(live);
  const { draft, queue } = useTweaks(setLive, refreshLive, pedal.say);
  const [saving, setSaving] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  const [drag, setDrag] = useState<{ from: number; over: number | null } | null>(null);

  const canUndo = onScratch && history.position > 0;
  const canRedo = onScratch && history.position < history.entries.length - 1;
  useShortcuts({
    undo: () => canUndo && act(() => api.undo()),
    redo: () => canRedo && act(() => api.redo()),
  });

  if (!status || status.connection !== "connected" || !live) return <NoTone />;

  const tone = withDraft(live, draft);
  const positionsOf = (fx: ChainEffect) => infos[fx.effect]?.positions ?? 1;
  const used = tone.chain.reduce((n, fx) => n + positionsOf(fx), 0);
  const slot = status.current_slot!;

  /** Send the whole tone with a new chain; the pedal reloads the scratch slot (about 0.1 s). */
  const setChain = (chain: ChainEffect[], done: string) =>
    act(() => api.audition({ tone: { ...tone, chain: chain.map(plainEffect) } }), (view) => {
      setLive(view);
      return done;
    });
  const move = (from: number, to: number) => {
    if (from === to) return;
    const chain = [...tone.chain];
    const [fx] = chain.splice(from, 1);
    chain.splice(to, 0, fx);
    setChain(chain, `Moved ${fx.effect}`);
  };
  const pick = (effect: string) => {
    const chain = [...tone.chain];
    const added: ChainEffect = { effect, on: true, knobs: {} };
    if (panel?.kind === "swap") {
      const [old] = chain.splice(panel.index, 1, { ...added, on: tone.chain[panel.index].on });
      setChain(chain, `Swapped ${old.effect} for ${effect}`);
    } else {
      setChain([...chain, added], `Added ${effect}`);
    }
    setPanel(null);
  };
  const swapping = panel?.kind === "swap" ? tone.chain[panel.index] : null;
  const freedPositions = swapping ? positionsOf(swapping) : 0;
  const freedDsp = swapping ? infos[swapping.effect]?.dsp_percent ?? 0 : 0;

  return (
    <section className="tone" aria-labelledby="tone-name">
      <div className="tone-head">
        <div className="tone-title">
          <p className="eyebrow">{onScratch ? `Trying out · slot ${slot}` : `Your patch · slot ${slot}`}</p>
          {onScratch ? (
            <NameField key={live.name} name={tone.name} onCommit={(name) => queue("name", { name })} />
          ) : (
            <h1 id="tone-name" className="tone-name">{tone.name}</h1>
          )}
        </div>
        <div className="tone-meters">
          <Meter label="DSP" value={tone.dsp_percent} max={100} text={`${Math.round(tone.dsp_percent)}%`} />
          <Meter label="Positions" value={used} max={MAX_POSITIONS} text={`${used} of ${MAX_POSITIONS}`} />
        </div>
        <div className="tone-volume">
          <Knob
            label="Patch volume"
            value={tone.volume}
            max={MAX_VOLUME}
            text={String(tone.volume)}
            disabled={!onScratch}
            onChange={(v) => queue("volume", { volume: v })}
          />
        </div>
      </div>

      <div className="toolbar" role="toolbar" aria-label="Tone tools">
        <div className="toolbar-group">
          <button className="button" disabled={!canUndo} onClick={() => act(() => api.undo())} title="Ctrl+Z">Undo</button>
          <button className="button" disabled={!canRedo} onClick={() => act(() => api.redo())} title="Ctrl+Shift+Z">Redo</button>
          <button className="button" aria-pressed={panel?.kind === "history"} onClick={() => setPanel(panel?.kind === "history" ? null : { kind: "history" })}>
            History{history.entries.length ? ` (${history.entries.length})` : ""}
          </button>
        </div>
        {onScratch && <ABSwitch tone={tone} />}
        <div className="toolbar-group">
          {onScratch && (
            <button className="button" disabled={used >= MAX_POSITIONS} onClick={() => setPanel({ kind: "add" })}>
              Add an effect
            </button>
          )}
          <button
            className="button"
            onClick={() => act(() => api.audition({ tone: NEW_TONE }), () => "Started a new tone on the scratch slot")}
          >
            New tone
          </button>
        </div>
      </div>

      {!onScratch && (
        <div className="notice">
          <p>
            This is your patch, so it can't be tweaked in place. Tweak a copy on slot {status.scratch_slot} and keep it
            when it sounds right.
          </p>
          <button
            className="button primary"
            onClick={() => act(() => api.audition({ slot }), () => `Copied ${tone.name} to slot ${status.scratch_slot}`)}
          >
            Tweak a copy
          </button>
        </div>
      )}

      <div className="board" role="list" aria-label="Effect chain, in signal order">
        {tone.chain.length === 0 && (
          <p className="board-empty">{onScratch ? "No effects yet. Add one to start." : "No effects in this patch."}</p>
        )}
        {tone.chain.map((fx, i) => (
          <div
            role="listitem"
            className={`board-slot${drag?.over === i && drag.from !== i ? " drop-here" : ""}${drag?.from === i ? " dragging" : ""}`}
            key={`${i}-${fx.effect}`}
            draggable={onScratch}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = "move";
              setDrag({ from: i, over: null });
            }}
            onDragOver={(e) => {
              if (!drag) return;
              e.preventDefault();
              if (drag.over !== i) setDrag({ ...drag, over: i });
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (drag) move(drag.from, i);
              setDrag(null);
            }}
            onDragEnd={() => setDrag(null)}
          >
            <Enclosure
              fx={fx}
              info={infos[fx.effect]}
              editable={onScratch}
              onKnob={(knob, value) => queue(`k:${i + 1}:${knob}`, { change: { effect: i + 1, knob, value } })}
              onToggle={(on) => queue(`on:${i + 1}`, { change: { effect: i + 1, on } })}
              actions={onScratch ? {
                onMoveLeft: i > 0 ? () => move(i, i - 1) : undefined,
                onMoveRight: i < tone.chain.length - 1 ? () => move(i, i + 1) : undefined,
                onSwap: () => setPanel({ kind: "swap", index: i }),
                onRemove: () => setChain(tone.chain.filter((_, j) => j !== i), `Removed ${fx.effect}`),
              } : undefined}
            />
          </div>
        ))}
        {onScratch && used < MAX_POSITIONS && (
          <div role="listitem" className="board-slot">
            <button className="enclosure-ghost" onClick={() => setPanel({ kind: "add" })}>
              <span aria-hidden="true">+</span>
              Add an effect
            </button>
          </div>
        )}
      </div>

      {onScratch && (
        <div className="tone-actions">
          <button className="button primary" onClick={() => setSaving(true)}>Keep it in a slot…</button>
          <span className="tone-hint">
            Drag a knob up or down, or scroll on it. Click a footswitch to turn an effect on or off. Drag a pedal to move it.
          </span>
        </div>
      )}

      {saving && <SaveDialog tone={tone} onClose={() => setSaving(false)} />}
      {(panel?.kind === "add" || panel?.kind === "swap") && (
        <EffectBrowser
          title={swapping ? `Swap ${swapping.effect} for…` : "Add an effect"}
          freePositions={MAX_POSITIONS - used + freedPositions}
          freeDsp={100 - tone.dsp_percent + freedDsp}
          onPick={pick}
          onClose={() => setPanel(null)}
        />
      )}
      {panel?.kind === "history" && <HistoryPanel onClose={() => setPanel(null)} />}
    </section>
  );
}

function NoTone() {
  const { status, linked } = usePedal();
  let text = "Reading the pedal…";
  if (!linked) text = "Start the g3xn daemon to see your pedal here.";
  else if (status?.connection === "disconnected") text = "No pedal yet. Plug the G3Xn in over USB; it connects by itself.";
  else if (status?.connection === "released") text = "The pedal is free for other programs. Take it back from the bar above.";
  return (
    <section className="tone">
      <p className="empty">{text}</p>
    </section>
  );
}

function NameField({ name, onCommit }: { name: string; onCommit: (name: string) => void }) {
  const [value, setValue] = useState(name);
  const commit = () => {
    const next = value.trim();
    if (next && next !== name) onCommit(next);
    else setValue(name);
  };
  return (
    <input
      id="tone-name"
      className="tone-name editable"
      value={value}
      maxLength={10}
      aria-label="Patch name (up to 10 characters)"
      spellCheck={false}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

function Meter({ label, value, max, text }: { label: string; value: number; max: number; text: string }) {
  const full = value / max;
  return (
    <div className={`meter${full > 1 ? " over" : full > 0.9 ? " near" : ""}`}>
      <span className="meter-label">{label}</span>
      <span className="meter-bar" aria-hidden="true">
        <span style={{ width: `${Math.min(full, 1) * 100}%` }} />
      </span>
      <span className="meter-text">{text}</span>
    </div>
  );
}

/** Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y), except while typing in a field. */
function useShortcuts(keys: { undo: () => void; redo: () => void }) {
  const ref = useRef(keys);
  ref.current = keys;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || (e.target as HTMLElement).closest("input, textarea")) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) ref.current.undo();
      else if ((k === "z" && e.shiftKey) || k === "y") ref.current.redo();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Effect details (knob ranges, defaults, display rules) for every effect in the chain. */
function useEffectInfos(tone: Tone | null) {
  const [infos, setInfos] = useState<Record<string, EffectInfo>>({});
  useEffect(() => {
    for (const fx of tone?.chain ?? []) {
      if (infos[fx.effect]) continue;
      effectInfo(fx.effect).then((info) => setInfos((s) => ({ ...s, [fx.effect]: info })), () => {});
    }
  }, [tone, infos]);
  return infos;
}

type Pending = { change?: TweakChange; volume?: number; name?: string };

/**
 * Sends tweaks one request at a time, always with the newest values. While a knob
 * is moving, its value is shown straight away (the draft) until the pedal confirms it.
 */
function useTweaks(setLive: (t: Tone) => void, refreshLive: () => void, say: (t: string, e?: boolean) => void) {
  const [draft, setDraft] = useState<Record<string, number | boolean | string>>({});
  const pending = useRef(new Map<string, Pending>());
  const busy = useRef(false);

  const flush = useCallback(async () => {
    if (busy.current || pending.current.size === 0) return;
    const batch = [...pending.current.values()];
    pending.current.clear();
    busy.current = true;
    try {
      const volume = batch.findLast((p) => p.volume !== undefined)?.volume;
      const name = batch.findLast((p) => p.name !== undefined)?.name;
      setLive(await api.tweak({ changes: batch.flatMap((p) => (p.change ? [p.change] : [])), volume, name }));
    } catch (err) {
      say(err instanceof Error ? err.message : String(err), true);
      pending.current.clear();
      refreshLive();
    } finally {
      busy.current = false;
      if (pending.current.size) flush();
      else setDraft({});
    }
  }, [setLive, refreshLive, say]);

  const queue = useCallback(
    (key: string, p: Pending) => {
      pending.current.set(key, p);
      const shown = p.change?.value ?? p.change?.on ?? p.volume ?? p.name;
      if (shown !== undefined) setDraft((d) => ({ ...d, [key]: shown }));
      flush();
    },
    [flush],
  );
  return { draft, queue };
}

function withDraft(tone: Tone, draft: Record<string, number | boolean | string>): Tone {
  if (Object.keys(draft).length === 0) return tone;
  return {
    ...tone,
    name: typeof draft.name === "string" ? draft.name : tone.name,
    volume: typeof draft.volume === "number" ? draft.volume : tone.volume,
    chain: tone.chain.map((fx, i) => {
      const knobs = { ...fx.knobs };
      for (const k of Object.keys(knobs)) {
        const v = draft[`k:${i + 1}:${k}`];
        if (typeof v === "number") knobs[k] = v;
      }
      const on = draft[`on:${i + 1}`];
      return { ...fx, knobs, on: typeof on === "boolean" ? on : fx.on };
    }),
  };
}

/** Tone JSON for one effect, without the screen text. */
export function plainEffect(fx: ChainEffect): ChainEffect {
  return { effect: fx.effect, on: fx.on, knobs: fx.knobs };
}
