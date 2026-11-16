"""One app, either pedal: the daemon switches between the G3Xn and the B1X FOUR on one address."""
import pin_mode  # noqa: F401  (G3Xn mode for these tests)
import argparse
import os
import tempfile
import time
import unittest

try:
    from g3xn import daemon
    from test_daemon import get_json, request, start_daemon
except ImportError:                       # the app extra isn't installed
    daemon = None

from g3xn import models
from g3xn.sim import VirtualPedal

GUITAR = {"name": "GTR", "volume": 90, "chain": [{"effect": "TS Drive", "knobs": {"Gain": 40}}, {"effect": "FD TWNR"}]}
BASS = {"name": "BASS", "volume": 90,
        "chain": [{"effect": "OptComp"}, {"effect": "AMPG SVT", "knobs": {"Gain": 40}},
                  {"effect": "SVT8x10"}, {"effect": "Room"}]}


def sim_args(*more):
    ap = argparse.ArgumentParser()
    daemon.add_pedal_options(ap)
    return ap.parse_args(["--sim"] + list(more))


def ready(url, key):
    """Wait until the daemon at `url` is on pedal `key` with every slot name read. Returns its status."""
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            status = get_json(url + "/api/status")
        except OSError:                   # between two pedals: the server is restarting
            time.sleep(0.05)
            continue
        if (status.get("model", {}).get("key") == key and status["connection"] == "connected"
                and status["doing"] is None and status["current_slot"]):
            return status
        time.sleep(0.05)
    raise RuntimeError("the daemon did not come up on %s" % key)


@unittest.skipIf(daemon is None, "pip install g3xn[app] to test the daemon")
class SwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = daemon.REPO, models.MODE_FILE
        daemon.REPO = tempfile.mkdtemp()                                # no pedal dump: blank virtual pedals
        models.MODE_FILE = os.path.join(tempfile.mkdtemp(), "mode.json")
        port = daemon.free_port()
        cls.url, cls.stop, cls.modes = daemon.start_modes_in_thread(daemon.app_builder(sim_args(), port), port, "g3xn")
        ready(cls.url, "g3xn")

    @classmethod
    def tearDownClass(cls):
        cls.stop()
        daemon.REPO, models.MODE_FILE = cls.saved
        os.environ["G3XN_PEDAL"] = "g3xn"                               # the daemon pinned its own pedal

    def switch(self, pedal):
        status, body, _ = request(self.url + "/api/mode", "POST", {"pedal": pedal})
        self.assertEqual(status, 200, body)
        return body

    def test_1_starts_on_the_guitar_pedal(self):
        status = ready(self.url, "g3xn")
        self.assertEqual((status["model"]["patches"], status["model"]["bank_size"], status["model"]["scratch_slot"]),
                         (150, 3, 150))
        self.assertEqual(status["model"]["chain"], {"rule": "positions", "max": 7})
        self.assertEqual([m["key"] for m in status["modes"]], ["g3xn", "b1xfour"])
        self.assertEqual(self.switch("guitar")["restarting"], False)    # already there

    def test_2_switches_to_the_bass_pedal_on_the_same_address(self):
        self.assertEqual(self.switch("bass"), {"mode": "b1xfour", "name": "B1X FOUR", "restarting": True})
        status = ready(self.url, "b1xfour")
        model = status["model"]
        self.assertEqual((model["patches"], model["bank_size"], model["scratch_slot"], model["screen_offset"]),
                         (50, 10, 50, 9))
        self.assertEqual(model["chain"], {"rule": "effects", "max": 5})
        self.assertEqual(status["scratch_slot"], 50)
        self.assertEqual(len(get_json(self.url + "/api/patches")["patches"]), 50)
        names = [e["name"] for e in get_json(self.url + "/api/effects?query=svt")["effects"]]
        self.assertIn("AMPG SVT", names)
        code, view, _ = request(self.url + "/api/audition", "POST", {"tone": BASS})
        self.assertEqual((code, view["slot"]), (200, 50), view)
        self.assertEqual([fx["effect"] for fx in view["chain"]], ["OptComp", "AMPG SVT", "SVT8x10", "Room"])
        code, body, _ = request(self.url + "/api/audition", "POST", {"tone": GUITAR})
        self.assertEqual(code, 400, body)                               # a guitar effect is not on the bass pedal
        self.assertFalse(os.path.exists(models.MODE_FILE))              # a virtual pedal never moves the mode

    def test_3_refuses_a_pedal_it_does_not_know(self):
        code, body, _ = request(self.url + "/api/mode", "POST", {"pedal": "ukulele"})
        self.assertEqual(code, 400)
        self.assertIn("g3xn or b1xfour", body["error"])

    def test_4_switches_back_and_each_pedal_keeps_its_own_state(self):
        self.switch("g3xn")
        ready(self.url, "g3xn")
        code, view, _ = request(self.url + "/api/audition", "POST", {"tone": GUITAR})
        self.assertEqual((code, view["slot"]), (200, 150), view)
        self.switch("b1xfour")
        status = ready(self.url, "b1xfour")
        self.assertEqual((status["current_slot"], status["current_name"]), (50, "BASS"))


@unittest.skipIf(daemon is None, "pip install g3xn[app] to test the daemon")
class OnePedalDaemonTest(unittest.TestCase):
    def test_a_daemon_without_a_switch_says_so(self):
        url, stop = start_daemon(VirtualPedal())
        try:
            self.assertEqual(get_json(url + "/api/status")["model"]["key"], "g3xn")
            code, body, _ = request(url + "/api/mode", "POST", {"pedal": "bass"})
            self.assertEqual(code, 400)
            self.assertIn("--pedal b1xfour", body["error"])
        finally:
            stop()


class FilesTest(unittest.TestCase):
    def test_each_pedal_keeps_its_own_app_files(self):
        guitar, bass = models.get("g3xn"), models.get("b1xfour")
        home = os.path.join(os.path.expanduser("~"), ".g3xn")
        self.assertEqual((guitar.history_file, guitar.gigs_folder, guitar.guitars_file),
                         (os.path.join(home, "history.json"), os.path.join(home, "gigs"),
                          os.path.join(home, "guitars.json")))
        self.assertEqual((bass.history_file, bass.gigs_folder, bass.guitars_file),
                         (os.path.join(home, "b1xfour", "history.json"), os.path.join(home, "b1xfour", "gigs"),
                          os.path.join(home, "b1xfour", "guitars.json")))

    @unittest.skipIf(daemon is None, "pip install g3xn[app] to test the daemon")
    def test_the_guitar_pedal_files_did_not_move(self):
        guitar = models.get("g3xn")
        self.assertEqual((guitar.history_file, guitar.gigs_folder, guitar.guitars_file),
                         (daemon.HISTORY_FILE, daemon.GIGS_FOLDER, daemon.GUITARS_FILE))

    @unittest.skipIf(daemon is None, "pip install g3xn[app] to test the daemon")
    def test_a_scratch_slot_the_bass_pedal_does_not_have_is_dropped(self):
        make = daemon.pedal_factory(sim_args("--scratch", "150"))
        self.assertEqual(make("g3xn")().scratch, 150)
        pedal = make("b1xfour")()
        pedal.open()
        try:
            self.assertEqual(pedal.scratch, 50)
        finally:
            pedal.close()


if __name__ == "__main__":
    unittest.main()
