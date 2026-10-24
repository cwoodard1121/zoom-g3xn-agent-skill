// The ghost band: the song's recording to rehearse along with when the band isn't there. While it
// plays, the recording is the clock: the words, the song map and the cues all follow it, a jump
// ("chorus", a click on a part) moves it, and its speed is the clock's (tap slower or drag Speed to
// practise it slower; the pitch stays put).
import { useEffect, useRef, useState } from "react";
import { api, trackKey } from "../api";
import type { GigEntry, TrackInfo } from "../api";
import { usePedal } from "../pedal";
import type { SongClock } from "../songclock";

export function GhostBand({ entry, clock }: { entry: GigEntry; clock: SongClock }) {
  const { act, say } = usePedal();
  const key = trackKey(entry);
  const [track, setTrack] = useState<TrackInfo | null | undefined>(undefined);
  const [on, setOn] = useState(false);
  const [volume, setVolume] = useState(() => readNumber("g3xn.bandVolume", 0.8));
  const [uploading, setUploading] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setOn(false);
    setTrack(undefined);
    if (!key) return setTrack(null);
    let gone = false;
    api.track(key).then((t) => !gone && setTrack(t), () => !gone && setTrack(null));
    return () => {
      gone = true;
    };
  }, [key]);

  // The clock moved (a jump, a pause, a tap, Top): the recording goes with it.
  useEffect(() => {
    const a = audio.current;
    if (!a || !on) return;
    const t = clock.time();
    if (Math.abs(a.currentTime - t) > 0.3) a.currentTime = t;
    a.playbackRate = clock.rate || 1;
    if (clock.running && a.paused) a.play().catch(() => {});
    if (!clock.running && !a.paused) a.pause();
  }, [on, clock.moved, clock.running, clock.rate]);

  // ...and the clock keeps to the recording, which is what you hear.
  useEffect(() => {
    const a = audio.current;
    if (!a || !on) return;
    const id = window.setInterval(() => {
      if (!a.paused && Math.abs(a.currentTime - clock.time()) > 0.08) clock.follow(a.currentTime, a.playbackRate, true);
    }, 400);
    return () => window.clearInterval(id);
  }, [on, clock]);

  useEffect(() => {
    if (audio.current) audio.current.volume = volume;
    try {
      localStorage.setItem("g3xn.bandVolume", String(volume));
    } catch {
      /* private window */
    }
  }, [volume, track]);

  const start = () => {
    const a = audio.current;
    if (!a) return;
    if (on) {
      a.pause();
      setOn(false);
      if (clock.running) clock.toggle();
      return;
    }
    // From where the words are (the top, or wherever they were left), at the clock's speed.
    a.currentTime = clock.time();
    a.playbackRate = clock.rate || 1;
    a.play().then(
      () => {
        setOn(true);
        clock.follow(a.currentTime, a.playbackRate, true);
      },
      () => say("The browser wouldn't play the recording", true),
    );
  };

  const upload = async (f: File) => {
    if (!key) return;
    setUploading(true);
    const t = await act(() => api.putTrack(key, f), (t) => `Kept ${t.name} as ${entry.song}'s recording`);
    setUploading(false);
    if (t) setTrack(t);
  };

  if (!key || track === undefined) return null;
  const speed = Math.round((clock.rate || 1) * 100);
  return (
    <div className={`ghost${on ? " on" : ""}`}>
      <span className="ghost-label">Ghost band</span>
      {track ? (
        <>
          <button className="button ghost-play" aria-pressed={on} onClick={start} title="Play along with the recording; the words follow it">
            <span className="ghost-dot" aria-hidden="true" />
            {on ? "Stop the band" : "Play the band"}
          </button>
          <label className="ghost-field" title="How fast the recording plays (the pitch stays the same)">
            <span>Speed</span>
            <input
              type="range" min={50} max={115} step={5} value={speed}
              onChange={(e) => clock.follow(audio.current && on ? audio.current.currentTime : clock.time(), Number(e.target.value) / 100, clock.running)}
            />
            <b>{speed}%</b>
          </label>
          <label className="ghost-field">
            <span>Volume</span>
            <input type="range" min={0} max={1} step={0.05} value={volume} onChange={(e) => setVolume(Number(e.target.value))} />
          </label>
          <span className="ghost-file" title={track.name}>{track.name}</span>
          <audio ref={audio} src={api.trackUrl(key, track.added)} preload="auto" onEnded={() => setOn(false)} />
        </>
      ) : (
        <span className="ghost-file">No recording of this song yet.</span>
      )}
      <button className="button" disabled={uploading} onClick={() => file.current?.click()}>
        {uploading ? "Uploading…" : track ? "Replace" : "Add the recording"}
      </button>
      <input
        ref={file} type="file" accept="audio/*,.mp3,.m4a,.ogg,.wav,.webm,.flac" hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) upload(f);
        }}
      />
    </div>
  );
}

function readNumber(name: string, fallback: number) {
  try {
    const v = Number(localStorage.getItem(name));
    return localStorage.getItem(name) !== null && Number.isFinite(v) ? v : fallback;
  } catch {
    return fallback;
  }
}
