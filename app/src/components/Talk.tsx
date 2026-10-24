// Push to talk. Hold the talk footswitch (or the Talk button), say it, let go: the words go
// to Claude and the sheet shows what was heard and what Claude changed.
// The laptop's microphone is recorded by the daemon; a phone records itself and sends the audio.
//
// Or hands free: "Hey Claude" (the Hey Claude button). This computer's mic listens in the daemon,
// and a phone with the app open over https listens too, sending what it hears; whichever hears it,
// it's done once. On by default; the button turns it off (remembered on each device).
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { usePedal } from "../pedal";
import { changesOnly, describe } from "./ClaudeStrip";
import { Icon } from "./Icon";

const PHONE_MIC_KEY = "g3xn.phoneMic";
const WAKE_KEY = "g3xn.wake";
const onThisComputer = ["127.0.0.1", "localhost"].includes(location.hostname);
/** A phone that can lend its mic (phones only allow it on https pages). */
const phoneMicHere = !onThisComputer && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;
/** The phone's own hold to talk is recording: its hands-free listening waits. */
const holding = { now: false };

export function TalkButton() {
  const { talk, act, say } = usePedal();
  const held = useRef(false);
  const [local, setLocal] = useState(false);
  const rec = useRef<{ recorder: MediaRecorder; at: number } | null>(null);
  const press = (down: boolean) => {
    if (held.current === down) return;
    held.current = down;
    if (phoneMicHere) return pressHere(down);
    act(() => api.talkSet({ pressed: down }));
  };
  // On a phone that lends its mic: record right here, and send it when it's let go.
  const pressHere = (down: boolean) => {
    holding.now = down;
    setLocal(down);
    if (!down) {
      rec.current?.recorder.stop();
      rec.current = null;
      return;
    }
    const at = performance.now();
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      if (!held.current) return stream.getTracks().forEach((t) => t.stop());
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        api.talkAudio(new Blob(chunks, { type: recorder.mimeType }), { ago: (performance.now() - at) / 1000 }).catch((err) => say(err.message, true));
      };
      recorder.start();
      rec.current = { recorder, at };
    }, () => say("This phone wouldn't lend its microphone.", true));
  };
  const live = local || talk.state === "listening";
  return (
    <button
      type="button"
      className={`button talk-button${live ? " live" : ""}`}
      aria-pressed={live}
      title={phoneMicHere ? "Hold to talk to Claude, into this phone" : "Hold to talk to Claude"}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        press(true);
      }}
      onPointerUp={() => press(false)}
      onPointerCancel={() => press(false)}
      onKeyDown={(e) => {
        if ((e.key === " " || e.key === "Enter") && !e.repeat) {
          e.preventDefault();
          press(true);
        }
      }}
      onKeyUp={(e) => (e.key === " " || e.key === "Enter") && press(false)}
    >
      <span className="talk-dot" aria-hidden="true" />
      Hold to talk
    </button>
  );
}

/** Hands free on (the default) or off, on this device. */
function useWakePref(): [boolean, (on: boolean) => void] {
  const read = () => {
    try {
      return localStorage.getItem(WAKE_KEY) !== "0";
    } catch {
      return true;
    }
  };
  const [on, setOn] = useState(read);
  useEffect(() => {
    const changed = () => setOn(read());
    window.addEventListener("g3xn-wake", changed);
    return () => window.removeEventListener("g3xn-wake", changed);
  }, []);
  const set = (next: boolean) => {
    try {
      localStorage.setItem(WAKE_KEY, next ? "1" : "0");
    } catch {
      // storage blocked: until the page closes
    }
    setOn(next);
    window.dispatchEvent(new Event("g3xn-wake"));
  };
  return [on, set];
}

/** "Hey Claude": lit while listening for it (here: this computer's mic; on a phone: the phone's). */
export function WakeButton() {
  const { talk, act } = usePedal();
  const [pref, setPref] = useWakePref();
  const lit = phoneMicHere ? pref : !!talk.wake;
  const toggle = () => {
    setPref(!lit);
    if (!phoneMicHere) act(() => api.talkSet({ wake: !lit }));
  };
  return (
    <button
      type="button"
      className={`button wake-button${lit ? " on" : ""}`}
      aria-pressed={lit}
      onClick={toggle}
      title={
        lit
          ? `Listening on ${phoneMicHere ? "this phone" : "this computer"} for "Hey Claude, …" ("Hey Claude, we're at the chorus"). Click to stop.`
          : `Listen hands free on ${phoneMicHere ? "this phone" : "this computer"}: say "Hey Claude, …"`
      }
    >
      <span className="wake-led" aria-hidden="true" />
      Hey Claude
    </button>
  );
}

/** Keeps hands-free listening on: this computer's (in the daemon) and, on a phone, the phone's. */
function useWake() {
  const { talk, linked, act } = usePedal();
  const [pref] = useWakePref();
  const asked = useRef(false);
  useEffect(() => {
    if (!linked) asked.current = false;
    // Once per link, so a computer with no mic isn't asked again and again.
    if (phoneMicHere || !linked || !talk.installed || !pref || talk.wake || asked.current) return;
    asked.current = true;
    act(() => api.talkSet({ wake: true }));
  }, [linked, talk.installed, talk.wake, pref, act]);
  usePhoneWake(phoneMicHere && pref && linked && talk.installed);
}

/** A phone listening hands free: loud stretches go to the daemon, which keeps "Hey Claude…". */
function usePhoneWake(on: boolean) {
  const { say } = usePedal();
  useEffect(() => {
    if (!on) return;
    let stopped = false;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    const wakeUp = () => ctx?.state === "suspended" && ctx.resume();
    navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true } }).then(
      (s) => {
        if (stopped) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        ctx = new AudioContext();
        const rate = ctx.sampleRate;
        const source = ctx.createMediaStreamSource(s);
        const node = ctx.createScriptProcessor(2048, 1, 1);
        const block = 2048 / rate;
        let floor = -60;
        const levels: number[] = []; // the last 5 s: the room's usual level is low in them
        const room = Math.ceil(5 / block);
        let run: Float32Array[] = [];
        let pre: Float32Array[] = [];
        let quiet = 0;
        let busy = false;
        let waiting: { audio: Blob; seconds: number; ended: number } | null = null;
        const send = (audio: Blob, seconds: number, ended: number) => {
          busy = true;
          api
            .talkAudio(audio, { wake: true, ago: seconds + (performance.now() - ended) / 1000 })
            .catch(() => {})
            .finally(() => {
              busy = false;
              const next = waiting;
              waiting = null;
              if (next && !stopped) send(next.audio, next.seconds, next.ended);
            });
        };
        node.onaudioprocess = (e) => {
          if (holding.now) {
            run = [];
            pre = [];
            return;
          }
          const x = new Float32Array(e.inputBuffer.getChannelData(0));
          let sum = 0;
          for (let i = 0; i < x.length; i++) sum += x[i] * x[i];
          const level = 10 * Math.log10(sum / x.length + 1e-12);
          if (levels.length) floor = [...levels].sort((a, b) => a - b)[Math.floor(levels.length * 0.3)];
          levels.push(level);
          if (levels.length > room) levels.shift();
          const loud = level > floor + 10;
          if (!run.length && !loud) {
            pre = [...pre, x].slice(-Math.ceil(0.3 / block));
            return;
          }
          run.push(x);
          quiet = loud ? 0 : quiet + 1;
          const secs = run.length * block;
          if (quiet * block < 0.6 && secs < 6) return;
          const all = [...pre, ...run];
          run = [];
          pre = [];
          quiet = 0;
          if (secs - 0.6 < 0.3) return;
          const audio = wav(all, rate);
          const seconds = all.length * block;
          if (busy) waiting = { audio, seconds, ended: performance.now() }; // the latest one waits
          else send(audio, seconds, performance.now());
        };
        source.connect(node);
        node.connect(ctx.destination); // silent: it only listens
        window.addEventListener("pointerdown", wakeUp);
      },
      () => say("This phone wouldn't lend its microphone for \"Hey Claude\".", true),
    );
    return () => {
      stopped = true;
      window.removeEventListener("pointerdown", wakeUp);
      ctx?.close();
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [on, say]);
}

/** 16 kHz 16-bit mono WAV of the blocks (at `rate`). */
function wav(blocks: Float32Array[], rate: number) {
  const n = blocks.reduce((a, b) => a + b.length, 0);
  const all = new Float32Array(n);
  let at = 0;
  for (const b of blocks) {
    all.set(b, at);
    at += b.length;
  }
  const out = Math.floor((n * 16000) / rate);
  const view = new DataView(new ArrayBuffer(44 + out * 2));
  const text = (o: number, t: string) => [...t].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + out * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true);
  view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, out * 2, true);
  for (let i = 0; i < out; i++) {
    const p = (i * rate) / 16000;
    const j = Math.floor(p);
    const v = all[j] + ((all[j + 1] ?? all[j]) - all[j]) * (p - j);
    view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true);
  }
  return new Blob([view.buffer], { type: "audio/wav" });
}

/** Which microphone push-to-talk uses. */
export function MicSettings() {
  const { talk, act } = usePedal();
  const [phoneMic, setPhoneMic] = usePhoneMic();
  if (!talk.installed) {
    return <p className="mic-note">Talking needs speech-to-text on this computer: <code>pip install g3xn[voice]</code></p>;
  }
  return (
    <div className="mic">
      <label className="mic-field">
        <span>Talk into</span>
        <select value={talk.mic} onChange={(e) => act(() => api.talkSet({ mic: e.target.value as "laptop" | "phone" }))}>
          <option value="laptop">This computer's mic</option>
          <option value="phone">My phone</option>
        </select>
      </label>
      <div className="mic-wake">
        <WakeButton />
        <span>{phoneMicHere ? "Listens on this phone" : "Listens on this computer"} for “Hey Claude, …”</span>
      </div>
      {talk.mic === "laptop" && (
        <label className="mic-field">
          <span>Mic</span>
          <select value={talk.input ?? ""} onChange={(e) => act(() => api.talkSet({ input: e.target.value }))}>
            <option value="">System default</option>
            {talk.inputs.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </label>
      )}
      {talk.mic === "phone" &&
        (onThisComputer ? (
          <p className="mic-note">Open the remote on your phone at its Tailscale https address and turn on its mic there.</p>
        ) : !window.isSecureContext ? (
          <p className="mic-note">Phones only lend their mic to https pages. Open the Tailscale https address instead.</p>
        ) : (
          <label className="mic-check">
            <input type="checkbox" checked={phoneMic} onChange={(e) => setPhoneMic(e.target.checked)} />
            Use this phone's mic
          </label>
        ))}
    </div>
  );
}

/** The sheet over everything while talking, and for a few seconds after Claude answers. */
export function TalkSheet() {
  const { talk, chat } = usePedal();
  const [shown, setShown] = useState(false);
  usePhoneRecorder();
  useWake();

  const active = talk.state !== "idle";
  useEffect(() => {
    if (talk.state === "listening") setShown(true);
  }, [talk.state]);
  useEffect(() => {
    if (!shown || active || chat.busy) return;
    const t = window.setTimeout(() => setShown(false), talk.problem ? 6000 : 4500);
    return () => window.clearTimeout(t);
  }, [shown, active, chat.busy, talk.problem]);
  useEffect(() => {
    if (!shown) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setShown(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown]);
  if (!shown) return null;

  const reply = talk.heard ? chat.messages[chat.messages.length - 1] : undefined;
  const heading =
    talk.state === "listening" ? "Listening" : talk.state === "transcribing" ? "Working out what you said" : talk.problem ? "Didn't get that" : chat.busy ? "Claude is on it" : "Done";

  return (
    <div className="talk-backdrop">
      <section className={`talk-sheet state-${talk.state}`} role="dialog" aria-modal="false" aria-label="Talking to Claude">
        <header className="talk-head">
          <span className={`talk-led${talk.state === "listening" ? " on" : ""}`} aria-hidden="true" />
          <h2>{heading}</h2>
          <span className="talk-source">
            {talk.state === "listening" ? `${talk.mic === "phone" ? "your phone" : "this computer"} · let go when you're done` : ""}
          </span>
          <button className="talk-close" onClick={() => setShown(false)} aria-label="Close">
            <Icon name="close" size={18} />
          </button>
        </header>
        {talk.state === "listening" && <div className="talk-meter" aria-hidden="true">{Array.from({ length: 32 }, (_, i) => <span key={i} style={{ animationDelay: `${(i * 97) % 700}ms` }} />)}</div>}
        {talk.heard && <p className="talk-heard">“{talk.heard}”</p>}
        {talk.problem && talk.state === "idle" && <p className="talk-problem">{talk.problem}</p>}
        {reply?.role === "claude" && (reply.text || changesOnly(reply.tools).length > 0 || reply.error) && (
          <div className="talk-reply">
            {reply.text && <p>{reply.text}</p>}
            {changesOnly(reply.tools).length > 0 && (
              <ul className="changes" aria-label="What Claude changed">
                {changesOnly(reply.tools).map((t, i) => (
                  <li key={i} className="change vfd">{describe(t)}</li>
                ))}
              </ul>
            )}
            {reply.error && <p className="talk-problem">{reply.error}</p>}
          </div>
        )}
      </section>
    </div>
  );
}

function usePhoneMic(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(PHONE_MIC_KEY) === "1";
    } catch {
      return false;
    }
  });
  const set = async (next: boolean) => {
    if (next) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); // asks once, now
        stream.getTracks().forEach((t) => t.stop());
      } catch {
        return;
      }
    }
    try {
      localStorage.setItem(PHONE_MIC_KEY, next ? "1" : "0");
    } catch {
      // storage blocked: works until the page closes
    }
    setOn(next);
  };
  return [on, set];
}

/** On a phone that lends its mic: record while the talk switch is held, then send it. */
function usePhoneRecorder() {
  const { talk, say } = usePedal();
  const rec = useRef<{ recorder: MediaRecorder; chunks: Blob[] } | null>(null);
  const listening = talk.state === "listening" && talk.mic === "phone";

  useEffect(() => {
    let mine = false;
    try {
      mine = !onThisComputer && window.isSecureContext && localStorage.getItem(PHONE_MIC_KEY) === "1";
    } catch {
      mine = false;
    }
    if (!mine) return;
    if (listening && !rec.current) {
      navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
        const recorder = new MediaRecorder(stream);
        const chunks: Blob[] = [];
        recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
        recorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          api.talkAudio(new Blob(chunks, { type: recorder.mimeType })).catch((err) => say(err.message, true));
        };
        recorder.start();
        rec.current = { recorder, chunks };
      }, () => say("This phone wouldn't lend its microphone.", true));
    } else if (!listening && rec.current) {
      rec.current.recorder.stop();
      rec.current = null;
    }
  }, [listening, say]);
}
