// Claude, as the last unit in the rack: type a change (or hold Talk), and its answer and
// every change it made to the pedal read out on the display. The conversation opens upward.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatMessage, ChatTool } from "../api";
import { usePedal } from "../pedal";
import { Icon } from "./Icon";
import { MicSettings, TalkButton } from "./Talk";

export function ClaudeStrip() {
  const { chat, act, linked } = usePedal();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLOListElement>(null);
  const last = chat.messages[chat.messages.length - 1];

  // "/" jumps to the box from anywhere, like a search field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || (e.target as HTMLElement).closest("input, textarea, select")) return;
      e.preventDefault();
      input.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (open) log.current?.lastElementChild?.scrollIntoView({ block: "end" });
  }, [open, chat.messages]);
  // The strip's height, so the tone's save bar can sit just above it.
  const strip = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    const root = document.documentElement.style;
    const ro = new ResizeObserver(() => root.setProperty("--claude-h", el.offsetHeight + "px"));
    ro.observe(el);
    return () => {
      ro.disconnect();
      root.setProperty("--claude-h", "0px");
    };
  }, []);

  const send = async () => {
    const said = text.trim();
    if (!said || chat.busy) return;
    setText("");
    const sent = await act(() => api.chatSend(said));
    if (!sent) setText(said);
  };

  return (
    <section ref={strip} className={`claude${open ? " open" : ""}`} aria-label="Claude">
      {open && (
        <div className="claude-log">
          <div className="claude-log-head">
            <MicSettings />
            <span className="claude-spacer" />
            <button className="link-button" onClick={() => act(() => api.chatTerminal(), () => "Opened the conversation in Claude Code")}>
              Open in Claude Code
            </button>
            <button className="link-button" disabled={!chat.messages.length} onClick={() => act(() => api.chatNew())}>
              New conversation
            </button>
          </div>
          {chat.messages.length === 0 ? (
            <p className="claude-empty">
              Ask for a change while you play: “less fizzy”, “more gain on the solo”, “build my Friday set”. Claude works on a
              copy in slot 150 and never saves over your patches unless you say so.
            </p>
          ) : (
            <ol className="claude-messages" ref={log}>
              {chat.messages.map((m, i) => (
                <Message key={i} message={m} writing={chat.busy && i === chat.messages.length - 1} />
              ))}
            </ol>
          )}
        </div>
      )}
      <div className="claude-face">
        <button className="claude-name" aria-expanded={open} onClick={() => setOpen(!open)} title={open ? "Hide the conversation" : "Show the conversation"}>
          <span className={`led${chat.busy ? " on" : ""}`} aria-hidden="true" />
          Claude
          <Icon name={open ? "down" : "up"} />
        </button>
        {!open && (
          <p className="claude-last vfd" aria-live="polite">
            {last ? lastLine(last, chat.busy) : chat.available ? "Ask for a change. Press / to jump here." : "Claude Code isn't installed on this computer."}
          </p>
        )}
        <form
          className="claude-form"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <label className="visually-hidden" htmlFor="claude-input">Ask Claude</label>
          <input
            id="claude-input"
            ref={input}
            className="claude-input"
            value={text}
            placeholder={chat.busy ? "Claude is on it…" : "Ask for a change…"}
            autoComplete="off"
            disabled={!linked}
            onChange={(e) => setText(e.target.value)}
          />
          {chat.busy ? (
            <button type="button" className="button" onClick={() => act(() => api.chatStop())}>Stop</button>
          ) : (
            <button type="submit" className="button primary" disabled={!text.trim()}>Send</button>
          )}
          <TalkButton />
        </form>
      </div>
    </section>
  );
}

function Message({ message, writing }: { message: ChatMessage; writing: boolean }) {
  if (message.role === "user") {
    return <li className="said">{message.text}</li>;
  }
  return (
    <li className="answer">
      {message.text ? <p>{message.text}</p> : writing ? <p className="working">Working on it…</p> : null}
      {changesOnly(message.tools).length > 0 && (
        <ul className="changes" aria-label="What Claude changed">
          {changesOnly(message.tools).map((t, i) => (
            <li key={i} className="change vfd">{describe(t)}</li>
          ))}
        </ul>
      )}
      {message.error && <p className="claude-error">{message.error}</p>}
    </li>
  );
}

function lastLine(m: ChatMessage, busy: boolean): string {
  if (m.error) return m.error;
  if (m.text) return m.text;
  const changed = changesOnly(m.tools);
  if (busy) return changed.length ? describe(changed[changed.length - 1]) : "Working on it…";
  return "";
}

/** One line for what a tool call did, in the pedal's terms. */
/** Tools that only look (the conversation shows what Claude changed, not what it read). */
const LOOKS = new Set(["pedal_status", "get_patch", "list_patches", "effect_details", "find_effects", "saved_gigs", "get_gig", "export_gig"]);

export function changesOnly(tools: ChatTool[] | undefined): ChatTool[] {
  return (tools ?? []).filter((t) => !LOOKS.has(t.name) && !t.name.includes("Search"));
}

export function describe(t: ChatTool): string {
  const i = t.input as Record<string, unknown>;
  const changes = Array.isArray(i.changes) ? (i.changes as Record<string, unknown>[]) : [];
  switch (t.name) {
    case "tweak":
      return changes
        .map((c) => (c.knob !== undefined ? `${c.effect} ${c.knob} ${c.value}` : `${c.effect} ${c.on ? "on" : "off"}`))
        .concat(i.volume !== undefined ? [`Volume ${i.volume}`] : [])
        .join(" · ") || "Tweak";
    case "audition":
      return i.slot !== undefined ? `Copy slot ${i.slot} to try` : `Try ${(i.tone as { name?: string })?.name ?? "a tone"}`;
    case "change_chain":
      return "Change the chain";
    case "select_patch":
      return `Switch to slot ${i.slot}`;
    case "save_to_slot":
      return `Save in slot ${i.slot}`;
    case "tuner":
      return i.on ? "Tuner on" : "Tuner off";
    default:
      return t.name.replace(/_/g, " ");
  }
}
