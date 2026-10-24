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
  artist?: string;
  notes?: string;
  tempo?: number;
  key?: string;
  pickup?: string; // the guitar's pickup selector for the song: "Bridge", "Neck", "2"…
  tuning?: string; // "Eb", "Drop D", "D A D G B E"… (none is standard): see tuning.ts
  cues?: string; // effects to switch as the song goes, a line each: "1:05 Octave on" (see cues.ts)
  chords?: string; // the song's chords by section, one section a line: "Verse: Dm C Bb A"
  lyrics?: string;
  synced?: string; // the lyrics with a [mm:ss.xx] time per line (from LRCLIB), for scrolling
  duration?: number; // the recording's length in seconds
}

/** A song's recording, kept by the daemon for the ghost band. */
export interface TrackInfo {
  key: string;
  name: string; // the file it came from
  type: string;
  size: number;
  added: number; // seconds since 1970
}

/** Where a song's recording is kept: its artist and title, as a key ("" if it has no title). */
export const trackKey = (e: { song: string; artist?: string }) =>
  e.song.trim()
    ? `${e.artist ?? ""} ${e.song}`.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80)
    : "";

/** A song that changed on the pedal since its gig was loaded. */
export interface GigChange {
  song: string;
  slot: number;
  patch: string;
  now: string;
  change?: string;
}

export interface Backup {
  name: string; // "auto/2026-10-23_101500"
  time: number; // seconds since 1970
  auto: boolean; // kept when the pedal was plugged in
  slots: number;
  first: boolean; // the oldest one: nothing to compare with
  changed: { slot: number; was: string | null; now: string | null }[]; // since the one before
}

export interface LyricsHit {
  found: boolean;
  song: string;
  artist?: string;
  lyrics?: string;
  synced?: string;
  duration?: number;
  source?: string;
}

export interface Gig {
  id?: string;
  name: string;
  start_slot: number;
  patches: GigEntry[];
  loaded?: {
    time: number;
    backup: string;
    // chain: the patch's effects as the gig loaded it, on or off
    slots: { song: string; slot: number; patch: string; chain?: { effect: string; on: boolean }[] }[];
  };
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

export interface ChatTool {
  name: string;
  input: Record<string, unknown>;
}

export interface ChatMessage {
  role: "user" | "claude";
  text: string;
  tools?: ChatTool[];
  error?: string;
}

export interface ChatInfo {
  busy: boolean;
  session: string | null;
  messages: ChatMessage[];
  available: boolean;
}

export type TalkState = "idle" | "listening" | "transcribing" | "heard";

export interface TalkInfo {
  state: TalkState;
  mic: "laptop" | "phone";
  input: string | null;
  inputs: string[];
  installed: boolean;
}

export type ChatEvent =
  | { type: "chat"; kind: "user"; text: string }
  | { type: "chat"; kind: "text"; delta: string }
  | ({ type: "chat"; kind: "tool" } & ChatTool)
  | { type: "chat"; kind: "done"; text: string }
  | { type: "chat"; kind: "error"; text: string }
  | { type: "chat"; kind: "new" };

export type TalkEvent = {
  type: "talk";
  state: TalkState;
  mic?: TalkInfo["mic"];
  text?: string;
  problem?: string;
  to?: "stage"; // the stage view takes these words (n counts them)
  n?: number;
} & Partial<TalkInfo>;

export type PedalEvent =
  | ({ type: "status" } & Status)
  | { type: "patches"; patches: PatchName[] }
  | { type: "patch"; slot: number; name: string }
  | { type: "current"; slot: number; name: string | null }
  | { type: "live"; tone: Tone }
  | { type: "tuner"; note: string | null; meter: number }
  | { type: "tempo"; bpm: number }
  | { type: "backup"; folder?: string; problem?: string }
  | ({ type: "history" } & HistorySummary)
  | { type: "gigs"; gigs: GigSummary[]; active: string | null }
  | ChatEvent
  | TalkEvent
  | { type: "footswitch" | "remote" | "midi" | "lock" };

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
  backups: () => call<{ backups: Backup[]; folder: string | null }>("GET", "/api/backups"),
  restoreSlot: (backup: string, slot: number) =>
    call<{ slot: number; patch: string; saved_current: string }>("POST", "/api/backups/restore", { backup, slot }),
  lyrics: (song: string, artist?: string) =>
    call<LyricsHit>("GET", `/api/lyrics?${new URLSearchParams({ song, artist: artist ?? "" })}`),
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
  /** Set one effect of the patch that's playing on or off (a chain number from 1, or a name).
   * With `slot`, only while the pedal is still on that slot. */
  stomp: (effect: number | string, on: boolean, slot?: number) =>
    call<Tone & { skipped?: string }>("POST", "/api/stomp", { effect, on, slot }),
  release: () => call<Status>("POST", "/api/release"),
  chat: () => call<ChatInfo>("GET", "/api/chat"),
  chatSend: (text: string) => call<{ sent: string }>("POST", "/api/chat", { text }),
  chatStop: () => call<ChatInfo>("POST", "/api/chat/stop"),
  chatNew: () => call<ChatInfo>("POST", "/api/chat/new"),
  chatTerminal: () => call<{ session: string | null }>("POST", "/api/chat/terminal"),
  talk: () => call<TalkInfo>("GET", "/api/talk"),
  /** The talk button (`pressed`), the mic, the stage view being open (`stage`: words go to it), or
   * words typed instead of said (`say`). */
  talkSet: (req: { pressed?: boolean; mic?: TalkInfo["mic"]; input?: string; stage?: boolean; say?: string }) =>
    call<TalkInfo>("POST", "/api/talk", req),
  talkAudio: async (audio: Blob) => {
    const res = await fetch("/api/talk/audio", { method: "POST", body: audio, headers: { "Content-Type": audio.type || "application/octet-stream" } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(data.error ?? `The daemon answered ${res.status}`);
    return data as { text: string | null };
  },
  connect: () => call<Status>("POST", "/api/connect"),
  /** A song's recording, or null (from the list, so a song without one isn't a failed request). */
  track: async (key: string) => (await call<{ tracks: TrackInfo[] }>("GET", "/api/tracks")).tracks.find((t) => t.key === key) ?? null,
  trackUrl: (key: string, added?: number) => `/api/tracks/${key}/audio${added ? `?v=${Math.round(added)}` : ""}`,
  putTrack: async (key: string, file: File) => {
    const res = await fetch(`/api/tracks/${key}?name=${encodeURIComponent(file.name)}`, {
      method: "PUT", body: file, headers: { "Content-Type": file.type || "application/octet-stream" },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(data.error ?? `The daemon answered ${res.status}`);
    return data as TrackInfo;
  },
  deleteTrack: (key: string) => call<{ deleted: string }>("DELETE", `/api/tracks/${key}`),
  /** Songs changed on the pedal since the gig was loaded; and the panic button, putting them back. */
  checkGig: (id: string) => call<{ changed: GigChange[] }>("POST", `/api/setlists/${id}/check`),
  restoreGig: (id: string) => call<{ restored: GigChange[]; backup: string | null }>("POST", `/api/setlists/${id}/restore`),
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
