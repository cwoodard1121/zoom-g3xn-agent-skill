// One effect in the chain, drawn as a stompbox. Its colour comes from the effect's
// group, and an effect that takes two of the pedal's seven positions is twice as wide.
import type { ChainEffect, EffectInfo } from "../api";
import { shownText } from "../api";
import { Knob } from "./Knob";

interface Props {
  fx: ChainEffect;
  info?: EffectInfo;
  editable: boolean;
  onKnob: (knob: string, value: number) => void;
  onToggle: (on: boolean) => void;
}

export function Enclosure({ fx, info, editable, onKnob, onToggle }: Props) {
  const names = Object.keys(fx.knobs);
  const screens: string[][] = [];
  for (let i = 0; i < names.length; i += 4) screens.push(names.slice(i, i + 4));

  return (
    <article
      className={`enclosure${info?.positions === 2 ? " wide" : ""}${fx.on ? "" : " bypassed"}`}
      data-group={info?.group ?? "UNKNOWN"}
      aria-label={`${fx.effect}, ${fx.on ? "on" : "off"}`}
    >
      <header className="enclosure-head">
        <span className={`led${fx.on ? " on" : ""}`} aria-hidden="true" />
        <h3 className="enclosure-name">{fx.effect}</h3>
        <span className="enclosure-group">{info?.group.toLowerCase()}</span>
      </header>
      <div className="enclosure-screens">
        {screens.map((screen, i) => (
          <div className="enclosure-knobs" key={i}>
            {screen.map((name) => {
              const param = info?.params.find((p) => p.name === name);
              const raw = fx.knobs[name];
              const text = param?.shown_as ? shownText(param, raw) : fx.shown?.[name] ?? String(raw);
              return (
                <Knob
                  key={name}
                  label={name}
                  value={raw}
                  max={param?.max ?? 100}
                  text={text}
                  defaultValue={param?.default}
                  hint={param?.explanation}
                  disabled={!editable || !param}
                  onChange={(v) => onKnob(name, v)}
                />
              );
            })}
          </div>
        ))}
      </div>
      <button
        className="footswitch"
        disabled={!editable}
        aria-pressed={fx.on}
        onClick={() => onToggle(!fx.on)}
        title={fx.on ? `Turn ${fx.effect} off` : `Turn ${fx.effect} on`}
      >
        <span className="visually-hidden">{fx.on ? `Turn ${fx.effect} off` : `Turn ${fx.effect} on`}</span>
      </button>
    </article>
  );
}
