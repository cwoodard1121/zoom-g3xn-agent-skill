"""The command line's own printing (the commands themselves are tested through the service)."""
import pin_mode  # noqa: F401  (G3Xn mode for these tests)
import contextlib
import io
import unittest

from g3xn import cli


class ModeCommandTest(unittest.TestCase):
    def test_mode_prints_the_pedal(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["mode"])
        self.assertEqual(code, 0)
        self.assertIn("G3Xn", out.getvalue())
        self.assertIn("150", out.getvalue())


if __name__ == "__main__":
    unittest.main()
