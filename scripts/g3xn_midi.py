"""USB-MIDI SysEx client for the Zoom G3n/G3Xn (device id 0x6E).

Protocol notes come from mungewell/zoom-zt2 (zoomzt2.py), which documents the
same SysEx family used by the G1Four/G3n/G5n generation.
"""
import binascii
import time

import mido

ZOOM = [0x52, 0x00, 0x6E]
PORT_PREFIX = "ZOOM G"


def pack7(data):
    """8-bit -> 7-bit: one byte of MSBs followed by up to 7 low-7-bit bytes."""
    out = bytearray()
    for i in range(0, len(data), 7):
        chunk = data[i:i + 7]
        hi = 0
        for j, b in enumerate(chunk):
            if b & 0x80:
                hi |= 0x40 >> j
        out.append(hi)
        out.extend(b & 0x7F for b in chunk)
    return bytes(out)


def unpack7(packet):
    out = bytearray()
    for i in range(0, len(packet), 8):
        hi = packet[i]
        for j, b in enumerate(packet[i + 1:i + 8]):
            out.append(b | 0x80 if hi & (0x40 >> j) else b)
    return bytes(out)


def crc_7bit(data):
    crc = binascii.crc32(data) ^ 0xFFFFFFFF
    return [crc & 0x7F, (crc >> 7) & 0x7F, (crc >> 14) & 0x7F, (crc >> 21) & 0x7F, (crc >> 28) & 0x0F]


def crc_from_7bit(tail):
    return tail[0] + (tail[1] << 7) + (tail[2] << 14) + (tail[3] << 21) + ((tail[4] & 0x0F) << 28)


class Pedal:
    def __init__(self, timeout=2.0):
        self.timeout = timeout
        self.inport = self.outport = None

    def __enter__(self):
        ins = [p for p in mido.get_input_names() if p.startswith(PORT_PREFIX)]
        outs = [p for p in mido.get_output_names() if p.startswith(PORT_PREFIX)]
        if not ins or not outs:
            raise RuntimeError("Zoom pedal not found (is it plugged in, and is ToneLib-Zoom closed?)")
        self.inport = mido.open_input(ins[0])
        self.outport = mido.open_output(outs[0])
        self._drain()
        self.editor_on()
        self.count, self.patch_size, self.bank_size = self.patch_info()
        return self

    def __exit__(self, *exc):
        try:
            self.editor_off()
        finally:
            self.inport.close()
            self.outport.close()

    def _drain(self):
        for _ in self.inport.iter_pending():
            pass

    def send(self, data, expect_reply=True, expect=None):
        """Send SysEx; return the first SysEx reply (starting with `expect`, if given)."""
        if expect_reply:
            self._drain()
        self.outport.send(mido.Message("sysex", data=data))
        if not expect_reply:
            return None
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            msg = self.inport.poll()
            if msg is not None and msg.type == "sysex":
                reply = bytes(msg.data)
                if expect is None or reply.startswith(bytes(expect)):
                    return reply
                continue
            time.sleep(0.002)
        raise TimeoutError("no reply to " + " ".join("%02x" % b for b in data[:8]))

    def identity(self):
        return self.send([0x7E, 0x00, 0x06, 0x01])

    def editor_on(self):
        self.send(ZOOM + [0x50], expect_reply=False)
        time.sleep(0.05)
        self._drain()

    def editor_off(self):
        self.send(ZOOM + [0x51], expect_reply=False)

    def patch_info(self):
        """Returns (patch_count, patch_size, bank_size)."""
        p = self.send(ZOOM + [0x44])
        return (p[5] << 7 | p[4], p[7] << 7 | p[6], p[11] << 7 | p[10])

    def read_patch(self, location):
        """Read stored patch 1..count; returns the raw 8-bit PTCF bytes."""
        bank, loc = divmod(location - 1, self.bank_size)
        p = self.send(ZOOM + [0x46, 0x00, 0x00, bank & 0x7F, bank >> 7, loc & 0x7F, loc >> 7])
        length = p[11] << 7 | p[10]
        if length == 0:
            return b""
        data = unpack7(p[12:12 + length + length // 7 + 1])[:length]
        if crc_from_7bit(p[-5:]) ^ 0xFFFFFFFF != binascii.crc32(data):
            raise ValueError("checksum mismatch reading patch %d" % location)
        return data

    # --- pedal file system (effect .ZD2 files, FLST_SEQ.ZT2) -- read-only ---

    def _filename_packet(self, head, name):
        return head + [ord(c) for c in name] + [0x00]

    def list_files(self):
        names = []
        first = True
        while True:
            head = ZOOM + [0x60, 0x25 if first else 0x26, 0x00, 0x00]
            first = False
            p = self.send(self._filename_packet(head, "*"))
            if p[4] != 4:
                break
            raw = p[14:]
            name = bytes(raw[:raw.index(0)] if 0 in raw else raw).decode("ascii", "replace")
            if not name or name in names:
                break
            names.append(name)
        self.send(ZOOM + [0x60, 0x27])
        return names

    def file_exists(self, name):
        resp = self.send(self._filename_packet(ZOOM + [0x60, 0x25, 0x00, 0x00], name))
        resp = self.send(ZOOM + [0x60, 0x05, 0x00])
        self.send(ZOOM + [0x60, 0x27])
        return resp[-5:] == bytes(5)

    def read_file(self, name):
        if not self.file_exists(name):
            raise FileNotFoundError(name)
        self.send(self._filename_packet(ZOOM + [0x60, 0x20, 0x02] + [0x00] * 9, name))
        data = bytearray()
        while True:
            self.send(ZOOM + [0x60, 0x05, 0x00])
            self.send(ZOOM + [0x60, 0x22, 0x14, 0x2F, 0x60, 0x00, 0x0C, 0x00, 0x04, 0x00, 0x00, 0x00])
            p = self.send(ZOOM + [0x60, 0x05, 0x00])
            length = p[9] << 7 | p[8]
            if p[4] != 4 or length == 0:
                break
            block = unpack7(p[10:10 + length + length // 7 + 1])[:length]
            if crc_from_7bit(p[-5:]) ^ 0xFFFFFFFF != binascii.crc32(block):
                raise ValueError("checksum mismatch reading " + name)
            data += block
        self.send(ZOOM + [0x60, 0x21, 0x40, 0x00, 0x00, 0x00, 0x00])
        self.send(ZOOM + [0x60, 0x09])
        return bytes(data)

    def read_current(self):
        p = self.send(ZOOM + [0x64, 0x13], expect=ZOOM + [0x64, 0x12, 0x01])
        length = p[7] << 7 | p[6]
        data = unpack7(p[8:8 + length + length // 7 + 1])[:length]
        if crc_from_7bit(p[-5:]) ^ 0xFFFFFFFF != binascii.crc32(data):
            raise ValueError("checksum mismatch reading current patch")
        return data

    # --- live control ---

    def _send_only(self, data):
        self.outport.send(mido.Message("sysex", data=data))

    def current_location(self):
        """Patch number (1..150) the pedal is on, from its CC0/CC32/PC reply to 0x33."""
        self._drain()
        self._send_only(ZOOM + [0x33])
        bank = prog = None
        deadline = time.time() + self.timeout
        while time.time() < deadline and prog is None:
            for m in self.inport.iter_pending():
                if m.type == "control_change" and m.control == 32:
                    bank = m.value
                elif m.type == "program_change":
                    prog = m.program
            time.sleep(0.005)
        if prog is None:
            raise TimeoutError("no program reply")
        return (bank or 0) * self.bank_size + prog + 1

    def select(self, location):
        bank, prog = divmod(location - 1, self.bank_size)
        self.outport.send(mido.Message("control_change", control=0, value=0))
        self.outport.send(mido.Message("control_change", control=32, value=bank))
        self.outport.send(mido.Message("program_change", program=prog))
        time.sleep(0.15)
        self._drain()

    def set_param(self, slot, param, value):
        """Live edit of the edit buffer. slot 0..6 is the chain position; 0x09 is
        the patch name, 0x0A system settings. param 0 = on/off, 1 = effect id,
        2.. = knobs. value is sent as five 7-bit groups, little-endian."""
        v = [(value >> s) & 0x7F for s in (0, 7, 14, 21, 28)]
        self._send_only(ZOOM + [0x64, 0x03, 0x00, slot, param] + v)
        time.sleep(0.02)
        self._drain()

    def tuner(self, on):
        self._send_only(ZOOM + [0x64, 0x0B if on else 0x0C])
        time.sleep(0.05)

    def write_current(self, data):
        """Load a patch into the edit buffer (audition; nothing is stored)."""
        n = len(data)
        self._send_only(ZOOM + [0x64, 0x12, 0x01, n & 0x7F, n >> 7] + list(pack7(data)) + crc_7bit(data))
        time.sleep(0.15)
        self._drain()

    def write_patch(self, location, data):
        """Store a patch into slot `location` (1..150)."""
        bank, loc = divmod(location - 1, self.bank_size)
        n = len(data)
        r = self.send(ZOOM + [0x45, 0x00, 0x00, bank & 0x7F, bank >> 7, loc & 0x7F, loc >> 7,
                              n & 0x7F, n >> 7] + list(pack7(data)) + crc_7bit(data))
        return r
