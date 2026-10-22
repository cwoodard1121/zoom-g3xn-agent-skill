"""MIDI footswitches: any MIDI controller (a USB foot controller, a keyboard, a pad)
drives the pedal through the daemon.

A binding ties one MIDI message to an action:

    {"id": "a1b2c3", "input": "FS-1 MIDI",        # or "*" for any input
     "message": {"type": "control_change", "channel": 0, "control": 80},
     "when": "press",                            # "release", or "any" (both: latching switches)
     "action": {"do": "next_song"}}

Messages: control_change (pressed = value 64 and up), note (note on is a press, note
off a release) and program_change (always a press).

Actions:
    next_song / previous_song   step through the gig on the pedal (or the next/previous slot)
    patch_up / patch_down       the next/previous slot
    select {"slot": n}          a slot
    tuner                       tuner on/off
    effect {"effect": n}        effect n of the patch playing now on/off; like the pedal's own
                                switches, autosave keeps it in the slot
    talk                        nothing on the pedal: the app hears press and release (push to talk)

Learning: say which action you want and press the switch; the first press that arrives
becomes its binding.
"""
import collections
import concurrent.futures
import json
import os
import threading
import time
import uuid

import mido

from .protocol import PORT_PREFIX

ACTIONS = ("next_song", "previous_song", "patch_up", "patch_down", "select", "tuner", "effect", "talk")
WHEN = ("press", "release", "any")
RESCAN_SECONDS = 2.0        # how often unplugged/plugged-in controllers are noticed


class Footswitches:
    def __init__(self, config_file=None, list_inputs=None, open_input=None):
        """config_file: where inputs and bindings are kept (None = until the daemon stops).
        list_inputs/open_input: mido's, unless a test supplies its own."""
        self.config_file = config_file
        self.config = self._load()
        self._list_inputs = list_inputs or mido.get_input_names
        self._open_input = open_input or mido.open_input
        self.ports = {}
        self.recent = collections.deque(maxlen=20)
        self._learning = None
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._thread = None
        self._act = self._emit = None

    # --- running ---

    def start(self, act, emit):
        """act(binding, pressed) carries out a binding's action; emit(event) tells the app."""
        self._act, self._emit = act, emit
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="g3xn-footswitches", daemon=True)
        self._thread.start()

    def stop(self):
        self._stopping.set()
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            for port in self.ports.values():
                port.close()
            self.ports.clear()

    def _run(self):
        while not self._stopping.is_set():
            self.sync()
            self._stopping.wait(RESCAN_SECONDS)

    def sync(self):
        """Open the chosen inputs that are plugged in; close the rest."""
        with self._lock:
            wanted = set(self.config["inputs"])
            try:
                present = set(self.available())
            except Exception:                    # a MIDI driver hiccup: try again next time
                return
            for name in list(self.ports):
                if name not in wanted or name not in present:
                    self.ports.pop(name).close()
            for name in sorted(wanted & present - set(self.ports)):
                try:
                    self.ports[name] = self._open_input(name, callback=lambda m, n=name: self.receive(n, m))
                except Exception as err:         # in use by another program, or just unplugged
                    self._tell({"type": "footswitch", "error": "can't open %s: %s" % (name, err)})

    def available(self):
        """MIDI inputs on this computer, except the G3Xn itself."""
        return [n for n in self._list_inputs() if not n.startswith(PORT_PREFIX)]

    # --- MIDI in (on the MIDI driver's thread) ---

    def receive(self, port, msg):
        key, pressed = message_key(msg)
        if key is None:
            return
        self.recent.append({"input": port, "message": key, "pressed": pressed, "time": time.time()})
        learning = self._learning
        if learning and pressed and not learning[2].done():
            learning[2].set_result(self._bind(port, key, learning[0], learning[1]))
            return
        for b in list(self.config["bindings"]):
            if b["message"] == key and b["input"] in ("*", port) and _fires(b["when"], pressed) and self._act:
                self._act(b, pressed)

    # --- bindings ---

    def learn(self, action, when=None, timeout=20.0):
        """Wait for a press and bind it to `action`. Returns the binding."""
        action = check_action(action)
        if not self.ports:
            raise ValueError("no MIDI controller is being listened to; choose one first")
        when = check_when(when or ("any" if action["do"] == "talk" else "press"))
        future = concurrent.futures.Future()
        self._learning = (action, when, future)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            raise ValueError("nothing was pressed in %d seconds" % timeout)
        finally:
            self._learning = None

    def add(self, input_name, message, action, when="press"):
        """A binding made by hand (without pressing anything)."""
        key, _ = message_key(message if isinstance(message, mido.Message) else _message(message))
        if key is None:
            raise ValueError("bind a control_change, note or program_change")
        return self._bind(input_name or "*", key, check_action(action), check_when(when))

    def remove(self, binding_id):
        with self._lock:
            kept = [b for b in self.config["bindings"] if b["id"] != binding_id]
            if len(kept) == len(self.config["bindings"]):
                raise KeyError("no binding %r" % binding_id)
            self.config["bindings"] = kept
            self._save()

    def choose_inputs(self, names):
        """Listen to these inputs (names from available())."""
        with self._lock:
            self.config["inputs"] = sorted(set(names))
            self._save()
        self.sync()

    def info(self):
        with self._lock:
            listening = sorted(self.ports)
        try:
            available = self.available()
        except Exception:
            available = []
        return {"available": available, "inputs": self.config["inputs"], "listening": listening,
                "bindings": self.config["bindings"], "recent": list(self.recent)}

    def _bind(self, port, key, action, when):
        """Add a binding; a press of the same switch that did something else now does this."""
        binding = {"id": uuid.uuid4().hex[:6], "input": port, "message": key, "when": when, "action": action}
        with self._lock:
            self.config["bindings"] = [b for b in self.config["bindings"]
                                       if not (b["message"] == key and b["input"] == port and b["when"] == when)]
            self.config["bindings"].append(binding)
            self._save()
        self._tell({"type": "footswitch", "learned": binding})
        return binding

    def _tell(self, event):
        if self._emit:
            self._emit(event)

    # --- storage ---

    def _load(self):
        try:
            with open(self.config_file, encoding="utf-8") as f:
                config = json.load(f)
            return {"inputs": list(config.get("inputs", [])), "bindings": list(config.get("bindings", []))}
        except (TypeError, OSError, ValueError):
            return {"inputs": [], "bindings": []}

    def _save(self):
        if not self.config_file:
            return
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        tmp = self.config_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=1)
        os.replace(tmp, self.config_file)


def message_key(msg):
    """(what a binding matches, pressed) for a MIDI message; (None, None) for anything else."""
    if msg.type == "control_change":
        return {"type": "control_change", "channel": msg.channel, "control": msg.control}, msg.value >= 64
    if msg.type in ("note_on", "note_off"):
        return {"type": "note", "channel": msg.channel, "note": msg.note}, msg.type == "note_on" and msg.velocity > 0
    if msg.type == "program_change":
        return {"type": "program_change", "channel": msg.channel, "program": msg.program}, True
    return None, None


def check_action(action):
    if not isinstance(action, dict) or action.get("do") not in ACTIONS:
        raise ValueError("action must be {\"do\": one of %s}" % ", ".join(ACTIONS))
    for needs in {"select": "slot", "effect": "effect"}.get(action["do"], "").split():
        if not isinstance(action.get(needs), int):
            raise ValueError("%s needs a number: {\"do\": %r, %r: n}" % (action["do"], action["do"], needs))
    return action


def check_when(when):
    if when not in WHEN:
        raise ValueError("when must be one of %s" % ", ".join(WHEN))
    return when


def _fires(when, pressed):
    return when == "any" or (when == "press") == pressed


def _message(spec):
    """A mido message from a binding's message spec (for bindings made by hand)."""
    kind = spec.get("type")
    channel = spec.get("channel", 0)
    if kind == "control_change":
        return mido.Message("control_change", channel=channel, control=spec["control"], value=127)
    if kind == "note":
        return mido.Message("note_on", channel=channel, note=spec["note"], velocity=100)
    if kind == "program_change":
        return mido.Message("program_change", channel=channel, program=spec["program"])
    raise ValueError("message type must be control_change, note or program_change")
