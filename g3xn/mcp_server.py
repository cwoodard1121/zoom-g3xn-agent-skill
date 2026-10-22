"""MCP server: lets any MCP client (Claude Code, Claude Desktop, ...) design
and play tones on a connected Zoom G3n / G3Xn.

    g3xn-mcp            # stdio transport

Tones use the same JSON format as the CLI:
    {"name": "BLUES", "volume": 90,
     "chain": [{"effect": "TS Drive", "on": true, "knobs": {"Gain": 40}}, ...]}
"""
from . import Patch, Pedal, PedalError, catalog

try:
    from mcp.server.mcpserver import MCPServer as _Server   # mcp >= 2
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server       # mcp 1.x

INSTRUCTIONS = """Controls a Zoom G3Xn guitar pedal over USB.
Workflow: audition(tone) to hear a tone on the scratch slot, tweak(...) to adjust it live while the
user plays, save_to_slot(n) only when the user says to keep it. Never write over a slot that holds
one of the user's patches without asking. Knob values are the raw numbers the pedal stores; each
result also has `shown`, the text on the pedal's screen, which is what the user sees."""

server = _Server("g3xn", instructions=INSTRUCTIONS)


def _tone(patch):
    """A patch as tone JSON (what tools accept), plus volume/DSP info."""
    return {"name": patch.name, "volume": patch.volume, "dsp_percent": patch.dsp_percent,
            "chain": [{"effect": c.name, "on": c.enabled, "knobs": c.knobs()} for c in patch.chain]}


def _live_view(pedal):
    """What the user is hearing right now, with the screen's own text for each knob."""
    tone = _tone(pedal.edit_buffer())
    for fx, shown in zip(tone["chain"], pedal.display()):
        fx["shown"] = shown["knobs"]
    tone["slot"] = pedal.current()
    return tone


def _occupied(pedal, slot):
    """An error if `slot` holds a patch (anything but Empty), else None."""
    name = pedal.read(slot).name
    if name != "Empty":
        return {"error": "slot %d holds %r. Ask the user before replacing it, then call again with "
                         "replace=true (or pick an Empty slot from list_patches)." % (slot, name)}
    return None


def _run(fn):
    try:
        with Pedal() as pedal:
            return fn(pedal)
    except (PedalError, KeyError, ValueError, IndexError) as err:
        return {"error": err.args[0] if isinstance(err, KeyError) and err.args else str(err)}


# --- looking around ---

@server.tool()
def pedal_status() -> dict:
    """Pedal model, firmware, the patch it is on, and the scratch slot used for auditions."""
    def go(p):
        info = p.identity()
        n = p.current()
        info.update(current_slot=n, current_name=p.read(n).name, scratch_slot=p.scratch,
                    auditioning=n == p.scratch)
        return info
    return _run(go)


@server.tool()
def list_patches() -> dict:
    """Every slot number and patch name ("Empty" = free slot). Slots 1-75 are Zoom factory demos."""
    return _run(lambda p: {"patches": [{"slot": n, "name": p.read(n).name} for n in range(1, p.patch_count + 1)]})


@server.tool()
def get_patch(slot: int) -> dict:
    """A slot's effect chain and knobs as tone JSON. If the pedal is on that slot, this is what is
    playing right now (including unsaved tweaks) and includes `shown` screen values."""
    def go(p):
        if p.current() == slot:
            return _live_view(p)
        return dict(_tone(p.read(slot)), slot=slot)
    return _run(go)


@server.tool()
def find_effects(query: str = "", group: str = "") -> dict:
    """Search the pedal's 162 effects by name or description (e.g. "fuzz", "Marshall", "spring").
    group: DYNAMICS, FILTER, DRIVE, AMP, CABINET, MODULATION, SFX, DELAY, REVERB, PEDAL, LOOPER, RHYTHM.
    Amps and some big effects take 2 of the 7 chain positions."""
    return {"effects": [{"name": e.name, "group": e.group, "positions": e.positions, "dsp_percent": e.dsp_percent,
                         "description": e.description} for e in catalog().search(query, group or None)]}


@server.tool()
def effect_details(name: str) -> dict:
    """One effect's knobs: name, range (0..max), the pedal's default, and what each knob does."""
    try:
        return catalog().get(name).summary()
    except KeyError as err:
        return {"error": err.args[0]}


# --- hearing tones ---

@server.tool()
def audition(tone: dict | None = None, slot: int | None = None) -> dict:
    """Play a tone on the pedal right now, on the scratch slot (nothing of the user's is changed).
    Pass `tone` (tone JSON: name, volume 0-120, chain of {effect, on, knobs}; effects in signal
    order, max 7 positions, unset knobs use defaults) or `slot` to audition a copy of a stored patch."""
    def go(p):
        patch = p.read(slot) if slot else Patch.from_dict(tone or {})
        problems = patch.problems()
        if problems:
            return {"error": "; ".join(problems)}
        p.audition(patch)
        return _live_view(p)
    return _run(go)


@server.tool()
def tweak(changes: list[dict] | None = None, volume: int | None = None, name: str | None = None) -> dict:
    """Adjust the tone being auditioned, live (under 0.1 s). Each change is
    {"effect": "FD TWNR", "knob": "Treble", "value": 40} or {"effect": "TS Drive", "on": false}.
    `effect` may be a name or its 1-based chain number. Make several related changes in one call."""
    def go(p):
        if p.current() != p.scratch:
            return {"error": "nothing is being auditioned; call audition first"}
        patch = p.edit_buffer()
        for ch in changes or []:
            fx = patch.effect(ch["effect"])
            if "knob" in ch:
                fx[ch["knob"]] = int(ch["value"])
            if "on" in ch:
                fx.enabled = bool(ch["on"])
        if volume is not None:
            patch.volume = volume
        if name:
            patch.name = name[:10]
        p.push(patch)
        return _live_view(p)
    return _run(go)


@server.tool()
def change_chain(tone: dict) -> dict:
    """Replace the auditioned tone with a new chain (add/remove/reorder effects). Same as audition,
    but keeps you on the scratch slot. Use tweak for knob-only changes; it is faster."""
    return audition(tone=tone)


@server.tool()
def save_to_slot(slot: int, name: str | None = None, replace: bool = False) -> dict:
    """Store the tone being auditioned into `slot` and switch the pedal to it. Only do this when the
    user asks. A slot that isn't Empty is refused unless replace=true, which needs the user's explicit yes."""
    def go(p):
        taken = None if replace else _occupied(p, slot)
        if taken:
            return taken
        if name:
            p.set_name(name[:10])
        p.save_scratch(slot)
        return {"saved": p.read(slot).name, "slot": slot}
    return _run(go)


@server.tool()
def write_tone(tone: dict, slot: int, replace: bool = False) -> dict:
    """Write a tone straight into a slot without auditioning it. A slot that isn't Empty is
    refused unless replace=true, which needs the user's explicit yes."""
    def go(p):
        taken = None if replace else _occupied(p, slot)
        if taken:
            return taken
        patch = Patch.from_dict(tone)
        p.write(slot, patch)
        return {"written": patch.name, "slot": slot}
    return _run(go)


@server.tool()
def load_gig(gig: dict, confirm: bool = False) -> dict:
    """Load a setlist into consecutive slots. gig = {"name", "start_slot", "patches": [entries]}, each
    entry {"song", "tone": tone JSON} or {"song", "from_slot": n} (optionally "slot" to pin it).
    Without confirm=true this only returns the plan: show it to the user, especially any
    overwrites_real_patch, and call again with confirm=true once they agree. Writing always backs up
    every slot first."""
    from . import gig as gigs

    def go(p):
        if not confirm:
            return {"plan": gigs.public(gigs.plan(p, gig)), "confirmed": False}
        steps, folder = gigs.write(p, gig)
        return {"written": gigs.public(steps), "backup": folder, "confirmed": True}
    return _run(go)


@server.tool()
def export_gig(first_slot: int, last_slot: int, name: str = "Exported gig") -> dict:
    """Read a run of slots as a gig (full tone JSON for each non-Empty slot), to save or edit."""
    from . import gig as gigs
    return _run(lambda p: gigs.export(p, first_slot, last_slot, name))


@server.tool()
def select_patch(slot: int) -> dict:
    """Switch the pedal to a stored patch (nothing is changed)."""
    def go(p):
        p.select(slot)
        return {"slot": slot, "name": p.read(slot).name}
    return _run(go)


@server.tool()
def backup_pedal(folder: str = "") -> dict:
    """Copy every slot to .zptc files (default: ~/g3xn-backups/<timestamp>). Do this before
    writing several slots."""
    import datetime
    import os
    folder = folder or os.path.join(os.path.expanduser("~"), "g3xn-backups",
                                    datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    return _run(lambda p: {"backup": p.backup(folder)})


@server.tool()
def tuner(seconds: float = 8.0) -> dict:
    """Turn on the tuner for a few seconds while the user plays a string; returns the notes seen and
    how far off they were (meter: negative = flat, 0 = in tune, positive = sharp)."""
    def go(p):
        p.tuner(True)
        try:
            seen = [r for r in p.tuner_readings(seconds) if r["note"]]
        finally:
            p.tuner(False)
        if not seen:
            return {"readings": [], "note": "no signal; ask the user to play a string while the tuner runs"}
        last = seen[-5:]
        return {"note": last[-1]["note"], "meter": round(sum(r["meter"] for r in last) / len(last), 1),
                "readings": len(seen)}
    return _run(go)


def main():
    server.run()


if __name__ == "__main__":
    main()
