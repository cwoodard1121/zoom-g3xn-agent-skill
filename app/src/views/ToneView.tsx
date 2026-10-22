// The tone playing now: its chain as a row of stompboxes you can tweak live.
// Tweaks only ever happen on the scratch slot; a stored patch is copied there first.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, effectInfo } from "../api";
import type { EffectInfo, Tone, TweakChange } from "../api";
import { Enclosure } from "../components/Enclosure";
import { Knob } from "../components/Knob";
import { usePedal } from "../pedal";
import { SaveDialog } from "./SaveDialog";

const MAX_POSITIONS = 7;
const MAX_VOLUME = 120;

export function ToneView() {
  const pedal = usePedal();
  const { live, status, onScratch, act, setLive, refreshLive } = pedal;
  const infos = useEffectInfos(live);
  const { draft, queue } = useTweaks(setLive, refreshLive, pedal.say);
  const [saving, setSaving] = useState(false);

  if (!status || status.connection !== "connected" || !live) return <NoTone />;

  const tone = withDraft(live, draft);
  const positions = tone.chain.reduce((n, fx) => n + (infos[fx.effect]?.positions ?? 1), 0);
  const slot = status.current_slot!;

  return (
    <section className="tone" aria-labelledby="tone-name">
      <div className="tone-head">
        <div className="tone-title">
          <p className="eyebrow">
            {onScratch ? `Trying out · slot ${slot}` : `Your patch · slot ${slot}`}
          </p>
          {onScratch ? (
            <NameField key={live.name} name={tone.name} onCommit={(name) => queue("name", { name })} />
          ) : (
            <h1 id="tone-name" className="tone-name">{tone.name}</h1>
          )}
        </div>
        <div className="tone-meters">
          <Meter label="DSP" value={tone.dsp_percent} max={100} text={`${Math.round(tone.dsp_percent)}%`} />
          <Meter label="Positions" value={positions} max={MAX_POSITIONS} text={`${positions} of ${MAX_POSITIONS}`} />
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
        {tone.chain.length === 0 && <p className="board-empty">No effects in this patch.</p>}
        {tone.chain.map((fx, i) => (
          <div role="listitem" className="board-slot" key={`${i}-${fx.effect}`}>
            <Enclosure
              fx={fx}
              info={infos[fx.effect]}
              editable={onScratch}
              onKnob={(knob, value) => queue(`k:${i + 1}:${knob}`, { change: { effect: i + 1, knob, value } })}
              onToggle={(on) => queue(`on:${i + 1}`, { change: { effect: i + 1, on } })}
            />
          </div>
        ))}
      </div>

      {onScratch && (
        <div className="tone-actions">
          <button className="button primary" onClick={() => setSaving(true)}>Keep it in a slot…</button>
          <span className="tone-hint">Drag a knob up or down, or scroll on it. Click a footswitch to turn an effect on or off.</span>
        </div>
      )}
      {saving && <SaveDialog tone={tone} onClose={() => setSaving(false)} />}
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
