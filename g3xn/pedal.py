"""Talk to a Zoom G3n / G3Xn over USB-MIDI.

    from g3xn import Pedal, Patch

    with Pedal() as pedal:                  # ToneLib / Guitar Lab must be closed
        print(pedal.current())              # 73
        tone = pedal.read(73)               # Patch
        tone.effect("FD TWNR")["Gain"] = 45
        pedal.push(tone)                    # hear it now (on the scratch slot)
        pedal.save_scratch(73)              # keep it

Safety model. These pedals usually run with AUTOSAVE on: any live edit is
written into whatever slot is selected. So:
  * every live edit goes to the scratch slot (default 150), never a real patch;
  * the scratch slot must be Empty the first time it is claimed;
  * a slot cannot be written while the pedal is sitting on it (the pedal's
    edit buffer would overwrite it).
"""
import json
import os
import time

import mido

from . import protocol as P
from .patch import Patch

STATE_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "state.json")


class PedalError(RuntimeError):
    pass


class Pedal:
    def __init__(self, scratch=150, timeout=2.0):
        self.scratch = scratch
        self.timeout = timeout
        self.inport = self.outport = None

    # --- connection ---

    def open(self):
        ins = [p for p in mido.get_input_names() if p.startswith(P.PORT_PREFIX)]
        outs = [p for p in mido.get_output_names() if p.startswith(P.PORT_PREFIX)]
        if not ins or not outs:
            raise PedalError("no Zoom G-series pedal found. Is it plugged in over USB, and is ToneLib/Guitar Lab closed?")
        try:
            self.inport = mido.open_input(ins[0])
            self.outport = mido.open_output(outs[0])
        except Exception as err:
            raise PedalError("could not open %s (another program may be using it): %s" % (ins[0], err))
        self._drain()
        self._send(P.msg(P.EDITOR_ON))
        time.sleep(0.05)
        self._drain()
        info = self._request(P.msg(P.PATCH_INFO))
        self.patch_count = info[5] << 7 | info[4]
        self.patch_size = info[7] << 7 | info[6]
        self.bank_size = info[11] << 7 | info[10]
        return self

    def close(self):
        if self.outport:
            self._send(P.msg(P.EDITOR_OFF))
            time.sleep(0.05)
            # input first: on Windows, closing the output while the input is
            # open can block forever inside midiOutClose
            self.inport.close()
            self.outport.close()
        self.inport = self.outport = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # --- information ---

    def identity(self):
        r = self._request([0x7E, 0x00, 0x06, 0x01])
        return {"manufacturer": "Zoom", "device_id": r[5], "firmware": bytes(r[-4:]).decode("ascii", "replace"),
                "patches": self.patch_count, "patch_size": self.patch_size, "bank_size": self.bank_size}

    def current(self):
        """The patch number (1-based) the pedal is on."""
        self._drain()
        self._send(P.msg(P.CURRENT_PROGRAM))
        bank, deadline = 0, time.time() + self.timeout
        while time.time() < deadline:
            for m in self.inport.iter_pending():
                if m.type == "control_change" and m.control == 32:
                    bank = m.value
                elif m.type == "program_change":
                    return bank * self.bank_size + m.program + 1
            time.sleep(0.003)
        raise PedalError("pedal did not report its current patch")

    def select(self, location):
        """Switch to patch `location` and wait for the pedal to confirm."""
        self._check_location(location)
        bank, index = P.location_to_bank(location, self.bank_size)
        for _ in range(5):
            self.outport.send(mido.Message("control_change", control=0, value=0))
            self.outport.send(mido.Message("control_change", control=32, value=bank))
            self.outport.send(mido.Message("program_change", program=index))
            time.sleep(0.08)
            if self.current() == location:
                return
        raise PedalError("pedal did not switch to patch %d" % location)

    # --- stored patches ---

    def read_raw(self, location):
        self._check_location(location)
        bank, index = P.location_to_bank(location, self.bank_size)
        r = self._request(P.msg(P.PATCH_READ, 0, 0, P.u14(bank), P.u14(index)))
        n = r[11] << 7 | r[10]
        data = P.unpack7(r[12:12 + n + n // 7 + 1])[:n]
        if not P.verify_checksum(data, r[-5:]):
            raise PedalError("checksum mismatch reading patch %d" % location)
        return data

    def read(self, location):
        return Patch.decode(self.read_raw(location))

    def read_all(self):
        return {n: self.read(n) for n in range(1, self.patch_count + 1)}

    def write(self, location, patch):
        """Store a patch (Patch or raw bytes) into slot `location`."""
        self._check_location(location)
        data = patch.encode() if isinstance(patch, Patch) else bytes(patch)
        if isinstance(patch, Patch) and patch.problems():
            raise PedalError("refusing to write: " + "; ".join(patch.problems()))
        if len(data) != self.patch_size:
            raise PedalError("patch is %d bytes; this pedal stores %d" % (len(data), self.patch_size))
        if self.current() == location:
            raise PedalError("the pedal is on patch %d; select another patch before overwriting it" % location)
        bank, index = P.location_to_bank(location, self.bank_size)
        self._request(P.msg(P.PATCH_WRITE, 0, 0, P.u14(bank), P.u14(index), P.u14(len(data)),
                            P.pack7(data), P.checksum(data)))
        if self.read_raw(location) != data:
            raise PedalError("patch %d did not read back as written" % location)

    def backup(self, folder):
        """Save every slot as NNN_NAME.zptc. Returns the folder path."""
        os.makedirs(folder, exist_ok=True)
        for n in range(1, self.patch_count + 1):
            data = self.read_raw(n)
            name = "".join(c if c.isalnum() or c in " -_" else "_" for c in Patch.decode(data).name) or "blank"
            with open(os.path.join(folder, "%03d_%s.zptc" % (n, name.strip())), "wb") as f:
                f.write(data)
        return folder

    # --- the edit buffer ---

    def edit_buffer(self):
        """The patch as currently loaded (including unsaved live edits)."""
        r = self._request(P.msg(P.EDIT, P.EDIT_READ_BUFFER), expect=P.msg(P.EDIT, P.EDIT_BUFFER_DUMP, 0x01))
        n = r[7] << 7 | r[6]
        data = P.unpack7(r[8:8 + n + n // 7 + 1])[:n]
        if not P.verify_checksum(data, r[-5:]):
            raise PedalError("checksum mismatch reading the edit buffer")
        return Patch.decode(data)

    # --- auditioning on the scratch slot ---

    def audition(self, patch):
        """Load a patch onto the scratch slot and switch to it, so you hear it now."""
        self._claim_scratch()
        if self.current() == self.scratch:
            self.select(self.scratch - 1 if self.scratch > 1 else self.scratch + 1)
        self.write(self.scratch, patch)
        self.select(self.scratch)

    def push(self, patch):
        """Make the pedal sound like `patch`, as fast as possible.
        If the scratch slot already holds the same chain, only changed knobs,
        on/off states, volume and name are sent as live edits; otherwise the
        whole patch is auditioned."""
        if self.current() != self.scratch:
            return self.audition(patch)
        live = self.edit_buffer()
        if [s.id for s in live.slots] != [s.id for s in patch.slots]:
            return self.audition(patch)
        for pos, (old, new) in enumerate(zip(live.slots, patch.slots)):
            if new.is_empty or new.is_continuation:
                continue
            for k, (a, b) in enumerate(zip(old.knobs, new.knobs)):
                if a != b:
                    self.set_knob(pos, k, b)
            if old.enabled != new.enabled:
                self.set_enabled(pos, new.enabled)
        if live.volume != patch.volume:
            self.set_volume(patch.volume)
        if live.name != patch.name:
            self.set_name(patch.name)

    def save_scratch(self, location):
        """Store what you are hearing on the scratch slot into a real slot, then
        switch to it. Reads the live edit buffer: autosave can lag behind live edits."""
        if location == self.scratch:
            raise PedalError("that is the scratch slot")
        if self.current() != self.scratch:
            raise PedalError("the pedal is not on the scratch slot; nothing is being auditioned")
        patch = self.edit_buffer()
        patch.size = self.patch_size
        self.write(location, patch)
        self.select(location)

    # --- live edits (scratch slot only) ---

    def set_knob(self, position, knob, value):
        """Knob `knob` (0-based) of the effect at chain position `position` (0..6)."""
        self._live(position, P.PARAM_FIRST_KNOB + knob, value)

    def set_enabled(self, position, on):
        self._live(position, P.PARAM_ON_OFF, int(bool(on)))

    def set_effect(self, position, effect_id):
        """Load an effect into a chain position (it starts with default knobs)."""
        self._live(position, P.PARAM_EFFECT, effect_id)

    def set_volume(self, value):
        self._live(P.TARGET_SETTINGS, P.SETTING_VOLUME, value)

    def set_tempo(self, bpm):
        self._live(P.TARGET_SETTINGS, P.SETTING_TEMPO, bpm)

    def set_name(self, name):
        for i, ch in enumerate(name[:10].ljust(10)):
            self._live(P.TARGET_NAME, i, ord(ch))

    def _live(self, target, param, value):
        if self.current() != self.scratch:
            raise PedalError("live edits only run on the scratch slot (%d); audition a patch first" % self.scratch)
        self._send(P.msg(P.EDIT, P.EDIT_PARAM, 0, target, param, P.u35(value)))
        time.sleep(0.015)
        self._drain()

    # --- tuner ---

    def tuner(self, on=True):
        self._send(P.msg(P.EDIT, P.TUNER_ON if on else P.TUNER_OFF))
        time.sleep(0.05)
        self._drain()

    def tuner_readings(self, seconds=5.0):
        """Yield {"note": "E", "cents": int} while the tuner is on.
        Cents is the pedal's raw 0..15 meter value re-centred on 0 (8 = in tune)."""
        note = None
        end = time.time() + seconds
        while time.time() < end:
            for m in self.inport.iter_pending():
                if m.type != "control_change":
                    continue
                if m.control == P.TUNER_NOTE_CC:
                    note = P.TUNER_NOTES[m.value - 1] if 1 <= m.value <= 12 else None
                elif m.control == P.TUNER_CENTS_CC:
                    yield {"note": note, "meter": m.value - 8}
            time.sleep(0.005)

    # --- screen text ---

    def screen(self, position):
        """One display screen (one per chain position): six cells, each
        {"label", "text"}: on/off, effect name, then four knobs as shown."""
        r = self._request(P.msg(P.EDIT, P.EDIT_SCREEN, position, position, 0))
        body = r[5:]
        cells = [{"label": "", "text": ""} for _ in range(6)]
        for i in range(0, len(body) - 13, 14):
            param, kind = body[i + 1], body[i + 2]
            text = bytes(body[i + 4:i + 14]).split(b"\x00")[0].decode("ascii", "replace")
            if param < 6:
                cells[param]["text" if kind == 0 else "label"] = text
        return cells

    def display(self):
        """Every effect's knobs as the pedal shows them (e.g. delay time in ms):
        [{"position", "effect", "on", "knobs": {label: text}}]."""
        out = []
        for pos, slot in enumerate(self.edit_buffer().slots):
            if slot.is_empty:
                continue
            cells = self.screen(pos)
            knobs = {c["label"]: c["text"] for c in cells[2:] if c["label"]}
            if slot.is_continuation and out:
                out[-1]["knobs"].update(knobs)       # second screen of a two-position effect
            else:
                out.append({"position": pos, "effect": cells[1]["text"], "on": slot.enabled, "knobs": knobs})
        return out

    # --- pedal file system (effect .ZD2 files) ---

    def list_files(self):
        names, first = [], True
        while True:
            r = self._request(P.msg(0x60, 0x25 if first else 0x26, 0, 0, _cstr("*")))
            first = False
            if r[4] != 4:
                break
            name = bytes(r[14:]).split(b"\x00")[0].decode("ascii", "replace")
            if not name or name in names:
                break
            names.append(name)
        self._request(P.msg(0x60, 0x27))
        return names

    def read_file(self, name):
        self._request(P.msg(0x60, 0x25, 0, 0, _cstr(name)))
        found = self._request(P.msg(0x60, 0x05, 0))[-5:] == bytes(5)
        self._request(P.msg(0x60, 0x27))
        if not found:
            raise FileNotFoundError(name)
        self._request(P.msg(0x60, 0x20, 0x02, [0] * 9, _cstr(name)))
        data = bytearray()
        while True:
            self._request(P.msg(0x60, 0x05, 0))
            self._request(P.msg(0x60, 0x22, 0x14, 0x2F, 0x60, 0, 0x0C, 0, 0x04, 0, 0, 0))
            r = self._request(P.msg(0x60, 0x05, 0))
            n = r[9] << 7 | r[8]
            if r[4] != 4 or n == 0:
                break
            block = P.unpack7(r[10:10 + n + n // 7 + 1])[:n]
            if not P.verify_checksum(block, r[-5:]):
                raise PedalError("checksum mismatch reading " + name)
            data += block
        self._request(P.msg(0x60, 0x21, 0x40, 0, 0, 0, 0))
        self._request(P.msg(0x60, 0x09))
        return bytes(data)

    # --- plumbing ---

    def _send(self, data):
        self.outport.send(mido.Message("sysex", data=data))

    def _request(self, data, expect=None):
        self._drain()
        self._send(data)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            m = self.inport.poll()
            if m is None:
                time.sleep(0.002)
            elif m.type == "sysex" and (expect is None or bytes(m.data).startswith(bytes(expect))):
                return bytes(m.data)
        raise PedalError("no reply to %s" % " ".join("%02X" % b for b in data[3:10]))

    def _drain(self):
        for _ in self.inport.iter_pending():
            pass

    def _check_location(self, location):
        if not isinstance(location, int) or not 1 <= location <= self.patch_count:
            raise PedalError("patch number must be 1..%d" % self.patch_count)

    def _claim_scratch(self):
        state = _load_state()
        if state.get("scratch") == self.scratch:
            return
        name = self.read(self.scratch).name
        if name != "Empty":
            raise PedalError("scratch slot %d holds %r. Pick an Empty slot with Pedal(scratch=N) "
                             "or clear it first; it will be overwritten by auditions." % (self.scratch, name))
        state["scratch"] = self.scratch
        _save_state(state)


def _cstr(s):
    return [ord(c) for c in s] + [0]


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)
