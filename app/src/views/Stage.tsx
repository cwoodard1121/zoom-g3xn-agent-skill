// Stage: the gig that's on the pedal, readable from where you stand.
// It follows the pedal: stomp to the next patch and the next song comes up.
// Arrow keys, space and Page Up/Down (what Bluetooth page-turner pedals send) step through the set.
// Moving on is the one big moment: the next song's title flies out of the setlist into place, the
// last one slides away, and the patch's effects light up one after another (View Transitions,
// where the browser has them and motion is welcome; otherwise it just changes).
// Between songs in different tunings a RETUNE banner says which strings go where, and lights each
// one as the tuner holds it in tune.
// Tapping in (songclock.ts) starts the song clock: the words follow it, and so do the song's cues,
// which switch its effects at set points. The effects are buttons too, and while recording cues,
// each press becomes one at that point in the song.
// Where the song is can be said, too (push to talk while this view is open): "chorus", "second
// verse", "you're two bars behind", a line of the words (songmap.ts). Anything else goes to Claude.
// [ and ] move the words a bar back or on.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { api } from "../api";
import type { Gig, GigEntry } from "../api";
import type React from "react";
import { ClockBar, Lyrics } from "../components/Lyrics";
import { GhostBand } from "../components/GhostBand";
import { Recap } from "../components/Recap";
import type { Played } from "../components/Recap";
import { Scope } from "../components/Scope";
import { SongMap, StageNote } from "../components/SongMap";
import { TalkButton, WakeButton } from "../components/Talk";
import { addCue, effectIndex, parseCues, parseNotes } from "../cues";
import type { Cue } from "../cues";
import { fillLyrics, length, lines, lyricsMessage } from "../lyrics";
import { usePedal } from "../pedal";
import { mmss, useSongClock, useSongTime } from "../songclock";
import type { SongClock } from "../songclock";
import { partsOf, understand } from "../songmap";
import { sameTuning, tuningOf } from "../tuning";
import type { Tuning } from "../tuning";

const SEGMENTS = Array.from({ length: 15 }, (_, i) => i - 7);
// The recording, to play along with. A search, since a gig only knows titles.
const PLAYERS = {
  youtube: { label: "YouTube", url: (q: string) => `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}` },
  spotify: { label: "Spotify", url: (q: string) => `https://open.spotify.com/search/${encodeURIComponent(q)}` },
};
type Player = keyof typeof PLAYERS;

export function Stage() {
  const { gigs, status, names, tuner, live, act, say, stageHeard, talk, guitars } = usePedal();
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
  const playing = slots.findIndex((s) => s.slot === current);

  // The song on screen trails the pedal by the length of the transition into it.
  const [index, setShown] = useState(playing);
  const [incoming, setIncoming] = useState<number | null>(null);
  useEffect(() => {
    if (playing === index || incoming !== null) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!document.startViewTransition || still || index < 0 || playing < 0) setShown(playing);
    else setIncoming(playing);              // first mark the setlist row the title flies out of
  }, [playing, index, incoming]);
  useLayoutEffect(() => {
    if (incoming === null) return;
    const to = incoming;
    const move = document.startViewTransition(() => flushSync(() => {
      setShown(to);
      setIncoming(null);
    }));
    move.finished.catch(() => {});
  }, [incoming]);

  const song = index >= 0 ? slots[index] : null;
  useEffect(() => {
    // Just the setlist's own box: scrollIntoView would move the whole page as well.
    const box = document.querySelector<HTMLElement>(".stage-side .setlist");
    const row = box?.querySelector<HTMLElement>('[aria-current="true"]')?.closest("li");
    if (box && row) box.scrollTo({ top: row.offsetTop - box.clientHeight / 2 + row.clientHeight / 2, behavior: "smooth" });
  }, [index]);
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
  const clock = useSongClock(info);
  const goTo = async (i: number) => {
    const s = slots[i];
    if (!s) return;
    await putBackCues();
    act(() => api.select(s.slot));
  };

  // The show so far, for the recap: each song as it comes up, and the band's tempo each time it's tapped.
  const [played, setPlayed] = useState<Played[]>([]);
  const [recap, setRecap] = useState(false);
  useEffect(() => {
    if (!song) return;
    setPlayed((p) => (p[p.length - 1]?.song === song.song ? p : [...p, { song: song.song, album: info?.tempo, tempos: [] }]));
  }, [song?.song]);
  useEffect(() => {
    if (!clock.bpm || !song) return;
    setPlayed((p) => p.map((x, i) => (i === p.length - 1 && x.song === song.song ? { ...x, tempos: [...x.tempos, clock.bpm!] } : x)));
  }, [clock.bpm]);

  // The song's parts, and what was said about where it is.
  const allLines = useMemo(() => (info ? lines(info) : []), [info]);
  const total = info ? length(info, allLines) : 0;
  const parts = useMemo(() => (info ? partsOf(info, allLines, total) : []), [info, allLines, total]);
  const notes = useMemo(() => parseNotes(info?.cues), [info?.cues]);
  const [heard, setHeard] = useState<{ text: string; did: string | null; n: number } | null>(null);
  const bars = (by: number) => {
    const n = Math.round((Math.abs(by) / (4 * clock.beat)) * 2) / 2;
    return `${by > 0 ? "on" : "back"} ${n === 0.5 ? "half a bar" : `${n} bar${n === 1 ? "" : "s"}`}`;
  };
  const hearRef = useRef((_text: string, _since: number | null, _exact: boolean) => {});
  hearRef.current = (text, since, exact) => {
    const h = info ? understand(text, { now: clock.time(), beat: clock.beat, parts, lines: allLines, total }) : null;
    let did: string | null = null;
    if (!h) {
      // Only one open stage passes it on, or Claude would hear it from the phone too.
      if (["127.0.0.1", "localhost"].includes(location.hostname)) act(() => api.chatSend(text));
    } else if (h.do === "jump") {
      // "We're at the chorus" was true when they started saying it: the song has moved on since,
      // by however long hearing it and working it out took. Without the words' own time, they're
      // taken to start talking 0.4 s after the switch went down.
      const late = h.live && since !== null ? Math.max(0, (performance.now() - since) / 1000 - (exact ? 0 : 0.4)) * (clock.rate || 1) : 0;
      clock.jump(h.at + late);
      did = h.said;
    } else if (h.do === "nudge") {
      clock.nudge(h.by);
      did = bars(h.by);
    } else if (h.do === "pause") {
      if (clock.running) clock.toggle();
      did = "Paused";
    } else if (h.do === "go") {
      if (!clock.running) clock.toggle();
      did = "Carrying on";
    } else {
      clock.reset();
      did = "From the top";
    }
    setHeard((x) => ({ text, did, n: (x?.n ?? 0) + 1 }));
  };
  const seenHeard = useRef(stageHeard?.n);
  useEffect(() => {
    if (!stageHeard || stageHeard.n === seenHeard.current) return;
    seenHeard.current = stageHeard.n;
    hearRef.current(stageHeard.text, stageHeard.since, stageHeard.exact);
  }, [stageHeard]);
  useEffect(() => {
    if (!heard) return;
    const id = window.setTimeout(() => setHeard(null), 3200);
    return () => window.clearTimeout(id);
  }, [heard]);
  // Tell the daemon this view is open, so talking comes here first (it forgets after 20 s).
  useEffect(() => {
    const open = () => api.talkSet({ stage: true }).catch(() => {});
    open();
    const id = window.setInterval(open, 8000);
    return () => {
      window.clearInterval(id);
      api.talkSet({ stage: false }).catch(() => {});
    };
  }, []);

  const stepRef = useRef((_d: number) => {});
  stepRef.current = (d: number) => goTo(index < 0 ? 0 : Math.min(slots.length - 1, Math.max(0, index + d)));
  const nudgeRef = useRef((_bars: number) => {});
  nudgeRef.current = (n: number) => {
    clock.nudge(n * 4 * clock.beat);
    setHeard((x) => ({ text: n > 0 ? "]" : "[", did: bars(n * 4 * clock.beat), n: (x?.n ?? 0) + 1 }));
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // [ and ] work from a slider too (the ghost band's speed); typing in a box is left alone.
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target as HTMLElement).closest("input:not([type=range]), textarea, select")) return;
      if (e.key === "[" || e.key === "]") {
        e.preventDefault();
        nudgeRef.current(e.key === "]" ? 1 : -1);
        return;
      }
      if ((e.target as HTMLElement).closest("input")) return;
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

  // Retuning: the guitar is in the tuning of the song shown before this one (on first arriving,
  // the song before it in the set; before the first song, standard).
  const entryAt = (i: number): GigEntry | undefined =>
    gig && slots[i] ? gig.patches.find((p) => p.song === slots[i].song) ?? gig.patches[i] : undefined;
  const [retune, setRetune] = useState<{ from: Tuning; to: Tuning } | null>(null);
  const [tuned, setTuned] = useState<number[]>([]);       // strings the tuner has held in tune
  const shownBefore = useRef<number | null>(null);
  const tunerByBanner = useRef(false);                      // the banner turned the tuner on: it turns it off
  const tunerOff = () => {
    if (tunerByBanner.current && tunerOnRef.current) act(() => api.tuner(false));
    tunerByBanner.current = false;
  };
  useEffect(() => {
    if (index < 0) return;
    const before = shownBefore.current ?? index - 1;
    shownBefore.current = index;
    tunerOff();                                             // a new song: play, don't tune
    const from = tuningOf(entryAt(before)?.tuning), to = tuningOf(entryAt(index)?.tuning);
    setTuned([]);
    setRetune(sameTuning(from, to) ? null : { from, to });
  }, [index]);
  const changing = retune?.to.strings?.map((n, s) => n !== retune.from.strings?.[s]) ?? [];
  const allTuned = !!retune?.to.strings && changing.every((c, s) => !c || tuned.includes(s));
  const finish = () => {
    setRetune(null);
    tunerOff();
  };
  const finishRef = useRef(finish);
  finishRef.current = finish;

  // A string counts once the tuner has held its note in tune for a moment (not just swept past
  // it). Strings sharing a note (the two E's) light lowest first, one per hold.
  const holding = retune && tuner?.note && tuner.meter === 0 ? tuner.note : null;
  useEffect(() => {
    const to = retune?.to.strings;
    if (!holding || !to) return;
    const id = window.setTimeout(() => setTuned((t) => {
      const s = to.findIndex((n, i) => n === holding && changing[i] && !t.includes(i));
      return s < 0 ? t : [...t, s];
    }), 400);
    return () => window.clearTimeout(id);
  }, [holding, retune]);
  useEffect(() => {
    if (!allTuned) return;
    const id = window.setTimeout(() => finishRef.current(), 1500);
    return () => window.clearTimeout(id);
  }, [allTuned]);

  // Cues. Each effect a cue names is on or off as the last cue passed says, and before any has
  // passed, as the gig loaded it: so jumping back undoes cues, and a song starts the way it was
  // loaded even though autosave kept last time's changes in the slot. Only a cue coming due
  // switches anything; an effect stomped by hand stays stomped.
  const cues = useMemo(() => parseCues(info?.cues), [info?.cues]);
  const cueRun = useRef<{ slot: number; arrived: boolean[]; sent: Map<number, boolean> } | null>(null);
  useEffect(() => {
    cueRun.current = null;                                  // a new song: it starts from scratch
  }, [song?.slot]);
  const cueNow = useRef({ cues, loadedChain: song ? slots[index]?.chain : undefined, live, song, clock });
  cueNow.current = { cues, loadedChain: song ? slots[index]?.chain : undefined, live, song, clock };
  const cueStarts = (i: number) => {
    const { loadedChain, live } = cueNow.current;
    const loaded = loadedChain?.[i];
    return loaded && loaded.effect === live?.chain[i]?.effect ? loaded.on : cueRun.current!.arrived[i];
  };
  useEffect(() => {
    const id = window.setInterval(() => {
      const { cues, live, song, clock } = cueNow.current;
      if (!song || !live || live.slot !== song.slot || !cues.length) return;
      if (cueRun.current?.slot !== song.slot) {
        cueRun.current = { slot: song.slot, arrived: live.chain.map((c) => c.on), sent: new Map(live.chain.map((c, i) => [i, c.on])) };
      }
      const run = cueRun.current;
      const t = clock.time();
      const want = new Map<number, boolean>();
      for (const cue of cues) {
        const i = effectIndex(live.chain, cue.effect);
        if (i < 0) continue;
        if (!want.has(i)) want.set(i, cueStarts(i));
        if (cue.at <= t) want.set(i, cue.on);
      }
      for (const [i, on] of want) {
        if (run.sent.get(i) === on) continue;
        run.sent.set(i, on);
        act(() => api.stomp(i + 1, on, run.slot));          // never the next song's patch
      }
    }, 250);
    return () => window.clearInterval(id);
  }, []);
  // Leaving the song from here: put its effects back first, so the slot is as loaded for next time
  // (moving on from the pedal can't wait for this; the song puts itself right when it comes up).
  const putBackCues = async () => {
    const run = cueRun.current;
    const { live } = cueNow.current;
    if (!run || live?.slot !== run.slot) return;
    for (const [i, on] of run.sent) {
      if (on !== cueStarts(i)) await act(() => api.stomp(i + 1, cueStarts(i), run.slot));
    }
    cueRun.current = null;
  };

  // Recording cues: pressing an effect on the stage adds a cue for it at that point in the song.
  const [recording, setRecording] = useState(false);
  const pressEffect = (i: number) => {
    const fx = live?.chain[i];
    if (!fx || !gig || !info) return;
    if (recording && clock.time() > 0) {
      const next = { ...gig, patches: gig.patches.map((p) => (p === info ? { ...p, cues: addCue(p.cues, clock.time(), fx.effect, !fx.on) } : p)) };
      setGig(next);
      act(() => api.saveGig(next));
    }
    act(() => api.stomp(i + 1, !fx.on));
  };

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
  const tunerReadout = (
    <div className="stage-tuner" aria-live="polite">
      <span className={`stage-tuner-note${meter === 0 ? " in-tune" : ""}`}>{tuner?.note ?? "–"}</span>
      <span className="tuner-meter compact" aria-hidden="true">
        {SEGMENTS.map((s) => (
          <span key={s} className={`seg${s === 0 ? " center" : ""}${meter !== null && s === meter ? " lit" : ""}`} />
        ))}
      </span>
    </div>
  );
  const tuning = tuningOf(info?.tuning);
  // The guitar for each song: the gig's, else the one named for its patch's slot.
  const guitarAt = (i: number) => (slots[i] ? entryAt(i)?.guitar || guitars.slots[slots[i].slot] : undefined);
  const guitar = guitarAt(index);
  const nextGuitar = guitarAt(index + 1);
  const switching = !!(next && nextGuitar && guitar && nextGuitar !== guitar);
  const switched = index > 0 && !!guitar && !!guitarAt(index - 1) && guitarAt(index - 1) !== guitar;

  return (
    <section className="stage" ref={stageRef} aria-labelledby="stage-song">
      <div className="stage-now">
        <p className="stage-where" style={{ viewTransitionName: "stage-where" }}>
          {gig.name} · {song ? `song ${index + 1} of ${slots.length}` : `${slots.length} songs`}
        </p>
        {song ? (
          <>
            <h1 id="stage-song" className="stage-song" style={{ viewTransitionName: incoming !== null ? "stage-leaving" : "stage-song" }}>
              {song.song}
            </h1>
            {retune && (
              <div className={`retune${allTuned ? " done" : ""}`} role="alert" key={`retune-${song.slot}`}>
                <p className="retune-head">
                  <span className="retune-word">{allTuned ? "In tune" : "Retune"}</span>
                  <span className="retune-to">
                    {retune.to.name}
                    {retune.to.about && <small>{retune.to.about}</small>}
                  </span>
                </p>
                {retune.to.strings && (
                  <ol className="retune-strings" aria-label="Strings, low to high">
                    {retune.to.strings.map((n, s) => (
                      <li key={s} className={`${changing[s] ? "change" : "stays"}${tuned.includes(s) ? " tuned" : ""}`}>
                        <span className="retune-string">{6 - s}</span>
                        <b>{n}</b>
                        <span className="retune-from">
                          {!changing[s] ? "stays" : retune.from.strings ? `from ${retune.from.strings[s]}` : ""}
                          {tuned.includes(s) && <span className="visually-hidden">, in tune</span>}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
                <div className="retune-actions">
                  {tunerOn ? (
                    tunerReadout
                  ) : (
                    <button
                      className="button"
                      onClick={async () => {
                        if (await act(() => api.tuner(true))) tunerByBanner.current = true;
                      }}
                    >
                      Tuner
                    </button>
                  )}
                  <button className="button primary" onClick={finish}>Done</button>
                </div>
              </div>
            )}
            <div className="stage-patch" style={{ viewTransitionName: "stage-patch" }}>
              <span className="stage-lcd" aria-label={`Slot ${song.slot}, ${song.patch}`}>
                <span className="stage-lcd-slot">{String(song.slot).padStart(3, "0")}</span>
                <span>{song.patch}</span>
              </span>
              {guitar && (
                <span className={`stage-fact stage-guitar${switched ? " switched" : ""}`} key={`guitar-${song.slot}`}>
                  {switched ? "Now on the" : "Guitar"} <b>{guitar}</b>
                </span>
              )}
              {info?.tempo && <span className="stage-fact"><b>{info.tempo}</b> BPM</span>}
              {info?.key && <span className="stage-fact">Key <b>{info.key}</b></span>}
              {info?.pickup && <span className="stage-fact">Pickup <b>{info.pickup}</b></span>}
              {tuning.name !== "Standard" && <span className="stage-fact">Tuning <b>{tuning.name}</b></span>}
            </div>
            {live && live.slot === song.slot && live.chain.length > 0 && (
              <div className="stage-effects" style={{ viewTransitionName: "stage-stomps" }}>
                <ul className="stage-stomps" aria-label="Effects in this patch" key={song.slot}>
                  {live.chain.map((c, i) => (
                    <li key={i} className={c.on ? "on" : ""} style={{ "--i": i } as React.CSSProperties}>
                      <button
                        className="stage-stomp"
                        aria-pressed={c.on}
                        title={recording ? `Turn ${c.effect} ${c.on ? "off" : "on"} and make it a cue here` : `Turn ${c.effect} ${c.on ? "off" : "on"}`}
                        onClick={() => pressEffect(i)}
                      >
                        <span className="stage-stomp-led" aria-hidden="true" />
                        {c.effect}
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="stage-cues">
                  <button
                    className={`button cue-record${recording ? " on" : ""}`}
                    aria-pressed={recording}
                    onClick={() => setRecording(!recording)}
                    title="While this is on, pressing an effect adds a cue for it at that point in the song"
                  >
                    {recording ? "Recording cues" : "Record cues"}
                  </button>
                  <NextCue cues={cues} clock={clock} recording={recording} />
                </div>
              </div>
            )}
            {info?.notes && <p className="stage-notes" style={{ viewTransitionName: "stage-notes" }}>{info.notes}</p>}
            {info?.chords && (
              <dl className="stage-chords" aria-label="Chords" style={{ viewTransitionName: "stage-chords" }}>
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

        {tunerOn && !retune && tunerReadout}

        <div className="stage-next" style={{ viewTransitionName: "stage-next" }}>
          {next ? (
            <p>
              <span className="stage-next-label">Next</span> {next.song} <span className="stage-next-slot">slot {next.slot}</span>
              {switching && <span className="stage-next-guitar">switch to the <b>{nextGuitar}</b></span>}
            </p>
          ) : song ? (
            <p><span className="stage-next-label">Next</span> That's the last song.</p>
          ) : null}
        </div>

        <div className="stage-controls" style={{ viewTransitionName: "stage-controls" }}>
          <button className="stage-step" onClick={() => stepRef.current(-1)} disabled={index <= 0}>Previous</button>
          <button className="stage-step primary" onClick={() => stepRef.current(1)} disabled={index >= slots.length - 1}>
            {song ? "Next" : "Start"}
          </button>
          <span className="stage-spacer" />
          {talk.installed && <TalkButton />}
          {talk.installed && <WakeButton />}
          <button className="button" aria-pressed={tunerOn} onClick={() => act(() => api.tuner(!tunerOn))}>
            Tuner
          </button>
        </div>

        {song && info && (
          <div className="stage-lyrics-wrap" style={{ viewTransitionName: "stage-words" }}>
            <ClockBar entry={info} clock={clock} />
            {parts.length > 1 && <SongMap parts={parts} total={total} clock={clock} cues={cues} notes={notes} />}
            <StageNote notes={notes} clock={clock} />
            {heard && (
              <p className={`stage-heard${heard.did ? "" : " claude"}`} role="status" key={heard.n}>
                <span className="stage-heard-said">{heard.text.length > 2 ? `\u201c${heard.text}\u201d` : heard.text}</span>
                <span className="stage-heard-did">{heard.did ?? "to Claude"}</span>
              </p>
            )}
            {info.lyrics ? (
              <Lyrics entry={info} clock={clock} />
            ) : (
              <p className="stage-no-lyrics">
                No lyrics for this song yet.{" "}
                <button className="button" disabled={finding} onClick={findLyrics}>
                  {finding ? "Finding lyrics…" : "Find lyrics for the set"}
                </button>
              </p>
            )}
          </div>
        )}
      </div>

      {recap && <Recap gig={gig} played={played} onClose={() => setRecap(false)} />}
      {/* Beside the song: the set, then what's for rehearsing, then the desk's own tools. */}
      <aside className="stage-side">
        <ol className="setlist" aria-label="Setlist">
          {slots.map((s, i) => (
            <li key={s.slot}>
              <button
                className={`setlist-song${index >= 0 && i < index ? " played" : ""}`}
                aria-current={i === index ? "true" : undefined}
                style={i === index ? { viewTransitionName: "setlist-now" } : undefined}
                onClick={() => goTo(i)}
              >
                <span className="setlist-n">{i + 1}</span>
                <span className="setlist-title" style={i === incoming ? { viewTransitionName: "stage-song" } : undefined}>{s.song}</span>
                {i > 0 && guitarAt(i) && guitarAt(i) !== guitarAt(i - 1) && <span className="setlist-guitar">{guitarAt(i)}</span>}
                <span className="setlist-slot">{s.slot}</span>
              </button>
            </li>
          ))}
        </ol>
        {song && info && (
          <section className="side-panel" aria-label="Rehearse">
            <h2 className="side-title">Rehearse</h2>
            <GhostBand entry={info} clock={clock} />
            <span className="stage-rehearse" role="group" aria-label="Open the recording">
              {(Object.keys(PLAYERS) as Player[]).map((p) => (
                <button key={p} className="button" title={`Open this song on ${PLAYERS[p].label}`} onClick={() => play(index, p)}>
                  {PLAYERS[p].label}
                </button>
              ))}
            </span>
          </section>
        )}
        <section className="side-panel" aria-label="Tools">
          <h2 className="side-title">Desk</h2>
          <div className="side-tools">
            <button className="button" onClick={() => setRecap(true)} title="Tempo against the record, and patches changed on the pedal (with the button that puts them back)">
              Recap
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
          <Scope onLevel={(db) => setPlayed((p) => p.map((x, i) => (i === p.length - 1 ? { ...x, levels: [...(x.levels ?? []).slice(-400), db] } : x)))} />
        </section>
    </aside>
    </section>
  );
}

function NextCue({ cues, clock, recording }: { cues: Cue[]; clock: SongClock; recording: boolean }) {
  const now = useSongTime(clock);
  if (recording) {
    return <p className="cue-next">{clock.time() > 0 ? `Press an effect to cue it at ${mmss(now)}` : "Tap in first, then press effects as the song goes"}</p>;
  }
  if (!cues.length) return null;
  const next = cues.find((c) => c.at > now);
  if (!next) return <p className="cue-next">No more cues</p>;
  const wait = (next.at - now) / (clock.rate || 1);
  return (
    <p className="cue-next">
      Next cue <b>{next.effect} {next.on ? "on" : "off"}</b> at {mmss(next.at)}
      {clock.running && <> · in <b className="cue-count">{mmss(wait)}</b></>}
    </p>
  );
}
