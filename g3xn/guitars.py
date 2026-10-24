"""Which guitar each tone is for: "Strat", "Les Paul", "the Tele in Eb"... The pedal has nowhere to
keep it, so it lives here, by slot:

    ~/.g3xn/guitars.json    {"slots": {"12": "Strat", "101": "Les Paul"}}

A gig can also name a song's guitar; loading the gig carries it (or the guitar of the slot the
song's patch came from) to the slot the song goes into.
"""
import json
import os
import threading

FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "guitars.json")
LONGEST = 40


class Guitars:
    def __init__(self, path=None):
        """path: where it's kept (None = only until the daemon stops)."""
        self.path = path
        self._lock = threading.Lock()
        self.slots = {}
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    self.slots = {int(k): v for k, v in json.load(f).get("slots", {}).items() if v}
            except (OSError, ValueError, AttributeError):
                self.slots = {}

    def get(self, slot):
        return self.slots.get(int(slot)) if slot is not None else None

    def set(self, slot, guitar):
        """Name the guitar for a slot's tone ("" or None forgets it)."""
        slot = int(slot)
        if not 1 <= slot <= 999:
            raise ValueError("no slot %d" % slot)
        guitar = " ".join((guitar or "").split())[:LONGEST]
        with self._lock:
            if guitar:
                self.slots[slot] = guitar
            else:
                self.slots.pop(slot, None)
            self._save()
        return guitar or None

    def names(self):
        """Every guitar named so far, most used first."""
        count = {}
        for g in self.slots.values():
            count[g] = count.get(g, 0) + 1
        return sorted(count, key=lambda g: (-count[g], g.lower()))

    def info(self):
        return {"slots": {str(k): v for k, v in sorted(self.slots.items())}, "names": self.names()}

    def _save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"slots": {str(k): v for k, v in sorted(self.slots.items())}}, f, indent=1)
        os.replace(tmp, self.path)
