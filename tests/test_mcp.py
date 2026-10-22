"""MCP tools on a virtual pedal: opening the pedal directly, and through a running daemon."""
import json
import os
import tempfile
import unittest

try:
    from g3xn import mcp_server
except ImportError:                       # the mcp extra isn't installed
    mcp_server = None

from g3xn import Patch, Pedal
from g3xn.sim import VirtualPedal

TONE = {"name": "MCP", "chain": [{"effect": "TS Drive"}, {"effect": "Delay"}]}


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

    def tearDown(self):
        mcp_server.open_pedal, mcp_server.DAEMON_FILE = self.saved

    def test_tools(self):
        run_tools(self)


try:
    from g3xn.daemon import start_in_thread
except ImportError:
    start_in_thread = None


@unittest.skipIf(mcp_server is None or start_in_thread is None, "needs the mcp and app extras")
class ThroughDaemonTest(unittest.TestCase):
    """A daemon is running: tool calls go to it, and the pedal is never opened directly."""

    def setUp(self):
        from test_daemon import start_daemon
        url, self.stop = start_daemon(pedal_with_mine())
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


if __name__ == "__main__":
    unittest.main()
