"""Offline tests (no pedal needed):  python -m unittest discover tests"""
import glob
import os
import unittest

from g3xn import Patch, catalog
from g3xn import protocol as P

ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKUPS = sorted(glob.glob(os.path.join(ROOT, "data", "pedal_dump", "*.zptc")))


class Protocol(unittest.TestCase):
    def test_pack7_roundtrip(self):
        data = bytes(range(256)) * 3
        self.assertEqual(P.unpack7(P.pack7(data)), data)

    def test_checksum(self):
        data = b"PTCF" + bytes(100)
        self.assertTrue(P.verify_checksum(data, P.checksum(data)))

    def test_tuner_notes(self):
        # Checked on the real pedal: an open low E string sends 7.
        self.assertEqual(P.tuner_note(7), "E")
        self.assertEqual(P.tuner_note(12), "A")
        self.assertIsNone(P.tuner_note(0))
        self.assertEqual([P.tuner_note(P.tuner_value(n)) for n in P.TUNER_NOTES], P.TUNER_NOTES)


class Catalog(unittest.TestCase):
    def test_lookup(self):
        c = catalog()
        self.assertEqual(c.get("fd twnr").name, "FD TWNR")
        self.assertIs(c.get("0x04000020"), c.get("FD TWNR"))
        self.assertEqual(c.get("FD TWNR").positions, 2)
        self.assertEqual(c.get("TS Drive").param("gain").max, 100)

    def test_every_effect_has_a_template(self):
        for e in catalog().effects:
            self.assertIsNotNone(e.template, e.name)


class Patches(unittest.TestCase):
    def test_build_and_reload(self):
        p = Patch.blank("TEST")
        p.add("TS Drive", Gain=40)
        p.add("FD TWNR", Treble=45)
        p.add("Gt GEQ 7", knobs={"1.6k": 30})
        p.volume = 90
        q = Patch.decode(p.encode())
        self.assertEqual(q.to_dict(), p.to_dict())
        self.assertEqual(q.effect("FD TWNR")["Treble"], 45)
        self.assertEqual([s.id for s in q.slots][2], 0x00000001)   # amp takes two positions
        self.assertEqual(p.problems(), [])

    def test_limits(self):
        p = Patch.blank()
        with self.assertRaises(ValueError):
            p.add("TS Drive", Gain=101)
        p = Patch.blank()
        for name in ("MS 1959", "UK 30A", "FD TWNR"):
            p.add(name)
        with self.assertRaises(ValueError):
            p.add("Gt GEQ 7")

    def test_edit_chain(self):
        p = Patch.from_dict({"name": "X", "chain": [{"effect": "TS Drive"}, {"effect": "FD TWNR"}, {"effect": "HD Hall"}]})
        p.move("HD Hall", 1)
        self.assertEqual([c.name for c in p.chain], ["HD Hall", "TS Drive", "FD TWNR"])
        p.replace("TS Drive", "RC Boost")
        self.assertEqual([c.name for c in p.chain], ["HD Hall", "RC Boost", "FD TWNR"])
        p.remove("HD Hall")
        self.assertEqual(len(p.slots), 7)

    @unittest.skipUnless(BACKUPS, "no pedal backup in data/pedal_dump")
    def test_backups_roundtrip_exactly(self):
        for f in BACKUPS:
            with open(f, "rb") as fh:
                raw = fh.read()
            self.assertEqual(Patch.decode(raw).encode(), raw, f)


if __name__ == "__main__":
    unittest.main()
