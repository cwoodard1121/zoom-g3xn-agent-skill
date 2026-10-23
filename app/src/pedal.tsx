// One shared picture of the pedal, kept current by the daemon's live events.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError, subscribe } from "./api";
import type { ChatInfo, ChatMessage, GigSummary, HistorySummary, PedalEvent, Status, TalkInfo, TalkState, Tone } from "./api";

interface State {
  linked: boolean; // WebSocket to the daemon is open
  status: Status | null;
  names: Record<number, string>;
  live: Tone | null;
  tuner: { note: string | null; meter: number } | null;
  /** The tempo last tapped on the pedal (its own tap tempo), and when. */
  pedalTempo: { bpm: number; at: number } | null;
  history: HistorySummary;
  gigs: { list: GigSummary[]; active: string | null };
  chat: { messages: ChatMessage[]; busy: boolean; available: boolean };
  /** Push to talk: the microphone settings, and what's being heard right now. */
  talk: TalkInfo & { heard: string | null; problem: string | null };
}

type Action =
  | PedalEvent
  | { type: "linked"; open: boolean }
  | { type: "live-read"; tone: Tone | null }
  | { type: "chat-read"; info: ChatInfo }
  | { type: "talk-read"; info: TalkInfo };

/** The conversation with one more event applied: Claude's reply is the last message. */
function chatWith(chat: State["chat"], a: Extract<PedalEvent, { type: "chat" }>): State["chat"] {
  const messages = [...chat.messages];
  const reply = messages[messages.length - 1]?.role === "claude" ? { ...messages[messages.length - 1] } : null;
  const put = (m: ChatMessage) => (messages[messages.length - 1] = m);
  switch (a.kind) {
    case "user":
      return { ...chat, busy: true, messages: [...messages, { role: "user", text: a.text }, { role: "claude", text: "", tools: [] }] };
    case "text":
      if (reply) put({ ...reply, text: reply.text + a.delta });
      return { ...chat, messages };
    case "tool":
      if (reply) put({ ...reply, tools: [...(reply.tools ?? []), { name: a.name, input: a.input }] });
      return { ...chat, messages };
    case "done":
      if (reply && !reply.text) put({ ...reply, text: a.text });
      return { ...chat, busy: false, messages };
    case "error":
      if (reply) put({ ...reply, error: a.text });
      return { ...chat, busy: false, messages };
    case "new":
      return { ...chat, busy: false, messages: [] };
  }
}

function reduce(s: State, a: Action): State {
  switch (a.type) {
    case "linked":
      return { ...s, linked: a.open };
    case "status": {
      const { type: _type, ...status } = a;
      return { ...s, status };
    }
    case "patches":
      return { ...s, names: Object.fromEntries(a.patches.map((p) => [p.slot, p.name])) };
    case "patch":
      return { ...s, names: { ...s.names, [a.slot]: a.name } };
    case "current":
      return s.status ? { ...s, status: { ...s.status, current_slot: a.slot, current_name: a.name } } : s;
    case "live":
    case "live-read":
      return { ...s, live: a.tone };
    case "tuner":
      return { ...s, tuner: { note: a.note, meter: a.meter } };
    case "tempo":
      return { ...s, pedalTempo: { bpm: a.bpm, at: Date.now() } };
    case "history":
      return { ...s, history: { position: a.position, entries: a.entries } };
    case "gigs":
      return { ...s, gigs: { list: a.gigs, active: a.active } };
    case "chat":
      return { ...s, chat: chatWith(s.chat, a) };
    case "chat-read":
      return { ...s, chat: { messages: a.info.messages, busy: a.info.busy, available: a.info.available } };
    case "talk-read":
      return { ...s, talk: { ...s.talk, ...a.info } };
    case "talk": {
      const { type: _type, text, problem, ...info } = a;
      const state = a.state as TalkState;
      return {
        ...s,
        talk: {
          ...s.talk,
          ...info,
          state,
          heard: state === "listening" ? null : text ?? s.talk.heard,
          problem: state === "listening" ? null : problem ?? (state === "idle" ? s.talk.problem : null),
        },
      };
    }
    default:
      return s;
  }
}

export interface Toast {
  id: number;
  text: string;
  error?: boolean;
}

/** The stored patch the scratch slot holds a copy of, while it's being tweaked. */
export interface CopyOf {
  slot: number;
  name: string;
}

interface Pedal extends State {
  onScratch: boolean;
  copyOf: CopyOf | null;
  setCopyOf: (c: CopyOf | null) => void;
  /** Run an action; failures become an error toast instead of an exception. */
  act: <T>(fn: () => Promise<T>, done?: (result: T) => string | void) => Promise<T | undefined>;
  toasts: Toast[];
  say: (text: string, error?: boolean) => void;
  refreshLive: () => void;
  setLive: (tone: Tone) => void;
}

const PedalContext = createContext<Pedal | null>(null);

export function PedalProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, {
    linked: false, status: null, names: {}, live: null, tuner: null, pedalTempo: null, history: { position: -1, entries: [] },
    gigs: { list: [], active: null },
    chat: { messages: [], busy: false, available: true },
    talk: { state: "idle", mic: "laptop", input: null, inputs: [], installed: false, heard: null, problem: null },
  });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [copyOf, setCopyOf] = useState<CopyOf | null>(null);
  const nextToast = useRef(1);

  useEffect(() => subscribe((e) => dispatch(e), (open) => dispatch({ type: "linked", open })), []);
  // The conversation and microphone so far, read again whenever the link comes back.
  useEffect(() => {
    if (!state.linked) return;
    api.chat().then((info) => dispatch({ type: "chat-read", info }), () => {});
    api.talk().then((info) => dispatch({ type: "talk-read", info }), () => {});
  }, [state.linked]);

  const say = useCallback((text: string, error = false) => {
    const id = nextToast.current++;
    setToasts((t) => [...t.slice(-3), { id, text, error }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 7000 : 3500);
  }, []);

  const act = useCallback(
    async <T,>(fn: () => Promise<T>, done?: (result: T) => string | void) => {
      try {
        const result = await fn();
        const message = done?.(result);
        if (message) say(message);
        return result;
      } catch (err) {
        say(err instanceof ApiError ? err.message : "Can't reach the g3xn daemon. Is it running?", true);
        return undefined;
      }
    },
    [say],
  );

  // Whenever the pedal lands on a different patch, read what it is playing.
  const current = state.status?.connection === "connected" ? state.status.current_slot : null;
  const refreshLive = useCallback(() => {
    api.live().then((tone) => dispatch({ type: "live-read", tone }), () => dispatch({ type: "live-read", tone: null }));
  }, []);
  useEffect(() => {
    if (current) refreshLive();
  }, [current, refreshLive]);
  const setLive = useCallback((tone: Tone) => dispatch({ type: "live-read", tone }), []);
  // Off the scratch slot, whatever plays there next may not be that copy any more.
  const scratch = state.status?.scratch_slot;
  useEffect(() => {
    if (current && current !== scratch) setCopyOf(null);
  }, [current, scratch]);

  const value = useMemo<Pedal>(
    () => ({
      ...state,
      onScratch: !!state.status && state.status.current_slot === state.status.scratch_slot,
      copyOf,
      setCopyOf,
      act,
      toasts,
      say,
      refreshLive,
      setLive,
    }),
    [state, copyOf, act, toasts, say, refreshLive, setLive],
  );
  return <PedalContext.Provider value={value}>{children}</PedalContext.Provider>;
}

export function usePedal(): Pedal {
  const p = useContext(PedalContext);
  if (!p) throw new Error("usePedal outside PedalProvider");
  return p;
}
