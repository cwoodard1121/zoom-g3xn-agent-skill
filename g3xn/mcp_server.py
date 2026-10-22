"""MCP server: lets any MCP client (Claude Code, Claude Desktop, ...) design
and play tones on a connected Zoom G3n / G3Xn.

    g3xn-mcp            # stdio transport

While the g3xn daemon (the desktop app) is running it owns the pedal, so tool
calls go through it and the app shows every change; otherwise each call opens
the pedal itself.

Tones use the same JSON format as the CLI:
    {"name": "BLUES", "volume": 90,
     "chain": [{"effect": "TS Drive", "on": true, "knobs": {"Gain": 40}}, ...]}
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import Pedal, PedalError, gig, service

try:
    from mcp.server.mcpserver import MCPServer as _Server   # mcp >= 2
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server       # mcp 1.x

INSTRUCTIONS = """Controls a Zoom G3Xn guitar pedal over USB.
Workflow: audition(tone) to hear a tone on the scratch slot, tweak(...) to adjust it live while the
user plays, save_to_slot(n) only when the user says to keep it. Never write over a slot that holds
one of the user's patches without asking. Knob values are the raw numbers the pedal stores; each
result also has `shown`, the text on the pedal's screen, which is what the user sees.
Gigs saved in the g3xn app: saved_gigs, get_gig, edit_gig (one change to every song; preview
first), load_saved_gig, and check_gig to find and undo changes made on the pedal during a show."""

DAEMON_FILE = os.path.join(os.path.expanduser("~"), ".g3xn", "daemon.json")
GIGS_FOLDER = gig.FOLDER    # the app's saved gigs
open_pedal = Pedal          # tests swap in a virtual pedal

server = _Server("g3xn", instructions=INSTRUCTIONS)


def _pedal(direct, method, path, body=None, needs_pedal=True):
    """Run a tool through the g3xn daemon when it is running (the app owns the pedal then),
    otherwise open the pedal for this one call (needs_pedal=False: call direct(None)).
    Errors come back as {"error": ...}."""
    url = _daemon_url()
    if url:
        try:
            return _http(url, method, path, body)
        except urllib.error.HTTPError as err:
            reply = json.loads(err.read() or b"{}")
            return {"error": reply.get("error") or str(reply.get("detail") or err)}
        except urllib.error.URLError:
            pass                                            # stale daemon.json: no daemon running
    try:
        if not needs_pedal:
            return direct(None)
        with open_pedal() as pedal:
            return direct(pedal)
    except (PedalError, KeyError, ValueError, IndexError) as err:
        return {"error": err.args[0] if isinstance(err, KeyError) and err.args else str(err)}


def _daemon_url():
    try:
        with open(DAEMON_FILE) as f:
            return json.load(f)["url"]
    except (OSError, ValueError, KeyError):
        return None


def _http(url, method, path, body):
    req = urllib.request.Request(url + path, method=method,
                                 headers={"Content-Type": "application/json", "X-G3xn-Source": "claude"},
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def _status_from_daemon(snap):
    """The daemon's /api/status in the same shape as service.status."""
    return dict(snap.get("pedal") or {}, current_slot=snap["current_slot"], current_name=snap["current_name"],
                scratch_slot=snap["scratch_slot"], auditioning=snap["current_slot"] == snap["scratch_slot"],
                connection=snap["connection"], problem=snap["problem"], via="g3xn app")


# --- looking around ---

@server.tool()
def pedal_status() -> dict:
    """Pedal model, firmware, the patch it is on, and the scratch slot used for auditions."""
    result = _pedal(service.status, "GET", "/api/status")
    return _status_from_daemon(result) if "connection" in result else result


@server.tool()
def list_patches() -> dict:
    """Every slot number and patch name ("Empty" = free slot). Slots 1-75 are Zoom factory demos."""
    return _pedal(service.list_patches, "GET", "/api/patches")


@server.tool()
def get_patch(slot: int) -> dict:
    """A slot's effect chain and knobs as tone JSON. If the pedal is on that slot, this is what is
    playing right now (including unsaved tweaks) and includes `shown` screen values."""
    return _pedal(lambda p: service.get_patch(p, slot), "GET", "/api/patches/%d" % slot)


@server.tool()
def find_effects(query: str = "", group: str = "") -> dict:
    """Search the pedal's 162 effects by name or description (e.g. "fuzz", "Marshall", "spring").
    group: DYNAMICS, FILTER, DRIVE, AMP, CABINET, MODULATION, SFX, DELAY, REVERB, PEDAL, LOOPER, RHYTHM.
    Amps and some big effects take 2 of the 7 chain positions."""
    return service.find_effects(query, group)


@server.tool()
def effect_details(name: str) -> dict:
    """One effect's knobs: name, range (0..max), the pedal's default, and what each knob does."""
    try:
        return service.effect_details(name)
    except KeyError as err:
        return {"error": err.args[0]}


# --- hearing tones ---

@server.tool()
def audition(tone: dict | None = None, slot: int | None = None, reason: str = "") -> dict:
    """Play a tone on the pedal right now, on the scratch slot (nothing of the user's is changed).
    Pass `tone` (tone JSON: name, volume 0-120, chain of {effect, on, knobs}; effects in signal
    order, max 7 positions, unset knobs use defaults) or `slot` to audition a copy of a stored patch.
    `reason`: a few words on what you were going for; the g3xn app shows it in its history."""
    return _pedal(lambda p: service.audition(p, tone, slot), "POST", "/api/audition",
                  {"tone": tone, "slot": slot, "reason": reason})


@server.tool()
def tweak(changes: list[dict] | None = None, volume: int | None = None, name: str | None = None,
          reason: str = "") -> dict:
    """Adjust the tone being auditioned, live (under 0.1 s). Each change is
    {"effect": "FD TWNR", "knob": "Treble", "value": 40} or {"effect": "TS Drive", "on": false}.
    `effect` may be a name or its 1-based chain number. Make several related changes in one call.
    `reason`: why, in the user's terms ("too ice-picky"); the g3xn app shows it in its history."""
    return _pedal(lambda p: service.tweak(p, changes, volume, name), "POST", "/api/tweak",
                  {"changes": changes or [], "volume": volume, "name": name, "reason": reason})


@server.tool()
def change_chain(tone: dict, reason: str = "") -> dict:
    """Replace the auditioned tone with a new chain (add/remove/reorder effects). Same as audition,
    but keeps you on the scratch slot. Use tweak for knob-only changes; it is faster."""
    return audition(tone=tone, reason=reason)


@server.tool()
def save_to_slot(slot: int, name: str | None = None, replace: bool = False) -> dict:
    """Store the tone being auditioned into `slot` and switch the pedal to it. Only do this when the
    user asks. A slot that isn't Empty is refused unless replace=true, which needs the user's explicit yes."""
    return _pedal(lambda p: service.save_to_slot(p, slot, name, replace), "POST", "/api/patches/%d/save" % slot,
                  {"name": name, "replace": replace})


@server.tool()
def write_tone(tone: dict, slot: int, replace: bool = False) -> dict:
    """Write a tone straight into a slot without auditioning it. A slot that isn't Empty is
    refused unless replace=true, which needs the user's explicit yes."""
    return _pedal(lambda p: service.write_tone(p, tone, slot, replace), "PUT", "/api/patches/%d" % slot,
                  {"tone": tone, "replace": replace})


@server.tool()
def load_gig(gig: dict, confirm: bool = False) -> dict:
    """Load a setlist into consecutive slots. gig = {"name", "start_slot", "patches": [entries]}, each
    entry {"song", "tone": tone JSON} or {"song", "from_slot": n} (optionally "slot" to pin it).
    Without confirm=true this only returns the plan: show it to the user, especially any
    overwrites_real_patch, and call again with confirm=true once they agree. Writing always backs up
    every slot first."""
    if not confirm:
        return _pedal(lambda p: service.plan_gig(p, gig), "POST", "/api/gigs/plan", gig)
    return _pedal(lambda p: service.load_gig(p, gig), "POST", "/api/gigs/load", gig)


@server.tool()
def export_gig(first_slot: int, last_slot: int, name: str = "Exported gig") -> dict:
    """Read a run of slots as a gig (full tone JSON for each non-Empty slot), to save or edit."""
    query = urllib.parse.urlencode({"first_slot": first_slot, "last_slot": last_slot, "name": name})
    return _pedal(lambda p: service.export_gig(p, first_slot, last_slot, name), "GET", "/api/gigs/export?" + query)


# --- the app's saved gigs ---

def _library():
    return gig.GigLibrary(GIGS_FOLDER)


def _saved(gig_id):
    try:
        return _library().get(gig_id)
    except OSError:
        raise KeyError("no saved gig %r; saved_gigs lists them" % gig_id)


@server.tool()
def saved_gigs() -> dict:
    """The gigs (setlists) saved in the g3xn app: id, name, songs, first slot, when each was last
    loaded, which one is on the pedal (active) and which is locked for a show."""
    return _pedal(lambda p: {"gigs": _library().list()}, "GET", "/api/setlists", needs_pedal=False)


@server.tool()
def get_gig(gig_id: str) -> dict:
    """A saved gig's songs: each with its tone (or the slot it copies), tempo, key and notes, plus
    which slots it was last loaded into."""
    return _pedal(lambda p: gig.shown(_saved(gig_id)), "GET", "/api/setlists/%s" % urllib.parse.quote(gig_id),
                  needs_pedal=False)


@server.tool()
def edit_gig(gig_id: str, edit: dict, save: bool = False) -> dict:
    """Make one change to every song of a saved gig ("every reverb down 10%", "a venue EQ on every
    song"). edit is one of:
      {"change": "knob", "effects": "reverb", "knob": "Mix", "percent": -10}   (or "by": n, "to": n)
      {"change": "volume", "by": 5}
      {"change": "off", "effects": "delay"}   (or "on")
      {"change": "add", "effect": "Gt GEQ", "at": 1, "knobs": {...}}   (at: chain number; default end)
      {"change": "remove", "effects": "Comp"}
    effects: a group (reverb, delay, drive, amp, cabinet, modulation, filter, dynamics, pedal,
    sfx), an effect name, a list, or "all". percent is of each knob's current value.
    First call with save=false: it returns what each song would get and why any are left alone
    (no match, wouldn't fit on the pedal). Tell the user, then call with save=true. This changes
    the saved gig only; load_saved_gig puts it on the pedal."""
    return _pedal(lambda p: service.edit_gig(p, _library(), _saved(gig_id)["id"], edit, save),
                  "POST", "/api/setlists/%s/batch" % urllib.parse.quote(gig_id), {"edit": edit, "save": save})


@server.tool()
def load_saved_gig(gig_id: str, confirm: bool = False) -> dict:
    """Put a saved gig on the pedal. Without confirm=true this only returns the plan: show it to the
    user, especially any overwrites_real_patch (replaces_own means the slot already holds this gig's
    own song), and call again with confirm=true once they agree. Every slot is backed up first."""
    path = "/api/setlists/%s/" % urllib.parse.quote(gig_id)
    if not confirm:
        return _pedal(lambda p: service.plan_gig(p, _saved(gig_id)), "POST", path + "plan")
    return _pedal(lambda p: service.load_saved_gig(p, _library(), _saved(gig_id)["id"]), "POST", path + "load")


@server.tool()
def check_gig(gig_id: str, restore: bool = False) -> dict:
    """Which songs of a loaded gig changed on the pedal since it was loaded (turning a knob on the
    pedal autosaves into the slot), e.g. "Hall Mix 40 → 55". restore=true puts them back (the
    changed versions are backed up first, and the pedal stays on its patch); ask the user first,
    since it undoes their changes."""
    def direct(p):
        loaded = (_saved(gig_id).get("loaded") or {}).get("slots")
        if not loaded:
            raise ValueError("that gig hasn't been loaded to the pedal yet")
        return service.restore_gig(p, loaded) if restore else service.check_gig(p, loaded)
    return _pedal(direct, "POST", "/api/setlists/%s/%s" % (urllib.parse.quote(gig_id), "restore" if restore else "check"))


@server.tool()
def select_patch(slot: int) -> dict:
    """Switch the pedal to a stored patch (nothing is changed)."""
    return _pedal(lambda p: service.select_patch(p, slot), "POST", "/api/patches/%d/select" % slot)


@server.tool()
def backup_pedal(folder: str = "") -> dict:
    """Copy every slot to .zptc files (default: ~/g3xn-backups/<timestamp>). Do this before
    writing several slots."""
    return _pedal(lambda p: service.backup(p, folder), "POST", "/api/backup", {"folder": folder})


@server.tool()
def tuner(seconds: float = 8.0) -> dict:
    """Turn on the tuner for a few seconds while the user plays a string; returns the notes seen and
    how far off they were (meter: negative = flat, 0 = in tune, positive = sharp)."""
    return _pedal(lambda p: service.tuner(p, seconds), "POST", "/api/tuner/read", {"seconds": seconds})


def main():
    server.run()


if __name__ == "__main__":
    main()
