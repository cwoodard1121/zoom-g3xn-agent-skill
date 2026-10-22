"""The phone remote: the daemon's API on the local network, for paired phones only.

It is off until it's turned on from this computer (POST /api/remote, or
`g3xn-daemon --remote`). A phone pairs by entering a six-digit code shown on
the computer, and gets a cookie that works until the phone is forgotten.
Everything else on the network gets nothing but the page that asks for the code.

It's plain HTTP: on a shared network (venue Wi-Fi) someone listening in could
copy a phone's cookie. On stage, a phone hotspot is the safer network.
"""
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import uuid

import uvicorn

COOKIE = "g3xn_remote"
DEFAULT_PORT = 8372
CODE_SECONDS = 300          # a pairing code works for five minutes
CODE_TRIES = 5              # and is thrown away after five wrong guesses


class PairingRefused(PermissionError):
    pass


class Remote:
    """Pairing codes, paired phones, and the network listener."""

    def __init__(self, devices_file=None, port=DEFAULT_PORT, host="0.0.0.0"):
        """devices_file: where paired phones are remembered (None = until the daemon stops).
        host: the address to listen on; 0.0.0.0 is every network this computer is on."""
        self.devices_file, self.port, self.host = devices_file, port, host
        self.devices = self._load()
        self.code = None
        self._server = None
        self._thread = None

    # --- pairing ---

    def new_code(self):
        self.code = {"code": "%06d" % secrets.randbelow(10 ** 6), "expires": time.time() + CODE_SECONDS, "tries": 0}
        return self.code

    def pair(self, code, name=""):
        """(cookie token, device) for a phone that gave the open code. Raises PairingRefused."""
        open_code = self.code
        if not open_code or time.time() > open_code["expires"]:
            raise PairingRefused("no pairing code is open; get one on the computer")
        if not secrets.compare_digest(str(code).strip().encode(), open_code["code"].encode()):
            open_code["tries"] += 1
            if open_code["tries"] >= CODE_TRIES:
                self.code = None
                raise PairingRefused("too many wrong codes; get a new one on the computer")
            raise PairingRefused("that's not the code")
        self.code = None
        token = secrets.token_urlsafe(32)
        now = time.time()
        device = {"id": uuid.uuid4().hex[:8], "name": (name or "").strip()[:40] or "Phone",
                  "paired": now, "last_seen": now, "token": _digest(token)}
        self.devices.append(device)
        self._save()
        return token, _public(device)

    def device(self, token):
        """The paired phone holding this cookie token, or None."""
        if not token:
            return None
        digest = _digest(token)
        for d in self.devices:
            if secrets.compare_digest(d["token"], digest):
                if time.time() - d["last_seen"] > 60:
                    d["last_seen"] = time.time()
                    self._save()
                return d
        return None

    def forget(self, device_id):
        before = len(self.devices)
        self.devices = [d for d in self.devices if d["id"] != device_id]
        if len(self.devices) == before:
            raise KeyError("no paired phone %r" % device_id)
        self._save()

    def info(self, with_code=True):
        """What the computer shows: on/off, the address to open on the phone, the open code, paired phones."""
        code = self.code if self.code and time.time() < self.code["expires"] else None
        out = {"on": self.on, "url": self.url if self.on else None,
               "devices": [_public(d) for d in self.devices]}
        if with_code:
            out.update(code=code["code"] if code else None, code_expires=code["expires"] if code else None)
        return out

    # --- who may use the network listener ---

    def refusal(self, path, headers, cookies):
        """None if a request that arrived on the network listener may go ahead, else (status, why)."""
        host = headers.get("host") or ""
        if not _plausible_host(host.rsplit(":", 1)[0].strip("[]")):
            return 403, "unknown host"
        origin = headers.get("origin")
        if origin and origin != "http://" + host:
            return 403, "g3xn only answers its own pages"
        if path.startswith("/api/remote"):
            return 403, "pairing is managed from the computer"
        if path == "/api/pair":
            return None
        if (path.startswith("/api/") or path in ("/docs", "/redoc", "/openapi.json")) and not self.device(
                cookies.get(COOKIE)):
            return 401, "pair this phone first: enter the code shown on the computer"
        return None

    # --- the listener ---

    @property
    def on(self):
        return self._server is not None

    @property
    def url(self):
        return "http://%s:%d" % (lan_address() if self.host == "0.0.0.0" else self.host, self.port)

    def start(self, app):
        """Serve `app` on the network (blocking until it's listening)."""
        if self.on:
            return
        server = uvicorn.Server(uvicorn.Config(app, host=self.host, port=self.port, log_level="warning",
                                               lifespan="off"))      # the daemon is already started
        thread = threading.Thread(target=server.run, name="g3xn-remote", daemon=True)
        thread.start()
        while not server.started:
            if not thread.is_alive():
                raise OSError("can't listen on port %d (is something else using it?)" % self.port)
            time.sleep(0.02)
        self._server, self._thread = server, thread
        if not self.code:
            self.new_code()

    def stop(self):
        if not self.on:
            return
        self._server.should_exit = True
        self._thread.join(timeout=10)
        self._server = self._thread = None
        self.code = None

    # --- storage ---

    def _load(self):
        try:
            with open(self.devices_file, encoding="utf-8") as f:
                return json.load(f)["devices"]
        except (TypeError, OSError, ValueError, KeyError):
            return []

    def _save(self):
        if not self.devices_file:
            return
        os.makedirs(os.path.dirname(self.devices_file), exist_ok=True)
        tmp = self.devices_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"devices": self.devices}, f, indent=1)
        os.replace(tmp, self.devices_file)


def lan_address():
    """This computer's address on the local network (what the phone opens)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))      # picks the outgoing interface; nothing is sent
            return s.getsockname()[0]
        except OSError:
            return socket.gethostbyname(socket.gethostname())


def _plausible_host(name):
    """An IP address or this computer's own name: a page from another site that points its
    own domain at this computer (DNS rebinding) doesn't qualify."""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        me = socket.gethostname().lower()
        return name.lower() in ("localhost", me, me + ".local")


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _public(device):
    return {k: v for k, v in device.items() if k != "token"}
