"""Backups of the whole pedal: one folder of NNN_NAME.zptc files per backup.

    ~/g3xn-backups/2026-10-22_210634/        a backup made on purpose (g3xn backup, a gig load)
    ~/g3xn-backups/auto/2026-10-23_101500/   one made when the pedal was plugged in

Every time the daemon connects to the pedal it reads all 150 slots anyway (for their names), so it
keeps them as an automatic backup, but only when something changed since the last one.
`history()` lists every backup with what changed since the one before it; `slot()` reads one patch
back out, for putting a single slot back.
"""
import datetime
import os
import re

from .patch import Patch

FOLDER = os.path.join(os.path.expanduser("~"), "g3xn-backups")
FILE = re.compile(r"^(\d{3})_.*\.zptc$")
STAMP = "%Y-%m-%d_%H%M%S"


class Backups:
    def __init__(self, root=FOLDER):
        self.root = root

    def auto(self, patches):
        """Keep {slot: raw bytes} as a backup if anything differs from the last automatic one.
        Returns the new folder, or None when nothing changed."""
        last = self._latest_auto()
        if last and self._load(last) == patches:
            return None
        folder = os.path.join(self.root, "auto", datetime.datetime.now().strftime(STAMP))
        write(folder, patches)
        return folder

    def history(self):
        """Every backup, newest first: {"name", "time", "auto", "slots", "changed": [{slot, was, now}]},
        "changed" being what differs from the backup before it."""
        found = sorted(self._folders(), key=lambda f: f[1])
        out, before = [], None
        for path, when, auto in found:
            patches = self._load(path)
            changed = []
            if before is not None:
                for n in sorted(set(patches) | set(before)):
                    if patches.get(n) != before.get(n):
                        changed.append({"slot": n, "was": _name(before.get(n)), "now": _name(patches.get(n))})
            out.append({"name": self._name_of(path), "time": when.timestamp(), "auto": auto,
                        "slots": len(patches), "changed": changed, "first": before is None})
            before = patches
        return out[::-1]

    def slot(self, name, n):
        """The raw patch slot `n` held in backup `name`."""
        path = self._path_of(name)
        data = self._load(path).get(n)
        if data is None:
            raise KeyError("backup %s has no slot %d" % (name, n))
        return data

    # --- folders ---

    def _folders(self):
        """(path, time, auto) for each backup folder."""
        for sub, auto in (("", False), ("auto", True)):
            base = os.path.join(self.root, sub)
            if not os.path.isdir(base):
                continue
            for entry in os.listdir(base):
                path = os.path.join(base, entry)
                try:
                    when = datetime.datetime.strptime(entry[:17], STAMP)
                except ValueError:
                    continue
                if os.path.isdir(path):
                    yield path, when, auto

    def _latest_auto(self):
        autos = [f for f in self._folders() if f[2]]
        return max(autos, key=lambda f: f[1])[0] if autos else None

    def _name_of(self, path):
        rel = os.path.relpath(path, self.root)
        return rel.replace(os.sep, "/")

    def _path_of(self, name):
        parts = name.split("/")
        if not 1 <= len(parts) <= 2 or (len(parts) == 2 and parts[0] != "auto") or any(p in ("", ".", "..") for p in parts):
            raise KeyError("no backup called %s" % name)
        path = os.path.join(self.root, *parts)
        if not os.path.isdir(path):
            raise KeyError("no backup called %s" % name)
        return path

    @staticmethod
    def _load(path):
        patches = {}
        for entry in os.listdir(path):
            m = FILE.match(entry)
            if m:
                with open(os.path.join(path, entry), "rb") as f:
                    patches[int(m.group(1))] = f.read()
        return patches


def write(folder, patches):
    """Save {slot: raw bytes} as NNN_NAME.zptc files (the same layout Pedal.backup writes)."""
    os.makedirs(folder, exist_ok=True)
    for n, data in sorted(patches.items()):
        name = "".join(c if c.isalnum() or c in " -_" else "_" for c in _name(data)) or "blank"
        with open(os.path.join(folder, "%03d_%s.zptc" % (n, name.strip())), "wb") as f:
            f.write(data)
    return folder


def _name(data):
    if data is None:
        return None
    try:
        return Patch.decode(data).name
    except Exception:          # a damaged file still lists, just without a name
        return "?"
