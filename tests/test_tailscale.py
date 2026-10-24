"""Tailscale serve left over by a force-stopped g3xn is stopped; a running g3xn's isn't."""
import os
import unittest
from unittest import mock

from g3xn import tailscale


class LeftOverTest(unittest.TestCase):
    def test_only_orphaned_serves_of_this_port(self):
        listing = "\n".join([
            '11 900 "C:\\Program Files\\Tailscale\\tailscale.EXE" serve --https=443 http://127.0.0.1:8372',   # orphaned
            '12 901 "C:\\Program Files\\Tailscale\\tailscale.EXE" serve --https=443 http://127.0.0.1:8372',   # owned
            '13 900 "C:\\Program Files\\Tailscale\\tailscale.EXE" serve --https=443 http://127.0.0.1:9999',   # another port
            '14 900 "C:\\Program Files\\Tailscale\\tailscale.EXE" up',
        ])
        ran, killed = [], []

        def run(cmd, **_):
            ran.append(cmd)
            return mock.Mock(stdout=listing)

        with mock.patch.object(tailscale, "_alive", lambda pid: pid == 901), \
                mock.patch.object(tailscale.os, "kill", lambda pid, sig: killed.append(pid)), \
                mock.patch.object(tailscale.time, "sleep", lambda s: None):
            stopped = tailscale.stop_left_over(8372, run=run)
        self.assertEqual(stopped, [11])
        if os.name == "nt":
            self.assertEqual(ran[-1][:3], ["taskkill", "/PID", "11"])
        else:
            self.assertEqual(killed, [11])


if __name__ == "__main__":
    unittest.main()
