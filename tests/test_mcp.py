"""MCP tools on a virtual pedal: opening the pedal directly, and through a running daemon."""
import json
import os
import tempfile
import unittest

try:
    from g3xn import mcp_server
except ImportError:                       # the mcp extra isn't installed
    mcp_server = None

from g3xn import Patch, Pedal, gig
from g3xn.sim import VirtualPedal

TONE = {"name": "MCP", "chain": [{"effect": "TS Drive"}, {"effect": "Delay"}]}
WET = {"name": "WET", "chain": [{"effect": "TS Drive"}, {"effect": "Hall", "knobs": {"Mix": 40}}]}
GIG = {"name": "Saturday", "start_slot": 125, "patches": [
    {"song": "Dry", "tone": TONE}, {"song": "Wet", "tone": WET}, {"song": "Mine", "from_slot": 1}]}


def pedal_with_mine():
    return VirtualPedal({1: Patch.from_dict({"name": "MINE", "chain": [{"effect": "TS Drive"}]})})


@unittest.skipIf(mcp_server is None, "pip install g3xn[mcp] to test the MCP server")
class DirectTest(unittest.TestCase):
    """No daemon: each tool call opens the (virtual) pedal itself."""

    def setUp(self):
        vp = pedal_with_mine()
        self.saved = mcp_server.open_pedal, mcp_server.DAEMON_FILE
        mcp_server.open_pedal = lambda: Pedal(device=vp)
        mcp_server.DAEMON_FILE = os.path.join(tempfile.mkdtemp(), "none.json")
        self.saved_gigs = mcp_server.GIGS_FOLDER
        mcp_server.GIGS_FOLDER = tempfile.mkdtemp()

    def tearDown(self):
        mcp_server.open_pedal, mcp_server.DAEMON_FILE = self.saved
        mcp_server.GIGS_FOLDER = self.saved_gigs

    def test_tools(self):
        run_tools(self)

    def test_saved_gigs(self):
        gig.GigLibrary(mcp_server.GIGS_FOLDER).save(dict(GIG, id="sat"))
        run_gig_tools(self, "sat")


try:
    from g3xn.daemon import start_in_thread
except ImportError:
    start_in_thread = None


@unittest.skipIf(mcp_server is None or start_in_thread is None, "needs the mcp and app extras")
class ThroughDaemonTest(unittest.TestCase):
    """A daemon is running: tool calls go to it, and the pedal is never opened directly."""

    def setUp(self):
        from test_daemon import start_daemon
        self.url, self.stop = start_daemon(pedal_with_mine())
        url = self.url
        self.saved = mcp_server.open_pedal, mcp_server.DAEMON_FILE
        mcp_server.open_pedal = None                              # would crash if used
        mcp_server.DAEMON_FILE = os.path.join(tempfile.mkdtemp(), "daemon.json")
        with open(mcp_server.DAEMON_FILE, "w") as f:
            json.dump({"url": url}, f)

    def tearDown(self):
        mcp_server.open_pedal, mcp_server.DAEMON_FILE = self.saved
        self.stop()

    def test_tools(self):
        run_tools(self)
        self.assertEqual(mcp_server.pedal_status()["via"], "g3xn app")

    def test_saved_gigs(self):
        import urllib.request
        req = urllib.request.Request(self.url + "/api/setlists/new", method="PUT", data=json.dumps(GIG).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            gid = json.loads(r.read())["id"]
        run_gig_tools(self, gid)


def run_tools(t):
    status = mcp_server.pedal_status()
    t.assertEqual(status["firmware"], "2.20")
    t.assertEqual(mcp_server.list_patches()["patches"][0]["name"], "MINE")
    view = mcp_server.audition(tone=TONE)
    t.assertEqual((view["slot"], view["name"]), (150, "MCP"))
    view = mcp_server.tweak(changes=[{"effect": "Delay", "knob": "Time", "value": 349}], volume=95)
    t.assertEqual((view["chain"][1]["shown"]["Time"], view["volume"]), ("350", 95))
    t.assertIn("MINE", mcp_server.save_to_slot(1)["error"])        # refuses without replace
    t.assertEqual(mcp_server.save_to_slot(141, name="KEPT")["saved"], "KEPT")
    plan = mcp_server.load_gig({"name": "Gig", "start_slot": 120, "patches": [{"song": "A", "tone": TONE}]})
    t.assertFalse(plan["confirmed"])
    t.assertIn("error", mcp_server.effect_details("No Such Pedal"))
    t.assertEqual(mcp_server.select_patch(141)["name"], "KEPT")


def run_gig_tools(t, gid):
    t.assertEqual([g["name"] for g in mcp_server.saved_gigs()["gigs"]], ["Saturday"])
    preview = mcp_server.edit_gig(gid, {"change": "knob", "effects": "reverbs", "knob": "Mix", "percent": -10})
    t.assertEqual([(s["song"], s["change"]) for s in preview["songs"]],
                  [("Dry", None), ("Wet", "Hall Mix 40 → 36"), ("Mine", None)])
    t.assertEqual(preview["songs"][0]["left_alone"], "no reverbs with a Mix knob")
    t.assertFalse(preview["saved"])
    t.assertEqual(mcp_server.get_gig(gid)["patches"][1]["tone"]["chain"][1]["knobs"]["Mix"], 40)  # only a preview
    added = mcp_server.edit_gig(gid, {"change": "add", "effect": "Gt GEQ", "at": 1}, save=True)
    t.assertEqual(added["changed"], 3)
    t.assertEqual(added["songs"][2]["was_a_copy_of_slot"], 1)
    songs = mcp_server.get_gig(gid)["patches"]
    t.assertEqual([s["tone"]["chain"][0]["effect"] for s in songs], ["Gt GEQ"] * 3)
    t.assertNotIn("from_slot", songs[2])
    t.assertIn("error", mcp_server.edit_gig(gid, {"change": "knob", "effects": "reverb", "knob": "Mix"}))
    t.assertIn("error", mcp_server.edit_gig(gid, {"change": "off", "effects": "NoSuchThing"}))
    t.assertIn("error", mcp_server.check_gig(gid))                       # not loaded yet
    plan = mcp_server.load_saved_gig(gid)
    t.assertEqual([s["slot"] for s in plan["plan"]], [125, 126, 127])
    t.assertEqual(len(mcp_server.load_saved_gig(gid, confirm=True)["written"]), 3)
    t.assertEqual(mcp_server.check_gig(gid)["changed"], [])
    t.assertEqual(mcp_server.saved_gigs()["gigs"][0]["loaded"]["slots"][0]["slot"], 125)


if __name__ == "__main__":
    unittest.main()
