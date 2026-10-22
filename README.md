# g3xn

**Build, edit and play Zoom G3n / G3Xn patches from code, the command line, or an AI agent.**

No ToneLib, no Guitar Lab. `g3xn` talks to the pedal over USB-MIDI, knows every one of its 162 effects by name, and lets you hear a change about a tenth of a second after you make it.

```text
$ g3xn audition examples/texas_blues.json
TEXAS BLUE  (volume 90, DSP 55.5%)
  1. TS Drive   on  Gain=35  Boost=0  Tone=60  VOL=85
  2. FD TWNR    on  Bass=40  MID=50  Treble=55  BRGHT=0  Gain=40  VOL=70  DEPTH=40  SPEED=40
  3. Spring     on  PreD=0  Decay=19  Mix=25  Tail=0

$ g3xn set "FD TWNR" Treble 40     # too ice-picky? hear the fix instantly
$ g3xn save 123                    # keep it
```

> Verified on a G3Xn running firmware 2.20. The G3n uses the same protocol and should work too. Not affiliated with Zoom.

---

## What it can do

| | |
|---|---|
| **Read & write patches** | All 150 slots, byte-exact (every factory and user patch round-trips unchanged) |
| **Build patches offline** | By effect and knob name, with the pedal's own defaults, range checks, chain-length and DSP limits |
| **Audition instantly** | Loads any patch onto a scratch slot (~0.1 s); knob, on/off, volume and name changes go live (<0.1 s) |
| **See what the pedal shows** | Reads the screen text, so you get the numbers and names the pedal displays (FD TWNR's knobs read 10 higher on screen than in the file; Rhythm shows pattern names like `GUIDE`) |
| **Tuner** | Turn it on and stream the note + meter |
| **Effect catalog** | 162 effects: name, group, description, DSP cost, chain positions, every knob's range/default/explanation |
| **Backups** | Dump every slot to `.zptc` files in one command |

## Install

```bash
git clone https://github.com/cwoodard1121/zoom-g3xn-agent-skill
cd zoom-g3xn-agent-skill
pip install -e .
```

Plug the pedal in over USB and **close ToneLib / Guitar Lab**: Windows lets only one program use a MIDI port at a time.

## Command line

```text
g3xn info                          pedal, firmware, current patch
g3xn list                          every slot's name
g3xn show 121                      a slot's chain and knobs
g3xn effects drive                 search the catalog (--group AMP|DRIVE|DELAY|...)
g3xn effect "MS 1959"              one effect's knobs, ranges, defaults

g3xn audition tone.json            hear a patch now (also .zptc files or a slot number)
g3xn set "FD TWNR" Gain 45         change a knob live
g3xn on|off "TS Drive"             toggle an effect live
g3xn volume 95                     patch level live
g3xn save 123                      store what you're hearing into slot 123

g3xn write tone.json 123           write a file straight into a slot
g3xn export 121 free_bird.json     save a slot as JSON or .zptc
g3xn build tone.json tone.zptc     validate / convert offline
g3xn backup                        copy every slot into backups/<timestamp>/
g3xn tuner 30                      live tuner for 30 s
```

Add `--json` to any command for machine-readable output.

## Python

```python
from g3xn import Pedal, Patch, catalog

catalog().get("FD TWNR").params          # [<Param Bass 0..90 default 38>, ...]

tone = Patch.blank("CRUNCH")
tone.add("TS Drive", Gain=30, Tone=55)
tone.add("MS 1959", Treble=55, Input1=70)
tone.add("HD Hall", Mix=20)
tone.volume = 95

with Pedal() as pedal:
    pedal.audition(tone)                 # hear it
    tone.effect("MS 1959")["PRSNC"] = 30
    pedal.push(tone)                     # sends only what changed
    pedal.save_scratch(123)              # keep it
```

| `Patch` | |
|---|---|
| `Patch.blank(name)` / `Patch.load(path)` / `Patch.from_dict(spec)` | create |
| `.add(effect, at=None, enabled=True, **knobs)` | insert an effect (knob names ignore case and punctuation) |
| `.remove(key)` `.move(key, to)` `.replace(key, effect)` | edit the chain (`key` = name or 1-based number) |
| `.effect(key)["Gain"] = 45` / `.effect(key).enabled = False` | knobs and on/off |
| `.volume` `.name` `.chain` `.dsp_percent` `.problems()` | settings and checks |
| `.encode()` / `.save(path)` / `.to_dict()` | serialise |

| `Pedal` | |
|---|---|
| `current()` `select(n)` `identity()` | where the pedal is |
| `read(n)` `write(n, patch)` `backup(folder)` | stored slots |
| `audition(patch)` `push(patch)` `save_scratch(n)` | hear and keep |
| `set_knob` `set_enabled` `set_effect` `set_volume` `set_name` `set_tempo` | live edits (scratch only) |
| `edit_buffer()` `display()` `screen(pos)` | what's loaded, and what the screens show |
| `tuner(on)` `tuner_readings(seconds)` | tuner |
| `list_files()` `read_file(name)` | the pedal's effect files |

## Tone files

A patch is a short JSON file, which is easy for people and agents to write:

```json
{
 "name": "TEXAS BLUE",
 "volume": 90,
 "chain": [
  {"effect": "TS Drive", "on": true, "knobs": {"Gain": 35, "Tone": 60}},
  {"effect": "FD TWNR", "knobs": {"Treble": 55, "Gain": 40}},
  {"effect": "Spring", "knobs": {"Mix": 25}}
 ]
}
```

Effects run in signal order. Knobs you leave out get the pedal's defaults. `.zptc` (the pedal's raw 736-byte format) works anywhere a `.json` does.

## Safety

These pedals usually run with **autosave on**: any live edit is written into whichever slot is selected. So `g3xn`:

- does every live edit on a **scratch slot** (default **150**, change with `--scratch N` / `Pedal(scratch=N)`), and refuses live edits anywhere else;
- only claims a scratch slot that is **Empty**;
- refuses to write a slot the pedal is currently sitting on, because the pedal's edit buffer would overwrite it;
- reads every write back and checks it byte-for-byte.

Run `g3xn backup` before big changes anyway.

## How it works

The G3n/G3Xn speaks Zoom's SysEx dialect (`F0 52 00 6E ... F7`). [`g3xn/protocol.py`](g3xn/protocol.py) documents every message this project uses. All of them were verified on hardware, including tuner, live edits, screen text and the patch-select quirks.

The effect catalog ([`g3xn/data/effects.json`](g3xn/data/effects.json)) is extracted from the pedal itself:

1. [`tools/pull_from_pedal.py`](tools/pull_from_pedal.py) downloads every `.ZD2` effect file from the pedal's storage, backs up all slots, and loads each effect once on the scratch slot to record exactly what the pedal stores.
2. [`tools/build_catalog.py`](tools/build_catalog.py) pulls names and descriptions from each `.ZD2`, reads knob ranges and defaults out of the effect's embedded DSP binary (a TI C6x ELF), and cross-checks chain positions against real patches.

Patch format notes live at the top of [`g3xn/patch.py`](g3xn/patch.py).

## Roadmap

- **Agent plugin**: a Claude Code / Claude Desktop plugin (MCP server + skill) so you can say *"make it less fizzy"* or *"build me the Sultans of Swing tone"* and hear it on the pedal right away
- **Desktop app**: patch librarian, tuner, gig setlists, built-in AI tone assistant

## Credits

Built on reverse-engineering work by [mungewell/zoom-zt2](https://github.com/mungewell/zoom-zt2) (PTCF and ZD2 formats, file transfer protocol) and [shooking](https://github.com/shooking/ZoomPedalFun) (looper/rhythm IDs). MIT licensed.
