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

from .catalog import catalog
from .history import changes, describe
from .patch import Patch

FOLDER = os.path.join(os.path.expanduser("~"), ".g3xn", "gigs")     # where the app keeps saved gigs
CHANGES = ("knob", "volume", "on", "off", "add", "remove")


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
        # A song whose patch is already in its slot (from_slot is the slot itself) is left as it is.
        in_place = entry.get("from_slot") == target and "tone" not in entry and "file" not in entry
        steps.append({"order": i, "song": entry.get("song") or patch.name, "slot": target, "patch": patch.name,
                      "replaces": current, "replaces_own": own, "in_place": in_place,
                      "overwrites_real_patch": current != "Empty" and not own and not in_place, "_patch": patch})
        slot = target + 1
    return steps


def write(pedal, gig, backup_dir=None):
    """Back up the pedal, then write every entry. Returns (steps, backup folder)."""
    steps = plan(pedal, gig)
    backup_dir = backup_dir or os.path.join(os.path.expanduser("~"), "g3xn-backups",
                                            datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    pedal.backup(backup_dir)
    writes = [s for s in steps if not s["in_place"]]
    if pedal.current() in {s["slot"] for s in writes}:
        pedal.select(pedal.scratch)
    for s in writes:
        pedal.write(s["slot"], s["_patch"])
    pedal.select(steps[0]["slot"])
    return steps, backup_dir


def snapshot(steps):
    """What `write` put in each slot, kept with the gig so changes can be found and undone later."""
    return [{"song": s["song"], "slot": s["slot"], "patch": s["patch"],
             "data": base64.b64encode(s["_patch"].encode()).decode("ascii")} for s in steps]


def differences(pedal, loaded):
    """The songs whose slot no longer holds what the gig loaded there (`loaded` from `snapshot`).
    Each has "change", e.g. "Hall Mix 40 → 55; Volume 90 → 80" (from what was loaded to what's there now)."""
    out = []
    for s in loaded:
        if "data" not in s:                       # loaded before snapshots were kept
            continue
        want, now = Patch.decode(base64.b64decode(s["data"])), pedal.read(s["slot"])
        if _plain(now) != _plain(want):
            change = "; ".join(changes(_plain(want), _plain(now)))
            if describe(_plain(want), _plain(now))[0].startswith("Loaded "):     # a different tone altogether
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


def batch_edit(pedal, gig, edit):
    """Make one change to every song of a gig. The pedal is only read (for from_slot songs);
    load the gig again to put the result on it. Returns (edited gig, report).

    edit is one of:
        {"change": "knob", "effects": "reverb", "knob": "Mix", "percent": -10}
        {"change": "volume", "by": 5}
        {"change": "off", "effects": "delay"}                (or "on")
        {"change": "add", "effect": "Gt GEQ", "at": 1, "knobs": {...}}   (at: chain number; default the end)
        {"change": "remove", "effects": "Comp"}
    "effects" is a group (reverb, delay, drive, amp, cabinet, modulation, filter, dynamics,
    pedal, sfx), an effect name, a list of those, or "all". Amounts: "percent" (of the
    current value), "by" (added to the stored value) or "to" (set), clamped to the knob's range.

    A song is left as it was, and the report says why, when nothing in it matches, when the
    result wouldn't fit on the pedal (positions or DSP), or when it's already that way. A song
    that copied a slot (from_slot) becomes its own tone when it changes."""
    kind = edit.get("change")
    if kind not in CHANGES:
        raise ValueError("change must be one of: %s" % ", ".join(CHANGES))
    if kind in ("knob", "volume") and not {"percent", "by", "to"} & set(edit):
        raise ValueError("say how much: percent, by or to")
    if kind == "knob" and not edit.get("knob"):
        raise ValueError("which knob? e.g. \"knob\": \"Mix\"")
    if kind == "add":
        edit = dict(edit, effect=catalog().get(edit.get("effect") or "").name)
    match = _matcher(edit.get("effects")) if kind in ("knob", "on", "off", "remove") else None

    entries, report, knobs = [], [], set()
    for i, entry in enumerate(gig["patches"], 1):
        patch = _resolve(pedal, entry, gig.get("_dir", "."))
        song = entry.get("song") or patch.name
        before = _plain(patch)
        if match:
            knobs.update(p.name for c in patch.chain if c.effect and match(c) for p in c.effect.params)
        try:
            why_not = _apply(patch, kind, edit, match)
        except (ValueError, KeyError, IndexError) as err:
            why_not = err.args[0] if err.args else str(err)
        if not why_not and patch.problems():
            why_not = "wouldn't fit: " + "; ".join(patch.problems())
        elif not why_not and _plain(patch) == before:
            why_not = "already that way"
        if why_not:
            entries.append(entry)
            report.append({"order": i, "song": song, "change": None, "left_alone": why_not})
            continue
        after = _plain(patch)
        entries.append(dict({k: v for k, v in entry.items() if k not in ("tone", "from_slot", "file")}, tone=after))
        report.append({"order": i, "song": song, "change": "; ".join(changes(before, after)), "left_alone": None,
                       "was_a_copy_of_slot": entry.get("from_slot")})
    if kind == "knob" and knobs and not _has_knob_named(knobs, edit["knob"]):
        raise ValueError("no %s in this gig has a %r knob; their knobs are: %s"
                         % (_describe_match(edit["effects"]), edit["knob"], ", ".join(sorted(knobs))))
    return dict(gig, patches=entries), report


def _apply(patch, kind, edit, match):
    """Change one patch; returns why it was left alone, or None."""
    if kind == "volume":
        patch.volume = _amount(patch.volume, edit, 100)
        return None
    if kind == "add":
        if any(c.name == edit["effect"] for c in patch.chain):
            return "already has %s" % edit["effect"]
        at = edit.get("at")
        patch.add(edit["effect"], at=at if isinstance(at, int) and at <= len(patch.chain) else None,
                  knobs=edit.get("knobs"))
        return None
    hits = [n for n, c in enumerate(patch.chain, 1) if match(c)]
    if kind == "knob":
        hits = [n for n in hits if _has_knob(patch.chain[n - 1], edit["knob"])]
    if not hits:
        return "no %s%s" % (_describe_match(edit.get("effects")),
                             " with a %s knob" % edit["knob"] if kind == "knob" else "")
    for n in sorted(hits, reverse=True):          # from the end, so removing keeps the numbers right
        c = patch.chain[n - 1]
        if kind == "knob":
            p = c.effect.param(edit["knob"])
            c[p.name] = _amount(c[p.name], edit, p.max)
        elif kind == "remove":
            patch.remove(n)
        else:
            c.enabled = kind == "on"
    return None


def _amount(value, edit, top):
    if "to" in edit:
        new = edit["to"]
    elif "by" in edit:
        new = value + edit["by"]
    else:
        new = value * (1 + edit["percent"] / 100)
    return max(0, min(top, int(round(new))))


def _matcher(effects):
    """A test for chain effects from a group name, an effect name, a list of those, or "all"."""
    if not effects:
        raise ValueError("which effects? a group (%s), an effect name, or \"all\"" % ", ".join(catalog().groups()).lower())
    groups = {g.lower() for g in catalog().groups()}
    names, kinds = set(), set()
    for item in [effects] if isinstance(effects, str) else effects:
        if item.lower() == "all":
            return lambda c: True
        group = item.lower() if item.lower() in groups else item.lower()[:-1]    # "reverbs" works too
        if group in groups:
            kinds.add(group)
        else:
            names.add(catalog().get(item).name)
    return lambda c: c.name in names or (c.effect is not None and c.effect.group.lower() in kinds)


def _has_knob(c, knob):
    try:
        return c.effect is not None and c.effect.param(knob) is not None
    except KeyError:
        return False


def _has_knob_named(names, knob):
    key = re.sub(r"[^a-z0-9]", "", knob.lower())
    return any(re.sub(r"[^a-z0-9]", "", n.lower()) == key for n in names)


def _describe_match(effects):
    if effects == "all" or effects == ["all"]:
        return "effect"
    return effects if isinstance(effects, str) else " or ".join(effects or [])


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
