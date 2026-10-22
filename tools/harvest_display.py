"""Record how the pedal displays each knob value (raw value -> screen text).

    python tools/harvest_display.py data/display.json

For every effect, loads it on the scratch slot (must be Empty; left Empty) and
for each knob: small ranges (max <= 24) are swept fully, which captures option
lists like OFF/ON; larger ranges are sampled at 0, 1, default, max-1, max and a
few points between.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from g3xn import Patch, Pedal, catalog  # noqa: E402


def samples(p):
    if p.max <= 24:
        return list(range(p.max + 1))
    pts = {0, 1, p.default, p.max - 1, p.max} | {p.max * k // 8 for k in range(1, 8)}
    return sorted(v for v in pts if 0 <= v <= p.max)


def main():
    out_path = sys.argv[1]
    result = json.load(open(out_path)) if os.path.exists(out_path) else {}
    empty = Patch.blank("Empty")
    with Pedal() as pedal:
        parking = pedal.scratch - 1
        if pedal.read(pedal.scratch).name != "Empty":
            sys.exit("scratch slot is not Empty")
        t = time.time()
        for e in catalog().effects:
            key = "0x%08x" % e.id
            if key in result:
                continue
            pedal.select(parking)
            pedal.write(pedal.scratch, empty)
            pedal.select(pedal.scratch)
            pedal.set_effect(0, e.id)
            time.sleep(0.08)
            knobs = {}
            for p in e.params:
                screen, cell = divmod(p.index, 4)
                seen = {}
                for v in samples(p):
                    pedal.set_knob(0, p.index, v)
                    seen[v] = pedal.screen(screen)[2 + cell]["text"]
                pedal.set_knob(0, p.index, p.default)
                knobs[p.name] = seen
            result[key] = knobs
            json.dump(result, open(out_path, "w"), indent=1)
            print("%-11s %3.0fs" % (e.name, time.time() - t), flush=True)
        pedal.select(parking)
        pedal.write(pedal.scratch, empty)
    print("done")


if __name__ == "__main__":
    main()
