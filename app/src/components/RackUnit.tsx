// One effect in the chain, drawn as a unit in a rack. The faceplate reads out the first
// knobs on its display; open it and its drawer slides out with every knob. An effect
// that takes two of the pedal's seven positions is a 2U unit.
import type { ChainEffect, EffectInfo } from "../api";
import { shownText } from "../api";
import { Icon } from "./Icon";
import { Knob } from "./Knob";

export interface ChainActions {
  onMoveUp?: () => void; // undefined = already first
  onMoveDown?: () => void;
  onSwap: () => void;
  onRemove: () => void;
}

interface Props {
  fx: ChainEffect;
  info?: EffectInfo;
  open: boolean;
  onOpen: () => void;
  onKnob: (knob: string, value: number) => void;
  onToggle: (on: boolean) => void;
  actions: ChainActions;
}

const READOUT_KNOBS = 4;

export function RackUnit({ fx, info, open, onOpen, onKnob, onToggle, actions }: Props) {
  const knobs = Object.keys(fx.knobs).map((name) => {
    const param = info?.params.find((p) => p.name === name);
    const raw = fx.knobs[name];
    const text = param?.shown_as ? shownText(param, raw) : fx.shown?.[name] ?? String(raw);
    return { name, param, raw, text };
  });
  const drawerId = `drawer-${fx.effect.replace(/\W+/g, "-")}`;

  return (
    <article
      className={`unit${info?.positions === 2 ? " double" : ""}${fx.on ? "" : " bypassed"}${open ? " open" : ""}`}
      data-group={info?.group ?? "UNKNOWN"}
      aria-label={`${fx.effect}, ${fx.on ? "on" : "off"}`}
    >
      <div className="unit-face">
        <span className={`led${fx.on ? " on" : ""}`} aria-hidden="true" />
        <button className="unit-name" aria-expanded={open} aria-controls={drawerId} onClick={onOpen} title={open ? "Close its knobs" : "Show its knobs"}>
          {fx.effect}
          <span className="unit-group">{info?.group.toLowerCase() ?? "effect"}</span>
        </button>
        <div className="unit-readout vfd" onClick={onOpen} aria-hidden="true">
          {knobs.slice(0, READOUT_KNOBS).map((k) => (
            <span key={k.name}>
              <span className="readout-label">{k.name}</span> {k.text}
            </span>
          ))}
        </div>
        <div className="unit-tools">
          <button onClick={actions.onMoveUp} disabled={!actions.onMoveUp} aria-label={`Move ${fx.effect} earlier`} title="Earlier in the chain">
            <Icon name="up" />
          </button>
          <button onClick={actions.onMoveDown} disabled={!actions.onMoveDown} aria-label={`Move ${fx.effect} later`} title="Later in the chain">
            <Icon name="down" />
          </button>
          <button onClick={actions.onSwap} aria-label={`Swap ${fx.effect} for another effect`} title="Swap for another effect">
            <Icon name="swap" />
          </button>
          <button onClick={actions.onRemove} aria-label={`Remove ${fx.effect}`} title="Remove">
            <Icon name="close" />
          </button>
        </div>
        <button
          className="power"
          aria-pressed={fx.on}
          onClick={() => onToggle(!fx.on)}
          title={fx.on ? `Turn ${fx.effect} off` : `Turn ${fx.effect} on`}
        >
          <span className="power-lever" aria-hidden="true" />
          <span className="power-text">{fx.on ? "On" : "Off"}</span>
          <span className="visually-hidden">{fx.on ? `Turn ${fx.effect} off` : `Turn ${fx.effect} on`}</span>
        </button>
      </div>
      {open && (
        <div className="unit-drawer" id={drawerId}>
          {knobs.map((k) => (
            <Knob
              key={k.name}
              label={k.name}
              value={k.raw}
              max={k.param?.max ?? 100}
              text={k.text}
              defaultValue={k.param?.default}
              hint={k.param?.explanation}
              disabled={!k.param}
              onChange={(v) => onKnob(k.name, v)}
            />
          ))}
        </div>
      )}
    </article>
  );
}
