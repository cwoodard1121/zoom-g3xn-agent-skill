"""Command line for the Zoom G3n / G3Xn.

    g3xn info                         pedal, firmware, current patch
    g3xn list                         every slot's name
    g3xn show 121                     a slot's chain and knobs (as the pedal displays them)
    g3xn show tone.json|tone.zptc     a patch file
    g3xn effects [text] [--group AMP] search the effect catalog
    g3xn effect "FD TWNR"             one effect's knobs, ranges and defaults
    g3xn select 121                   switch patches

    g3xn audition tone.json|.zptc|121 hear a patch now, on the scratch slot
    g3xn set "FD TWNR" Gain 45        tweak the scratch patch live
    g3xn on|off "TS Drive"            toggle an effect live
    g3xn volume 95                    patch level live
    g3xn save 123                     store the scratch patch into a slot

    g3xn export 121 out.json|out.zptc save a slot to a file
    g3xn write tone.json 123          write a file straight into a slot
    g3xn build tone.json out.zptc     convert / validate offline
    g3xn backup [folder]              copy every slot to .zptc files
    g3xn tuner [seconds]              live tuner readout

Add --json to any command for machine-readable output.
Live edits only ever touch the scratch slot (default 150, --scratch N).
"""
import argparse
import datetime
import json
import os
import sys

from . import Patch, Pedal, PedalError, catalog


def main(argv=None):
    ap = argparse.ArgumentParser(prog="g3xn", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--scratch", type=int, default=150, help="slot used for auditions (default 150)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info")
    sub.add_parser("list")
    sub.add_parser("show").add_argument("source")
    s = sub.add_parser("effects")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("--group")
    sub.add_parser("effect").add_argument("name")
    sub.add_parser("select").add_argument("slot", type=int)

    sub.add_parser("audition").add_argument("source")
    s = sub.add_parser("set")
    s.add_argument("effect")
    s.add_argument("knob")
    s.add_argument("value", type=int)
    sub.add_parser("on").add_argument("effect")
    sub.add_parser("off").add_argument("effect")
    sub.add_parser("volume").add_argument("value", type=int)
    sub.add_parser("save").add_argument("slot", type=int)

    s = sub.add_parser("export")
    s.add_argument("slot", type=int)
    s.add_argument("file")
    s = sub.add_parser("write")
    s.add_argument("file")
    s.add_argument("slot", type=int)
    s = sub.add_parser("build")
    s.add_argument("file")
    s.add_argument("out", nargs="?")
    sub.add_parser("backup").add_argument("folder", nargs="?")
    sub.add_parser("tuner").add_argument("seconds", nargs="?", type=float, default=10)

    a = ap.parse_args(argv)
    try:
        result = COMMANDS[a.cmd](a)
    except (PedalError, KeyError, ValueError, IndexError, FileNotFoundError) as err:
        msg = err.args[0] if isinstance(err, KeyError) and err.args else str(err)
        if a.json:
            print(json.dumps({"error": msg}))
        else:
            print("error: %s" % msg, file=sys.stderr)
        return 1
    if result is not None:
        print(json.dumps(result, indent=1) if a.json else render(result))
    return 0


# --- commands (each returns plain data; render() makes it readable) ---

def cmd_info(a):
    with Pedal(a.scratch) as pedal:
        info = pedal.identity()
        n = pedal.current()
        info.update(current=n, current_name=pedal.read(n).name, scratch=a.scratch)
        return info


def cmd_list(a):
    with Pedal(a.scratch) as pedal:
        return [{"slot": n, "name": pedal.read(n).name} for n in range(1, pedal.patch_count + 1)]


def cmd_show(a):
    if a.source.isdigit():
        with Pedal(a.scratch) as pedal:
            slot = int(a.source)
            live = pedal.current() == slot
            patch = pedal.edit_buffer() if live else pedal.read(slot)   # live = what you hear
            out = patch.to_dict()
            out["slot"] = slot
            if live:
                for fx, d in zip(out["chain"], pedal.display()):
                    fx["shown"] = d["knobs"]
            return out
    return load_patch(a.source).to_dict()


def cmd_effects(a):
    return [{"name": e.name, "group": e.group, "positions": e.positions, "dsp_percent": e.dsp_percent,
             "description": e.description} for e in catalog().search(a.text, a.group)]


def cmd_effect(a):
    return catalog().get(a.name).summary()


def cmd_select(a):
    with Pedal(a.scratch) as pedal:
        pedal.select(a.slot)
        return {"slot": a.slot, "name": pedal.read(a.slot).name}


def cmd_audition(a):
    with Pedal(a.scratch) as pedal:
        patch = pedal.read(int(a.source)) if a.source.isdigit() else load_patch(a.source)
        pedal.audition(patch)
        return {"auditioning": patch.name, "scratch": a.scratch, **patch.to_dict()}


def _live(a, change):
    with Pedal(a.scratch) as pedal:
        if pedal.current() != a.scratch:
            raise PedalError("nothing is being auditioned; run `g3xn audition ...` first")
        patch = pedal.edit_buffer()
        change(patch)
        pedal.push(patch)
        return pedal.edit_buffer().to_dict()


def cmd_set(a):
    return _live(a, lambda p: p.effect(_fx_key(a.effect)).__setitem__(a.knob, a.value))


def cmd_on(a):
    return _live(a, lambda p: setattr(p.effect(_fx_key(a.effect)), "enabled", True))


def cmd_off(a):
    return _live(a, lambda p: setattr(p.effect(_fx_key(a.effect)), "enabled", False))


def cmd_volume(a):
    return _live(a, lambda p: setattr(p, "volume", a.value))


def cmd_save(a):
    with Pedal(a.scratch) as pedal:
        pedal.save_scratch(a.slot)
        return {"saved": pedal.read(a.slot).name, "slot": a.slot}


def cmd_export(a):
    with Pedal(a.scratch) as pedal:
        patch = pedal.read(a.slot)
    save_patch(patch, a.file)
    return {"exported": patch.name, "file": a.file}


def cmd_write(a):
    patch = load_patch(a.file)
    with Pedal(a.scratch) as pedal:
        pedal.write(a.slot, patch)
    return {"written": patch.name, "slot": a.slot}


def cmd_build(a):
    patch = load_patch(a.file)
    problems = patch.problems()
    if a.out and not problems:
        save_patch(patch, a.out)
    return {"patch": patch.to_dict(), "problems": problems, "file": a.out if not problems else None}


def cmd_backup(a):
    folder = a.folder or os.path.join("backups", datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    with Pedal(a.scratch) as pedal:
        pedal.backup(folder)
    return {"backup": os.path.abspath(folder)}


def cmd_tuner(a):
    with Pedal(a.scratch) as pedal:
        pedal.tuner(True)
        try:
            last = None
            for r in pedal.tuner_readings(a.seconds):
                if r != last and not a.json:
                    bar = "-" * 7
                    pos = max(0, min(14, r["meter"] + 7))
                    line = (bar + "|" + bar)[:pos] + "o" + (bar + "|" + bar)[pos + 1:]
                    print("\r%-2s [%s] %+d  " % (r["note"] or "-", line, r["meter"]), end="", flush=True)
                last = r
        finally:
            pedal.tuner(False)
    if not a.json:
        print()
    return None


COMMANDS = {k[4:]: v for k, v in globals().items() if k.startswith("cmd_")}


# --- helpers ---

def _fx_key(text):
    return int(text) if text.isdigit() else text


def load_patch(path):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            return Patch.from_dict(json.load(f))
    return Patch.load(path)


def save_patch(patch, path):
    if path.lower().endswith(".json"):
        spec = {"name": patch.name, "volume": patch.volume,
                "chain": [{"effect": c.name, "on": c.enabled, "knobs": c.knobs()} for c in patch.chain]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=1)
    else:
        patch.save(path)


def render(data):
    """Human-readable text for command results."""
    if isinstance(data, list):
        return "\n".join(_row(x) for x in data)
    if "chain" in data:
        lines = ["%s  (volume %s, DSP %s%%)" % (data["name"], data["volume"], data["dsp_percent"])]
        for i, fx in enumerate(data["chain"], 1):
            knobs = fx.get("shown") or fx["knobs"]
            lines.append("  %d. %-10s %-3s %s" % (i, fx["name"], "on" if fx["enabled"] else "off",
                                                  "  ".join("%s=%s" % kv for kv in knobs.items())))
        return "\n".join(lines)
    if "params" in data:
        lines = ["%s (%s, %d position%s, DSP %s%%)" % (data["name"], data["group"], data["positions"],
                                                       "s" if data["positions"] > 1 else "", data["dsp_percent"]),
                 "  " + data["description"]]
        lines += ["  %-10s 0..%-5d default %-5d %s" % (p["name"], p["max"], p["default"], p["explanation"])
                  for p in data["params"]]
        return "\n".join(lines)
    if "patch" in data:
        return render(data["patch"]) + ("\nproblems: " + "; ".join(data["problems"]) if data["problems"] else
                                        "\nok" + (" -> " + data["file"] if data["file"] else ""))
    return "  ".join("%s: %s" % kv for kv in data.items())


def _row(x):
    if "slot" in x:
        return "%3d  %s" % (x["slot"], x["name"])
    return "%-11s %-10s %d pos  %5.1f%%  %s" % (x["name"], x["group"], x["positions"], x["dsp_percent"],
                                                x["description"][:60])


if __name__ == "__main__":
    sys.exit(main())
