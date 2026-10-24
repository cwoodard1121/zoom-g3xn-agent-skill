"""Backing tracks for the ghost band: one recording of a song per key, played in time with the band.

    ~/.g3xn/tracks/sultans-of-swing/track.mp3    the recording, as it was uploaded
    ~/.g3xn/tracks/sultans-of-swing/info.json    {"key", "name", "type", "size", "added"}

A key is lower-case letters, digits and dashes (the app picks it, e.g. from the song). Uploading
again under the same key replaces the recording. The folder is only made when the first one arrives.
"""
import json
import os
import re
import shutil
import time

FOLDER = os.path.join(os.path.expanduser("~"), ".g3xn", "tracks")
KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
LIMIT = 80 * 1024 * 1024
TYPES = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg", "wav": "audio/wav",
         "webm": "audio/webm", "flac": "audio/flac"}                # what each kind is served as
EXTS = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mpeg3": "mp3", "audio/x-mpeg-3": "mp3",
        "audio/mp4": "m4a", "audio/m4a": "m4a", "audio/x-m4a": "m4a", "audio/aac": "m4a",
        "audio/ogg": "ogg", "audio/opus": "ogg", "audio/wav": "wav", "audio/x-wav": "wav",
        "audio/wave": "wav", "audio/vnd.wave": "wav", "audio/webm": "webm", "audio/flac": "flac",
        "audio/x-flac": "flac"}
# Types that say nothing useful on their own (browsers call audio-only .webm and .m4a files video):
# the file's name decides.
VAGUE = ("", "application/octet-stream", "video/webm", "video/mp4", "video/ogg")


class Tracks:
    def __init__(self, root=FOLDER):
        self.root = root

    def info(self, key):
        """{"key", "name", "type", "size", "added"} for the recording under `key`, or None."""
        folder = self._folder(key)
        try:
            with open(os.path.join(folder, "info.json")) as f:
                return json.load(f)
        except (OSError, ValueError):          # none, or half written
            return None

    def put(self, key, data, name, content_type):
        """Keep `data` (the uploaded file's bytes) as the recording for `key`, replacing any earlier
        one. `name` is the file's own name; with `content_type` it says what kind of audio it is."""
        folder = self._folder(key)
        ext = _kind(name, content_type)
        if not data:
            raise ValueError("that file is empty")
        if len(data) > LIMIT:
            raise ValueError("that recording is over %d MB" % (LIMIT // (1024 * 1024)))
        os.makedirs(folder, exist_ok=True)
        new = os.path.join(folder, "upload.part")
        with open(new, "wb") as f:              # written in full before the old one goes
            f.write(data)
        try:
            for old in os.listdir(folder):       # an mp3 replaced by a wav leaves no mp3 behind
                if old.startswith("track."):
                    os.remove(os.path.join(folder, old))
            os.replace(new, os.path.join(folder, "track." + ext))
        except PermissionError:                 # Windows: it's being played right now
            os.remove(new)
            raise ValueError("that song's recording is playing; stop it, then upload again")
        info = {"key": key, "name": os.path.basename(name or "")[:200] or "%s.%s" % (key, ext),
                "type": TYPES[ext], "size": len(data), "added": time.time()}
        with open(os.path.join(folder, "info.json"), "w") as f:
            json.dump(info, f)
        return info

    def path(self, key):
        """The recording's file, or None."""
        folder = self._folder(key)
        if os.path.isdir(folder):
            for entry in os.listdir(folder):
                if entry.startswith("track."):
                    return os.path.join(folder, entry)
        return None

    def delete(self, key):
        """Forget the recording under `key`. False if there wasn't one."""
        folder = self._folder(key)
        if not os.path.isdir(folder):
            return False
        shutil.rmtree(folder)
        return True

    def list(self):
        """Every recording's info, by key."""
        if not os.path.isdir(self.root):
            return []
        found = [self.info(k) for k in sorted(os.listdir(self.root)) if KEY.fullmatch(k)]
        return [i for i in found if i]

    def _folder(self, key):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValueError("a track's key is up to 80 lower-case letters, digits and dashes (not %r)" % key)
        return os.path.join(self.root, key)


def _kind(name, content_type):
    """mp3, m4a, ogg, wav, webm or flac, from the upload's type, or its name when the type is vague."""
    kind = (content_type or "").split(";")[0].strip().lower()
    by_name = os.path.splitext(name or "")[1].lstrip(".").lower()
    if kind in EXTS:
        return EXTS[kind]
    if kind.startswith("audio/") or kind in VAGUE:
        if by_name in TYPES:
            return by_name
        raise ValueError("can't tell what kind of audio that is: send an mp3, m4a, ogg, wav, webm or flac")
    raise ValueError("that isn't audio (it's %s): send an mp3, m4a, ogg, wav, webm or flac" % kind)
