"""Build data/effects.json from the .ZD2 effect files pulled off the pedal.

ZD2 = "ZDLF" container: header (version, id, name, group) then tagged sections
ICON / TXJ1 / TXE1 (English description) / INFO (dsp load) / DATA (TI C6x ELF)
/ PRMJ / PRME (JSON: parameter names + explanations).

Parameter ranges and defaults are not in PRME; they live in the ELF's .const
section as 56-byte records: name[12], max u32, default u32, ... . Records 0 and 1
are OnOff and the effect itself; records 2.. are the knobs in EDTB p1..p12 order.

usage: python build_catalog.py <dir with .ZD2 files> [patch dump dir] > effects.json
"""
import glob
import io
import json
import os
import re
import struct
import sys

from elftools.elf.elffile import ELFFile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g3xn_ptcf import CONTINUATION_ID, Patch  # noqa: E402

RECORD = 0x38


def sections(data):
    out = {}
    for tag in (b"ICON", b"TXJ1", b"TXE1", b"INFO", b"DATA", b"PRMJ", b"PRME"):
        i = data.find(tag, 0x60)
        if i >= 0:
            (n,) = struct.unpack_from("<I", data, i + 4)
            out[tag.decode()] = data[i + 8:i + 8 + n]
    return out


def cstr(b):
    return b.split(b"\x00", 1)[0].decode("ascii", "replace")


def parse_zd2(path):
    data = open(path, "rb").read()
    sec = sections(data)
    ver_at = re.search(rb"\d\.\d\d\x00\x00", data[:0x80]).start()
    version = data[ver_at:ver_at + 4].decode()
    (effect_id,) = struct.unpack_from("<I", data, ver_at + 7)
    rest = data[ver_at + 11:ver_at + 11 + 22]
    name, group = cstr(rest[:11]), cstr(rest[11:])

    prme = json.loads(sec["PRME"].decode("ascii", "replace"))["Parameters"]
    info = sec["INFO"]
    (dsp,) = struct.unpack_from("<f", info, len(info) - 4)

    elf = ELFFile(io.BytesIO(sec["DATA"]))
    const = elf.get_section_by_name(".const").data()
    base = const.find(b"OnOff\x00")
    recs = []
    for k in range(2 + len(prme)):
        r = const[base + k * RECORD:base + (k + 1) * RECORD]
        mx, default = struct.unpack_from("<2I", r, 12)
        recs.append((cstr(r[:12]), mx, default))
    if base < 0 or recs[0][0] != "OnOff":
        raise ValueError("%s: unexpected descriptor layout" % path)

    params = []
    for (pname, mx, default), meta in zip(recs[2:], prme):
        params.append({
            "name": meta.get("name") or pname,
            "max": mx,
            "default": default,
            "explanation": meta.get("explanation", ""),
            "pedal": bool(meta.get("pedal")),
        })
    return {
        "id": "0x%08x" % effect_id,
        "name": name,
        "group": group,
        "file": os.path.basename(path),
        "version": version,
        "dsp": round(dsp, 2),
        "description": sec.get("TXE1", b"").decode("ascii", "replace").strip(),
        "params": params,
    }


def observed_two_slot(dump_dir):
    """Effects followed by a continuation entry occupy two chain positions."""
    two = set()
    for f in glob.glob(os.path.join(dump_dir, "*.zptc")):
        slots = Patch.decode(open(f, "rb").read()).slots
        for a, b in zip(slots, slots[1:]):
            if b.id == CONTINUATION_ID:
                two.add("0x%08x" % a.id)
    return two


# Built into the firmware, no .ZD2. Seen in patches; names not yet confirmed on-device.
BUILTINS = {
    "0x1e000010": {"name": "Builtin 1E10", "group": "BUILTIN"},
    "0x1f000010": {"name": "Builtin 1F10", "group": "BUILTIN"},
    "0x1f000020": {"name": "Builtin 1F20", "group": "BUILTIN"},
}


def main():
    zd2_dir = sys.argv[1]
    seen_two = observed_two_slot(sys.argv[2]) if len(sys.argv) > 2 else set()
    effects = {}
    for path in sorted(glob.glob(os.path.join(zd2_dir, "*.ZD2"))):
        e = parse_zd2(path)
        # Every two-screen (8-knob) effect seen in a patch takes two chain
        # positions and every one-screen effect takes one; apply that rule to the rest.
        e["slots"] = 2 if len(e["params"]) > 4 else 1
        e["slots_confirmed"] = e["id"] in seen_two or len(e["params"]) <= 4
        if e["id"] in seen_two and e["slots"] != 2:
            raise ValueError("%s breaks the two-screen rule" % e["name"])
        effects[e["id"]] = e
    for k, v in BUILTINS.items():
        effects[k] = dict(v, id=k, file=None, slots=1, slots_confirmed=True, params=[], dsp=None)
    json.dump(effects, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
