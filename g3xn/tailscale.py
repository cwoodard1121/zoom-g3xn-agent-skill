"""Tailscale: reach the phone remote from anywhere, and over HTTPS.

With Tailscale on the computer and the phone (signed in to the same account), the phone
reaches this computer at its tailnet address whatever network each is on: home Wi-Fi,
a phone hotspot at a gig, or mobile data.

`tailscale serve` also puts the remote behind HTTPS at https://<computer>.<tailnet>.ts.net,
which is what lets a phone's browser use its microphone. That needs HTTPS certificates
turned on once for the tailnet (admin console, DNS page). The serve runs only while the
remote is on, as a child process, so it leaves no standing configuration behind.
"""
import json
import os
import shutil
import subprocess
import threading
import time

WINDOWS_PATH = r"C:\Program Files\Tailscale\tailscale.exe"


def executable():
    found = shutil.which("tailscale")
    if found:
        return found
    return WINDOWS_PATH if os.name == "nt" and os.path.isfile(WINDOWS_PATH) else None


def status(run=subprocess.run):
    """{"running", "name", "ip", "https"} for this computer, or None without Tailscale."""
    exe = executable()
    if not exe:
        return None
    try:
        out = run([exe, "status", "--json"], capture_output=True, text=True, timeout=5, **_quiet())
        data = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    me = data.get("Self") or {}
    ips = [ip for ip in me.get("TailscaleIPs") or [] if "." in ip]
    return {"running": data.get("BackendState") == "Running",
            "name": (me.get("DNSName") or "").rstrip(".") or None,
            "ip": ips[0] if ips else None,
            "https": bool(data.get("CertDomains"))}


class Serve:
    """`tailscale serve` in front of a local port, for as long as it's running."""

    def __init__(self, port):
        self.port = port
        self.problem = None
        self._proc = None

    @property
    def on(self):
        return self._proc is not None and self._proc.poll() is None

    def start(self, info=None):
        """Start serving when Tailscale is running with HTTPS turned on. Returns the https URL or None."""
        info = info or status()
        self.problem = None
        if not info or not info["running"]:
            self.problem = "Tailscale isn't running on this computer."
            return None
        if not info["https"]:
            self.problem = ("Turn on HTTPS certificates for your tailnet (Tailscale admin console, DNS page) "
                            "so the phone's microphone works.")
            return None
        if not self.on:
            self._proc = subprocess.Popen([executable(), "serve", "--https=443", "http://127.0.0.1:%d" % self.port],
                                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True, **_quiet())
            threading.Thread(target=self._watch, args=(self._proc,), daemon=True).start()
            time.sleep(0.5)
            if not self.on:
                self.problem = self.problem or "tailscale serve stopped straight away"
                return None
        return "https://%s" % info["name"]

    def stop(self):
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _watch(self, proc):
        """Keep the last thing it said; if it stops while still wanted, that's why."""
        last = ""
        for line in proc.stdout:
            last = line.strip() or last
        if proc is self._proc:
            self.problem = last or "tailscale serve stopped"


def _quiet():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
