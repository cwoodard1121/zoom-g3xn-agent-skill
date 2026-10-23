// Every slot on the pedal, in its banks of three (the three footswitches).
import { useEffect, useMemo, useState } from "react";
import { api, effectInfo } from "../api";
import type { Tone } from "../api";
import { Icon } from "../components/Icon";
import { usePedal } from "../pedal";

const BANK_SIZE = 3;

export function Library({ onTry }: { onTry: () => void }) {
  const { names, status, act, setCopyOf } = usePedal();
  const [filter, setFilter] = useState("");
  const [picked, setPicked] = useState<number | null>(null);
  const slots = Object.keys(names).map(Number).sort((a, b) => a - b);
  const empty = slots.filter((n) => names[n] === "Empty").length;

  const banks = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const out: number[][] = [];
    for (let i = 0; i < slots.length; i += BANK_SIZE) {
      const bank = slots.slice(i, i + BANK_SIZE);
      if (!q || bank.some((n) => names[n].toLowerCase().includes(q) || String(n) === q)) out.push(bank);
    }
    return out;
  }, [slots, names, filter]);

  if (slots.length === 0) {
    return (
      <section className="library">
        <p className="empty">{status?.doing ?? "Your patches show up here once the pedal is connected."}</p>
      </section>
    );
  }

  return (
    <section className="library" aria-labelledby="library-title">
      <div className="library-head">
        <div>
          <h1 id="library-title" className="view-title">Patches</h1>
          <p className="view-sub">{slots.length - empty} patches · {empty} empty slots</p>
        </div>
        <input
          className="search"
          type="search"
          placeholder="Find a patch or slot"
          aria-label="Find a patch or slot"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div className="library-body">
        <ol className="banks">
          {banks.map((bank) => (
            <li className="bank" key={bank[0]}>
              {bank.map((n) => (
                <button
                  key={n}
                  className={[
                    "slot",
                    names[n] === "Empty" ? "is-empty" : "",
                    n === status?.current_slot ? "is-current" : "",
                    n === picked ? "is-picked" : "",
                  ].join(" ")}
                  onClick={() => setPicked(n)}
                  aria-current={n === status?.current_slot ? "true" : undefined}
                >
                  <span className="slot-number">{n}</span>
                  <span className="slot-name">{n === status?.scratch_slot && names[n] === "Empty" ? "scratch" : names[n]}</span>
                  {n === status?.current_slot && <span className="led on" aria-label="playing now" />}
                </button>
              ))}
            </li>
          ))}
          {banks.length === 0 && <li className="empty">Nothing matches “{filter}”.</li>}
        </ol>
        {picked !== null && (
          <PatchDetail
            key={picked}
            slot={picked}
            name={names[picked]}
            isCurrent={picked === status?.current_slot}
            onSelect={() => act(() => api.select(picked), (r) => `Switched the pedal to ${r.name}`)}
            onTry={async () => {
              const ok = await act(() => api.audition({ slot: picked }), () => `Copied ${names[picked]} to slot ${status?.scratch_slot} to tweak`);
              if (ok) {
                setCopyOf({ slot: picked, name: names[picked] });
                onTry();
              }
            }}
            onClose={() => setPicked(null)}
          />
        )}
      </div>
    </section>
  );
}

interface DetailProps {
  slot: number;
  name: string;
  isCurrent: boolean;
  onSelect: () => void;
  onTry: () => void;
  onClose: () => void;
}

function PatchDetail({ slot, name, isCurrent, onSelect, onTry, onClose }: DetailProps) {
  const [tone, setTone] = useState<Tone | null>(null);
  const [groups, setGroups] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    if (name === "Empty") return;
    api.patch(slot).then(setTone, (e) => setError(e.message));
  }, [slot, name]);
  useEffect(() => {
    for (const fx of tone?.chain ?? []) {
      effectInfo(fx.effect).then((i) => setGroups((g) => ({ ...g, [fx.effect]: i.group })), () => {});
    }
  }, [tone]);

  return (
    <aside className="detail" aria-labelledby="detail-title">
      <button className="detail-close" onClick={onClose} aria-label="Close"><Icon name="close" size={20} /></button>
      <div className="detail-head">
        <span className="detail-slot vfd">{String(slot).padStart(3, "0")}</span>
        <h2 id="detail-title" className="detail-name">{name}</h2>
      </div>
      {name === "Empty" ? (
        <p className="detail-note">An empty slot. Keep a tone here from the Tone view.</p>
      ) : error ? (
        <p className="detail-note error">{error}</p>
      ) : !tone ? (
        <p className="detail-note">Reading the patch…</p>
      ) : (
        <>
          <ol className="chips" aria-label="Effects, in signal order">
            {tone.chain.map((fx, i) => (
              <li key={i} className={`chip${fx.on ? "" : " bypassed"}`} data-group={groups[fx.effect] ?? "UNKNOWN"}>
                {fx.effect}
              </li>
            ))}
          </ol>
          <p className="detail-note">Volume {tone.volume} · DSP {Math.round(tone.dsp_percent)}%</p>
          <div className="detail-actions">
            <button className="button primary" onClick={onTry}>Tweak a copy</button>
            <button className="button" onClick={onSelect} disabled={isCurrent}>
              {isCurrent ? "Playing now" : "Switch the pedal to it"}
            </button>
          </div>
        </>
      )}
    </aside>
  );
}
