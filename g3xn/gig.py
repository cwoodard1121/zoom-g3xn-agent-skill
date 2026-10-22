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

GigLibrary keeps gigs as JSON files (the app's saved setlists). A gig that
has been loaded keeps a snapshot of exactly what went into each slot, so
`differences` can tell what changed since (a knob turned with autosave on)
and `restore` can put it back.
"""
import base64
import datetime
import json
import os
import re
import uuid

from .history import describe
from .patch import Patch


def load(path):
    with open(path, encoding="utf-8") as f:
        gig = json.load(f)
    gig["_dir"] = os.path.dirname(os.path.abspath(path))
    return gig


def plan(pedal, gig):
    """Work out what goes where, without writing. Returns a list of steps."""
    steps, slot, used = [], gig.get("start_slot", 1), set()
    ours = {s["slot"]: s["patch"] for s in (gig.get("loaded") or {}).get("slots", [])}   # put there by this gig
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
        own = ours.get(target) == current
        steps.append({"order": i, "song": entry.get("song") or patch.name, "slot": target, "patch": patch.name,
                      "replaces": current, "replaces_own": own, "overwrites_real_patch": current != "Empty" and not own,
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


def snapshot(steps):
    """What `write` put in each slot, kept with the gig so changes can be found and undone later."""
    return [{"song": s["song"], "slot": s["slot"], "patch": s["patch"],
             "data": base64.b64encode(s["_patch"].encode()).decode("ascii")} for s in steps]


def differences(pedal, loaded):
    """The songs whose slot no longer holds what the gig loaded there (`loaded` from `snapshot`).
    Each has "change", e.g. "Hall Mix 40 → 55" (from what was loaded to what's there now)."""
    out = []
    for s in loaded:
        if "data" not in s:                       # loaded before snapshots were kept
            continue
        want, now = Patch.decode(base64.b64decode(s["data"])), pedal.read(s["slot"])
        if _plain(now) != _plain(want):
            change = describe(_plain(want), _plain(now))[0]
            if change.startswith("Loaded "):      # a different tone altogether
                change = "Replaced by %s" % now.name
            out.append({"song": s["song"], "slot": s["slot"], "patch": s["patch"], "now": now.name,
                        "change": change, "_patch": want, "_now": now})
    return out


def restore(pedal, loaded, backup_dir):
    """Put back every song whose slot changed since the gig was loaded. The changed versions
    are saved to backup_dir first. Ends on the slot it started on (if that slot is put back,
    the pedal hops to the scratch slot for a moment). Returns the songs put back."""
    changed = differences(pedal, loaded)
    if not changed:
        return changed
    os.makedirs(backup_dir, exist_ok=True)
    for c in changed:
        c["_now"].save(os.path.join(backup_dir, "%03d_%s.zptc" % (c["slot"], _file_name(c["now"]))))
    here = pedal.current()
    if here in {c["slot"] for c in changed}:
        pedal.select(pedal.scratch)               # a write to the slot the pedal is on is lost
    for c in changed:
        pedal.write(c["slot"], c["_patch"])
    if pedal.current() != here:
        pedal.select(here)
    return changed


def _plain(patch):
    return {"name": patch.name, "volume": patch.volume,
            "chain": [{"effect": c.name, "on": c.enabled, "knobs": c.knobs()} for c in patch.chain]}


def _file_name(name):
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip() or "blank"


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
                            "start_slot": g.get("start_slot"), "loaded": shown(g)["loaded"]})
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


def shown(gig):
    """A saved gig without the patch data in its snapshot (for showing, not restoring)."""
    loaded = gig.get("loaded")
    if loaded:
        loaded = dict(loaded, slots=[{k: v for k, v in s.items() if k != "data"} for s in loaded["slots"]])
    return dict(gig, loaded=loaded)


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
