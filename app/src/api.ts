// Talking to the g3xn daemon: HTTP for actions, a WebSocket for live events.
// Every route is documented at http://127.0.0.1:8370/docs.

export type Knobs = Record<string, number>;

export interface ChainEffect {
  effect: string;
  on: boolean;
  knobs: Knobs;
  shown?: Record<string, string>; // the pedal's own screen text, when read live
}

export interface Tone {
  name: string;
  volume: number;
  dsp_percent: number;
  chain: ChainEffect[];
  slot?: number;
}

export type Connection = "connecting" | "connected" | "disconnected" | "released";

export interface Status {
  connection: Connection;
  problem: string;
  doing: string | null;
  pedal: { firmware?: string; patches?: number; virtual?: boolean };
  current_slot: number | null;
  current_name: string | null;
  scratch_slot: number | null;
  tuner: boolean;
}

export interface PatchName {
  slot: number;
  name: string;
}

export interface Param {
  name: string;
  max: number;
  default: number;
  explanation: string;
  shown_as?: { offset?: number; options?: string[] };
}

export interface EffectInfo {
  id: string;
  name: string;
  group: string;
  positions: number;
  dsp_percent: number;
  description: string;
  params: Param[];
}

export interface EffectSummary {
  name: string;
  group: string;
  positions: number;
  dsp_percent: number;
  description: string;
}

export interface HistoryEntry {
  id: number;
  time: number; // seconds since 1970
  label: string;
  source: "app" | "claude" | string;
  reason: string;
}

export interface HistorySummary {
  position: number;
  entries: HistoryEntry[];
}

export interface GigEntry {
  song: string;
  tone?: Tone;
  from_slot?: number;
  slot?: number;
  notes?: string;
  tempo?: number;
  key?: string;
}

export interface Gig {
  id?: string;
  name: string;
  start_slot: number;
  patches: GigEntry[];
  loaded?: { time: number; backup: string; slots: { song: string; slot: number; patch: string }[] };
}

export interface GigSummary {
  id: string;
  name: string;
  songs: number;
  start_slot: number;
  loaded?: Gig["loaded"];
}

export interface PlanStep {
  order: number;
  song: string;
  slot: number;
  patch: string;
  replaces: string;
  replaces_own: boolean; // the slot holds what this gig put there last time
  overwrites_real_patch: boolean;
}

export type PedalEvent =
  | ({ type: "status" } & Status)
  | { type: "patches"; patches: PatchName[] }
  | { type: "patch"; slot: number; name: string }
  | { type: "current"; slot: number; name: string | null }
  | { type: "live"; tone: Tone }
  | { type: "tuner"; note: string | null; meter: number }
  | ({ type: "history" } & HistorySummary)
  | { type: "gigs"; gigs: GigSummary[]; active: string | null };

export interface TweakChange {
  effect: number; // 1-based chain number
  knob?: string;
  value?: number;
  on?: boolean;
}

export class ApiError extends Error {}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error ?? `The daemon answered ${res.status}`);
  return data as T;
}

export const api = {
  status: () => call<Status>("GET", "/api/status"),
  live: () => call<Tone>("GET", "/api/live"),
  patch: (slot: number) => call<Tone>("GET", `/api/patches/${slot}`),
  select: (slot: number) => call<{ slot: number; name: string }>("POST", `/api/patches/${slot}/select`),
  audition: (req: { tone?: Tone; slot?: number }) => call<Tone>("POST", "/api/audition", req),
  play: (tone: Tone) => call<Tone>("POST", "/api/play", { tone }),
  morph: (to: Tone, seconds: number) => call<Tone>("POST", "/api/morph", { to, seconds }),
  undo: () => call<Tone>("POST", "/api/undo"),
  redo: () => call<Tone>("POST", "/api/redo"),
  goTo: (entryId: number) => call<Tone>("POST", `/api/history/${entryId}/play`),
  effects: () => call<{ effects: EffectSummary[] }>("GET", "/api/effects"),
  gig: (id: string) => call<Gig>("GET", `/api/setlists/${id}`),
  saveGig: (gig: Gig) => call<Gig>("PUT", `/api/setlists/${gig.id ?? "new"}`, gig),
  deleteGig: (id: string) => call<{ deleted: string }>("DELETE", `/api/setlists/${id}`),
  planGig: (id: string) => call<{ plan: PlanStep[] }>("POST", `/api/setlists/${id}/plan`),
  loadGig: (id: string) => call<{ written: PlanStep[]; backup: string }>("POST", `/api/setlists/${id}/load`),
  exportGig: (first: number, last: number, name: string) =>
    call<Gig>("GET", `/api/gigs/export?first_slot=${first}&last_slot=${last}&name=${encodeURIComponent(name)}`),
  tweak: (req: { changes?: TweakChange[]; volume?: number; name?: string }) => call<Tone>("POST", "/api/tweak", req),
  save: (slot: number, name: string | undefined, replace: boolean) =>
    call<{ saved: string; slot: number; kept?: string }>("POST", `/api/patches/${slot}/save`, { name, replace }),
  effect: (name: string) => call<EffectInfo>("GET", `/api/effects/${encodeURIComponent(name)}`),
  tuner: (on: boolean) => call<{ tuner: boolean }>("POST", "/api/tuner", { on }),
  release: () => call<Status>("POST", "/api/release"),
  connect: () => call<Status>("POST", "/api/connect"),
};

let allEffects: Promise<EffectSummary[]> | null = null;
/** Every effect the pedal has (fetched once). */
export function effectList(): Promise<EffectSummary[]> {
  allEffects ??= api.effects().then((r) => r.effects, (err) => { allEffects = null; throw err; });
  return allEffects;
}

/** Effect details never change, so each is fetched once. */
const effects = new Map<string, Promise<EffectInfo>>();
export function effectInfo(name: string): Promise<EffectInfo> {
  if (!effects.has(name)) {
    effects.set(name, api.effect(name).catch((err) => { effects.delete(name); throw err; }));
  }
  return effects.get(name)!;
}

/** The pedal's screen text for a stored knob value, from the effect's display rule. */
export function shownText(param: Param | undefined, raw: number): string {
  const rule = param?.shown_as;
  if (rule?.options) return rule.options[raw] ?? String(raw);
  if (rule?.offset !== undefined) return String(raw + rule.offset);
  return String(raw);
}

/** Live events. Reconnects by itself (the daemon may restart). */
export function subscribe(onEvent: (e: PedalEvent) => void, onOpen: (open: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let stopped = false;
  let retry: number | undefined;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/events`);
    ws.onopen = () => onOpen(true);
    ws.onmessage = (m) => onEvent(JSON.parse(m.data));
    ws.onclose = () => {
      onOpen(false);
      if (!stopped) retry = window.setTimeout(open, 1500);
    };
  };
  open();
  return () => {
    stopped = true;
    window.clearTimeout(retry);
    ws?.close();
  };
}
