// Every effect the pedal has, by group. Effects that won't fit (chain positions or
// DSP) are shown but can't be picked, with the reason.
import { useEffect, useMemo, useState } from "react";
import { effectList } from "../api";
import type { EffectSummary } from "../api";
import { Drawer } from "./Drawer";

const GROUP_ORDER = ["DYNAMICS", "FILTER", "DRIVE", "AMP", "CABINET", "MODULATION", "SFX", "DELAY", "REVERB", "PEDAL"];
interface Props {
  title: string;
  /** The pedal's chain: `max` positions (a big effect takes 2), or `max` effects whatever their size. */
  chain: { rule: "positions" | "effects"; max: number };
  freePositions: number; // positions (or effect places) left, plus what the effect being swapped out frees
  freeDsp: number; // DSP % left (likewise)
  onPick: (effect: string) => void;
  onClose: () => void;
}

export function EffectBrowser({ title, chain, freePositions, freeDsp, onPick, onClose }: Props) {
  const byEffect = chain.rule === "effects";
  const [effects, setEffects] = useState<EffectSummary[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    effectList().then(setEffects, (e) => setError(e.message));
  }, []);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const hits = effects.filter(
      (e) => GROUP_ORDER.includes(e.group) &&
        (!q || e.name.toLowerCase().includes(q) || e.description.toLowerCase().includes(q) || e.group.toLowerCase() === q),
    );
    return GROUP_ORDER.map((g) => [g, hits.filter((e) => e.group === g)] as const).filter(([, list]) => list.length);
  }, [effects, query]);

  const whyNot = (e: EffectSummary) => {
    if (byEffect) {
      if (freePositions < 1) return `The pedal holds ${chain.max} effects`;
    } else if (e.positions > freePositions) {
      return e.positions === 2 ? "Takes 2 positions; not enough free" : "No chain positions free";
    }
    if (e.dsp_percent > freeDsp + 0.05) return `Needs ${Math.round(e.dsp_percent)}% DSP; ${Math.max(0, Math.round(freeDsp))}% free`;
    return "";
  };

  return (
    <Drawer title={title} onClose={onClose}>
      <input
        className="search drawer-search"
        type="search"
        placeholder="Search: fuzz, Marshall, spring…"
        aria-label="Search effects"
        value={query}
        autoFocus
        onChange={(e) => setQuery(e.target.value)}
      />
      <p className="drawer-note">
        {freePositions} of {chain.max} {byEffect ? "effects" : "positions"} and {Math.max(0, Math.round(freeDsp))}% DSP free
      </p>
      {error && <p className="drawer-note error">{error}</p>}
      {groups.map(([group, list]) => (
        <section key={group} className="fx-group">
          <h3 className="fx-group-title" data-group={group}>{group.toLowerCase()}</h3>
          <ul className="fx-list">
            {list.map((e) => {
              const reason = whyNot(e);
              return (
                <li key={e.name}>
                  <button className="fx-item" disabled={!!reason} onClick={() => onPick(e.name)}>
                    <span className="fx-name">{e.name}</span>
                    <span className="fx-meta">
                      {e.positions === 2 ? (byEffect ? "2 screens · " : "2 positions · ") : ""}
                      {Math.round(e.dsp_percent)}% DSP
                    </span>
                    <span className="fx-desc">{reason || e.description}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      {effects.length > 0 && groups.length === 0 && <p className="drawer-note">No effect matches “{query}”.</p>}
    </Drawer>
  );
}
