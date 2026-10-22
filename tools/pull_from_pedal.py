"""Pull everything the catalog is built from off a connected pedal.

    python tools/pull_from_pedal.py data
    python tools/build_catalog.py data > g3xn/data/effects.json

Writes data/pedal_dump/ (every slot), data/pedal_files/ (.ZD2 effects) and
data/templates.json (what the pedal stores when each effect is loaded fresh,
recorded on the scratch slot, which must be Empty and is left Empty).
"""
import json
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from g3xn import Patch, Pedal  # noqa: E402

EXTRA_IDS = ["0x1e000010", "0x1f000010", "0x1f000020", "0x1f000030", "0x1f000040"]  # Rhythm + loopers


def effect_id(path):
    """The u32 effect id that follows the "N.NN\\0\\0" version string in a ZD2 header."""
    data = open(path, "rb").read(0x80)
    at = re.search(rb"\d\.\d\d\x00\x00", data).start()
    return "0x%08x" % struct.unpack_from("<I", data, at + 7)[0]


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "data"
    with Pedal() as pedal:
        print("backing up %d slots..." % pedal.patch_count)
        pedal.backup(os.path.join(root, "pedal_dump"))

        files_dir = os.path.join(root, "pedal_files")
        os.makedirs(files_dir, exist_ok=True)
        names = [n for n in pedal.list_files() if n.endswith((".ZD2", ".ZT2"))]
        print("reading %d effect files..." % len(names))
        for n in names:
            with open(os.path.join(files_dir, n), "wb") as f:
                f.write(pedal.read_file(n))

        print("recording effect templates on scratch slot %d..." % pedal.scratch)
        empty = Patch.blank("Empty")
        if pedal.read(pedal.scratch).name != "Empty":
            sys.exit("scratch slot %d is not Empty" % pedal.scratch)
        parking = pedal.scratch - 1
        ids = [effect_id(os.path.join(files_dir, n)) for n in names if n.endswith(".ZD2")]
        templates = {}
        for h in ids + EXTRA_IDS:
            pedal.select(parking)
            pedal.write(pedal.scratch, empty)
            pedal.select(pedal.scratch)
            pedal.set_effect(0, int(h, 16))
            time.sleep(0.1)
            s = pedal.edit_buffer().slots
            templates[h] = {"loaded_id": "0x%08x" % s[0].id, "record": s[0].pack().hex(),
                            "params": s[0].knobs, "enabled": s[0].enabled, "next_id": "0x%08x" % s[1].id}
        pedal.select(parking)
        pedal.write(pedal.scratch, empty)
    with open(os.path.join(root, "templates.json"), "w") as f:
        json.dump(templates, f, indent=1)
    print("done")


if __name__ == "__main__":
    main()
