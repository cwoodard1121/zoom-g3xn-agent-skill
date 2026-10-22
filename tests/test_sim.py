"""The real Pedal class against the virtual pedal (no hardware needed)."""
import unittest

from g3xn import Patch, Pedal, PedalError
from g3xn.sim import VirtualPedal

TONE = {"name": "SIMTEST", "volume": 90,
        "chain": [{"effect": "TS Drive", "knobs": {"Gain": 40}},
                  {"effect": "FD TWNR", "knobs": {"Treble": 45}},
                  {"effect": "Delay", "knobs": {"Time": 349}}]}


class VirtualPedalTest(unittest.TestCase):
    def setUp(self):
        mine = Patch.from_dict({"name": "MINE", "chain": [{"effect": "TS Drive"}]})
        self.vp = VirtualPedal({1: mine}, current=1)
        self.pedal = Pedal(device=self.vp).open()

    def tearDown(self):
        self.pedal.close()

    def test_identity_and_slots(self):
        info = self.pedal.identity()
        self.assertEqual((info["firmware"], info["patches"], info["bank_size"]), ("2.20", 150, 3))
        self.assertEqual(self.pedal.current(), 1)
        self.assertEqual(self.pedal.read(1).name, "MINE")
        self.assertEqual(self.pedal.read(2).name, "Empty")

    def test_audition_tweak_save(self):
        p = self.pedal
        tone = Patch.from_dict(TONE)
        p.audition(tone)
        self.assertEqual(p.current(), 150)
        tone.effect("FD TWNR")["Treble"] = 55
        tone.volume = 95
        p.push(tone)                                   # live edits, not a rewrite
        live = p.edit_buffer()
        self.assertEqual(live.effect("FD TWNR")["Treble"], 55)
        self.assertEqual(live.volume, 95)
        self.assertEqual(p.read(150).effect("FD TWNR")["Treble"], 55)    # autosave
        p.save_scratch(149)
        self.assertEqual((p.current(), p.read(149).name), (149, "SIMTEST"))

    def test_saving_over_keeps_the_old_patch(self):
        from g3xn import service
        self.pedal.audition(Patch.from_dict(TONE))
        self.pedal.select(150)
        with self.assertRaises(PedalError):
            service.save_to_slot(self.pedal, 1)                     # MINE: asks first
        self.pedal.select(150)
        result = service.save_to_slot(self.pedal, 1, replace=True)
        self.assertEqual(result["saved"], "SIMTEST")
        self.assertTrue(result["kept"].startswith(self.vp.backup_root))
        self.assertEqual(Patch.load(result["kept"]).name, "MINE")
        self.assertNotIn("kept", service.write_tone(self.pedal, TONE, 2, replace=True))   # was Empty

    def test_screen_text(self):
        self.pedal.audition(Patch.from_dict(TONE))
        shown = {d["effect"]: d["knobs"] for d in self.pedal.display()}
        self.assertEqual(shown["Delay"]["Time"], "350")                 # stored 349, shown +1
        self.assertEqual(len(shown["FD TWNR"]), 8)                      # both screens

    def test_safety_rules(self):
        with self.assertRaises(PedalError):
            self.pedal.write(1, Patch.blank("X"))                       # the pedal is on slot 1
        self.vp.slots[150] = Patch.blank("SOMEONES").encode()
        with self.assertRaises(PedalError):
            self.pedal.audition(Patch.from_dict(TONE))                  # scratch isn't ours

    def test_tuner(self):
        self.pedal.tuner(True)
        readings = list(self.pedal.tuner_readings(0.2))
        self.pedal.tuner(False)
        self.assertTrue(readings)
        self.assertEqual(readings[-1]["note"], "E")


if __name__ == "__main__":
    unittest.main()
