"""Everything you can do with the pedal, as plain functions that return JSON-ready dicts.

The MCP server (Claude) and the daemon (the app) both call these, so the
safety rules live in one place:
  * auditions and live tweaks only touch the scratch slot;
  * a slot that holds a patch is never overwritten without replace=True;
  * loading a gig backs up every slot first.

Functions that need the pedal take it as the first argument. Refusals raise
PedalError with a message meant for the user.

Tone JSON (what audition / write_tone / gigs take):
    {"name": "BLUES", "volume": 90,
     "chain": [{"effect": "TS Drive", "on": true, "knobs": {"Gain": 40}}, ...]}
"""
import datetime
import os
import time

from . import gig as gigs
from .catalog import catalog
from .patch import Patch
from .pedal import PedalError

BACKUP_ROOT = os.path.join(os.path.expanduser("~"), "g3xn-backups")


# --- tone JSON ---

def tone(patch):
    """A patch as tone JSON, plus volume and DSP load."""
    return {"name": patch.name, "volume": patch.volume, "dsp_percent": patch.dsp_percent,
            "chain": [{"effect": c.name, "on": c.enabled, "knobs": c.knobs()} for c in patch.chain]}


def live_view(pedal):
    """What the pedal is playing right now, with the screen's own text for each knob."""
    view = tone(pedal.edit_buffer())
    for fx, shown in zip(view["chain"], pedal.display()):
        fx["shown"] = shown["knobs"]
    view["slot"] = pedal.current()
    return view


# --- looking around ---

def status(pedal):
    """Model, firmware, the patch the pedal is on, and the scratch slot."""
    info = pedal.identity()
    n = pedal.current()
    info.update(current_slot=n, current_name=pedal.read(n).name, scratch_slot=pedal.scratch,
                auditioning=n == pedal.scratch)
    return info


def list_patches(pedal):
    return {"patches": [{"slot": n, "name": pedal.read(n).name} for n in range(1, pedal.patch_count + 1)]}


def get_patch(pedal, slot):
    """A slot as tone JSON. The slot the pedal is on is read live (unsaved tweaks + screen text)."""
    if pedal.current() == slot:
        return live_view(pedal)
    return dict(tone(pedal.read(slot)), slot=slot)


def find_effects(query="", group=""):
    return {"effects": [{"name": e.name, "group": e.group, "positions": e.positions, "dsp_percent": e.dsp_percent,
                         "description": e.description} for e in catalog().search(query, group or None)]}


def effect_details(name):
    return catalog().get(name).summary()


# --- hearing tones (scratch slot) ---

def audition(pedal, tone=None, slot=None):
    """Play a tone (or a copy of a stored slot) on the scratch slot."""
    patch = pedal.read(slot) if slot else Patch.from_dict(tone or {})
    problems = patch.problems()
    if problems:
        raise PedalError("; ".join(problems))
    pedal.audition(patch)
    return live_view(pedal)


def tweak(pedal, changes=None, volume=None, name=None):
    """Live changes to the auditioned tone. Each change is
    {"effect", "knob", "value"} or {"effect", "on"}; effect = name or 1-based chain number."""
    if pedal.current() != pedal.scratch:
        raise PedalError("nothing is being auditioned; audition a tone first")
    patch = pedal.edit_buffer()
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
    pedal.push(patch)
    return live_view(pedal)


def play(pedal, tone):
    """Make the scratch slot sound like `tone` as fast as possible: live edits when only
    knobs, on/off, volume or name differ from what is playing, else a full audition.
    (Undo, the time machine and A/B use this.)"""
    patch = Patch.from_dict(tone)
    problems = patch.problems()
    if problems:
        raise PedalError("; ".join(problems))
    pedal.push(patch)
    return live_view(pedal)


def morph(pedal, to, seconds=3.0, steps_per_second=12):
    """Glide from the tone playing now to `to` over a few seconds, for swells and build-ups.
    Both need the same effects in the same order. Knobs sweep; switches (on/off, and knobs
    with named settings like Tail OFF/ON) flip halfway; the patch volume lands at the end."""
    if pedal.current() != pedal.scratch:
        raise PedalError("nothing is being auditioned; audition a tone first")
    start, target = pedal.edit_buffer(), Patch.from_dict(to)
    if [s.id for s in start.slots] != [s.id for s in target.slots]:
        raise PedalError("morphing needs the same effects in the same order (%s vs %s)" % (
            " > ".join(c.name for c in start.chain), " > ".join(c.name for c in target.chain)))
    sent = [list(s.knobs) for s in start.slots]
    on = [s.enabled for s in start.slots]
    steps = max(1, int(seconds * steps_per_second))
    t0 = time.time()
    for step in range(1, steps + 1):
        f = step / steps
        for pos, (a, b) in enumerate(zip(start.slots, target.slots)):
            if b.is_empty or b.is_continuation:
                continue
            effect = catalog().find(b.id)
            for k, (va, vb) in enumerate(zip(a.knobs, b.knobs)):
                param = effect.params[k] if effect and k < len(effect.params) else None
                if va == vb or param is None:
                    continue
                switch = bool(param.display and "options" in param.display)
                value = (vb if f >= 0.5 else va) if switch else round(va + (vb - va) * f)
                if value != sent[pos][k]:
                    pedal.set_knob(pos, k, value)
                    sent[pos][k] = value
            if f >= 0.5 and on[pos] != b.enabled:
                pedal.set_enabled(pos, b.enabled)
                on[pos] = b.enabled
        time.sleep(max(0.0, t0 + seconds * f - time.time()))
    if start.volume != target.volume:
        pedal.set_volume(target.volume)
    return live_view(pedal)


# --- storing patches ---

def save_to_slot(pedal, slot, name=None, replace=False):
    """Store the auditioned tone into `slot` and switch to it."""
    if not replace:
        _refuse_if_taken(pedal, slot)
    if name:
        pedal.set_name(name[:10])
    pedal.save_scratch(slot)
    return {"saved": pedal.read(slot).name, "slot": slot}


def write_tone(pedal, tone, slot, replace=False):
    """Write a tone straight into a slot without auditioning it."""
    if not replace:
        _refuse_if_taken(pedal, slot)
    patch = Patch.from_dict(tone)
    pedal.write(slot, patch)
    return {"written": patch.name, "slot": slot}


def select_patch(pedal, slot):
    pedal.select(slot)
    return {"slot": slot, "name": pedal.read(slot).name}


def backup(pedal, folder=""):
    """Copy every slot to .zptc files (default ~/g3xn-backups/<timestamp>)."""
    return {"backup": pedal.backup(folder or _backup_folder(pedal))}


# --- gigs ---

def plan_gig(pedal, gig):
    """Where each song would go, and what it would replace. Writes nothing."""
    return {"plan": gigs.public(gigs.plan(pedal, gig)), "confirmed": False}


def load_gig(pedal, gig):
    """Back up every slot, then write the gig."""
    steps, folder = gigs.write(pedal, gig, _backup_folder(pedal))
    return {"written": gigs.public(steps), "backup": folder, "confirmed": True}


def export_gig(pedal, first_slot, last_slot, name="Exported gig"):
    return gigs.export(pedal, first_slot, last_slot, name)


# --- tuner ---

def tuner(pedal, seconds=8.0):
    """Run the tuner for a few seconds; the note and how far off it was (meter: - flat, 0 in tune, + sharp)."""
    pedal.tuner(True)
    try:
        seen = [r for r in pedal.tuner_readings(seconds) if r["note"]]
    finally:
        pedal.tuner(False)
    if not seen:
        return {"readings": [], "note": "no signal; play a string while the tuner runs"}
    last = seen[-5:]
    return {"note": last[-1]["note"], "meter": round(sum(r["meter"] for r in last) / len(last), 1),
            "readings": len(seen)}


# --- helpers ---

def _refuse_if_taken(pedal, slot):
    name = pedal.read(slot).name
    if name != "Empty":
        raise PedalError("slot %d holds %r. Ask the user before replacing it, then call again with "
                         "replace=true (or pick an Empty slot)." % (slot, name))


def _backup_folder(pedal):
    root = getattr(pedal.device, "backup_root", BACKUP_ROOT)     # a virtual pedal backs up elsewhere
    return os.path.join(root, datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
