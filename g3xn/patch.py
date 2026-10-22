"""Zoom G3n / G3Xn patches: the 736-byte PTCF image stored in each slot.

    from g3xn import Patch

    p = Patch.blank("BLUES")
    p.add("TS Drive", Gain=40, Tone=55)
    p.add("FD TWNR", Gain=35, Treble=45)
    p.add("HD Hall", Mix=25)
    p.volume = 90
    open("blues.zptc", "wb").write(p.encode())

Binary layout (little-endian), after mungewell/zoom-zt2's decode_preset.py:

    0x00  "PTCF"  u32 length  u32 version(1)  u32 count  u32 target(4)  6 x 00
    0x1A  name[10]  (ASCII, space padded)
    0x24  u32 effect_id[count]
          "TXJ1" u32 len  data     Japanese description
          "TXE1" u32 len  data     English description
          "EDTB" u32 len  count x 24-byte effect records
          "PPRM" u32 len  12 bytes (patch volume, selected slot, ...)
          zero padding to the slot size (736 on the G3Xn)

An EDTB record read as one 192-bit little-endian integer holds, from bit 0:
enabled:1, id:29, knobs p1..p5:12 bits, p6..p8:8 bits, p9..p12:12 bits,
then 30 bits the pedal fills in itself (kept verbatim).

A two-screen effect (8 knobs) occupies two chain positions: its own record
followed by a continuation record (id 0x00000001).
"""
import struct

from .catalog import DSP_BUDGET, MAX_POSITIONS, catalog

SLOT_SIZE = 736
KNOB_BITS = [12, 12, 12, 12, 12, 8, 8, 8, 12, 12, 12, 12]
EMPTY_ID = 0x00000000
CONTINUATION_ID = 0x00000001
MAX_VOLUME = 120
BLANK_PPRM = bytes.fromhex("000000000000000032840c00")


class Slot:
    """One raw chain position (EDTB record)."""

    def __init__(self, id=EMPTY_ID, enabled=True, knobs=None, extra=0, tail=0):
        self.id = id
        self.enabled = enabled
        self.knobs = list(knobs) if knobs else [0] * 12
        self.extra = extra    # 6 bits after p12
        self.tail = tail      # top 24 bits

    @classmethod
    def unpack(cls, raw):
        v = int.from_bytes(raw, "little")
        enabled, v = bool(v & 1), v >> 1
        id, v = v & (1 << 29) - 1, v >> 29
        knobs = []
        for bits in KNOB_BITS:
            knobs.append(v & (1 << bits) - 1)
            v >>= bits
        return cls(id, enabled, knobs, v & 0x3F, v >> 6)

    def pack(self):
        v = self.tail << 6 | self.extra & 0x3F
        for bits, k in reversed(list(zip(KNOB_BITS, self.knobs))):
            if not 0 <= k < 1 << bits:
                raise ValueError("knob value %d does not fit in %d bits" % (k, bits))
            v = v << bits | k
        v = v << 29 | self.id & (1 << 29) - 1
        v = v << 1 | int(bool(self.enabled))
        return v.to_bytes(24, "little")

    def copy(self):
        return Slot.unpack(self.pack())

    @property
    def is_empty(self):
        return self.id == EMPTY_ID

    @property
    def is_continuation(self):
        return self.id == CONTINUATION_ID


class ChainEffect:
    """An effect in a patch, with knobs addressed by name."""

    def __init__(self, patch, position, slot):
        self.patch = patch
        self.position = position        # raw chain position 0..6 (what live edits address)
        self.slot = slot
        self.effect = catalog().find(slot.id)

    @property
    def name(self):
        return self.effect.name if self.effect else "0x%08x" % self.slot.id

    @property
    def enabled(self):
        return self.slot.enabled

    @enabled.setter
    def enabled(self, on):
        self.slot.enabled = bool(on)

    def __getitem__(self, knob):
        return self.slot.knobs[self._param(knob).index]

    def __setitem__(self, knob, value):
        p = self._param(knob)
        self.slot.knobs[p.index] = p.check(value)

    def knobs(self):
        if not self.effect:
            return {}
        return {p.name: self.slot.knobs[p.index] for p in self.effect.params}

    def _param(self, knob):
        if not self.effect:
            raise KeyError("unknown effect 0x%08x has no named knobs" % self.slot.id)
        return self.effect.param(knob)

    def to_dict(self):
        return {"position": self.position, "name": self.name, "enabled": self.enabled,
                "group": self.effect.group if self.effect else None, "knobs": self.knobs()}

    def __repr__(self):
        return "<%s %s @%d %s>" % (self.name, "on" if self.enabled else "off", self.position, self.knobs())


class Patch:
    def __init__(self):
        self.version = 1
        self.target = 4
        self.reserved = bytes(6)
        self.name = ""
        self.slots = []
        self.txj1 = b""
        self.txe1 = b""
        self.pprm = BLANK_PPRM
        self.size = SLOT_SIZE

    # --- construction / serialisation ---

    @classmethod
    def blank(cls, name="NEW PATCH"):
        p = cls()
        p.name = name
        p.slots = [Slot() for _ in range(MAX_POSITIONS)]
        return p

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls.decode(f.read())

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.encode())

    @classmethod
    def decode(cls, data):
        if data[:4] != b"PTCF":
            raise ValueError("not a PTCF patch")
        p = cls()
        p.size = max(len(data), SLOT_SIZE)
        _, p.version, count, p.target = struct.unpack_from("<4I", data, 4)
        if p.version != 1:
            raise ValueError("PTCF version %d is not the G3n/G3Xn format" % p.version)
        p.reserved = bytes(data[20:26])
        p.name = data[26:36].decode("ascii", "replace").rstrip(" \x00")
        ids = struct.unpack_from("<%dI" % count, data, 36)
        off = 36 + 4 * count
        chunks = {}
        for tag in (b"TXJ1", b"TXE1", b"EDTB", b"PPRM"):
            if data[off:off + 4] != tag:
                raise ValueError("expected %s at offset 0x%x" % (tag.decode(), off))
            (n,) = struct.unpack_from("<I", data, off + 4)
            chunks[tag] = bytes(data[off + 8:off + 8 + n])
            off += 8 + n
        p.txj1, p.txe1, p.pprm = chunks[b"TXJ1"], chunks[b"TXE1"], chunks[b"PPRM"]
        p.slots = [Slot.unpack(chunks[b"EDTB"][i * 24:i * 24 + 24]) for i in range(count)]
        for i, (sid, slot) in enumerate(zip(ids, p.slots)):
            if sid != slot.id:
                raise ValueError("position %d: header id 0x%x != record id 0x%x" % (i, sid, slot.id))
        # bytes past `length` are zero in stored slots and stale garbage in the edit buffer
        return p

    def encode(self):
        name = self.name.encode("ascii")
        if len(name) > 10:
            raise ValueError("patch name is limited to 10 characters")
        body = b"".join([
            struct.pack("<%dI" % len(self.slots), *(s.id for s in self.slots)),
            b"TXJ1" + struct.pack("<I", len(self.txj1)) + self.txj1,
            b"TXE1" + struct.pack("<I", len(self.txe1)) + self.txe1,
            b"EDTB" + struct.pack("<I", 24 * len(self.slots)) + b"".join(s.pack() for s in self.slots),
            b"PPRM" + struct.pack("<I", len(self.pprm)) + self.pprm,
        ])
        head = b"PTCF" + struct.pack("<4I", 36 + len(body), self.version, len(self.slots), self.target)
        out = head + self.reserved + name.ljust(10, b" ") + body
        if len(out) > self.size:
            raise ValueError("patch is %d bytes; a slot holds %d" % (len(out), self.size))
        return out.ljust(self.size, b"\x00")

    def copy(self):
        return Patch.decode(self.encode())

    # --- patch-level settings (PPRM bits 63..69 = volume, 70..72 = selected slot) ---

    @property
    def volume(self):
        return int.from_bytes(self.pprm, "little") >> 63 & 0x7F

    @volume.setter
    def volume(self, value):
        if not isinstance(value, int) or not 0 <= value <= MAX_VOLUME:
            raise ValueError("patch volume must be 0..%d" % MAX_VOLUME)
        v = int.from_bytes(self.pprm, "little") & ~(0x7F << 63) | value << 63
        self.pprm = v.to_bytes(len(self.pprm), "little")

    @property
    def description(self):
        return self.txe1.decode("ascii", "replace").rstrip("\x00").strip()

    # --- the effect chain ---

    @property
    def chain(self):
        """Effects in signal order (empty and continuation positions skipped)."""
        return [ChainEffect(self, i, s) for i, s in enumerate(self.slots)
                if not s.is_empty and not s.is_continuation]

    def effect(self, key):
        """An effect by chain number (1-based) or by name."""
        chain = self.chain
        if isinstance(key, int):
            if not 1 <= key <= len(chain):
                raise IndexError("patch has %d effects; no effect #%d" % (len(chain), key))
            return chain[key - 1]
        matches = [c for c in chain if c.effect and c.effect is catalog().get(key)]
        if not matches:
            raise KeyError("%r is not in this patch (%s)" % (key, ", ".join(c.name for c in chain) or "empty"))
        return matches[0]

    def add(self, effect, at=None, enabled=True, knobs=None, **kw):
        """Insert an effect (name or id) before chain number `at` (1-based), or at the end.
        Knobs are matched ignoring case and punctuation (FB=30 sets "F.B"); use
        knobs={"1.6k": 30} for names that aren't valid keywords. Unset knobs keep
        the pedal's defaults."""
        e = catalog().get(effect)
        if e.template is None:
            raise ValueError("%s has no template; it cannot be built offline" % e.name)
        slot = Slot.unpack(e.template)
        slot.enabled = enabled
        groups = self._groups()
        index = len(groups) if at is None else at - 1
        if not 0 <= index <= len(groups):
            raise IndexError("can insert at 1..%d" % (len(groups) + 1))
        group = [slot] + [Slot(CONTINUATION_ID) for _ in range(e.positions - 1)]
        groups.insert(index, group)
        self._rebuild(groups)
        added = self.chain[index]
        for k, v in {**(knobs or {}), **kw}.items():
            added[k] = v
        return added

    def remove(self, key):
        target = self.effect(key)
        groups = [g for g in self._groups() if g[0] is not target.slot]
        self._rebuild(groups)

    def move(self, key, to):
        """Move an effect to chain number `to` (1-based)."""
        target = self.effect(key)
        groups = self._groups()
        group = next(g for g in groups if g[0] is target.slot)
        groups.remove(group)
        groups.insert(to - 1, group)
        self._rebuild(groups)

    def replace(self, key, effect, knobs=None, **kw):
        """Swap an effect for another in the same place."""
        target = self.effect(key)
        at = [c.slot for c in self.chain].index(target.slot) + 1
        self.remove(key)
        return self.add(effect, at=at, enabled=target.enabled, knobs=knobs, **kw)

    def _groups(self):
        groups = []
        for s in self.slots:
            if s.is_continuation and groups:
                groups[-1].append(s)
            elif not s.is_empty:
                groups.append([s])
        return groups

    def _rebuild(self, groups):
        slots = [s for g in groups for s in g]
        if len(slots) > MAX_POSITIONS:
            raise ValueError("chain needs %d positions; the G3Xn has %d" % (len(slots), MAX_POSITIONS))
        self.slots = slots + [Slot() for _ in range(MAX_POSITIONS - len(slots))]

    # --- checks / reporting ---

    @property
    def dsp(self):
        return sum(c.effect.dsp for c in self.chain if c.effect)

    @property
    def dsp_percent(self):
        return round(self.dsp / DSP_BUDGET * 100, 1)

    def problems(self):
        """Reasons the pedal would reject or mis-play this patch (empty list = fine)."""
        out = []
        used = sum(1 for s in self.slots if not s.is_empty)
        if used > MAX_POSITIONS:
            out.append("uses %d chain positions (max %d)" % (used, MAX_POSITIONS))
        if self.dsp > DSP_BUDGET:
            out.append("DSP load %.0f%% exceeds 100%%" % self.dsp_percent)
        for c in self.chain:
            if not c.effect:
                continue
            for p in c.effect.params:
                if c.slot.knobs[p.index] > p.max:
                    out.append("%s %s=%d exceeds max %d" % (c.name, p.name, c.slot.knobs[p.index], p.max))
        try:
            self.encode()
        except ValueError as err:
            out.append(str(err))
        return out

    def to_dict(self):
        return {"name": self.name, "volume": self.volume, "dsp_percent": self.dsp_percent,
                "description": self.description, "chain": [c.to_dict() for c in self.chain]}

    @classmethod
    def from_dict(cls, spec):
        """Build a patch from the JSON tone format:

            {"name": "BLUES", "volume": 90,
             "chain": [{"effect": "TS Drive", "on": true, "knobs": {"Gain": 40}},
                       {"effect": "FD TWNR", "knobs": {"Gain": 35}}]}

        Effects go in signal order; unspecified knobs keep the pedal defaults."""
        p = cls.blank(spec.get("name", "NEW PATCH"))
        for item in spec.get("chain", []):
            p.add(item.get("effect") or item["name"], enabled=item.get("on", item.get("enabled", True)),
                  knobs=item.get("knobs"))
        if "volume" in spec:
            p.volume = spec["volume"]
        return p

    def __repr__(self):
        return "<Patch %r vol %d: %s>" % (self.name, self.volume, " > ".join(c.name for c in self.chain) or "empty")
