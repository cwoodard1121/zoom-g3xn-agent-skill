"""The daemon end to end: a real HTTP server on a virtual pedal."""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

try:
    from websockets.sync.client import connect as ws_connect
    from g3xn.daemon import free_port, start_in_thread
except ImportError:                       # the app extra isn't installed
    start_in_thread = None

import mido

from g3xn import Patch, Pedal
from g3xn.sim import VirtualPedal

TONE = {"name": "DAEMON", "volume": 90,
        "chain": [{"effect": "TS Drive", "knobs": {"Gain": 40}}, {"effect": "FD TWNR"}, {"effect": "Delay"}]}


def start_daemon(device, **options):
    """A daemon on a free port, connected to `device` with every slot name read. Returns (url, stop)."""
    url, stop = start_in_thread(lambda: Pedal(device=device), free_port(), announce=False, **options)
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


def request(url, method="GET", body=None, headers=None):
    """(status, JSON body, headers), for answers that are errors too."""
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null"), r.headers
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"null"), err.headers


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


@unittest.skipIf(start_in_thread is None, "pip install g3xn[app] to test the daemon")
class BackupTest(unittest.TestCase):
    """A backup each time the pedal connects (only when something changed), and putting one slot back."""

    def test_backup_on_connect_and_put_back(self):
        import tempfile
        root = tempfile.mkdtemp(prefix="g3xn-test-backups-")
        device = VirtualPedal()
        url, stop = start_daemon(device, backups_folder=root)
        try:
            listed = get_json(url + "/api/backups")["backups"]
            self.assertEqual(len(listed), 1)
            first = listed[0]
            self.assertTrue(first["auto"] and first["first"])
            self.assertEqual(first["slots"], 150)
            name7 = get_json(url + "/api/patches/7")["name"]

            # Write over slot 7, then reconnect: a second backup, showing what changed.
            self.assertEqual(request(url + "/api/patches/7", "PUT", {"tone": dict(TONE, name="CHANGED"), "replace": True})[0], 200)
        finally:
            stop()
        time.sleep(1.1)                  # backups are named to the second
        url, stop = start_daemon(device, backups_folder=root)
        try:
            listed = get_json(url + "/api/backups")["backups"]
            self.assertEqual(len(listed), 2)
            self.assertEqual(listed[0]["changed"], [{"slot": 7, "was": name7, "now": "CHANGED"}])

            # Put slot 7 back from the first backup; what it held is kept.
            status, body, _ = request(url + "/api/backups/restore", "POST", {"backup": first["name"], "slot": 7})
            self.assertEqual((status, body["patch"]), (200, name7))
            self.assertEqual(get_json(url + "/api/patches/7")["name"], name7)
            import os
            self.assertTrue(any(f.startswith("007_CHANGED") for f in os.listdir(body["saved_current"])))
            self.assertEqual(request(url + "/api/backups/restore", "POST", {"backup": "../etc", "slot": 7})[0], 400)
        finally:
            stop()
        time.sleep(1.1)
        url, stop = start_daemon(device, backups_folder=root)     # back to how the first one had it, so
        try:                                                       # a third: nothing changed is skipped,
            self.assertEqual(len(get_json(url + "/api/backups")["backups"]), 3)    # but this did change
        finally:
            stop()
        time.sleep(1.1)
        url, stop = start_daemon(device, backups_folder=root)
        try:
            self.assertEqual(len(get_json(url + "/api/backups")["backups"]), 3)    # unchanged: no new one
        finally:
            stop()


@unittest.skipIf(start_in_thread is None, "pip install g3xn[app] to test the daemon")
class RemoteTest(unittest.TestCase):
    """The phone remote. It listens on 127.0.0.1 here, so the tests never open a port on the network."""

    @classmethod
    def setUpClass(cls):
        from g3xn.remote import Remote
        cls.remote_port = free_port()
        cls.url, cls.stop = start_daemon(VirtualPedal(), remote=Remote(port=cls.remote_port, host="127.0.0.1"))
        cls.phone = "http://127.0.0.1:%d" % cls.remote_port

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    def test_pairing(self):
        local, phone = self.url, self.phone
        self.assertFalse(request(local + "/api/remote")[1]["on"])
        info = request(local + "/api/remote", "POST", {"on": True})[1]
        self.assertEqual((info["on"], info["url"]), (True, phone))
        self.assertEqual(request(phone + "/api/status")[0], 401)

        wrong = "%06d" % ((int(info["code"]) + 1) % 10 ** 6)
        answers = [request(phone + "/api/pair", "POST", {"code": wrong})[1]["error"] for _ in range(5)]
        self.assertIn("too many", answers[-1])
        self.assertEqual(request(phone + "/api/pair", "POST", {"code": info["code"]})[0], 403)    # burned
        self.assertEqual(request(phone + "/api/remote/code", "POST")[0], 403)    # codes come from the computer
        code = request(local + "/api/remote/code", "POST")[1]["code"]
        status, body, headers = request(phone + "/api/pair", "POST", {"code": code, "name": "Test phone"})
        self.assertEqual((status, body["paired"]["name"]), (200, "Test phone"))
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        cookie = {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}

        self.assertEqual(request(phone + "/api/status", headers=cookie)[1]["connection"], "connected")
        self.assertEqual(request(phone + "/api/remote", headers=cookie)[0], 403)
        evil = dict(cookie, Origin="http://evil.example")
        self.assertEqual(request(phone + "/api/patches/7/select", "POST", headers=evil)[0], 403)
        rebound = dict(cookie, Host="evil.example:%d" % self.remote_port)
        self.assertEqual(request(phone + "/api/status", headers=rebound)[0], 403)
        events = "ws://127.0.0.1:%d/api/events" % self.remote_port
        with ws_connect(events, additional_headers=cookie) as ws:
            self.assertEqual(json.loads(ws.recv(timeout=5))["type"], "status")
        with self.assertRaises(Exception):
            with ws_connect(events) as ws:                                     # no cookie, no events
                ws.recv(timeout=5)

        devices = request(local + "/api/remote")[1]["devices"]
        self.assertEqual([d["name"] for d in devices], ["Test phone"])
        self.assertNotIn("token", devices[0])
        request(local + "/api/remote/devices/%s" % devices[0]["id"], "DELETE")
        self.assertEqual(request(phone + "/api/status", headers=cookie)[0], 401)
        request(local + "/api/remote", "POST", {"on": False})
        with self.assertRaises(urllib.error.URLError):
            urllib.request.urlopen(phone + "/api/status", timeout=3)


class FakeController:
    """A MIDI foot controller that a test presses (no real MIDI port is opened)."""

    def __init__(self, name, callback):
        self.name, self.callback, self.closed = name, callback, False

    def press(self, kind, **fields):
        self.callback(mido.Message(kind, **fields))

    def close(self):
        self.closed = True


@unittest.skipIf(start_in_thread is None, "pip install g3xn[app] to test the daemon")
class FootswitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from g3xn.footswitch import Footswitches
        cls.plugged_in, cls.opened = ["ZOOM G Series", "Foot Controller"], {}

        def open_input(name, callback):
            cls.opened[name] = FakeController(name, callback)
            return cls.opened[name]
        cls.fs = Footswitches(list_inputs=lambda: list(cls.plugged_in), open_input=open_input)
        cls.vp = VirtualPedal()
        cls.url, cls.stop = start_daemon(cls.vp, footswitches=cls.fs)

    @classmethod
    def tearDownClass(cls):
        cls.stop()

    def call(self, method, path, body=None):
        status, reply, _ = request(self.url + path, method, body)
        self.assertLess(status, 300, reply)
        return reply

    def wait_for(self, test, what):
        deadline = time.time() + 5
        while time.time() < deadline:
            if test():
                return
            time.sleep(0.02)
        self.fail("timed out waiting for " + what)

    def test_footswitches(self):
        info = self.call("GET", "/api/midi")
        self.assertEqual((info["available"], info["listening"]), (["Foot Controller"], []))   # not the G3Xn
        self.assertEqual(self.call("PUT", "/api/midi/inputs", {"inputs": ["Foot Controller"]})["listening"],
                         ["Foot Controller"])
        foot = self.opened["Foot Controller"]

        learned = {}
        learning = threading.Thread(target=lambda: learned.update(
            self.call("POST", "/api/midi/learn", {"action": {"do": "next_song"}})))
        learning.start()
        self.wait_for(lambda: self.fs._learning, "learn mode")
        foot.press("control_change", control=80, value=127)
        learning.join()
        self.assertEqual((learned["message"], learned["when"]),
                         ({"type": "control_change", "channel": 0, "control": 80}, "press"))

        songs = [{"song": n, "tone": dict(TONE, name=n.upper())} for n in ("One", "Two", "Three")]
        gid = self.call("PUT", "/api/setlists/new", {"name": "Feet", "start_slot": 110, "patches": songs})["id"]
        self.call("POST", "/api/setlists/%s/load" % gid)
        self.assertEqual(self.vp.current, 110)
        for expected in (111, 112, 112):                     # stops at the last song
            foot.press("control_change", control=80, value=127)
            foot.press("control_change", control=80, value=0)    # the release does nothing
            self.wait_for(lambda: self.vp.current == expected, "slot %d" % expected)
            time.sleep(0.1)

        self.call("POST", "/api/midi/bindings", {"message": {"type": "note", "note": 60}, "action": {"do": "previous_song"}})
        foot.press("note_on", note=60, velocity=90)
        self.wait_for(lambda: self.vp.current == 111, "previous song")

        self.call("POST", "/api/midi/bindings", {"message": {"type": "program_change", "program": 5},
                                                 "action": {"do": "effect", "effect": 3}})
        foot.press("program_change", program=5)
        self.wait_for(lambda: not self.call("GET", "/api/live")["chain"][2]["on"], "the delay off")

        self.call("POST", "/api/midi/bindings", {"message": {"type": "control_change", "control": 81},
                                                 "action": {"do": "talk"}, "when": "any"})
        with ws_connect("ws://127.0.0.1:%d/api/events" % int(self.url.rsplit(":", 1)[1])) as ws:
            foot.press("control_change", control=81, value=127)
            foot.press("control_change", control=81, value=0)
            talk = []
            while len(talk) < 2:
                ev = json.loads(ws.recv(timeout=5))
                if ev["type"] == "footswitch" and ev.get("action", {}).get("do") == "talk":
                    talk.append(ev["pressed"])
        self.assertEqual(talk, [True, False])

        status, reply, _ = request(self.url + "/api/midi/bindings", "POST",
                                   {"message": {"type": "note", "note": 61}, "action": {"do": "fly"}})
        self.assertEqual(status, 400)
        self.call("DELETE", "/api/midi/bindings/%s" % learned["id"])
        foot.press("control_change", control=80, value=127)
        time.sleep(0.3)
        self.assertEqual(self.vp.current, 111)                   # unbound: nothing happens
        self.assertTrue(self.call("GET", "/api/midi")["recent"])

        self.plugged_in.remove("Foot Controller")                # unplugged
        self.fs.sync()
        self.assertTrue(foot.closed)
        self.assertEqual(self.call("GET", "/api/midi")["listening"], [])


if __name__ == "__main__":
    unittest.main()
