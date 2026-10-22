"""Build g3xn/data/effects.json from the pedal's own files.

    python tools/pull_from_pedal.py data/            # .ZD2 files, patch backup, templates
    python tools/build_catalog.py data/ > g3xn/data/effects.json

Inputs (all inside the data folder):
    pedal_files/*.ZD2   effect binaries read off the pedal
    pedal_dump/*.zptc   a backup of every patch slot (to cross-check slot usage)
    templates.json      what the pedal stores when each effect is loaded fresh

ZD2 = "ZDLF" container: header (version, id, name, group), then tagged chunks
ICON / TXJ1 / TXE1 (English description) / INFO (DSP load as a float, last 4
bytes) / DATA (TI C6x ELF with the DSP code) / PRMJ / PRME (JSON: knob names +
explanations).

Knob ranges and defaults are not in PRME. They live in the ELF's .const section
as 56-byte records starting at "OnOff": name[12], max u32, default u32, ...
Record 0 is OnOff, record 1 the effect itself, records 2.. the knobs in EDTB
order.
"""
import glob
import io
import json
import os
import re
import struct
import sys

from elftools.elf.elffile import ELFFile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from g3xn.patch import CONTINUATION_ID, Patch  # noqa: E402

RECORD = 0x38

# Built into the firmware (no .ZD2). IDs from patches and mungewell/zoom-zt2#34;
# knob names from the pedal's own screen.
BUILTINS = {
    "0x1e000010": ("Rhythm", "RHYTHM", ["Pattern", "Dummy", "BPM", "VOL"]),
    "0x1f000010": ("LP Mono", "LOOPER", ["Time", "Undo", "Stop", "VOL"]),
    "0x1f000020": ("LP Stereo", "LOOPER", ["Time", "Undo", "Stop", "VOL"]),
    "0x1f000030": ("LP Mono 2", "LOOPER", ["Unused", "Unused", "Unused", "Unused", "Time", "Undo", "Stop", "VOL"]),
    "0x1f000040": ("LP Stereo 2", "LOOPER", ["Unused", "Unused", "Unused", "Unused", "Time", "Undo", "Stop", "VOL"]),
}


def chunks(data):
    out = {}
    for tag in (b"TXE1", b"INFO", b"DATA", b"PRME"):
        i = data.find(tag, 0x60)
        if i >= 0:
            (n,) = struct.unpack_from("<I", data, i + 4)
            out[tag.decode()] = data[i + 8:i + 8 + n]
    return out


def cstr(b):
    return b.split(b"\x00", 1)[0].decode("ascii", "replace")


def parse_zd2(path):
    data = open(path, "rb").read()
    c = chunks(data)
    at = re.search(rb"\d\.\d\d\x00\x00", data[:0x80]).start()
    (effect_id,) = struct.unpack_from("<I", data, at + 7)
    names = data[at + 11:at + 33]

    prme = json.loads(c["PRME"].decode("ascii", "replace"))["Parameters"]
    (dsp,) = struct.unpack_from("<f", c["INFO"], len(c["INFO"]) - 4)

    const = ELFFile(io.BytesIO(c["DATA"])).get_section_by_name(".const").data()
    base = const.find(b"OnOff\x00")
    if base < 0:
        raise ValueError("%s: no OnOff record" % path)
    records = []
    for k in range(2 + len(prme)):
        r = const[base + k * RECORD:base + (k + 1) * RECORD]
        records.append(struct.unpack_from("<2I", r, 12))

    return {
        "id": "0x%08x" % effect_id,
        "name": cstr(names[:11]),
        "group": cstr(names[11:]),
        "file": os.path.basename(path),
        "version": data[at:at + 4].decode(),
        "dsp": round(dsp, 2),
        "description": c.get("TXE1", b"").decode("ascii", "replace").strip(),
        "params": [{"name": meta.get("name", ""), "max": mx, "default": default,
                    "explanation": meta.get("explanation", ""), "pedal": bool(meta.get("pedal"))}
                   for (mx, default), meta in zip(records[2:], prme)],
    }


def observed_two_position(dump_dir):
    two = set()
    for f in glob.glob(os.path.join(dump_dir, "*.zptc")):
        slots = Patch.load(f).slots
        two.update("0x%08x" % a.id for a, b in zip(slots, slots[1:]) if b.id == CONTINUATION_ID)
    return two


def display_rule(param_max, seen):
    """From {raw: screen text} samples, a rule the library can apply offline:
    {"offset": n} (shown = raw + n) or {"options": [...]} (shown = options[raw]).
    Samples were read quickly, so blank/stale readings are ignored and only
    rules that several clean readings agree on are kept."""
    seen = {int(k): v for k, v in seen.items() if v}
    nums = {k: float(v) for k, v in seen.items() if re.fullmatch(r"-?\d+(\.\d+)?", v)}
    if nums:
        offsets = {}
        for k, v in nums.items():
            offsets[round(v - k, 3)] = offsets.get(round(v - k, 3), 0) + 1
        off, n = max(offsets.items(), key=lambda kv: kv[1])
        if n >= 3 and n >= 0.7 * len(nums) and len(nums) >= 0.6 * len(seen):
            return {"offset": int(off) if off == int(off) else off}
    elif param_max <= 24 and len(seen) == param_max + 1:
        return {"options": [seen[i] for i in range(param_max + 1)]}
    return None


def main():
    root = sys.argv[1]
    templates = json.load(open(os.path.join(root, "templates.json")))
    display_path = os.path.join(root, "display.json")
    display = json.load(open(display_path)) if os.path.exists(display_path) else {}
    seen_two = observed_two_position(os.path.join(root, "pedal_dump"))

    effects = {}
    for path in sorted(glob.glob(os.path.join(root, "pedal_files", "*.ZD2"))):
        e = parse_zd2(path)
        effects[e["id"]] = e
    for k, (name, group, knobs) in BUILTINS.items():
        t = templates[k]
        effects[k] = {"id": k, "name": name, "group": group, "file": None, "version": None, "dsp": 0.0,
                      "description": "Built into the firmware.",
                      "params": [{"name": n, "max": 127, "default": d, "explanation": "", "pedal": False}
                                 for n, d in zip(knobs, t["params"])]}

    for k, e in effects.items():
        t = templates[k]
        if t["loaded_id"] != k:
            raise ValueError("%s did not load on the pedal" % e["name"])
        e["slots"] = 2 if t["next_id"] == "0x%08x" % CONTINUATION_ID else 1
        if k in seen_two and e["slots"] != 2:
            raise ValueError("%s: template and backups disagree on positions" % e["name"])
        e["template"] = t["record"]
        for p in e["params"]:
            rule = display_rule(p["max"], display.get(k, {}).get(p["name"], {}))
            if rule:
                p["display"] = rule

    json.dump(effects, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
