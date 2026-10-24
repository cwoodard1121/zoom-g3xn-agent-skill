// One shared picture of the pedal, kept current by the daemon's live events.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError, subscribe } from "./api";
import type { ChatInfo, ChatMessage, GigSummary, Guitars, HistorySummary, PedalEvent, StageMove, Status, TalkInfo, TalkState, Tone } from "./api";

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
  talk: TalkInfo & { heard: string | null; problem: string | null; since: number | null };
  /** Which guitar each slot's tone is for (by slot number), and the guitars named so far. */
  guitars: { slots: Record<number, string>; names: string[] };
  /** Counts the phone remote's changes (a phone paired, the remote turned on), to read it again. */
  remoteSeen: number;
  /** The last words meant for the stage view ("chorus", "two bars behind"), counted. */
  /** Words for the stage. `since`: when they started being said (performance.now()); `exact`
   * when that's from the words themselves, not from when the switch went down. */
  stageHeard: { text: string; n: number; since: number | null; exact: boolean } | null;
  /** The last move for the stage from outside it (the API, Claude's stage tool). */
  stageMove: { move: StageMove; n: number; since: number | null } | null;
}

type Action =
  | PedalEvent
  | { type: "linked"; open: boolean }
  | { type: "live-read"; tone: Tone | null }
  | { type: "chat-read"; info: ChatInfo }
  | { type: "talk-read"; info: TalkInfo }
  | { type: "guitars-read"; info: Guitars };

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
    case "guitars":
    case "guitars-read": {
      const info = a.type === "guitars" ? a : a.info;
      return { ...s, guitars: { slots: Object.fromEntries(Object.entries(info.slots).map(([k, v]) => [Number(k), v])), names: info.names } };
    }
    case "remote":
      return { ...s, remoteSeen: s.remoteSeen + 1 };
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
    case "stage": {
      const { type: _type, n, ...move } = a;
      return { ...s, stageMove: { move, n, since: typeof move.ago === "number" ? performance.now() - move.ago * 1000 : null } };
    }
    case "talk": {
      const { type: _type, text, problem, to, n, ago, ...info } = a;
      const state = a.state as TalkState;
      // `since`: when the talking started (performance.now()), so the stage can allow for the delay:
      // from the words' own time (`ago`) when there is one, else from when the switch went down.
      const exact = typeof ago === "number";
      const since = exact ? performance.now() - ago * 1000 : state === "listening" ? performance.now() : s.talk.since;
      if (to === "stage" && text && n) return { ...s, stageHeard: { text, n, since, exact }, talk: { ...s.talk, state, heard: text, problem: null, since } };
      return {
        ...s,
        talk: {
          ...s.talk,
          ...info,
          state,
          since,
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
  /** Name the guitar for a slot's tone ("" forgets it). */
  setGuitar: (slot: number, guitar: string) => Promise<void>;
}

const PedalContext = createContext<Pedal | null>(null);

export function PedalProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, {
    linked: false, status: null, names: {}, live: null, tuner: null, pedalTempo: null, history: { position: -1, entries: [] },
    gigs: { list: [], active: null },
    chat: { messages: [], busy: false, available: true },
    talk: { state: "idle", mic: "laptop", input: null, inputs: [], installed: false, heard: null, problem: null, since: null },
    stageHeard: null,
    stageMove: null,
    remoteSeen: 0,
    guitars: { slots: {}, names: [] },
  });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [copyOf, setCopyOf] = useState<CopyOf | null>(null);
  const nextToast = useRef(1);

  useEffect(
    () =>
      subscribe(
        (e) => {
          dispatch(e);
          if (e.type === "backup") say(e.problem ? `Pedal not backed up: ${e.problem}` : "Pedal backed up: something changed since last time", !!e.problem);
        },
        (open) => dispatch({ type: "linked", open }),
      ),
    [],
  );
  // The conversation and microphone so far, read again whenever the link comes back.
  useEffect(() => {
    if (!state.linked) return;
    api.chat().then((info) => dispatch({ type: "chat-read", info }), () => {});
    api.talk().then((info) => dispatch({ type: "talk-read", info }), () => {});
    api.guitars().then((info) => dispatch({ type: "guitars-read", info }), () => {});   // older daemons: none
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
  const setGuitar = useCallback(
    async (slot: number, guitar: string) => {
      const info = await act(() => api.setGuitar(slot, guitar));
      if (info) dispatch({ type: "guitars-read", info });
    },
    [act],
  );
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
      setGuitar,
    }),
    [state, copyOf, act, toasts, say, refreshLive, setLive, setGuitar],
  );
  return <PedalContext.Provider value={value}>{children}</PedalContext.Provider>;
}

export function usePedal(): Pedal {
  const p = useContext(PedalContext);
  if (!p) throw new Error("usePedal outside PedalProvider");
  return p;
}
