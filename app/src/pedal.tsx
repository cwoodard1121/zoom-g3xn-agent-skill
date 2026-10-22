// One shared picture of the pedal, kept current by the daemon's live events.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError, subscribe } from "./api";
import type { HistorySummary, PedalEvent, Status, Tone } from "./api";

interface State {
  linked: boolean; // WebSocket to the daemon is open
  status: Status | null;
  names: Record<number, string>;
  live: Tone | null;
  tuner: { note: string | null; meter: number } | null;
  history: HistorySummary;
}

type Action = PedalEvent | { type: "linked"; open: boolean } | { type: "live-read"; tone: Tone | null };

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
    case "history":
      return { ...s, history: { position: a.position, entries: a.entries } };
  }
}

export interface Toast {
  id: number;
  text: string;
  error?: boolean;
}

interface Pedal extends State {
  onScratch: boolean;
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
    linked: false, status: null, names: {}, live: null, tuner: null, history: { position: -1, entries: [] },
  });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextToast = useRef(1);

  useEffect(() => subscribe((e) => dispatch(e), (open) => dispatch({ type: "linked", open })), []);

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

  const value = useMemo<Pedal>(
    () => ({
      ...state,
      onScratch: !!state.status && state.status.current_slot === state.status.scratch_slot,
      act,
      toasts,
      say,
      refreshLive,
      setLive,
    }),
    [state, act, toasts, say, refreshLive, setLive],
  );
  return <PedalContext.Provider value={value}>{children}</PedalContext.Provider>;
}

export function usePedal(): Pedal {
  const p = useContext(PedalContext);
  if (!p) throw new Error("usePedal outside PedalProvider");
  return p;
}
