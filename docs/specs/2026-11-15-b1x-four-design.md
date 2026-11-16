# Zoom B1X FOUR bass pedal support (#1)

## Goal

You ask Claude for a bass tone, and Claude builds it and plays it on the B1X FOUR. A mode picks the pedal. The bass side keeps its own effect catalog, scratch slot, scratch state and backups, apart from the G3Xn.

## Facts from the pedal (2026-11-15, firmware 2.00)

| Fact | G3Xn | B1X FOUR |
|---|---|---|
| USB-MIDI port name | ZOOM G Series | ZOOM G Series |
| SysEx device id | 0x6E | 0x6E |
| Identity model bytes | 1F 00 | 0F 00 |
| Patches x bytes, per bank (`44` reply) | 150 x 736, 3 | 50 x 760, 10 |
| PTCF target | 4 | 128 |
| Chain | 7 positions | 5 effects; a two-screen effect adds a continuation position (5 to 7 positions) |
| Empty PPRM | 000000000000000032840c00 | 000000000000000032000000 |
| Effects | 162 | 80 .ZD2 files, no rhythm or looper templates |
| Highest factory DSP | 231.3 | 222.5 |
| Free slots | 148-149 (150 = scratch) | 42-50 (50 = scratch) |

The suite reads B1X FOUR patches with the G3Xn decoder unchanged. All 50 patches re-encode byte for byte. All 80 harvested templates hold the knob defaults the .ZD2 files give, so the knob bit layout is the same. Patch write, select, `64 03` effect load and `64 13` edit buffer read work. A stored slot keeps leftover bytes past the PTCF length, so a read-back compares only up to that length.

Not tested on the B1X FOUR: live knob, on/off, volume and name edits, screen text (`64 02`), tuner, tempo.

## Decisions

| Question | Options | Choice |
|---|---|---|
| Is the pedal here? | yes / not yet / bandmate | Yes. Its files, patches and templates were dumped, then it was unplugged |
| How does the mode switch? | one pedal at a time / both live / auto | Owner said "figure it out": one pedal at a time, picked by a mode |
| What is "separate"? | same suite with per-pedal data / a second package | Same suite. Each pedal has its own catalog, scratch slot, state file and backups |
| Scope | full app / basic | Owner: "just make a basic one, I just wanna ask Claude to make tones". No UI work |

## Design

`g3xn/models.py` holds one `Model` per pedal (key, name, patch count, size, bank size, scratch slot, PTCF target, chain rule, empty PPRM, DSP numbers, catalog file, state file, backup folder, whether screen text works). The mode comes from `G3XN_PEDAL`, else `~/.g3xn/mode.json`, else `g3xn`. It is read on every call, so a long-running MCP server follows a switch.

`Pedal` opens the Zoom port whose `44` reply matches the mode's model and refuses with a "switch the mode" message when the connected pedal is the other one. Its scratch slot and state file come from the model.

`Patch` carries its model. `decode` takes it from the PTCF target. `blank` and `from_dict` use the mode's model. The chain rule, size, PPRM and DSP checks come from the model. `Pedal.write` refuses a patch built for the other pedal.

`catalog(model)` keeps one catalog per model. The B1X catalog ships as `g3xn/data/effects_b1xfour.json`, built by `tools/build_catalog.py data/b1xfour`.

`Pedal.push` on a model without proven live edits reads the edit buffer back after the edits and rewrites the scratch slot when they did not apply. `display()` returns nothing on a model whose screen text is untested.

The MCP server gets `pedal_mode` (show or switch the mode). `pedal_status` reports the model's limits. The instructions stop naming the G3Xn's numbers. The CLI gets `g3xn mode [g3xn|b1xfour]`.

## Surfaces

MCP tools (Claude), the CLI and the Python API. The desktop app and the daemon stay G3Xn only.

## Data and interfaces

New: `~/.g3xn/mode.json`, `~/.g3xn/b1xfour/state.json`, `~/g3xn-backups-b1xfour/`, MCP tool `pedal_mode`, CLI `g3xn mode`. Nothing changes for the G3Xn.

## Edge cases

The mode says G3Xn but the bass pedal is plugged in (or the other way round): the pedal refuses to open and names the fix. A patch file from the other pedal: `write` and `audition` refuse it. The daemon is running while the mode is bass: `pedal_mode` says to close the app first.

## Success check

With the B1X FOUR plugged in, the owner switches to bass mode, asks Claude for a bass tone and hears it on slot 50.

## Left out

The desktop app, the daemon, gigs, the tuner and tempo in bass mode, and screen text. Each needs either UI design or a hardware test.
