"""Gigs: an ordered setlist of patches loaded into a run of slots.

    {
     "name": "Friday at the Legion",
     "start_slot": 80,
     "patches": [
      {"song": "Sultans of Swing", "tone": {"name": "SULTANS", "chain": [...]}},
      {"song": "Free Bird", "from_slot": 121},
      {"song": "Mr Brightside", "file": "tones/brightside.json"}
     ]
    }

Each entry is a tone (tone JSON), a copy of a slot already on the pedal
(`from_slot`), or a .json/.zptc/.zg3xn file. An entry may set "slot" to pin
it; otherwise entries fill consecutive slots from start_slot. Entries may
also carry "notes", "tempo" and "key" for the stage view.

GigLibrary keeps gigs as JSON files (the app's saved setlists).
"""
import datetime
import json
import os
import re
import uuid

from .patch import Patch


def load(path):
    with open(path, encoding="utf-8") as f:
        gig = json.load(f)
    gig["_dir"] = os.path.dirname(os.path.abspath(path))
    return gig


def plan(pedal, gig):
    """Work out what goes where, without writing. Returns a list of steps."""
    steps, slot, used = [], gig.get("start_slot", 1), set()
    for i, entry in enumerate(gig["patches"], 1):
        target = entry.get("slot", slot)
        if target in used:
            raise ValueError("entry %d: slot %d is used twice" % (i, target))
        if target == pedal.scratch:
            raise ValueError("entry %d: slot %d is the scratch slot" % (i, target))
        used.add(target)
        patch = _resolve(pedal, entry, gig.get("_dir", "."))
        problems = patch.problems()
        if problems:
            raise ValueError("entry %d (%s): %s" % (i, patch.name, "; ".join(problems)))
        current = pedal.read(target).name
        steps.append({"order": i, "song": entry.get("song") or patch.name, "slot": target, "patch": patch.name,
                      "replaces": current, "overwrites_real_patch": current != "Empty",
                      "_patch": patch})
        slot = target + 1
    return steps


def write(pedal, gig, backup_dir=None):
    """Back up the pedal, then write every entry. Returns (steps, backup folder)."""
    steps = plan(pedal, gig)
    backup_dir = backup_dir or os.path.join(os.path.expanduser("~"), "g3xn-backups",
                                            datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    pedal.backup(backup_dir)
    if pedal.current() in {s["slot"] for s in steps}:
        pedal.select(pedal.scratch)
    for s in steps:
        pedal.write(s["slot"], s["_patch"])
    pedal.select(steps[0]["slot"])
    return steps, backup_dir


def export(pedal, first, last, name="Exported gig"):
    """A gig file (with full tones) for slots first..last."""
    patches = []
    for n in range(first, last + 1):
        p = pedal.read(n)
        if p.name == "Empty":
            continue
        patches.append({"song": p.name, "slot": n,
                        "tone": {"name": p.name, "volume": p.volume,
                                 "chain": [{"effect": c.name, "on": c.enabled, "knobs": c.knobs()} for c in p.chain]}})
    return {"name": name, "start_slot": first, "patches": patches}


class GigLibrary:
    """Saved gigs, one JSON file each. A gig's "id" is its file name."""

    def __init__(self, folder):
        self.folder = folder

    def list(self):
        out = []
        for name in sorted(os.listdir(self.folder)) if os.path.isdir(self.folder) else []:
            if name.endswith(".json"):
                try:
                    g = self.get(name[:-5])
                except (OSError, ValueError):
                    continue
                out.append({"id": g["id"], "name": g.get("name", ""), "songs": len(g.get("patches", [])),
                            "start_slot": g.get("start_slot"), "loaded": g.get("loaded")})
        return sorted(out, key=lambda g: g["name"].lower())

    def get(self, gig_id):
        with open(self._path(gig_id), encoding="utf-8") as f:
            gig = json.load(f)
        gig["id"] = gig_id
        return gig

    def save(self, gig):
        """Create or update; returns the saved gig (with its id)."""
        gig = dict(gig)
        gig_id = gig.get("id") or "%s-%s" % (re.sub(r"[^a-z0-9]+", "-", gig.get("name", "gig").lower()).strip("-")[:40]
                                             or "gig", uuid.uuid4().hex[:6])
        gig["id"] = gig_id
        os.makedirs(self.folder, exist_ok=True)
        tmp = self._path(gig_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(gig, f, indent=1)
        os.replace(tmp, self._path(gig_id))
        return gig

    def delete(self, gig_id):
        os.remove(self._path(gig_id))

    def _path(self, gig_id):
        if not re.fullmatch(r"[a-z0-9-]+", gig_id or ""):
            raise ValueError("bad gig id %r" % gig_id)
        return os.path.join(self.folder, gig_id + ".json")


def public(steps):
    return [{k: v for k, v in s.items() if not k.startswith("_")} for s in steps]


def _resolve(pedal, entry, base):
    if "tone" in entry:
        return Patch.from_dict(entry["tone"])
    if "from_slot" in entry:
        return pedal.read(entry["from_slot"])
    if "file" in entry:
        path = entry["file"] if os.path.isabs(entry["file"]) else os.path.join(base, entry["file"])
        if path.lower().endswith(".json"):
            with open(path, encoding="utf-8") as f:
                return Patch.from_dict(json.load(f))
        return Patch.load(path)
    raise ValueError("gig entry needs tone, from_slot or file: %r" % entry)
