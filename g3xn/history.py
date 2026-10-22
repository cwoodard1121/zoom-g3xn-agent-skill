"""Every version of the tone being tried, so any of them can be played again.

The daemon records an entry after each audition, tweak or chain change, from
the app or from Claude, with a label saying what changed ("FD TWNR Treble
45 → 55") and, for Claude, why. Quick repeats of the same change (a knob
being dragged) fold into one entry. Undo/redo and the time machine move
`position` and replay that entry's tone; a new change after going back
drops the entries after it, like undo in any editor.
"""
import itertools
import json
import os
import threading
import time

from .catalog import catalog

LIMIT = 300
MERGE_SECONDS = 2.5
_unique = itertools.count(1)


class History:
    def __init__(self, path=None, limit=LIMIT):
        self.path = path
        self.limit = limit
        self.entries = []
        self.position = -1
        self._next_id = 1
        self._lock = threading.Lock()
        self._load()

    # --- recording ---

    def record(self, tone, source="app", reason="", merge=False):
        """Add the tone now playing. Returns the entry (None if nothing changed).
        merge: fold into the last entry if it was the same kind of change moments ago
        (a knob being dragged sends many tweaks)."""
        tone = _plain(tone)
        with self._lock:
            before = self.entries[self.position]["tone"] if self.position >= 0 else None
            label, key = describe(before, tone)
            if key is None:
                return None
            last = self.entries[self.position] if self.position >= 0 else None
            del self.entries[self.position + 1:]
            if (merge and last and last["key"] == key and last["source"] == source and not reason
                    and time.time() - last["time"] < MERGE_SECONDS and self.position >= 1):
                label, still = describe(self.entries[self.position - 1]["tone"], tone)
                if still is None:                       # dragged back to where it started
                    del self.entries[self.position]
                    self.position -= 1
                    self._save()
                    return None
                last.update(tone=tone, time=time.time(), label=label)
                entry = last
            else:
                entry = {"id": self._next_id, "time": time.time(), "label": label, "key": key,
                         "source": source, "reason": reason, "tone": tone}
                self._next_id += 1
                self.entries.append(entry)
                if len(self.entries) > self.limit:
                    del self.entries[0]
                self.position = len(self.entries) - 1
            self._save()
            return entry

    # --- moving around ---

    def find(self, entry_id):
        for i, e in enumerate(self.entries):
            if e["id"] == entry_id:
                return i
        raise KeyError("no history entry %d" % entry_id)

    def go(self, index):
        """Make entry `index` the current one; returns its tone (the caller plays it)."""
        with self._lock:
            if not 0 <= index < len(self.entries):
                raise IndexError("nothing to go back or forward to")
            self.position = index
            self._save()
            return self.entries[index]["tone"]

    def summary(self):
        """The entries without their tones (what the app lists)."""
        return {"position": self.position,
                "entries": [{k: e[k] for k in ("id", "time", "label", "source", "reason")} for e in self.entries]}

    # --- storage ---

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.entries, self.position = data["entries"], data["position"]
            self._next_id = max((e["id"] for e in self.entries), default=0) + 1
        except (OSError, ValueError, KeyError):
            pass

    def _save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"entries": self.entries, "position": self.position}, f)
        os.replace(tmp, self.path)


def describe(before, after):
    """(label, key) for the change from tone `before` to `after`. The key is the same
    for repeats of the same kind of change, so a dragged knob makes one entry.
    key is None when nothing changed."""
    if before is None:
        return "Loaded %s" % after["name"], "load:%d" % next(_unique)
    old, new = [f["effect"] for f in before["chain"]], [f["effect"] for f in after["chain"]]
    if old != new:
        if not set(old) & set(new):                     # nothing in common: a different tone
            return "Loaded %s" % after["name"], "load:%d" % next(_unique)
        return _chain_label(old, new), "chain:%d" % next(_unique)
    changes, keys = [], []
    for i, (a, b) in enumerate(zip(before["chain"], after["chain"])):
        if a["on"] != b["on"]:
            changes.append("%s %s" % (b["effect"], "on" if b["on"] else "off"))
            keys.append("on:%d" % i)
        for knob, value in b["knobs"].items():
            old = a["knobs"].get(knob)
            if old != value:
                changes.append("%s %s %s → %s" % (b["effect"], knob, _shown(b["effect"], knob, old),
                                                  _shown(b["effect"], knob, value)))
                keys.append("knob:%d:%s" % (i, knob))
    if before.get("volume") != after.get("volume"):
        changes.append("Volume %s → %s" % (before.get("volume"), after.get("volume")))
        keys.append("volume")
    if before["name"] != after["name"]:
        changes.append("Renamed to %s" % after["name"])
        keys.append("name")
    if not changes:
        return "", None
    label = changes[0] if len(changes) == 1 else "%s and %d more" % (changes[0], len(changes) - 1)
    return label, "|".join(sorted(keys))


def _chain_label(old, new):
    added = [e for e in new if e not in old]
    removed = [e for e in old if e not in new]
    parts = (["added " + ", ".join(added)] if added else []) + (["removed " + ", ".join(removed)] if removed else [])
    text = "; ".join(parts) or "reordered the chain"
    return text[0].upper() + text[1:]


def _shown(effect, knob, raw):
    """A knob value as the pedal's screen shows it."""
    if raw is None:
        return "?"
    try:
        return catalog().get(effect).param(knob).shown(raw) or str(raw)
    except KeyError:
        return str(raw)


def _plain(tone):
    """A tone as tone JSON only (no screen text or slot), so entries stay small and comparable."""
    return {"name": tone["name"], "volume": tone.get("volume"),
            "chain": [{"effect": f["effect"], "on": f["on"], "knobs": dict(f["knobs"])} for f in tone["chain"]]}
