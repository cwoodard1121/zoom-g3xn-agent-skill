"""The g3xn desktop app: the UI in its own window, with the daemon running inside it.

    g3xn-app                  # build the UI once first: cd app && npm install && npm run build
    g3xn-app --sim            # on a virtual pedal, nothing plugged in

If a g3xn daemon is already running, the window opens onto it instead of
starting another. Without pywebview the app opens in your browser.
"""
import argparse
import contextlib
import json
import os
import sys
import tempfile
import threading
import urllib.request
import webbrowser

from . import daemon

TITLE = "g3xn"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="g3xn-app", description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=daemon.DEFAULT_PORT)
    daemon.add_pedal_options(ap)
    args = ap.parse_args(argv)

    if not os.path.isdir(daemon.UI_DIR):
        sys.exit("The app's screens aren't built yet. Run once:  cd app && npm install && npm run build")

    url, stop = _running_daemon(), None
    if url is None or args.sim is not None:
        port = args.port if args.sim is None else daemon.free_port()
        real = args.sim is None
        url, stop = daemon.start_in_thread(daemon.pedal_factory(args), port, announce=real,
                                           history_file=daemon.HISTORY_FILE if real else None,
                                           gigs_folder=daemon.GIGS_FOLDER if real else None,
                                           remote=daemon.Remote(daemon.REMOTE_FILE if real else None, use_tailscale=real),
                                           footswitches=daemon.Footswitches(daemon.MIDI_FILE if real else None),
                                           backups_folder=daemon.service.BACKUP_ROOT if real else None,
                                           tracks_folder=daemon.TRACKS_FOLDER if real else
                                           tempfile.mkdtemp(prefix="g3xn-tracks-"))
    try:
        _show(url)
    finally:
        if stop:
            stop()


def _running_daemon():
    """The URL of a g3xn daemon that is already running, if any."""
    try:
        with open(daemon.DISCOVERY_FILE) as f:
            url = json.load(f)["url"]
        with urllib.request.urlopen(url + "/api/status", timeout=1):
            return url
    except (OSError, ValueError, KeyError):
        return None


def _show(url):
    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        print("g3xn is open in your browser at %s. Press Ctrl+C to quit." % url)
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()
        return
    webview.create_window(TITLE, url, width=1440, height=940, min_size=(380, 560), background_color="#24262a")
    webview.start()


if __name__ == "__main__":
    main()
