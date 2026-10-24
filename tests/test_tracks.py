"""The ghost band's recordings: kept per song, replaced, refused when they aren't audio, and
served so an <audio> element can seek."""
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request

from g3xn.tracks import LIMIT, Tracks
from g3xn.sim import VirtualPedal

try:
    from test_daemon import request, start_daemon, start_in_thread
except ImportError:                       # the app extra isn't installed
    start_in_thread = None

SONG = bytes(range(256)) * 40             # stands in for an mp3: only the bytes matter here


class TracksTest(unittest.TestCase):
    def setUp(self):
        self.root = os.path.join(tempfile.mkdtemp(prefix="g3xn-test-tracks-"), "tracks")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.root), True)
        self.tracks = Tracks(self.root)

    def test_put_info_replace_delete(self):
        self.assertEqual((self.tracks.info("sultans"), self.tracks.list()), (None, []))
        self.assertFalse(os.path.exists(self.root))                       # made with the first one
        info = self.tracks.put("sultans", SONG, "Sultans of Swing.mp3", "audio/mpeg")
        self.assertEqual({k: info[k] for k in ("key", "name", "type", "size")},
                         {"key": "sultans", "name": "Sultans of Swing.mp3", "type": "audio/mpeg", "size": len(SONG)})
        self.assertEqual(self.tracks.info("sultans"), info)
        with open(self.tracks.path("sultans"), "rb") as f:
            self.assertEqual(f.read(), SONG)

        again = self.tracks.put("sultans", b"RIFF....", "take2.wav", "audio/x-wav")
        self.assertEqual((again["type"], again["size"]), ("audio/wav", 8))
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "sultans"))), ["info.json", "track.wav"])   # no mp3 left
        self.assertEqual([t["key"] for t in self.tracks.list()], ["sultans"])

        self.assertTrue(self.tracks.delete("sultans"))
        self.assertFalse(self.tracks.delete("sultans"))
        self.assertIsNone(self.tracks.path("sultans"))

    def test_kind_from_the_name_when_the_type_is_vague(self):
        self.assertEqual(self.tracks.put("a", SONG, "song.m4a", "application/octet-stream")["type"], "audio/mp4")
        self.assertEqual(self.tracks.put("b", SONG, "song.webm", "video/webm")["type"], "audio/webm")
        self.assertEqual(self.tracks.put("c", SONG, "song.flac", "")["type"], "audio/flac")
        self.assertEqual(self.tracks.put("d", SONG, "", "audio/ogg; codecs=opus")["name"], "d.ogg")

    def test_refusals(self):
        for key in ("", "Upper", "-dash-first", "a/b", "..", "a" * 81, "a\n", "a.b"):
            with self.assertRaises(ValueError):
                self.tracks.put(key, SONG, "x.mp3", "audio/mpeg")
        with self.assertRaises(ValueError):
            self.tracks.info("../etc")
        for name, kind in (("x.mp3", "text/plain"), ("x.png", "image/png"), ("notes.txt", "application/octet-stream"),
                           ("x.mp4", "video/mp4")):
            with self.assertRaises(ValueError):
                self.tracks.put("song", SONG, name, kind)
        with self.assertRaises(ValueError):
            self.tracks.put("song", b"", "x.mp3", "audio/mpeg")
        with self.assertRaises(ValueError):
            self.tracks.put("song", b"\0" * (LIMIT + 1), "x.mp3", "audio/mpeg")
        self.assertEqual(self.tracks.list(), [])


@unittest.skipIf(start_in_thread is None, "pip install g3xn[app] to test the daemon")
class TrackRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="g3xn-test-tracks-")
        cls.url, cls.stop = start_daemon(VirtualPedal(), tracks_folder=cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.stop()
        shutil.rmtree(cls.root, True)

    def upload(self, key, data, kind, name="", headers=None):
        """(status, JSON body) for a raw upload."""
        req = urllib.request.Request(self.url + "/api/tracks/%s?name=%s" % (key, urllib.request.quote(name)),
                                     method="PUT", data=data, headers={"Content-Type": kind, **(headers or {})})
        status, body, _ = _send(req)
        return status, body

    def audio(self, key, headers=None):
        """(status, headers, bytes) for the recording itself."""
        req = urllib.request.Request(self.url + "/api/tracks/%s/audio" % key, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def test_upload_seek_replace_delete(self):
        status, info = self.upload("sultans", SONG, "audio/mpeg", "Sultans of Swing.mp3")
        self.assertEqual((status, info["key"], info["name"], info["size"]), (200, "sultans", "Sultans of Swing.mp3", len(SONG)))
        self.assertEqual(request(self.url + "/api/tracks/sultans")[1], info)
        self.assertEqual(request(self.url + "/api/tracks")[1], {"tracks": [info]})

        status, headers, data = self.audio("sultans")
        self.assertEqual((status, headers["Content-Type"], headers["Accept-Ranges"], data), (200, "audio/mpeg", "bytes", SONG))
        status, headers, data = self.audio("sultans", {"Range": "bytes=1000-1099"})       # a seek
        self.assertEqual((status, headers["Content-Range"], data),
                         (206, "bytes 1000-1099/%d" % len(SONG), SONG[1000:1100]))
        status, headers, data = self.audio("sultans", {"Range": "bytes=-10"})             # the end
        self.assertEqual((status, data), (206, SONG[-10:]))

        status, info = self.upload("sultans", b"OggS" + SONG, "audio/ogg", "live.ogg")
        self.assertEqual((status, info["type"], info["size"]), (200, "audio/ogg", len(SONG) + 4))
        self.assertEqual(self.audio("sultans")[2], b"OggS" + SONG)

        self.assertEqual(request(self.url + "/api/tracks/sultans", "DELETE")[:2], (200, {"deleted": "sultans"}))
        self.assertEqual(request(self.url + "/api/tracks/sultans")[0], 404)
        self.assertEqual(self.audio("sultans")[0], 404)
        self.assertEqual(request(self.url + "/api/tracks/sultans", "DELETE")[0], 404)
        self.assertEqual(request(self.url + "/api/tracks")[1], {"tracks": []})

    def test_refusals(self):
        status, body = self.upload("Bad_Key", SONG, "audio/mpeg", "x.mp3")
        self.assertEqual(status, 400)
        self.assertIn("key", body["error"])
        self.assertEqual(request(self.url + "/api/tracks/Bad_Key")[0], 400)
        status, body = self.upload("notes", b"just some words", "text/plain", "notes.txt")
        self.assertEqual(status, 400)
        self.assertIn("isn't audio", body["error"])
        self.assertEqual(request(self.url + "/api/tracks/notes")[0], 404)                  # nothing kept
        req = urllib.request.Request(self.url + "/api/tracks/huge", method="PUT", data=b"tiny",
                                     headers={"Content-Type": "audio/mpeg", "Content-Length": str(LIMIT + 1)})
        with self.assertRaises(urllib.error.HTTPError) as ctx:      # refused from its size, before the body
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("80 MB", ctx.exception.read().decode())
        self.assertFalse(os.path.exists(os.path.join(self.root, "huge")))
        self.assertEqual(request(self.url + "/api/tracks/x", headers={"Origin": "https://evil.example"})[0], 403)


def _send(req):
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read()), err.headers


if __name__ == "__main__":
    unittest.main()
