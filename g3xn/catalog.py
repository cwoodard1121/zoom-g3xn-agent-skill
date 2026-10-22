"""The effect catalog: every effect the pedal can load, by name or id.

Built from the .ZD2 files on the pedal (see tools/build_catalog.py) plus a
per-effect template recorded by loading each effect on the pedal
(tools/harvest_templates.py). Ships as g3xn/data/effects.json.
"""
import json
import os
import re

DATA = os.path.join(os.path.dirname(__file__), "data", "effects.json")

# DSP units as stored in each .ZD2. ToneLib's "DSP %" is this / 2.5, so 250 = 100%.
# Inferred, not observed: no patch has been seen rejected. Factory patches peak at
# 231 (92%), so anything up to that is known to work.
DSP_BUDGET = 250.0
DSP_PROVEN = 231.3
MAX_POSITIONS = 7    # chain positions; two-screen effects take two


class Param:
    def __init__(self, index, d):
        self.index = index            # 0-based knob number (EDTB p1 = 0)
        self.name = d["name"]
        self.max = d["max"]
        self.default = d["default"]
        self.explanation = d.get("explanation", "")
        self.pedal = d.get("pedal", False)
        self.display = d.get("display")   # {"offset": n} or {"options": [...]}, if known

    def shown(self, raw):
        """The pedal's screen text for a stored value ('' if the mapping is unknown)."""
        if not self.display:
            return ""
        if "options" in self.display:
            opts = self.display["options"]
            return opts[raw] if 0 <= raw < len(opts) else ""
        return "%g" % (raw + self.display["offset"])

    def from_shown(self, text):
        """Stored value for a screen value (e.g. what a forum post quotes)."""
        text = str(text).strip()
        if self.display and "options" in self.display:
            for i, o in enumerate(self.display["options"]):
                if o.lower() == text.lower():
                    return i
            raise ValueError("%s shows one of %s" % (self.name, ", ".join(self.display["options"])))
        offset = self.display["offset"] if self.display else 0
        return self.check(int(round(float(text) - offset)))

    def check(self, value):
        if not isinstance(value, int) or not 0 <= value <= self.max:
            raise ValueError("%s must be an integer 0..%d (got %r)" % (self.name, self.max, value))
        return value

    def __repr__(self):
        return "<Param %s 0..%d default %d>" % (self.name, self.max, self.default)


class Effect:
    def __init__(self, d):
        self.id = int(d["id"], 16)
        self.name = d["name"]
        self.group = d["group"]
        self.description = d.get("description", "")
        self.dsp = d.get("dsp") or 0.0
        self.positions = d["slots"]
        self.params = [Param(i, p) for i, p in enumerate(d.get("params", []))]
        self.template = bytes.fromhex(d["template"]) if d.get("template") else None

    @property
    def dsp_percent(self):
        return round(self.dsp / DSP_BUDGET * 100, 1)

    def param(self, name):
        key = _norm(name)
        for p in self.params:
            if _norm(p.name) == key:
                return p
        raise KeyError("%s has no parameter %r (has: %s)" % (self.name, name, ", ".join(p.name for p in self.params)))

    def summary(self):
        return {
            "id": "0x%08x" % self.id,
            "name": self.name,
            "group": self.group,
            "positions": self.positions,
            "dsp_percent": self.dsp_percent,
            "description": self.description,
            "params": [dict({"name": p.name, "max": p.max, "default": p.default, "explanation": p.explanation},
                            **({"shown_as": p.display} if p.display else {}))
                       for p in self.params],
        }

    def __repr__(self):
        return "<Effect %s (%s) 0x%08x>" % (self.name, self.group, self.id)


class Catalog:
    def __init__(self, path=DATA):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.effects = [Effect(d) for d in raw.values()]
        self._by_id = {e.id: e for e in self.effects}
        self._by_name = {_norm(e.name): e for e in self.effects}

    def get(self, key):
        """Look up by id (int or '0x..' string) or name (case/punctuation-insensitive)."""
        if isinstance(key, Effect):
            return key
        if isinstance(key, int):
            if key in self._by_id:
                return self._by_id[key]
            raise KeyError("unknown effect id 0x%08x" % key)
        if re.fullmatch(r"0x[0-9a-fA-F]+", key):
            return self.get(int(key, 16))
        e = self._by_name.get(_norm(key))
        if e is None:
            close = [x.name for x in self.search(key)][:5]
            raise KeyError("unknown effect %r%s" % (key, " (did you mean: %s?)" % ", ".join(close) if close else ""))
        return e

    def find(self, effect_id):
        """Like get() by id, but returns None for unknown ids."""
        return self._by_id.get(effect_id)

    def search(self, text="", group=None):
        text = _norm(text)
        return [e for e in self.effects
                if (not group or e.group.lower() == group.lower())
                and (not text or text in _norm(e.name) or text in e.description.lower().replace(" ", ""))]

    def groups(self):
        return sorted({e.group for e in self.effects})


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


_default = None


def catalog():
    """The shared catalog instance (loaded on first use)."""
    global _default
    if _default is None:
        _default = Catalog()
    return _default
