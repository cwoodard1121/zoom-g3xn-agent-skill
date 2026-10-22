"""The daemon end to end: a real HTTP server on a virtual pedal."""
import json
import time
import unittest
import urllib.error
import urllib.request

try:
    from websockets.sync.client import connect as ws_connect
    from g3xn.daemon import free_port, start_in_thread
except ImportError:                       # the app extra isn't installed
    start_in_thread = None

from g3xn import Patch, Pedal
from g3xn.sim import VirtualPedal

TONE = {"name": "DAEMON", "volume": 90,
        "chain": [{"effect": "TS Drive", "knobs": {"Gain": 40}}, {"effect": "FD TWNR"}, {"effect": "Delay"}]}


def start_daemon(device):
    """A daemon on a free port, connected to `device` with every slot name read. Returns (url, stop)."""
    url, stop = start_in_thread(lambda: Pedal(device=device), free_port(), announce=False)
    deadline = time.time() + 10
    while time.time() < deadline:
        status = get_json(url + "/api/status")
        if status["connection"] == "connected" and status["doing"] is None and status["current_slot"]:
            return url, stop
        time.sleep(0.02)
    stop()
    raise RuntimeError("daemon did not connect to the virtual pedal")


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


@unittest.skipIf(start_in_thread is None, "pip install g3xn[app] to test the daemon")
class DaemonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mine = Patch.from_dict({"name": "MINE", "chain": [{"effect": "TS Drive"}]})
        cls.vp = VirtualPedal({1: mine}, current=1)
        cls.url, cls.stop = start_daemon(cls.vp)
        cls.port = int(cls.url.rsplit(":", 1)[1])

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    @classmethod
    def call(cls, method, path, body=None, headers=None):
        req = urllib.request.Request(cls.url + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def error(self, method, path, body=None, headers=None):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.call(method, path, body, headers)
        return ctx.exception.code, json.loads(ctx.exception.read())["error"]

    def test_status_and_patches(self):
        status = self.call("GET", "/api/status")
        self.assertEqual(status["pedal"]["firmware"], "2.20")
        patches = self.call("GET", "/api/patches")["patches"]
        self.assertEqual((len(patches), patches[0]["name"]), (150, "MINE"))

    def test_audition_tweak_save(self):
        view = self.call("POST", "/api/audition", {"tone": TONE})
        self.assertEqual((view["slot"], view["name"]), (150, "DAEMON"))
        view = self.call("POST", "/api/tweak", {"changes": [{"effect": "Delay", "knob": "Time", "value": 349}]})
        self.assertEqual(view["chain"][2]["shown"]["Time"], "350")
        code, msg = self.error("POST", "/api/patches/1/save", {})
        self.assertEqual(code, 409)
        self.assertIn("MINE", msg)                                  # never overwrites without replace
        self.assertEqual(self.call("POST", "/api/patches/140/save", {"name": "KEEPER"})["saved"], "KEEPER")
        names = {p["slot"]: p["name"] for p in self.call("GET", "/api/patches")["patches"]}
        self.assertEqual(names[140], "KEEPER")

    def test_events(self):
        with ws_connect("ws://127.0.0.1:%d/api/events" % self.port) as ws:
            self.assertEqual(json.loads(ws.recv(timeout=5))["type"], "status")
            self.call("POST", "/api/patches/7/select")
            deadline = time.time() + 5
            while time.time() < deadline:
                ev = json.loads(ws.recv(timeout=5))
                if ev["type"] == "current" and ev["slot"] == 7:
                    break
            else:
                self.fail("no current event")

    def test_history_undo_redo(self):
        self.call("POST", "/api/audition", {"tone": TONE})
        self.call("POST", "/api/tweak", {"changes": [{"effect": 1, "knob": "Gain", "value": 60}]})
        self.call("POST", "/api/tweak", {"changes": [{"effect": 1, "knob": "Gain", "value": 70}]})   # same drag
        self.call("POST", "/api/tweak", {"changes": [{"effect": 3, "on": False}], "reason": "too washy"},
                  headers={"X-G3xn-Source": "claude"})
        entries = self.call("GET", "/api/history")["entries"]
        self.assertTrue(entries[-2]["label"].startswith("TS Drive Gain 40"))
        self.assertTrue(entries[-2]["label"].endswith("70"))
        self.assertEqual((entries[-1]["source"], entries[-1]["reason"]), ("claude", "too washy"))
        self.assertEqual(self.call("POST", "/api/undo")["chain"][2]["on"], True)
        self.assertEqual(self.call("POST", "/api/undo")["chain"][0]["knobs"]["Gain"], 40)
        self.assertEqual(self.call("POST", "/api/redo")["chain"][0]["knobs"]["Gain"], 70)
        played = self.call("POST", "/api/play", {"tone": dict(TONE, volume=100)})
        self.assertEqual(played["volume"], 100)
        self.assertEqual(self.error("POST", "/api/redo")[0], 400)      # a new change drops the redo

    def test_morph(self):
        self.call("POST", "/api/audition", {"tone": TONE})
        loud = {"name": "DAEMON", "volume": 100, "chain": [
            {"effect": "TS Drive", "knobs": {"Gain": 90}}, {"effect": "FD TWNR"}, {"effect": "Delay", "on": False}]}
        start = time.time()
        view = self.call("POST", "/api/morph", {"to": loud, "seconds": 0.5})
        self.assertGreaterEqual(time.time() - start, 0.45)
        self.assertEqual((view["chain"][0]["knobs"]["Gain"], view["chain"][2]["on"], view["volume"]), (90, False, 100))
        code, msg = self.error("POST", "/api/morph", {"to": {"name": "X", "chain": [{"effect": "Comp"}]}})
        self.assertEqual(code, 409)
        self.assertIn("same effects", msg)

    def test_saved_gigs(self):
        gig = {"name": "Friday Set", "start_slot": 120, "patches": [
            {"song": "Sultans", "tone": TONE, "notes": "capo off"}, {"song": "Mine", "from_slot": 1}]}
        saved = self.call("PUT", "/api/setlists/new", gig)
        gid = saved["id"]
        self.assertTrue(gid.startswith("friday-set-"))
        plan = self.call("POST", "/api/setlists/%s/plan" % gid)["plan"]
        self.assertEqual([(s["slot"], s["patch"]) for s in plan], [(120, "DAEMON"), (121, "MINE")])
        self.call("POST", "/api/setlists/%s/load" % gid)
        listed = self.call("GET", "/api/setlists")
        self.assertEqual(listed["active"], gid)
        loaded = self.call("GET", "/api/setlists/%s" % gid)["loaded"]
        self.assertEqual([(s["song"], s["slot"]) for s in loaded["slots"]], [("Sultans", 120), ("Mine", 121)])
        names = {p["slot"]: p["name"] for p in self.call("GET", "/api/patches")["patches"]}
        self.assertEqual((names[120], names[121]), ("DAEMON", "MINE"))
        self.call("PUT", "/api/setlists/%s" % gid, dict(saved, name="Friday Late"))    # an edit from an old copy
        self.assertEqual(self.call("GET", "/api/setlists/%s" % gid)["loaded"], loaded)  # keeps what's on the pedal
        self.call("DELETE", "/api/setlists/%s" % gid)
        self.assertIsNone(self.call("GET", "/api/setlists")["active"])
        self.assertEqual(self.error("GET", "/api/setlists/%s" % gid)[0], 400)

    def test_gig_check_lock_restore(self):
        clean = {"name": "CLEAN", "chain": [{"effect": "FD TWNR"}]}
        gig = {"name": "Saturday", "start_slot": 130, "patches": [{"song": "Drive", "tone": TONE},
                                                                 {"song": "Clean", "tone": clean}]}
        gid = self.call("PUT", "/api/setlists/new", gig)["id"]
        self.call("POST", "/api/setlists/%s/load" % gid)
        self.assertNotIn('"data"', json.dumps(self.call("GET", "/api/setlists/%s" % gid)))   # no patch blobs
        plan = self.call("POST", "/api/setlists/%s/plan" % gid)["plan"]
        self.assertEqual([(s["replaces_own"], s["overwrites_real_patch"]) for s in plan], [(True, False)] * 2)
        self.assertEqual(self.call("POST", "/api/setlists/%s/check" % gid)["changed"], [])

        self.call("POST", "/api/patches/130/select")
        self.vp.turn_knob(0, 0, 90)                                  # turned on the pedal: autosaved
        changed = self.call("POST", "/api/setlists/%s/check" % gid)["changed"]
        self.assertEqual([(c["slot"], c["change"]) for c in changed], [(130, "TS Drive Gain 40 → 90")])

        self.call("POST", "/api/setlists/%s/lock" % gid)
        try:
            self.assertEqual(self.call("GET", "/api/setlists")["locked"], gid)
            code, msg = self.error("POST", "/api/patches/131/save", {"replace": True})
            self.assertEqual(code, 409)
            self.assertIn("locked", msg)
            self.assertEqual(self.error("PUT", "/api/patches/130", {"tone": TONE, "replace": True})[0], 409)
            self.assertEqual(self.error("POST", "/api/setlists/%s/load" % gid)[0], 409)
            self.assertEqual(self.error("POST", "/api/gigs/load", gig)[0], 409)
            restored = self.call("POST", "/api/setlists/%s/restore" % gid)        # works while locked
            self.assertEqual([s["slot"] for s in restored["restored"]], [130])
            self.assertEqual(self.vp.current, 130)                                # still on the song
            self.assertEqual(self.call("POST", "/api/setlists/%s/check" % gid)["changed"], [])
            self.assertEqual(self.call("GET", "/api/patches/130")["chain"][0]["knobs"]["Gain"], 40)
        finally:
            self.call("POST", "/api/setlists/%s/lock" % gid, {"on": False})
        self.assertIsNone(self.call("GET", "/api/setlists")["locked"])
        self.call("DELETE", "/api/setlists/%s" % gid)

    def test_effects_and_errors(self):
        self.assertTrue(self.call("GET", "/api/effects?query=fuzz")["effects"])
        code, _ = self.error("GET", "/api/effects/NoSuchPedal")
        self.assertEqual(code, 400)

    def test_refuses_other_websites(self):
        code, _ = self.error("POST", "/api/patches/7/select", headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
