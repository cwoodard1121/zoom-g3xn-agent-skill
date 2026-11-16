"""The pedals g3xn drives, and the mode that picks one.

    from g3xn import models
    models.active().name          # "G3Xn" or "B1X FOUR"
    models.use("b1xfour")         # bass mode, kept in ~/.g3xn/mode.json

Both pedals speak the same Zoom protocol (device 0x6E) and show up as the
same "ZOOM G Series" port, so a pedal is told apart by its patch storage
reply (`44`): the G3Xn has 150 patches of 736 bytes, 3 to a bank; the
B1X FOUR has 50 of 760, 10 to a bank. Its patches carry PTCF target 128
where the G3Xn's carry 4.

One pedal at a time: the mode says which one the CLI, Claude and the API
drive, and each pedal keeps its own catalog, scratch slot, state and backups.
The mode is G3XN_PEDAL if set, else ~/.g3xn/mode.json, else the G3Xn; it is
read on every call, so a long-running MCP server follows a switch.
"""
import json
import os

HOME = os.path.join(os.path.expanduser("~"), ".g3xn")
MODE_FILE = os.path.join(HOME, "mode.json")


class Model:
    def __init__(self, key, name, kind, patch_count, patch_size, bank_size, scratch, target, chain,
                 empty_pprm, empty_txe1, catalog_file, home, backup_root, dsp_budget, dsp_proven,
                 check_live_edits, has_screen, screen_offset=0):
        self.key = key
        self.name = name
        self.kind = kind                      # "guitar" or "bass"
        self.patch_count = patch_count
        self.patch_size = patch_size
        self.bank_size = bank_size
        self.scratch = scratch                # the slot auditions and live tweaks use
        self.target = target                  # PTCF header field
        self.chain = chain                    # ("positions", 7): 7 places, two-screen effects take 2
                                              # ("effects", 5): 5 effects; a two-screen effect adds a place
        self.empty_pprm = bytes.fromhex(empty_pprm)
        self.empty_txe1 = empty_txe1
        self.catalog_file = catalog_file
        self.state_file = os.path.join(home, "state.json")
        self.history_file = os.path.join(home, "history.json")    # the app's time machine
        self.gigs_folder = os.path.join(home, "gigs")             # the app's saved gigs
        self.guitars_file = os.path.join(home, "guitars.json")    # which instrument each slot is for
        self.backup_root = backup_root
        self.dsp_budget = dsp_budget
        self.dsp_proven = dsp_proven          # highest factory patch: known to work
        self.check_live_edits = check_live_edits    # read live edits back; rewrite the slot when one is missing
        self.has_screen = has_screen          # 64 02 screen text works on this pedal
        self.screen_offset = screen_offset    # the pedal's own screen shows slot n as n + this

    @property
    def max_effects(self):
        return self.chain[1] if self.chain[0] == "effects" else None

    @property
    def base_positions(self):
        """Chain positions in an Empty patch."""
        return self.chain[1]

    def matches(self, patch_count, patch_size, bank_size):
        return (patch_count, patch_size, bank_size) == (self.patch_count, self.patch_size, self.bank_size)

    def limits(self):
        """What Claude needs to know to build a tone for this pedal."""
        rule, n = self.chain
        out = {"pedal": self.name, "kind": self.kind, "patches": self.patch_count, "scratch_slot": self.scratch,
               "chain": ("%d chain positions; amps and some big effects take 2" % n if rule == "positions"
                         else "up to %d effects; amps and some big effects fill 2 screens but count as 1" % n)}
        if self.screen_offset:
            out["numbering"] = ("tools count slots 1..%d; the pedal's screen shows slot n as n+%d (slot 1 = %d, "
                                "slot %d = %d). When the user reads a number off the pedal, subtract %d."
                                % (self.patch_count, self.screen_offset, 1 + self.screen_offset, self.patch_count,
                                   self.patch_count + self.screen_offset, self.screen_offset))
        return out

    def app_view(self):
        """What the app's screens need to draw this pedal."""
        return {"key": self.key, "name": self.name, "kind": self.kind, "patches": self.patch_count,
                "bank_size": self.bank_size, "scratch_slot": self.scratch,
                "chain": {"rule": self.chain[0], "max": self.chain[1]}, "screen_offset": self.screen_offset}

    def __repr__(self):
        return "<Model %s>" % self.key


_DATA = os.path.join(os.path.dirname(__file__), "data")

MODELS = {
    "g3xn": Model("g3xn", "G3Xn", "guitar", 150, 736, 3, 150, 4, ("positions", 7),
                  "000000000000000032840c00", 0, os.path.join(_DATA, "effects.json"), HOME,
                  os.path.join(os.path.expanduser("~"), "g3xn-backups"), 250.0, 231.3,
                  check_live_edits=False, has_screen=True),
    # read off a B1X FOUR, firmware 2.00, on 2026-11-15. Live edits and screen text ran on it on
    # 2026-11-16: 235 of 235 knob edits landed, but a read about 0.3 s after a patch change can be
    # 30 to 45 ms behind, so edits are read back (and read again) before g3xn reports them.
    "b1xfour": Model("b1xfour", "B1X FOUR", "bass", 50, 760, 10, 50, 128, ("effects", 5),
                     "000000000000000032000000", 200, os.path.join(_DATA, "effects_b1xfour.json"),
                     os.path.join(HOME, "b1xfour"), os.path.join(os.path.expanduser("~"), "g3xn-backups-b1xfour"),
                     250.0, 222.5, check_live_edits=True, has_screen=True,
                     screen_offset=9),     # Zoom's manual: patches show as 10..59
}
ALIASES = {"g3": "g3xn", "g3n": "g3xn", "guitar": "g3xn", "b1": "b1xfour", "b1four": "b1xfour",
           "b1xfour": "b1xfour", "bass": "b1xfour"}


def get(key):
    """A model by key, alias or name ("b1xfour", "bass", "B1X FOUR"); a Model passes through."""
    if isinstance(key, Model):
        return key
    k = "".join(c for c in str(key).lower() if c.isalnum())
    k = ALIASES.get(k, k)
    if k not in MODELS:
        raise ValueError("unknown pedal %r: pick %s" % (key, " or ".join(MODELS)))
    return MODELS[k]


def by_target(target):
    """The model whose patches carry this PTCF target, or None."""
    return next((m for m in MODELS.values() if m.target == target), None)


def detect(patch_count, patch_size, bank_size):
    """The model with this patch storage (the `44` reply), or None."""
    return next((m for m in MODELS.values() if m.matches(patch_count, patch_size, bank_size)), None)


def active():
    """The pedal the mode points at."""
    if os.environ.get("G3XN_PEDAL"):
        return get(os.environ["G3XN_PEDAL"])
    try:
        with open(MODE_FILE) as f:
            return get(json.load(f)["pedal"])
    except (OSError, ValueError, KeyError, TypeError):
        return MODELS["g3xn"]


def pin(key):
    """Fix this process (and the programs it starts) to one pedal, whatever the mode file says."""
    os.environ["G3XN_PEDAL"] = get(key).key


def use(key):
    """Switch the mode (kept in ~/.g3xn/mode.json). G3XN_PEDAL still wins for its own process."""
    model = get(key)
    os.makedirs(os.path.dirname(MODE_FILE), exist_ok=True)
    with open(MODE_FILE, "w") as f:
        json.dump({"pedal": model.key}, f)
    return model
