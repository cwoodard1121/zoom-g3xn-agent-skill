"""The B1X FOUR bass pedal: the mode, telling the pedals apart, bass patches, and Claude's tools
on a virtual B1X FOUR. Facts come from a real B1X FOUR (firmware 2.00) read on 2026-11-15."""
import pin_mode  # noqa: F401  (G3Xn mode unless a test switches)
import glob
import json
import os
import struct
import tempfile
import unittest
from unittest import mock

import mido

from g3xn import Patch, Pedal, PedalError, catalog, models, service
from g3xn.patch import CONTINUATION_ID
from g3xn.sim import VirtualPedal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP = os.path.join(REPO, "data", "b1xfour", "pedal_dump")      # gitignored: the owner's own patches
BASS = {"name": "BASS", "volume": 90,
        "chain": [{"effect": "OptComp"}, {"effect": "AMPG SVT", "knobs": {"Gain": 40}},
                  {"effect": "SVT8x10"}, {"effect": "Room"}]}


class bass_mode:
    """Run a block in bass mode, without touching this computer's mode file."""

    def __enter__(self):
        self.saved = os.environ.get("G3XN_PEDAL")
        os.environ["G3XN_PEDAL"] = "b1xfour"

    def __exit__(self, *exc):
        os.environ["G3XN_PEDAL"] = self.saved or "g3xn"


class ModeTest(unittest.TestCase):
    def setUp(self):
        self.saved = models.MODE_FILE, os.environ.pop("G3XN_PEDAL", None)
        models.MODE_FILE = os.path.join(tempfile.mkdtemp(), "mode.json")

    def tearDown(self):
        models.MODE_FILE = self.saved[0]
        os.environ["G3XN_PEDAL"] = self.saved[1] or "g3xn"

    def test_default_file_and_env(self):
        self.assertEqual(models.active().key, "g3xn")
        models.use("bass")
        self.assertEqual(models.active().key, "b1xfour")
        with open(models.MODE_FILE) as f:
            self.assertEqual(json.load(f), {"pedal": "b1xfour"})
        os.environ["G3XN_PEDAL"] = "g3xn"
        self.assertEqual(models.active().key, "g3xn")          # the variable wins for its process

    def test_names(self):
        for name in ("b1xfour", "B1X FOUR", "bass", "b1x-four"):
            self.assertEqual(models.get(name).key, "b1xfour")
        with self.assertRaises(ValueError):
            models.get("ms-60b")

    def test_detect_by_storage(self):
        self.assertEqual(models.detect(50, 760, 10).key, "b1xfour")
        self.assertEqual(models.detect(150, 736, 3).key, "g3xn")
        self.assertIsNone(models.detect(100, 500, 4))


class CatalogTest(unittest.TestCase):
    def test_each_pedal_has_its_own(self):
        bass, guitar = catalog("b1xfour"), catalog("g3xn")
        self.assertEqual(len(bass.effects), 80)
        self.assertEqual(len(guitar.effects), 162)
        self.assertEqual(bass.get("AMPG SVT").group, "AMP")
        self.assertEqual(bass.get("AMPG SVT").positions, 2)
        with self.assertRaises(KeyError):
            bass.get("TS Drive")                                # a G3Xn effect
        with bass_mode():
            self.assertIs(catalog(), bass)

    def test_templates_hold_the_defaults(self):
        """The knob bit layout is the G3Xn's: every template's knobs are the .ZD2 defaults."""
        for e in catalog("b1xfour").effects:
            knobs = Patch.blank("T", "b1xfour")
            fx = knobs.add(e.name)
            for p in e.params:
                if p.name.strip("-"):                           # Output VP has a junk unnamed "-" knob
                    self.assertEqual(fx[p.name], p.default, (e.name, p.name))


class BassPatchTest(unittest.TestCase):
    def test_blank(self):
        p = Patch.blank("Empty", "b1xfour")
        data = p.encode()
        self.assertEqual((len(data), p.target, len(p.slots)), (760, 128, 5))
        self.assertIs(Patch.decode(data).model, models.get("b1xfour"))

    def test_five_effects_whatever_their_size(self):
        p = Patch.from_dict(BASS, "b1xfour")
        self.assertEqual([c.name for c in p.chain], ["OptComp", "AMPG SVT", "SVT8x10", "Room"])
        self.assertEqual(len(p.slots), 6)                       # the SVT takes a continuation place
        self.assertEqual(p.slots[2].id, CONTINUATION_ID)
        p.add("BMAN100")                                        # a second two-screen amp: 5 effects
        self.assertEqual((len(p.chain), len(p.slots)), (5, 7))
        self.assertEqual(p.problems(), [])
        with self.assertRaises(ValueError):
            p.add("Spring")
        p.remove("Room")
        self.assertEqual((len(p.chain), len(p.slots)), (4, 7))  # 4 effects + 1 Empty place

    def test_guitar_tone_is_refused_in_bass(self):
        with self.assertRaises(KeyError):
            Patch.from_dict({"chain": [{"effect": "TS Drive"}]}, "b1xfour")

    @unittest.skipUnless(os.path.isdir(DUMP), "needs data/b1xfour/pedal_dump (a real B1X FOUR backup)")
    def test_real_patches_round_trip(self):
        files = sorted(glob.glob(os.path.join(DUMP, "*.zptc")))
        self.assertEqual(len(files), 50)
        for f in files:
            with open(f, "rb") as fh:
                data = fh.read()
            p = Patch.decode(data)
            n = struct.unpack_from("<I", data, 4)[0]
            self.assertIs(p.model, models.get("b1xfour"))
            self.assertEqual(p.encode()[:n], data[:n], f)
            self.assertEqual(len(p.encode()), 760)
            self.assertEqual(p.problems(), [], f)


class VirtualB1XTest(unittest.TestCase):
    def setUp(self):
        mine = Patch.from_dict({"name": "MINE", "chain": [{"effect": "Bass DRV"}]}, "b1xfour")
        self.vp = VirtualPedal({1: mine}, model="b1xfour")
        self.pedal = Pedal(device=self.vp).open()

    def tearDown(self):
        self.pedal.close()

    def test_opens_as_a_bass_pedal(self):
        info = self.pedal.identity()
        self.assertEqual((info["model"], info["patches"], info["patch_size"], info["bank_size"]),
                         ("B1X FOUR", 50, 760, 10))
        self.assertEqual(self.pedal.scratch, 50)

    def test_refuses_in_guitar_mode(self):
        with self.assertRaises(PedalError) as err:
            Pedal(device=self.vp, model="g3xn").open()
        self.assertIn("g3xn mode b1xfour", str(err.exception))

    def test_refuses_a_guitar_patch(self):
        guitar = Patch.from_dict({"name": "GTR", "chain": [{"effect": "TS Drive"}]}, "g3xn")
        with self.assertRaises(PedalError):
            self.pedal.write(45, guitar)

    def test_audition_tweak_save(self):
        p = self.pedal
        tone = Patch.from_dict(BASS, "b1xfour")
        p.audition(tone)
        self.assertEqual((p.current(), p.read(50).name), (50, "BASS"))
        tone.effect("AMPG SVT")["Gain"] = 60
        p.push(tone)
        self.assertEqual(p.edit_buffer().effect("AMPG SVT")["Gain"], 60)
        p.save_scratch(45)
        self.assertEqual((p.current(), p.read(45).name), (45, "BASS"))

    def test_push_rewrites_when_live_edits_do_not_stick(self):
        p = self.pedal
        tone = Patch.from_dict(BASS, "b1xfour")
        p.audition(tone)
        self.vp.live_edits_work = False
        tone.effect("AMPG SVT")["Gain"] = 70
        p.push(tone)
        self.assertEqual(p.edit_buffer().effect("AMPG SVT")["Gain"], 70)
        self.assertEqual(p.current(), 50)

    def test_no_screen_text_yet(self):
        self.pedal.audition(Patch.from_dict(BASS, "b1xfour"))
        self.assertEqual(self.pedal.display(), [])


class UsbPortTest(unittest.TestCase):
    """Both pedals are "ZOOM G Series" on USB: the patch storage reply tells them apart."""

    def ports(self, *pedals):
        conns = [vp.connect() for vp in pedals]
        names = ["ZOOM G Series %d" % i for i in range(len(pedals))]
        return mock.patch.multiple(
            mido, get_input_names=lambda: names, get_output_names=lambda: names,
            open_input=lambda n: conns[names.index(n)][0], open_output=lambda n: conns[names.index(n)][1])

    def test_wrong_pedal_names_the_fix(self):
        with self.ports(VirtualPedal(model="b1xfour")):
            with self.assertRaises(PedalError) as err:
                Pedal(model="g3xn").open()
        self.assertIn("is a B1X FOUR", str(err.exception))

    def test_picks_the_bass_pedal_from_two(self):
        guitar, bass = VirtualPedal(), VirtualPedal(model="b1xfour")
        with self.ports(guitar, bass), bass_mode():
            pedal = Pedal().open()
            try:
                self.assertEqual((pedal.model.key, pedal.scratch), ("b1xfour", 50))
            finally:
                pedal.close()


try:
    from g3xn import mcp_server
except ImportError:
    mcp_server = None


@unittest.skipIf(mcp_server is None, "pip install g3xn[mcp] to test the MCP server")
class ClaudeOnBassTest(unittest.TestCase):
    def setUp(self):
        self.vp = VirtualPedal(model="b1xfour")
        self.saved = mcp_server.open_pedal, mcp_server.DAEMON_FILE, models.MODE_FILE
        mcp_server.open_pedal = lambda: Pedal(device=self.vp)
        mcp_server.DAEMON_FILE = os.path.join(tempfile.mkdtemp(), "none.json")
        models.MODE_FILE = os.path.join(tempfile.mkdtemp(), "mode.json")
        os.environ.pop("G3XN_PEDAL", None)

    def tearDown(self):
        mcp_server.open_pedal, mcp_server.DAEMON_FILE, models.MODE_FILE = self.saved
        os.environ["G3XN_PEDAL"] = "g3xn"

    def test_switch_then_make_a_bass_tone(self):
        self.assertEqual(mcp_server.pedal_mode()["mode"], "g3xn")
        switched = mcp_server.pedal_mode("bass")
        self.assertEqual((switched["mode"], switched["scratch_slot"]), ("b1xfour", 50))
        names = [e["name"] for e in mcp_server.find_effects("svt")["effects"]]
        self.assertIn("AMPG SVT", names)
        result = mcp_server.audition(BASS)
        self.assertNotIn("error", result)
        self.assertEqual(self.vp.current, 50)
        status = mcp_server.pedal_status()
        self.assertEqual((status["pedal"], status["current_slot"]), ("B1X FOUR", 50))
        self.assertIn("error", mcp_server.pedal_mode("ms-50g"))

    def test_bass_backups_are_kept_apart(self):
        with bass_mode():
            pedal = Pedal(device=VirtualPedal(model="b1xfour"))
            pedal.device.backup_root = None                     # as a real pedal: the model's folder
            pedal.open()
            try:
                self.assertEqual(service._backup_root(pedal), models.get("b1xfour").backup_root)
            finally:
                pedal.close()
        self.assertNotEqual(models.get("b1xfour").backup_root, service.BACKUP_ROOT)


if __name__ == "__main__":
    unittest.main()
