"""The g3xn daemon: one process that owns the pedal, for the app, Claude and the CLI.

    g3xn-daemon                  # http://127.0.0.1:8370, API docs at /docs
    g3xn-daemon --sim            # a virtual pedal (data/pedal_dump if present), no hardware;
                                 # Claude's tool calls keep going to the real pedal

MIDI ports are exclusive and the pedal answers one request at a time, so a
single worker thread holds the port and runs every pedal action in turn.
Between actions it watches the pedal (patch changes, knob turns, tuner) and
reconnects by itself when the pedal is unplugged or another program lets go.

Clients get live events from the WebSocket at /api/events:
    {"type": "status", ...}                      connection, what the pedal is doing
    {"type": "patches", "patches": [...]}        every slot's name (after connecting)
    {"type": "patch", "slot": 12, "name": ...}   a slot was written
    {"type": "current", "slot": 150, "name": ...} the pedal switched patches
    {"type": "live", "tone": {...}}              the tone playing now changed
    {"type": "history", "position": 4, "entries": [...]}   the time machine (see history.py)
    {"type": "tuner", "note": "E", "meter": -1}  while the tuner is on

The daemon writes ~/.g3xn/daemon.json while it runs, so g3xn-mcp sends its
tool calls here instead of opening the port itself.
"""
import argparse
import asyncio
import concurrent.futures
import contextlib
import json
import os
import queue
import socket
import tempfile
import threading
import time
from typing import Optional, Union

import uvicorn
from fastapi import Body, FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import protocol as P
from . import service
from . import gig as gig_files
from .gig import GigLibrary, shown as shown_gig
from .chat import Chat, ChatError
from .footswitch import Footswitches
from .backups import Backups, write as write_backup
from .history import History
from .patch import Patch
from .lyrics import LyricsError
from . import lyrics as lyric_search
from .remote import COOKIE, Remote
from .remote import DEFAULT_PORT as REMOTE_PORT
from .pedal import Pedal, PedalError
from .voice import Talk

DEFAULT_PORT = 8370
DISCOVERY_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "daemon.json")
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "history.json")
GIGS_FOLDER = gig_files.FOLDER
REMOTE_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "remote.json")
MIDI_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "midi.json")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(REPO, "app", "dist")          # the built web UI (npm run build in app/)
RETRY_SECONDS = 2.0
WATCH_SECONDS = 1.0


class NotConnected(PedalError):
    pass


# --- the worker thread that owns the pedal ---

class PedalWorker(threading.Thread):
    """Runs pedal actions one at a time and watches the pedal in between."""

    def __init__(self, make_pedal, emit, backups=None):
        super().__init__(name="pedal", daemon=True)
        self.make_pedal = make_pedal      # () -> Pedal (not yet open)
        self.emit = emit                  # (event dict) -> None, thread-safe
        self.backups = backups            # a backups.Backups: keep every slot each time the pedal connects
        self.jobs = queue.Queue()
        self.pedal = None
        self.connection = "connecting"    # connected / disconnected / released
        self.problem = ""
        self.doing = None
        self.info = {}
        self.names = {}
        self.current = None
        self.tuner_on = False
        self._stopping = threading.Event()
        self._next_watch = 0.0
        self._live_dirty = None
        self._loaded = None                 # the edit buffer last time it was looked at (see _poll_current)

    # --- called from the web server ---

    def submit(self, label, fn, touches=()):
        """Queue fn(pedal). `touches`: slots it may write (or a function of its result),
        so their names are re-read afterwards. Returns a concurrent Future."""
        future = concurrent.futures.Future()
        self.jobs.put((label, fn, touches, future))
        return future

    def snapshot(self):
        return {"type": "status", "connection": self.connection, "problem": self.problem, "doing": self.doing,
                "pedal": self.info, "current_slot": self.current, "current_name": self.names.get(self.current),
                "scratch_slot": self.pedal.scratch if self.pedal else None, "tuner": self.tuner_on}

    def release(self):
        """Let go of the pedal (so ToneLib can use it) until connect() is called."""
        return self.submit("letting go of the pedal", lambda p: self._close("released"))

    def connect(self):
        if self.connection == "released":
            self.connection = "connecting"
            self._status()

    def stop(self):
        self._stopping.set()
        self.join(timeout=5)

    # --- the loop ---

    def run(self):
        while not self._stopping.is_set():
            if self.pedal is None:
                self._fail_waiting_jobs()
                if self.connection != "released":
                    self._open()
                if self.pedal is None:
                    self._stopping.wait(RETRY_SECONDS if self.connection != "released" else 0.1)
                continue
            try:
                job = self.jobs.get(timeout=0.05)
            except queue.Empty:
                self._watch()
                continue
            self._run(*job)
        if self.pedal:
            self._close("disconnected")

    def _run(self, label, fn, touches, future):
        if not future.set_running_or_notify_cancel():
            return
        self._busy(label)
        try:
            result = fn(self.pedal)
            if self.pedal:
                for slot in touches(result) if callable(touches) else touches:
                    self.names[slot] = self.pedal.read(slot).name
                    self.emit({"type": "patch", "slot": slot, "name": self.names[slot]})
            future.set_result(result)
        except Exception as err:
            future.set_exception(err)
            self._check_still_there()
        finally:
            self._busy(None)
            if self.pedal and not self.tuner_on:
                self._poll_current()

    def _open(self):
        try:
            pedal = self.make_pedal()
            pedal.open()
        except PedalError as err:
            if self.connection != "disconnected" or self.problem != str(err):
                self.connection, self.problem = "disconnected", str(err)
                self._status()
            return
        self.pedal, self.connection, self.problem = pedal, "connected", ""
        try:
            self.info = dict(pedal.identity(), virtual=pedal.device is not None)
            self._status()
            self._read_names()
            self._poll_current()
        except PedalError as err:
            self.problem = str(err)
            self._close("disconnected")

    def _read_names(self):
        count, raw = self.pedal.patch_count, {}
        for n in range(1, count + 1):
            if n % 15 == 1:
                self._busy("reading your patches %d/%d" % (n, count))
            raw[n] = self.pedal.read_raw(n)
            self.names[n] = Patch.decode(raw[n]).name
        self._busy(None)
        if self.backups:                  # they're all read anyway: keep them, if anything changed
            try:
                folder = self.backups.auto(raw)
            except OSError as err:
                self.emit({"type": "backup", "problem": "couldn't save the automatic backup: %s" % err})
            else:
                if folder:
                    self.emit({"type": "backup", "folder": folder})
        self.emit({"type": "patches", "patches": [{"slot": n, "name": self.names[n]} for n in range(1, count + 1)]})

    def _watch(self):
        """Between jobs: pass on what the pedal says, and check it's still there."""
        try:
            for ev in self.pedal.events():
                if ev["type"] == "tuner":
                    self.emit(ev)
                elif ev["type"] == "patch":
                    self._set_current(ev["slot"])
                elif ev["type"] == "edit":
                    if (ev["target"], ev["param"]) == (P.TARGET_SETTINGS, P.SETTING_TEMPO):
                        self.emit({"type": "tempo", "bpm": ev["value"]})     # tapped on the pedal
                    self._live_dirty = self._live_dirty or time.time()
            if self._live_dirty and time.time() - self._live_dirty > 0.15:
                self._live_dirty = None
                self.emit({"type": "live", "tone": service.live_view(self.pedal)})
            if time.time() >= self._next_watch and not self.tuner_on:
                self._next_watch = time.time() + WATCH_SECONDS
                self._poll_current()
        except PedalError:
            self._check_still_there()

    def _poll_current(self):
        self._set_current(self.pedal.current())
        # The pedal doesn't always say when its own footswitches turn an effect on or off (or a knob
        # is turned on it): compare what it has loaded with last time, and send the live tone if it moved.
        loaded = self.pedal.edit_buffer().encode()
        if self._loaded is not None and loaded != self._loaded:
            self._live_dirty = self._live_dirty or time.time()
        self._loaded = loaded

    def _set_current(self, slot):
        if slot != self.current:
            self.current = slot
            self.emit({"type": "current", "slot": slot, "name": self.names.get(slot)})

    def _check_still_there(self):
        if self.pedal and not self.pedal.present():
            self.problem = "the pedal was unplugged"
            self._close("disconnected")

    def _close(self, connection):
        with contextlib.suppress(Exception):
            if self.tuner_on:
                self.pedal.tuner(False)
            self.pedal.close()
        self.pedal, self.connection, self.tuner_on = None, connection, False
        self._status()

    def _fail_waiting_jobs(self):
        while True:
            try:
                *_, future = self.jobs.get_nowait()
            except queue.Empty:
                return
            if future.set_running_or_notify_cancel():
                future.set_exception(NotConnected("the pedal is not connected" + (": " + self.problem if self.problem else "")))

    def _busy(self, doing):
        self.doing = doing
        self._status()

    def _status(self):
        self.emit(self.snapshot())


# --- events to WebSocket clients ---

class EventHub:
    def __init__(self):
        self.clients = set()
        self.loop = None

    def emit(self, event):
        """Thread-safe: queue an event for every connected client."""
        if self.loop:
            self.loop.call_soon_threadsafe(self._publish, event)

    def _publish(self, event):
        for q in list(self.clients):
            if q.full():
                q.get_nowait()          # a slow client loses old events, not new ones
            q.put_nowait(event)


# --- the web app ---

class AuditionRequest(BaseModel):
    tone: dict | None = None
    slot: int | None = None
    reason: str = ""          # why (Claude says what it was going for); shown in the history


class TweakRequest(BaseModel):
    changes: list[dict] = []
    volume: int | None = None
    name: str | None = None
    reason: str = ""


class PlayRequest(BaseModel):
    tone: dict
    reason: str = ""


class MorphRequest(BaseModel):
    to: dict
    seconds: float = 3.0


class WriteRequest(BaseModel):
    tone: dict
    replace: bool = False


class SaveRequest(BaseModel):
    name: str | None = None
    replace: bool = False


class BackupRequest(BaseModel):
    folder: str = ""


class TunerRequest(BaseModel):
    on: bool = True


class StompRequest(BaseModel):
    effect: Union[int, str]   # its number in the chain (1 = first) or its name
    on: bool
    slot: Optional[int] = None  # only if the pedal is still on this slot (a song's cue, not the next song's)


class RestoreRequest(BaseModel):
    backup: str               # its name, as GET /api/backups lists it
    slot: int


class LockRequest(BaseModel):
    on: bool = True


class BatchRequest(BaseModel):
    edit: dict
    save: bool = False


class RemoteRequest(BaseModel):
    on: bool = True


class PairRequest(BaseModel):
    code: str
    name: str = ""


class MidiInputsRequest(BaseModel):
    inputs: list[str]


class LearnRequest(BaseModel):
    action: dict              # {"do": "next_song"}, {"do": "effect", "effect": 2}, ...
    when: str | None = None   # press (default), release or any (default for talk)
    seconds: float = 20.0


class BindingRequest(BaseModel):
    input: str = "*"
    message: dict             # {"type": "control_change", "channel": 0, "control": 80}, note, program_change
    action: dict
    when: str = "press"


class TunerReadRequest(BaseModel):
    seconds: float = 8.0


class ChatRequest(BaseModel):
    text: str


class TalkRequest(BaseModel):
    pressed: bool | None = None   # the app's hold-to-talk button: down (true) and up (false)
    mic: str | None = None        # laptop or phone
    input: str | None = None      # which of this computer's microphones ("" = the system default)


def create_app(make_pedal, port=DEFAULT_PORT, announce=True, history_file=None, gigs_folder=None,
               remote=None, remote_on=False, footswitches=None, chat=None, talk=None, backups_folder=None):
    """announce: write ~/.g3xn/daemon.json so g3xn-mcp finds this daemon.
    history_file: where the time machine keeps its versions (None = memory only).
    gigs_folder: where saved gigs live (None = a temporary folder).
    remote: the phone remote (a remote.Remote; default: one that forgets phones on exit);
    remote_on: start it listening on the network straight away.
    footswitches: MIDI controllers driving the pedal (a footswitch.Footswitches; default: one that
    forgets its bindings on exit).
    chat: Claude in the app (a chat.Chat; default: the user's Claude Code, on this daemon's tools).
    talk: push to talk (a voice.Talk; default: the laptop microphone, words to the chat).
    backups_folder: where whole-pedal backups are listed from, and where one is kept each time the
    pedal connects (None = no automatic backups, none listed)."""
    remote = remote or Remote()
    footswitches = footswitches or Footswitches()
    if remote.port == port:
        raise ValueError("the phone remote needs a port of its own (both are %d)" % port)
    hub = EventHub()
    backups = Backups(backups_folder) if backups_folder else None
    worker = PedalWorker(make_pedal, hub.emit, backups)
    history = History(history_file)
    gigs = GigLibrary(gigs_folder or tempfile.mkdtemp(prefix="g3xn-gigs-"))
    chat = chat or Chat("http://127.0.0.1:%d" % port, hub.emit)
    talk = talk or Talk(hub.emit, chat.send)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        hub.loop = asyncio.get_running_loop()
        worker.start()
        footswitches.start(on_footswitch, hub.emit)
        if announce:
            _write_discovery(port)
        if remote_on:
            await asyncio.to_thread(remote.start, app)
            info = remote.info()
            print("Phone remote: open %s on your phone and enter %s" % (info["url"], info["code"]))
        try:
            yield
        finally:
            if announce:
                _remove_discovery()
            await asyncio.to_thread(remote.stop)
            await asyncio.to_thread(chat.close)
            await asyncio.to_thread(footswitches.stop)
            await asyncio.to_thread(worker.stop)

    app = FastAPI(title="g3xn", version="0.1.0", lifespan=lifespan,
                  description="Control a Zoom G3n / G3Xn: patches, live tone editing, gigs and the tuner.")
    app.state.worker = worker
    loaded = [g for g in gigs.list() if g.get("loaded")]
    state = {"active_gig": max(loaded, key=lambda g: g["loaded"]["time"])["id"] if loaded else None,
             "locked_gig": None}

    async def run(label, fn, touches=()):
        return await asyncio.wrap_future(worker.submit(label, fn, touches))

    def playing(request, view, reason="", merge=False):
        """A new version of the tone being tried: tell every client and add it to the history."""
        hub.emit({"type": "live", "tone": view})
        if worker.pedal and view.get("slot") == worker.pedal.scratch:
            source = request.headers.get("x-g3xn-source", "app")
            history.record(view, source, reason, merge)
            hub.emit(dict(history.summary(), type="history"))
        return view

    def refusal(scope, path, headers, cookies):
        """None if a request may go ahead, else (status, why). On this computer's own port, only
        pages from this computer (so web pages on other sites can't drive the pedal through the
        browser); on the phone remote's port, only paired phones."""
        if _arrived_on(scope, remote.port):
            return remote.refusal(path, headers, cookies)
        return None if _local_request(headers) else (403, "g3xn only answers requests from this computer")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        refused = refusal(request.scope, request.url.path, request.headers, request.cookies)
        if refused:
            return JSONResponse({"error": refused[1]}, status_code=refused[0])
        return await call_next(request)

    @app.exception_handler(PedalError)
    async def pedal_error(request, err):
        return JSONResponse({"error": str(err)}, status_code=503 if isinstance(err, NotConnected) else 409)

    @app.exception_handler(PermissionError)
    async def refused(request, err):
        return JSONResponse({"error": str(err)}, status_code=403)

    @app.exception_handler(ValueError)
    @app.exception_handler(KeyError)
    @app.exception_handler(IndexError)
    async def bad_request(request, err):
        return JSONResponse({"error": err.args[0] if err.args else str(err)}, status_code=400)

    # --- the pedal ---

    @app.get("/api/status", tags=["pedal"])
    async def status():
        """Connection, what the pedal is doing right now, and the patch it is on."""
        return worker.snapshot()

    @app.post("/api/release", tags=["pedal"])
    async def release():
        """Let go of the pedal so another program (ToneLib, a standalone g3xn) can use it."""
        await asyncio.wrap_future(worker.release())
        return worker.snapshot()

    @app.post("/api/connect", tags=["pedal"])
    async def connect():
        """Take the pedal back after /api/release."""
        worker.connect()
        return worker.snapshot()

    @app.post("/api/backup", tags=["pedal"])
    async def backup(req: BackupRequest = BackupRequest()):
        """Copy every slot to .zptc files (default ~/g3xn-backups/<timestamp>)."""
        return await run("backing up every patch", lambda p: service.backup(p, req.folder))

    # --- patches ---

    @app.get("/api/patches", tags=["patches"])
    async def list_patches():
        """Every slot's name ("Empty" = free). Slots 1-75 are Zoom's demos."""
        if not worker.names:
            return await run("reading your patches", service.list_patches)
        return {"patches": [{"slot": n, "name": name} for n, name in sorted(worker.names.items())]}

    @app.get("/api/patches/{slot}", tags=["patches"])
    async def get_patch(slot: int):
        """A slot's chain and knobs. The slot the pedal is on is read live, with screen text."""
        return await run("reading patch %d" % slot, lambda p: service.get_patch(p, slot))

    @app.put("/api/patches/{slot}", tags=["patches"])
    async def write_patch(slot: int, req: WriteRequest):
        """Write a tone into a slot. A slot holding a patch needs replace=true."""
        refuse_if_locked([slot])
        return await run("writing patch %d" % slot, lambda p: service.write_tone(p, req.tone, slot, req.replace),
                         touches=[slot])

    @app.post("/api/patches/{slot}/select", tags=["patches"])
    async def select_patch(slot: int):
        """Switch the pedal to a slot (changes nothing)."""
        return await run("switching to patch %d" % slot, lambda p: service.select_patch(p, slot))

    @app.post("/api/patches/{slot}/save", tags=["patches"])
    async def save_to_slot(slot: int, req: SaveRequest = SaveRequest()):
        """Keep the auditioned tone: store it in `slot` and switch to it. A slot holding a patch needs replace=true."""
        refuse_if_locked([slot])
        return await run("saving to patch %d" % slot, lambda p: service.save_to_slot(p, slot, req.name, req.replace),
                         touches=lambda r: [worker.pedal.scratch, slot])

    # --- the tone playing now ---

    @app.get("/api/live", tags=["live"])
    async def live():
        """The tone playing now (unsaved tweaks included), with the screen's text for each knob."""
        return await run("reading the live tone", service.live_view)

    @app.post("/api/audition", tags=["live"])
    async def audition(req: AuditionRequest, request: Request):
        """Play a tone (or a copy of a slot) on the scratch slot. Nothing of yours is changed.
        This is also how the chain is edited: send the whole tone with effects added, removed or moved."""
        view = await run("loading a tone to audition", lambda p: service.audition(p, req.tone, req.slot),
                         touches=lambda r: [worker.pedal.scratch])
        return playing(request, view, req.reason)

    @app.post("/api/tweak", tags=["live"])
    async def tweak(req: TweakRequest, request: Request):
        """Change knobs, on/off, volume or name of the auditioned tone, live."""
        view = await run("tweaking", lambda p: service.tweak(p, req.changes, req.volume, req.name),
                         touches=[] if req.name is None else lambda r: [worker.pedal.scratch])
        return playing(request, view, req.reason, merge=True)

    @app.post("/api/play", tags=["live"])
    async def play(req: PlayRequest, request: Request):
        """Make the scratch slot sound like a tone the fastest way (live edits when the chain is
        the same). For A/B snapshots and anything else that already has the tone JSON."""
        view = await run("playing a tone", lambda p: service.play(p, req.tone),
                         touches=lambda r: [worker.pedal.scratch])
        return playing(request, view, req.reason)

    @app.post("/api/morph", tags=["live"])
    async def morph(req: MorphRequest, request: Request):
        """Glide from the tone playing now to another with the same effects, over `seconds`."""
        if not 0.2 <= req.seconds <= 30:
            raise ValueError("morph time must be 0.2 to 30 seconds")
        view = await run("morphing over %g s" % req.seconds, lambda p: service.morph(p, req.to, req.seconds),
                         touches=lambda r: [worker.pedal.scratch])
        return playing(request, view, "")

    # --- the time machine ---

    @app.get("/api/history", tags=["history"])
    async def get_history():
        """Every version of the tone being tried, oldest first; `position` is the one playing."""
        return history.summary()

    @app.get("/api/history/{entry_id}", tags=["history"])
    async def history_entry(entry_id: int):
        """One version, with its tone JSON."""
        return history.entries[history.find(entry_id)]

    @app.post("/api/history/{entry_id}/play", tags=["history"])
    async def history_play(entry_id: int):
        """Go back (or forward) to a version and hear it."""
        return await go(history.find(entry_id))

    @app.post("/api/undo", tags=["history"])
    async def undo():
        """Back to the previous version."""
        return await go(history.position - 1)

    @app.post("/api/redo", tags=["history"])
    async def redo():
        """Forward again after an undo."""
        return await go(history.position + 1)

    async def go(index):
        if not 0 <= index < len(history.entries):
            raise IndexError("nothing to go back or forward to")
        view = await run("going back to an earlier version", lambda p: service.play(p, history.entries[index]["tone"]),
                         touches=lambda r: [worker.pedal.scratch])
        history.go(index)
        hub.emit({"type": "live", "tone": view})
        hub.emit(dict(history.summary(), type="history"))
        return view

    # --- effects ---

    @app.get("/api/effects", tags=["effects"])
    async def find_effects(query: str = "", group: str = ""):
        """Search the pedal's effects by name or description."""
        return service.find_effects(query, group)

    @app.get("/api/effects/{name}", tags=["effects"])
    async def effect_details(name: str):
        """One effect's knobs: range, default, what each does, how the screen shows it."""
        return service.effect_details(name)

    # --- gigs ---

    @app.post("/api/gigs/plan", tags=["gigs"])
    async def plan_gig(gig: dict = Body(...)):
        """Where each song of a gig would go and what it would replace. Writes nothing."""
        return await run("planning a gig", lambda p: service.plan_gig(p, gig))

    @app.post("/api/gigs/load", tags=["gigs"])
    async def load_gig(gig: dict = Body(...)):
        """Back up every slot, then write the gig to the pedal."""
        refuse_if_locked()
        return await run("loading a gig", lambda p: service.load_gig(p, gig),
                         touches=lambda r: [s["slot"] for s in r["written"] if not s.get("in_place")])

    @app.get("/api/gigs/export", tags=["gigs"])
    async def export_gig(first_slot: int, last_slot: int, name: str = "Exported gig"):
        """A run of slots as a gig file."""
        return await run("reading slots %d-%d" % (first_slot, last_slot),
                         lambda p: service.export_gig(p, first_slot, last_slot, name))

    @app.get("/api/lyrics", tags=["gigs"])
    async def find_lyrics(song: str, artist: str = ""):
        """A song's words from LRCLIB, for a gig song's lyrics. {"found": false} when it has none."""
        try:
            hit = await asyncio.to_thread(lyric_search.find, song, artist or None)
        except LyricsError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        return dict(hit, found=True) if hit else {"found": False, "song": song}

    @app.post("/api/stomp", tags=["pedal"])
    async def stomp(req: StompRequest):
        """Turn one effect of the patch that's playing on or off, the way its footswitch does (with
        autosave on, the slot keeps it). It sets the state asked for; it never toggles, so asking
        twice is harmless. Like the footswitches, it still works while the app's edits are locked."""
        def go(p):
            if req.slot is not None and p.current() != req.slot:
                return {"skipped": "the pedal has moved on from slot %d" % req.slot}
            fx = _effect_in(p.edit_buffer().chain, req.effect)
            if fx.enabled != req.on:
                p.stomp(fx.position, req.on)
            view = service.live_view(p)
            hub.emit({"type": "live", "tone": view})
            return view
        return await run("turning %s %s" % (req.effect, "on" if req.on else "off"), go)

    # --- backups ---

    @app.get("/api/backups", tags=["backups"])
    async def list_backups():
        """Every whole-pedal backup, newest first, each with what changed since the one before."""
        return {"backups": await asyncio.to_thread(backups.history) if backups else [], "folder": backups and backups.root}

    @app.post("/api/backups/restore", tags=["backups"])
    async def restore_from_backup(req: RestoreRequest):
        """Put one slot back the way a backup has it. What the slot holds now is saved first
        (in <backups>/replaced/<time>/)."""
        if not backups:
            raise PedalError("this daemon keeps no backups")
        refuse_if_locked([req.slot])
        data = backups.slot(req.backup, req.slot)

        def put_back(p):
            now = p.read_raw(req.slot)
            folder = os.path.join(backups.root, "replaced", time.strftime("%Y-%m-%d_%H%M%S"))
            write_backup(folder, {req.slot: now})
            here = p.current()
            if here == req.slot:
                p.select(p.scratch)       # a write to the slot the pedal is on is lost
            p.write(req.slot, data)
            if here == req.slot:
                p.select(here)
            return {"slot": req.slot, "patch": Patch.decode(data).name, "saved_current": folder}

        return await run("putting slot %d back" % req.slot, put_back, touches=[req.slot])

    # --- saved gigs (the app's setlists) ---

    @app.get("/api/setlists", tags=["gigs"])
    async def list_setlists():
        """Saved gigs, by name. `active` is the one last loaded to the pedal (the stage view follows it);
        `locked` is the one locked for the show, if any."""
        return {k: v for k, v in gigs_event().items() if k != "type"}

    @app.get("/api/setlists/{gig_id}", tags=["gigs"])
    async def get_setlist(gig_id: str):
        return shown_gig(_gig_or_404(gig_id))

    @app.put("/api/setlists/{gig_id}", tags=["gigs"])
    async def save_setlist(gig_id: str, gig: dict = Body(...)):
        """Save a gig. Use the id "new" to create one. What was loaded to the pedal is kept as it was."""
        gig = dict({k: v for k, v in gig.items() if k != "loaded"}, id=None if gig_id == "new" else gig_id)
        if gig["id"]:
            try:
                gig["loaded"] = gigs.get(gig_id).get("loaded")
            except OSError:
                pass
        saved = gigs.save(gig)
        hub.emit(gigs_event())
        return shown_gig(saved)

    @app.delete("/api/setlists/{gig_id}", tags=["gigs"])
    async def delete_setlist(gig_id: str):
        _gig_or_404(gig_id)
        gigs.delete(gig_id)
        for key in ("active_gig", "locked_gig"):
            if state.get(key) == gig_id:
                state[key] = None
        hub.emit(gigs_event())
        return {"deleted": gig_id}

    @app.post("/api/setlists/{gig_id}/plan", tags=["gigs"])
    async def plan_setlist(gig_id: str):
        """Where each song would go and what it would replace. Writes nothing."""
        gig = _gig_or_404(gig_id)
        return await run("planning %s" % gig.get("name", "the gig"), lambda p: service.plan_gig(p, gig))

    @app.post("/api/setlists/{gig_id}/load", tags=["gigs"])
    async def load_setlist(gig_id: str):
        """Back up every slot, write the gig, and make it the one the stage view follows."""
        refuse_if_locked()
        gig = _gig_or_404(gig_id)
        result = await run("loading %s" % gig.get("name", "the gig"), lambda p: service.load_saved_gig(p, gigs, gig_id),
                           touches=lambda r: [s["slot"] for s in r["written"] if not s.get("in_place")])
        state["active_gig"] = gig_id
        hub.emit(gigs_event())
        return result

    @app.post("/api/setlists/{gig_id}/batch", tags=["gigs"])
    async def batch_setlist(gig_id: str, req: BatchRequest):
        """One change to every song: "every reverb down 10%", "a venue EQ on every song". The forms:
        {"change": "knob", "effects": "reverb", "knob": "Mix", "percent": -10} (or "by"/"to"),
        {"change": "volume", "by": 5}, {"change": "on"|"off", "effects": "delay"},
        {"change": "add", "effect": "Gt GEQ", "at": 1}, {"change": "remove", "effects": "Comp"}.
        save=false previews it (what each song would get, and why any are left alone); save=true
        keeps it in the gig. The pedal isn't written: load the gig again for that."""
        gig = _gig_or_404(gig_id)
        result = await run("editing %s" % gig.get("name", "the gig"),
                           lambda p: service.edit_gig(p, gigs, gig_id, req.edit, req.save))
        if result["saved"]:
            hub.emit(gigs_event())
        return result

    @app.post("/api/setlists/{gig_id}/check", tags=["gigs"])
    async def check_setlist(gig_id: str):
        """Which songs changed on the pedal since the gig was loaded (a knob turned on the pedal
        autosaves into the slot). Each has "change", e.g. "Hall Mix 40 → 55". Writes nothing."""
        gig = _gig_or_404(gig_id)
        loaded = loaded_slots(gig)
        return await run("checking %s" % gig.get("name", "the gig"), lambda p: service.check_gig(p, loaded))

    @app.post("/api/setlists/{gig_id}/restore", tags=["gigs"])
    async def restore_setlist(gig_id: str):
        """The panic button: put back every song that changed since the gig was loaded (the changed
        versions are backed up first). Works while the gig is locked; the pedal stays on its patch."""
        gig = _gig_or_404(gig_id)
        loaded = loaded_slots(gig)
        return await run("putting %s back" % gig.get("name", "the gig"), lambda p: service.restore_gig(p, loaded),
                         touches=lambda r: [s["slot"] for s in r["restored"]])

    @app.post("/api/setlists/{gig_id}/lock", tags=["gigs"])
    async def lock_setlist(gig_id: str, req: LockRequest = LockRequest()):
        """Lock a loaded gig for the show (on=false unlocks). While it's locked nothing going through
        the daemon (the app, Claude, the CLI) can write to its slots or load a gig; switching
        patches, auditions on the scratch slot and the tuner still work. It can't stop the pedal's
        own autosave when a knob is turned on the pedal: /restore puts that back. Unlocks when the
        daemon restarts."""
        gig = _gig_or_404(gig_id)
        if req.on:
            loaded_slots(gig)
            state["locked_gig"] = gig_id
        elif state["locked_gig"] == gig_id:
            state["locked_gig"] = None
        hub.emit(gigs_event())
        return {"locked": state["locked_gig"]}

    def gigs_event():
        return {"type": "gigs", "gigs": gigs.list(), "active": state["active_gig"], "locked": state["locked_gig"]}

    def refuse_if_locked(slots=None):
        """While a gig is locked, refuse writes to its slots (slots=None: refuse any gig load)."""
        if not state["locked_gig"]:
            return
        gig = gigs.get(state["locked_gig"])
        name = gig.get("name", "the gig")
        if slots is None:
            raise PedalError("%s is locked for the show. Unlock it before loading a gig." % name)
        for s in gig["loaded"]["slots"]:
            if s["slot"] in slots:
                raise PedalError("slot %d holds %s (%s) in %s, which is locked for the show. Unlock the gig "
                                 "first, or pick another slot." % (s["slot"], s["patch"], s["song"], name))

    def loaded_slots(gig):
        if not gig.get("loaded"):
            raise ValueError("%s hasn't been loaded to the pedal yet" % gig.get("name", "that gig"))
        return gig["loaded"]["slots"]

    def _gig_or_404(gig_id):
        try:
            return gigs.get(gig_id)
        except OSError:
            raise KeyError("no saved gig %r" % gig_id)

    # --- the phone remote ---

    @app.get("/api/remote", tags=["remote"])
    async def remote_info():
        """The phone remote: whether it's on, the address to open on the phone, the pairing code
        that's open (if any) and the paired phones. Only answered on this computer."""
        return remote.info()

    @app.post("/api/remote", tags=["remote"])
    async def remote_switch(req: RemoteRequest = RemoteRequest()):
        """Turn the phone remote on (listen on the network, with a fresh pairing code) or off."""
        if req.on:
            await asyncio.to_thread(remote.start, app)
        else:
            await asyncio.to_thread(remote.stop)
        hub.emit(remote_event())
        return remote.info()

    @app.post("/api/remote/code", tags=["remote"])
    async def remote_code():
        """A new six-digit pairing code (good for five minutes or five wrong tries)."""
        remote.new_code()
        return remote.info()

    @app.delete("/api/remote/devices/{device_id}", tags=["remote"])
    async def remote_forget(device_id: str):
        """Forget a paired phone: its cookie stops working."""
        remote.forget(device_id)
        hub.emit(remote_event())
        return remote.info()

    @app.post("/api/pair", tags=["remote"])
    async def pair(req: PairRequest, response: Response):
        """A phone on the network pairs with the code shown on the computer, and gets a cookie
        that works until it's forgotten."""
        token, device = remote.pair(req.code, req.name)
        response.set_cookie(COOKIE, token, max_age=400 * 86400, httponly=True, samesite="lax", path="/")
        hub.emit(remote_event())
        return {"paired": device}

    def remote_event():
        return dict(remote.info(with_code=False), type="remote")      # phones get events too: no code

    # --- MIDI footswitches ---

    @app.get("/api/midi", tags=["footswitches"])
    async def midi_info():
        """MIDI controllers on this computer (not the G3Xn), the ones listened to, the bindings,
        and the last few messages that came in (to see what a switch sends)."""
        return footswitches.info()

    @app.put("/api/midi/inputs", tags=["footswitches"])
    async def midi_inputs(req: MidiInputsRequest):
        """Listen to these MIDI inputs (names from /api/midi "available"). Kept for next time;
        a controller that's unplugged is picked up again when it's plugged back in."""
        await asyncio.to_thread(footswitches.choose_inputs, req.inputs)
        return footswitches.info()

    @app.post("/api/midi/learn", tags=["footswitches"])
    async def midi_learn(req: LearnRequest):
        """Bind the next switch pressed to an action. Waits up to `seconds` for the press.
        Actions: next_song, previous_song, patch_up, patch_down, select (slot), tuner,
        effect (effect: chain number, on/off), talk (press and release go to the app)."""
        if not 1 <= req.seconds <= 60:
            raise ValueError("wait 1 to 60 seconds")
        return await asyncio.to_thread(footswitches.learn, req.action, req.when, req.seconds)

    @app.post("/api/midi/bindings", tags=["footswitches"])
    async def midi_bind(req: BindingRequest):
        """Bind a MIDI message to an action without pressing anything."""
        return footswitches.add(req.input, req.message, req.action, req.when)

    @app.delete("/api/midi/bindings/{binding_id}", tags=["footswitches"])
    async def midi_unbind(binding_id: str):
        footswitches.remove(binding_id)
        return footswitches.info()

    def on_footswitch(binding, pressed):
        """A bound switch was pressed (on the MIDI driver's thread): tell the app, and do it."""
        action = binding["action"]
        hub.emit({"type": "footswitch", "action": action, "pressed": pressed})
        if action["do"] == "talk":
            talk.press() if pressed else talk.release()
            return
        job = worker.submit(action["do"].replace("_", " "), lambda p: footswitch_job(p, action))
        job.add_done_callback(footswitch_done)

    def footswitch_job(p, action):
        do = action["do"]
        if do == "tuner":
            worker.tuner_on = not worker.tuner_on
            p.tuner(worker.tuner_on)
            return {}
        if do == "effect":
            chain = p.edit_buffer().chain
            if not 1 <= action["effect"] <= len(chain):
                raise ValueError("this patch has %d effects; there's no effect %d" % (len(chain), action["effect"]))
            fx = chain[action["effect"] - 1]
            p.stomp(fx.position, not fx.enabled)
            return {"live": service.live_view(p)}
        here = p.current()
        if do == "select":
            target = action["slot"]
        elif do in ("next_song", "previous_song") and gig_slots():
            songs = gig_slots()
            step = 1 if do == "next_song" else -1
            target = songs[min(len(songs) - 1, max(0, songs.index(here) + step))] if here in songs else songs[0]
        else:
            target = next_slot(p, here, 1 if do in ("next_song", "patch_up") else -1)
        if target != here:
            service.select_patch(p, target)
        return {}

    # --- Claude, and push to talk ---

    @app.get("/api/chat", tags=["claude"])
    async def chat_info():
        """The conversation with Claude so far, and whether it's answering now."""
        return chat.info()

    @app.post("/api/chat", tags=["claude"])
    async def chat_send(req: ChatRequest):
        """Say something to Claude. The answer arrives as `chat` events on /api/events."""
        try:
            await asyncio.to_thread(chat.send, req.text)
        except ChatError as err:
            raise ValueError(str(err)) from err
        return {"sent": req.text}

    @app.post("/api/chat/stop", tags=["claude"])
    async def chat_stop():
        await asyncio.to_thread(chat.stop)
        return chat.info()

    @app.post("/api/chat/new", tags=["claude"])
    async def chat_new():
        await asyncio.to_thread(chat.new)
        return chat.info()

    @app.post("/api/chat/terminal", tags=["claude"])
    async def chat_terminal(request: Request):
        """Carry on this conversation in a Claude Code terminal on this computer."""
        if _arrived_on(request.scope, remote.port):
            raise PermissionError("open Claude Code from the computer")
        try:
            return await asyncio.to_thread(chat.open_terminal)
        except ChatError as err:
            raise ValueError(str(err)) from err

    @app.get("/api/talk", tags=["claude"])
    async def talk_info():
        """Push to talk: which microphone, and what it's doing."""
        return talk.info()

    @app.post("/api/talk", tags=["claude"])
    async def talk_switch(req: TalkRequest):
        """Pick the microphone (`mic`: laptop or phone; `input`: which of this computer's), or press
        and release the app's talk button (`pressed`)."""
        if req.mic is not None:
            talk.set_mic(req.mic)
        if req.input is not None:
            talk.set_input(req.input or None)
        if req.mic is not None or req.input is not None:
            hub.emit(dict(talk.info(), type="talk"))
        if req.pressed is not None:
            await asyncio.to_thread(talk.press if req.pressed else talk.release)
        return talk.info()

    @app.post("/api/talk/audio", tags=["claude"])
    async def talk_audio(request: Request):
        """A recording (webm, ogg, wav...) from the phone or the app: turned into words, then sent
        to Claude. Returns the words."""
        data = await request.body()
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("that recording is too long")
        return {"text": await asyncio.to_thread(talk.audio, data)}

    def footswitch_done(job):
        if job.exception():
            hub.emit({"type": "footswitch", "error": str(job.exception())})
        elif job.result().get("live"):
            hub.emit({"type": "live", "tone": job.result()["live"]})

    def gig_slots():
        """The slots of the gig on the pedal, in order ([] if none)."""
        try:
            return [s["slot"] for s in gigs.get(state["active_gig"])["loaded"]["slots"]] if state["active_gig"] else []
        except (OSError, KeyError, TypeError):
            return []

    def next_slot(p, slot, step):
        """The slot before or after, round the end, past the scratch slot."""
        while True:
            slot = (slot - 1 + step) % p.patch_count + 1
            if slot != p.scratch:
                return slot

    # --- tuner ---

    @app.post("/api/tuner", tags=["tuner"])
    async def tuner(req: TunerRequest):
        """Turn the tuner on or off. Readings arrive as "tuner" events on /api/events."""
        def go(p):
            p.tuner(req.on)
            worker.tuner_on = req.on
            return {"tuner": req.on}
        return await run("tuner on" if req.on else "tuner off", go)

    @app.post("/api/tuner/read", tags=["tuner"])
    async def tuner_read(req: TunerReadRequest = TunerReadRequest()):
        """Run the tuner for a few seconds and report the note and how far off it was."""
        return await run("tuning", lambda p: service.tuner(p, req.seconds))

    # --- live events ---

    @app.websocket("/api/events")
    async def events(ws: WebSocket):
        if refusal(ws.scope, "/api/events", ws.headers, ws.cookies):
            await ws.close(code=1008)
            return
        await ws.accept()
        q = asyncio.Queue(maxsize=500)
        hub.clients.add(q)

        async def send_events():
            await ws.send_json(worker.snapshot())
            if worker.names:
                await ws.send_json({"type": "patches", "patches": [{"slot": n, "name": name}
                                                                   for n, name in sorted(worker.names.items())]})
            await ws.send_json(dict(history.summary(), type="history"))
            await ws.send_json(gigs_event())
            while True:
                await ws.send_json(await q.get())

        sender = asyncio.create_task(send_events())
        try:
            while True:
                await ws.receive_text()        # nothing to read yet; this notices the client leaving
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            hub.clients.discard(q)

    if os.path.isdir(UI_DIR):
        app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")

    return app


def start_in_thread(make_pedal, port=DEFAULT_PORT, announce=True, history_file=None, gigs_folder=None,
                    remote=None, footswitches=None, chat=None, talk=None, backups_folder=None):
    """Run the daemon on a background thread (for the desktop window and tests).
    Returns (url, stop) once it is serving."""
    app = create_app(make_pedal, port, announce, history_file, gigs_folder, remote, footswitches=footswitches,
                     chat=chat, talk=talk, backups_folder=backups_folder)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="g3xn-daemon", daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("the g3xn daemon could not start (is port %d in use?)" % port)
        time.sleep(0.02)

    def stop():
        server.should_exit = True
        thread.join(timeout=10)
    return "http://127.0.0.1:%d" % port, stop


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _arrived_on(scope, port):
    """Did this request come in on `port` (rather than look like it, from its headers)?"""
    server = scope.get("server")
    return bool(server) and server[1] == port


def _local_request(headers):
    """Sent to 127.0.0.1/localhost by a page on this computer (or by a non-browser client)."""
    local = ("127.0.0.1", "localhost")
    host = (headers.get("host") or "").rsplit(":", 1)[0]
    origin = headers.get("origin")
    return host in local and (not origin or origin.split("://", 1)[-1].rsplit(":", 1)[0] in local)


def _write_discovery(port):
    os.makedirs(os.path.dirname(DISCOVERY_FILE), exist_ok=True)
    with open(DISCOVERY_FILE, "w") as f:
        json.dump({"url": "http://127.0.0.1:%d" % port, "pid": os.getpid()}, f)


def _remove_discovery():
    with contextlib.suppress(OSError):
        os.remove(DISCOVERY_FILE)


def add_pedal_options(ap):
    ap.add_argument("--scratch", type=int, default=150, help="slot used for auditions (default 150)")
    ap.add_argument("--sim", nargs="?", const="", metavar="BACKUP",
                    help="use a virtual pedal, loaded from a backup folder (default data/pedal_dump if present)")


def _effect_in(chain, which):
    """The effect in `chain` that `which` names: a number (1 = first) or a name ("octave" finds OctFuzz
    if nothing is called just that)."""
    if isinstance(which, int) or str(which).strip().isdigit():
        n = int(which)
        if not 1 <= n <= len(chain):
            raise ValueError("this patch has %d effects; there's no effect %d" % (len(chain), n))
        return chain[n - 1]
    want = str(which).strip().lower()
    for match in (lambda name: name == want, lambda name: name.startswith(want), lambda name: want in name):
        found = [fx for fx in chain if match(fx.name.lower())]
        if found:
            return found[0]
    raise ValueError("this patch has no %s (it has %s)" % (which, ", ".join(fx.name for fx in chain)))


def pedal_factory(args):
    """() -> Pedal for the options from add_pedal_options: the real pedal, or a virtual one."""
    if args.sim is None:
        return lambda: Pedal(scratch=args.scratch)
    from .sim import VirtualPedal
    folder = args.sim or os.path.join(REPO, "data", "pedal_dump")
    device = VirtualPedal.from_backup(folder) if os.path.isdir(folder) else VirtualPedal()
    return lambda: Pedal(scratch=args.scratch, device=device)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="g3xn-daemon", description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--remote", action="store_true", help="start the phone remote (listen on the local network)")
    ap.add_argument("--remote-port", type=int, default=REMOTE_PORT, help="the phone remote's port (default %d)" % REMOTE_PORT)
    add_pedal_options(ap)
    args = ap.parse_args(argv)

    real = args.sim is None
    app = create_app(pedal_factory(args), args.port, announce=real, history_file=HISTORY_FILE if real else None,
                     gigs_folder=GIGS_FOLDER if real else None, backups_folder=service.BACKUP_ROOT if real else None,
                     remote=Remote(REMOTE_FILE if real else None, port=args.remote_port, use_tailscale=real), remote_on=args.remote,
                     footswitches=Footswitches(MIDI_FILE if real else None))
    print("g3xn daemon on http://127.0.0.1:%d (API docs at /docs)%s" % (args.port, "" if os.path.isdir(UI_DIR) else
          "; build the app with: cd app && npm install && npm run build"))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
