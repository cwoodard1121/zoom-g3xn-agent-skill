// Stage: the gig that's on the pedal, readable from where you stand.
// It follows the pedal: stomp to the next patch and the next song comes up.
// Arrow keys, space and Page Up/Down (what Bluetooth page-turner pedals send) step through the set.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Gig, GigEntry } from "../api";
import { Lyrics } from "../components/Lyrics";
import { fillLyrics, lyricsMessage } from "../lyrics";
import { usePedal } from "../pedal";

const SEGMENTS = Array.from({ length: 15 }, (_, i) => i - 7);
// The recording, to play along with. A search, since a gig only knows titles.
const PLAYERS = {
  youtube: { label: "YouTube", url: (q: string) => `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}` },
  spotify: { label: "Spotify", url: (q: string) => `https://open.spotify.com/search/${encodeURIComponent(q)}` },
};
type Player = keyof typeof PLAYERS;

export function Stage() {
  const { gigs, status, names, tuner, live, act, say } = usePedal();
  const [gig, setGig] = useState<Gig | null>(null);
  const [finding, setFinding] = useState(false);
  const findLyrics = async () => {
    setFinding(true);
    const r = await act(() => fillLyrics(gig!));
    if (r?.changed) {
      const saved = await act(() => api.saveGig(r.gig));
      if (saved) setGig(saved);
    }
    setFinding(false);
    if (r) say(lyricsMessage(r.found, r.missing), !r.found && r.missing.length > 0);
  };
  const stageRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!gigs.active) return setGig(null);
    api.gig(gigs.active).then(setGig, () => setGig(null));
  }, [gigs.active, gigs.list]);

  const slots = gig?.loaded?.slots ?? [];
  const current = status?.current_slot ?? null;
  const index = slots.findIndex((s) => s.slot === current);
  const song = index >= 0 ? slots[index] : null;
  const next = slots[index + 1];
  // Notes, tempo and key can change after loading; match them by song title.
  const info: GigEntry | undefined = song
    ? gig!.patches.find((p) => p.song === song.song) ?? gig!.patches[index]
    : undefined;

  const search = (s: { song: string }, i: number) => {
    const artist = (gig!.patches.find((p) => p.song === s.song) ?? gig!.patches[i])?.artist;
    return [s.song, artist].filter(Boolean).join(" ");
  };
  const play = (i: number, p: Player) => {
    const s = slots[i];
    if (s) window.open(PLAYERS[p].url(search(s, i)), "g3xn-rehearse");
  };
  const goTo = (i: number) => {
    const s = slots[i];
    if (!s) return;
    act(() => api.select(s.slot));
  };

  const stepRef = useRef((_d: number) => {});
  stepRef.current = (d: number) => goTo(index < 0 ? 0 : Math.min(slots.length - 1, Math.max(0, index + d)));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement).closest("input, textarea, select")) return;
      const d = { ArrowRight: 1, ArrowDown: 1, PageDown: 1, " ": 1, ArrowLeft: -1, ArrowUp: -1, PageUp: -1 }[e.key];
      if (d) {
        e.preventDefault();
        stepRef.current(d);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The tuner turns off again when you leave the stage view.
  const tunerOn = !!status?.tuner;
  const tunerOnRef = useRef(tunerOn);
  tunerOnRef.current = tunerOn;
  useEffect(() => () => {
    if (tunerOnRef.current) api.tuner(false).catch(() => {});
  }, []);

  if (!gig || !slots.length) {
    return (
      <section className="stage stage-empty">
        <h1 className="view-title">Stage</h1>
        <p className="empty">
          Load a gig to the pedal and it shows up here, one song at a time. <a href="#gigs">Go to Gigs</a>
        </p>
      </section>
    );
  }

  const meter = tuner?.note ? tuner.meter : null;

  return (
    <section className="stage" ref={stageRef} aria-labelledby="stage-song">
      <div className="stage-now">
        <p className="stage-where">
          {gig.name} · {song ? `song ${index + 1} of ${slots.length}` : `${slots.length} songs`}
        </p>
        {song ? (
          <>
            <h1 id="stage-song" className="stage-song">{song.song}</h1>
            <div className="stage-patch">
              <span className="stage-lcd" aria-label={`Slot ${song.slot}, ${song.patch}`}>
                <span className="stage-lcd-slot">{String(song.slot).padStart(3, "0")}</span>
                <span>{song.patch}</span>
              </span>
              {info?.tempo && <span className="stage-fact"><b>{info.tempo}</b> BPM</span>}
              {info?.key && <span className="stage-fact">Key <b>{info.key}</b></span>}
              {info?.pickup && <span className="stage-fact">Pickup <b>{info.pickup}</b></span>}
            </div>
            {live && live.slot === song.slot && live.chain.length > 0 && (
              <ul className="stage-stomps" aria-label="Effects in this patch">
                {live.chain.map((c, i) => (
                  <li key={i} className={c.on ? "on" : ""}>
                    <span className="stage-stomp-led" aria-hidden="true" />
                    {c.effect}
                    <span className="visually-hidden">{c.on ? " on" : " off"}</span>
                  </li>
                ))}
              </ul>
            )}
            {info?.notes && <p className="stage-notes">{info.notes}</p>}
            {info?.chords && (
              <dl className="stage-chords" aria-label="Chords">
                {info.chords.split("\n").filter((l) => l.trim()).map((l, i) => {
                  const [part, chords] = l.includes(":") ? [l.slice(0, l.indexOf(":")), l.slice(l.indexOf(":") + 1)] : ["", l];
                  return (
                    <div key={i}>
                      <dt>{part.trim()}</dt>
                      <dd>{chords.trim()}</dd>
                    </div>
                  );
                })}
              </dl>
            )}
          </>
        ) : (
          <>
            <h1 id="stage-song" className="stage-song off-set">Not in the set</h1>
            <p className="stage-notes">
              The pedal is on slot {current}{current && names[current] ? `, ${names[current]}` : ""}.
              Press Next to start at {slots[0].song}.
            </p>
          </>
        )}

        {tunerOn && (
          <div className="stage-tuner" aria-live="polite">
            <span className={`stage-tuner-note${meter === 0 ? " in-tune" : ""}`}>{tuner?.note ?? "–"}</span>
            <span className="tuner-meter compact" aria-hidden="true">
              {SEGMENTS.map((s) => (
                <span key={s} className={`seg${s === 0 ? " center" : ""}${meter !== null && s === meter ? " lit" : ""}`} />
              ))}
            </span>
          </div>
        )}

        <div className="stage-next">
          {next ? (
            <p><span className="stage-next-label">Next</span> {next.song} <span className="stage-next-slot">slot {next.slot}</span></p>
          ) : song ? (
            <p><span className="stage-next-label">Next</span> That's the last song.</p>
          ) : null}
        </div>

        <div className="stage-controls">
          <button className="stage-step" onClick={() => stepRef.current(-1)} disabled={index <= 0}>Previous</button>
          <button className="stage-step primary" onClick={() => stepRef.current(1)} disabled={index >= slots.length - 1}>
            {song ? "Next" : "Start"}
          </button>
          <span className="stage-spacer" />
          <span className="stage-rehearse" role="group" aria-label="Play the recording">
            {(Object.keys(PLAYERS) as Player[]).map((p) => (
              <button
                key={p}
                className="button"
                disabled={index < 0}
                title={`Open this song on ${PLAYERS[p].label}`}
                onClick={() => play(index, p)}
              >
                {PLAYERS[p].label}
              </button>
            ))}
          </span>
          <button className="button" aria-pressed={tunerOn} onClick={() => act(() => api.tuner(!tunerOn))}>
            Tuner
          </button>
          <button
            className="button"
            onClick={() => {
              if (document.fullscreenElement) document.exitFullscreen();
              else stageRef.current?.requestFullscreen().catch(() => {});
            }}
          >
            Full screen
          </button>
        </div>

        {info?.lyrics ? (
          <Lyrics entry={info} />
        ) : song ? (
          <p className="stage-no-lyrics">
            No lyrics for this song yet.{" "}
            <button className="button" disabled={finding} onClick={findLyrics}>
              {finding ? "Finding lyrics…" : "Find lyrics for the set"}
            </button>
          </p>
        ) : null}
      </div>

      <ol className="setlist" aria-label="Setlist">
        {slots.map((s, i) => (
          <li key={s.slot}>
            <button
              className={`setlist-song${index >= 0 && i < index ? " played" : ""}`}
              aria-current={i === index ? "true" : undefined}
              onClick={() => goTo(i)}
            >
              <span className="setlist-n">{i + 1}</span>
              <span className="setlist-title">{s.song}</span>
              <span className="setlist-slot">{s.slot}</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
