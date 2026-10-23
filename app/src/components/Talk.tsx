// Push to talk. Hold the talk footswitch (or the Talk button), say it, let go: the words go
// to Claude and the sheet shows what was heard and what Claude changed.
// The laptop's microphone is recorded by the daemon; a phone records itself and sends the audio.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { usePedal } from "../pedal";
import { changesOnly, describe } from "./ClaudeStrip";
import { Icon } from "./Icon";

const PHONE_MIC_KEY = "g3xn.phoneMic";
const onThisComputer = ["127.0.0.1", "localhost"].includes(location.hostname);

export function TalkButton() {
  const { talk, act } = usePedal();
  const held = useRef(false);
  const press = (down: boolean) => {
    if (held.current === down) return;
    held.current = down;
    act(() => api.talkSet({ pressed: down }));
  };
  return (
    <button
      type="button"
      className={`button talk-button${talk.state === "listening" ? " live" : ""}`}
      aria-pressed={talk.state === "listening"}
      title="Hold to talk to Claude"
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
