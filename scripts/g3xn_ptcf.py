"""Decode/encode Zoom G3n/G3Xn PTCF patches (the 736-byte slot images).

Layout (little-endian), after mungewell/zoom-zt2 decode_preset.py:
  0x00 "PTCF"  u32 length  u32 version  u32 fx_count  u32 target  6 bytes  name[10]
  u32 ids[fx_count]
  TXJ1 <u32 len> data   TXE1 <u32 len> data
  EDTB <u32 len> fx_count x 24-byte slot records
  PPRM <u32 len> 12 bytes
  zero padding up to the slot size (736 on G3Xn fw 2.20)

Each EDTB record, read as one 192-bit little-endian integer, is (from bit 0):
  enabled:1  id:29  p1..p5:12 each  p6..p8:8 each  p9..p12:12 each  extra:6  tail:24
"""
import struct

SLOT_SIZE = 736
PARAM_WIDTHS = [12, 12, 12, 12, 12, 8, 8, 8, 12, 12, 12, 12]
CONTINUATION_ID = 0x00000001  # second chain position of a 2-slot effect (amps, GEQ7, ...)
EMPTY_ID = 0x00000000


class Slot:
    def __init__(self, id=EMPTY_ID, enabled=False, params=None, extra=0, tail=0):
        self.id = id
        self.enabled = enabled
        self.params = list(params) if params else [0] * 12
        self.extra = extra
        self.tail = tail

    @classmethod
    def unpack(cls, raw):
        v = int.from_bytes(raw, "little")
        enabled = bool(v & 1)
        v >>= 1
        id = v & ((1 << 29) - 1)
        v >>= 29
        params = []
        for w in PARAM_WIDTHS:
            params.append(v & ((1 << w) - 1))
            v >>= w
        extra = v & 0x3F
        v >>= 6
        return cls(id, enabled, params, extra, v)

    def pack(self):
        v = self.tail
        v = (v << 6) | (self.extra & 0x3F)
        for w, p in reversed(list(zip(PARAM_WIDTHS, self.params))):
            if not 0 <= p < (1 << w):
                raise ValueError("param %d out of range for %d-bit field" % (p, w))
            v = (v << w) | p
        v = (v << 29) | (self.id & ((1 << 29) - 1))
        v = (v << 1) | int(bool(self.enabled))
        return v.to_bytes(24, "little")

    def to_dict(self):
        return {"id": "0x%08x" % self.id, "enabled": self.enabled, "params": self.params}


class Patch:
    def __init__(self):
        self.version = 1
        self.target = 4
        self.header_extra = bytes(6)
        self.name = ""
        self.slots = []
        self.txj1 = b""
        self.txe1 = b""
        self.pprm = bytes(12)
        self.size = SLOT_SIZE

    # PPRM bitfield (zoom-zt2 PPRM_rev): bits 63..69 patch volume, 70..72 edit slot
    @property
    def volume(self):
        return (int.from_bytes(self.pprm, "little") >> 63) & 0x7F

    @volume.setter
    def volume(self, value):
        if not 0 <= value <= 0x7F:
            raise ValueError("volume must be 0..127")
        v = int.from_bytes(self.pprm, "little")
        v = (v & ~(0x7F << 63)) | (value << 63)
        self.pprm = v.to_bytes(len(self.pprm), "little")

    @property
    def edit_slot(self):
        return (int.from_bytes(self.pprm, "little") >> 70) & 0x7

    @classmethod
    def decode(cls, data):
        if data[:4] != b"PTCF":
            raise ValueError("not a PTCF patch")
        p = cls()
        p.size = len(data)
        _, p.version, count, p.target = struct.unpack_from("<4I", data, 4)
        p.header_extra = bytes(data[20:26])
        p.name = data[26:36].decode("ascii", "replace").rstrip(" \x00")
        ids = struct.unpack_from("<%dI" % count, data, 36)
        off = 36 + 4 * count
        sections = {}
        for tag in (b"TXJ1", b"TXE1", b"EDTB", b"PPRM"):
            if data[off:off + 4] != tag:
                raise ValueError("expected %s at 0x%x" % (tag, off))
            (length,) = struct.unpack_from("<I", data, off + 4)
            sections[tag] = bytes(data[off + 8:off + 8 + length])
            off += 8 + length
        if p.version > 1:
            raise ValueError("PTCF v%d (PRM2/NAME) not supported for G3Xn" % p.version)
        p.txj1, p.txe1, p.pprm = sections[b"TXJ1"], sections[b"TXE1"], sections[b"PPRM"]
        edtb = sections[b"EDTB"]
        p.slots = [Slot.unpack(edtb[i * 24:(i + 1) * 24]) for i in range(count)]
        for i, (sid, slot) in enumerate(zip(ids, p.slots)):
            if sid != slot.id:
                raise ValueError("slot %d id mismatch: header 0x%x vs EDTB 0x%x" % (i, sid, slot.id))
        # Stored slots are zero-padded past `length`; the edit buffer (0x64 0x13)
        # carries stale bytes there instead, so anything past `length` is ignored.
        return p

    def encode(self):
        name = self.name.encode("ascii")[:10].ljust(10, b" ")
        body = b"".join([
            struct.pack("<%dI" % len(self.slots), *[s.id for s in self.slots]),
            b"TXJ1" + struct.pack("<I", len(self.txj1)) + self.txj1,
            b"TXE1" + struct.pack("<I", len(self.txe1)) + self.txe1,
            b"EDTB" + struct.pack("<I", 24 * len(self.slots)) + b"".join(s.pack() for s in self.slots),
            b"PPRM" + struct.pack("<I", len(self.pprm)) + self.pprm,
        ])
        length = 36 + len(body)
        out = b"PTCF" + struct.pack("<4I", length, self.version, len(self.slots), self.target) \
            + self.header_extra + name + body
        if len(out) > self.size:
            raise ValueError("patch is %d bytes, slot holds %d" % (len(out), self.size))
        return out.ljust(self.size, b"\x00")

    def to_dict(self):
        return {
            "name": self.name,
            "volume": self.volume,
            "edit_slot": self.edit_slot,
            "slots": [s.to_dict() for s in self.slots],
        }
