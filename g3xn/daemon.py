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
import threading
import time

import uvicorn
from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service
from .history import History
from .pedal import Pedal, PedalError

DEFAULT_PORT = 8370
DISCOVERY_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "daemon.json")
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "history.json")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(REPO, "app", "dist")          # the built web UI (npm run build in app/)
RETRY_SECONDS = 2.0
WATCH_SECONDS = 1.0


class NotConnected(PedalError):
    pass


# --- the worker thread that owns the pedal ---

class PedalWorker(threading.Thread):
    """Runs pedal actions one at a time and watches the pedal in between."""

    def __init__(self, make_pedal, emit):
        super().__init__(name="pedal", daemon=True)
        self.make_pedal = make_pedal      # () -> Pedal (not yet open)
        self.emit = emit                  # (event dict) -> None, thread-safe
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
            self.info = pedal.identity()
            self._status()
            self._read_names()
            self._poll_current()
        except PedalError as err:
            self.problem = str(err)
            self._close("disconnected")

    def _read_names(self):
        count = self.pedal.patch_count
        for n in range(1, count + 1):
            if n % 15 == 1:
                self._busy("reading your patches %d/%d" % (n, count))
            self.names[n] = self.pedal.read(n).name
        self._busy(None)
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


class TunerReadRequest(BaseModel):
    seconds: float = 8.0


def create_app(make_pedal, port=DEFAULT_PORT, announce=True, history_file=None):
    """announce: write ~/.g3xn/daemon.json so g3xn-mcp finds this daemon.
    history_file: where the time machine keeps its versions (None = memory only)."""
    hub = EventHub()
    worker = PedalWorker(make_pedal, hub.emit)
    history = History(history_file)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        hub.loop = asyncio.get_running_loop()
        worker.start()
        if announce:
            _write_discovery(port)
        try:
            yield
        finally:
            if announce:
                _remove_discovery()
            await asyncio.to_thread(worker.stop)

    app = FastAPI(title="g3xn", version="0.1.0", lifespan=lifespan,
                  description="Control a Zoom G3n / G3Xn: patches, live tone editing, gigs and the tuner.")
    app.state.worker = worker

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

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Blocks web pages on other sites from driving the pedal through the browser.
        if not _local_request(request.headers):
            return JSONResponse({"error": "g3xn only answers requests from this computer"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(PedalError)
    async def pedal_error(request, err):
        return JSONResponse({"error": str(err)}, status_code=503 if isinstance(err, NotConnected) else 409)

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
        return await run("writing patch %d" % slot, lambda p: service.write_tone(p, req.tone, slot, req.replace),
                         touches=[slot])

    @app.post("/api/patches/{slot}/select", tags=["patches"])
    async def select_patch(slot: int):
        """Switch the pedal to a slot (changes nothing)."""
        return await run("switching to patch %d" % slot, lambda p: service.select_patch(p, slot))

    @app.post("/api/patches/{slot}/save", tags=["patches"])
    async def save_to_slot(slot: int, req: SaveRequest = SaveRequest()):
        """Keep the auditioned tone: store it in `slot` and switch to it. A slot holding a patch needs replace=true."""
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
        return await run("loading a gig", lambda p: service.load_gig(p, gig),
                         touches=lambda r: [s["slot"] for s in r["written"]])

    @app.get("/api/gigs/export", tags=["gigs"])
    async def export_gig(first_slot: int, last_slot: int, name: str = "Exported gig"):
        """A run of slots as a gig file."""
        return await run("reading slots %d-%d" % (first_slot, last_slot),
                         lambda p: service.export_gig(p, first_slot, last_slot, name))

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
        if not _local_request(ws.headers):
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


def start_in_thread(make_pedal, port=DEFAULT_PORT, announce=True, history_file=None):
    """Run the daemon on a background thread (for the desktop window and tests).
    Returns (url, stop) once it is serving."""
    server = uvicorn.Server(uvicorn.Config(create_app(make_pedal, port, announce, history_file), host="127.0.0.1",
                                           port=port, log_level="warning"))
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
    add_pedal_options(ap)
    args = ap.parse_args(argv)

    app = create_app(pedal_factory(args), args.port, announce=args.sim is None,
                     history_file=None if args.sim is not None else HISTORY_FILE)
    print("g3xn daemon on http://127.0.0.1:%d (API docs at /docs)%s" % (args.port, "" if os.path.isdir(UI_DIR) else
          "; build the app with: cd app && npm install && npm run build"))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
