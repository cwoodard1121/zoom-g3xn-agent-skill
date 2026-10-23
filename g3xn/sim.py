"""A G3Xn in software: answers the same MIDI messages as the real pedal.

    from g3xn import Pedal
    from g3xn.sim import VirtualPedal

    with Pedal(device=VirtualPedal()) as pedal:     # no hardware needed
        pedal.audition(tone)

The real `Pedal` class runs unchanged on top of it, so the app, the daemon
and the tests exercise the same code that talks to the hardware. Behaviour
follows what was observed on a G3Xn (firmware 2.20): autosave writes live
edits into the selected slot, a stored write to the selected slot is lost
to the edit buffer, settings edits are confirmed with a 64 03 01 echo.

What it doesn't do: the effect file system (lists no files), sound, and
knob turns made on the pedal itself (call `turn_knob` to fake one).
"""
import collections
import glob
import math
import os
import tempfile
import time

import mido

from . import protocol as P
from .catalog import catalog
from .patch import Patch, Slot

PATCH_COUNT = 150
PATCH_SIZE = 736
BANK_SIZE = 3
FIRMWARE = "2.20"


class VirtualPedal:
    def __init__(self, patches=None, current=1):
        """patches: {slot number: Patch or raw bytes}; missing slots are Empty."""
        empty = Patch.blank("Empty").encode()
        self.slots = {n: empty for n in range(1, PATCH_COUNT + 1)}
        for n, p in (patches or {}).items():
            self.slots[n] = p.encode() if isinstance(p, Patch) else bytes(p)
        home = tempfile.mkdtemp(prefix="g3xn-sim-")
        self.state_file = os.path.join(home, "state.json")
        self.backup_root = os.path.join(home, "backups")      # never mixed with real backups
        self.autosave = True
        self.tempo = 120
        self.tuner_on = False
        self.tuner_note = "E"          # what the fake string is playing
        self._bank = 0
        self._outbox = collections.deque()
        self._select(current)

    @classmethod
    def from_backup(cls, folder):
        """A virtual pedal loaded from a `g3xn backup` folder (NNN_NAME.zptc files)."""
        patches = {}
        for path in glob.glob(os.path.join(folder, "*.zptc")):
            prefix = os.path.basename(path).split("_", 1)[0]
            if prefix.isdigit():
                with open(path, "rb") as f:
                    patches[int(prefix)] = f.read()
        return cls(patches)

    def connect(self):
        """(input port, output port) for `Pedal`, like opening the USB-MIDI ports."""
        return _InPort(self), _OutPort(self)

    # --- things a player does on the pedal itself ---

    def turn_knob(self, position, knob, value):
        """Fake a knob turned on the pedal: changes the sound and reports it like the pedal does."""
        self._apply_edit(position, P.PARAM_FIRST_KNOB + knob, value)
        self._reply(P.msg(P.EDIT, P.EDIT_PARAM, 1, position, P.PARAM_FIRST_KNOB + knob, P.u35(value)))

    def stomp(self, location):
        """Fake a footswitch patch change."""
        self._select(location)
        bank, index = P.location_to_bank(location, BANK_SIZE)
        self._outbox.extend([mido.Message("control_change", control=0, value=0),
                             mido.Message("control_change", control=32, value=bank),
                             mido.Message("program_change", program=index)])

    # --- MIDI in ---

    def receive(self, m):
        if m.type == "control_change" and m.control == 32:
            self._bank = m.value
        elif m.type == "program_change":
            self._select(self._bank * BANK_SIZE + m.program + 1)
        elif m.type == "sysex":
            self._sysex(list(m.data))

    def _sysex(self, d):
        if d[:4] == [0x7E, 0x00, 0x06, 0x01]:
            return self._reply([0x7E, 0x00, 0x06, 0x02, 0x52, P.DEVICE_ID, 0x00, 0x1F, 0x00, 0x00, 0x00]
                               + list(FIRMWARE.encode()))
        if d[:3] != list(P.ZOOM):
            return
        cmd, body = d[3], d[4:]
        if cmd == P.PATCH_INFO:
            self._reply(P.msg(0x43, P.u14(PATCH_COUNT), P.u14(PATCH_SIZE), 0, 0, P.u14(BANK_SIZE)))
        elif cmd == P.CURRENT_PROGRAM:
            bank, index = P.location_to_bank(self.current, BANK_SIZE)
            self._outbox.extend([mido.Message("control_change", control=0, value=0),
                                 mido.Message("control_change", control=32, value=bank),
                                 mido.Message("program_change", program=index)])
        elif cmd == P.PATCH_READ:
            location = self._location(body)
            data = self.slots[location]
            self._reply(P.msg(0x47, body[:6], P.u14(len(data)), P.pack7(data), P.checksum(data)))
        elif cmd == P.PATCH_WRITE:
            location, n = self._location(body), body[6] | body[7] << 7
            data = P.unpack7(bytes(body[8:-5]))[:n]
            if P.verify_checksum(data, body[-5:]):
                self.slots[location] = data
            self._reply(P.msg(0x00, 0x00))
        elif cmd == P.EDIT:
            self._edit(body)
        elif cmd == 0x60:
            self._reply(P.msg(0x60, [0] * 12))      # file system: empty, no files

    def _edit(self, body):
        sub = body[0]
        if sub == P.EDIT_READ_BUFFER:
            data = self.buffer.encode()
            self._reply(P.msg(P.EDIT, P.EDIT_BUFFER_DUMP, 0x01, P.u14(len(data)), P.pack7(data), P.checksum(data)))
        elif sub == P.EDIT_PARAM and body[1] == 0:
            target, param, value = body[2], body[3], P.from_u35(body[4:9])
            self._apply_edit(target, param, value)
            self._reply(P.msg(P.EDIT, P.EDIT_PARAM, 1, target, param, P.u35(value)))
        elif sub == P.EDIT_SCREEN:
            for position in range(body[1], body[2] + 1):
                self._reply(P.msg(P.EDIT, P.EDIT_SCREEN_REPLY, self._screen(position)))
        elif sub in (P.TUNER_ON, P.TUNER_OFF):
            self.tuner_on = sub == P.TUNER_ON
            self._reply(P.msg(P.EDIT, sub))

    # --- pedal state ---

    def _select(self, location):
        self.current = location
        self.buffer = Patch.decode(self.slots[location])

    def _apply_edit(self, target, param, value):
        b = self.buffer
        if target == P.TARGET_NAME:
            name = list(b.name.ljust(10)[:10])
            name[param] = chr(value)
            b.name = "".join(name).rstrip()
        elif target == P.TARGET_SETTINGS:
            if param == P.SETTING_VOLUME:
                b.volume = value
            elif param == P.SETTING_TEMPO:
                self.tempo = value
            elif param == P.SETTING_AUTOSAVE:
                self.autosave = bool(value)
        else:
            slot = b.slots[target]
            if param == P.PARAM_ON_OFF:
                slot.enabled = bool(value)
            elif param == P.PARAM_EFFECT:
                effect = catalog().find(value)
                b.slots[target] = Slot.unpack(effect.template) if effect and effect.template else Slot(value)
            else:
                slot.knobs[param - P.PARAM_FIRST_KNOB] = value
        if self.autosave:
            self.slots[self.current] = b.encode()

    def _screen(self, position):
        """Six 14-byte records (on/off, effect name, four knobs) for one display screen."""
        slots = self.buffer.slots
        first, page = position, 0
        while first > 0 and slots[first].is_continuation:
            first, page = first - 1, page + 1
        slot = slots[first]
        effect = catalog().find(slot.id)
        cells = [(P.PARAM_ON_OFF, "", "ON" if slot.enabled else "OFF"),
                 (P.PARAM_EFFECT, "", effect.name if effect else "")]
        params = effect.params[page * 4:page * 4 + 4] if effect else []
        for i, p in enumerate(params):
            raw = slot.knobs[p.index]
            cells.append((P.PARAM_FIRST_KNOB + i, p.name, p.shown(raw) or str(raw)))
        out = []
        for param, label, text in cells:
            if label:
                out += [position, param, 1, 0] + _text10(label)
            out += [position, param, 0, 0] + _text10(text)
        return out

    def _tuner_tick(self):
        """While the tuner is on, report a slightly wobbly string, like a real one."""
        if not self.tuner_on:
            return
        cents = round(2 * math.sin(time.time() * 3))
        self._outbox.extend([mido.Message("control_change", control=P.TUNER_NOTE_CC,
                                          value=P.tuner_value(self.tuner_note)),
                             mido.Message("control_change", control=P.TUNER_CENTS_CC, value=8 + cents)])

    # --- plumbing ---

    def _reply(self, data):
        self._outbox.append(mido.Message("sysex", data=data))

    def _location(self, body):
        bank, index = body[2] | body[3] << 7, body[4] | body[5] << 7
        return bank * BANK_SIZE + index + 1


def _text10(s):
    return list(s.encode("ascii", "replace")[:10].ljust(10, b"\x00"))


class _InPort:
    def __init__(self, pedal):
        self.pedal = pedal
        self._last_tick = 0.0

    def poll(self):
        if time.time() - self._last_tick > 0.05:
            self._last_tick = time.time()
            self.pedal._tuner_tick()
        return self.pedal._outbox.popleft() if self.pedal._outbox else None

    def iter_pending(self):
        while True:
            m = self.poll()
            if m is None:
                return
            yield m

    def close(self):
        pass


class _OutPort:
    def __init__(self, pedal):
        self.pedal = pedal

    def send(self, m):
        self.pedal.receive(m)

    def close(self):
        pass
