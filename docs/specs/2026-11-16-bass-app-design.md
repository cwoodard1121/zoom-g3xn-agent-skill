# Bass mode in the Electron app, and a first release (#3)

## Goal

You open the g3xn app, pick Bass, and edit B1X FOUR tones with the same screens the G3Xn has. A GitHub release holds a Windows build that runs without the repo.

## Facts

- `desktop/` is already an Electron app. It starts the repo's `.venv` daemon and shows the daemon's web pages.
- The daemon and the app are pinned to the G3Xn (`models.pin("g3xn")`, added in #1).
- The app pages hard-code the G3Xn's numbers: 150 slots, banks of 3, 7 chain positions, the name "G3Xn".
- `desktop/build.js` writes this computer's repo path into the build. That build works on this computer only.
- Hardware run on 2026-11-16: live edits, screen text and the tuner work on the B1X FOUR.

## Decisions

| Question | Options | Choice |
|---|---|---|
| What is "it" in "make it an electron app"? | a second app / bass mode in the Electron app that exists | Bass mode in the existing app. One app, one switch |
| How does the app change pedal? | one daemon per pedal / one daemon that restarts its pedal side / hot swap inside every route | One daemon. On a switch it rebuilds its API for the other pedal on the same port |
| Who owns the mode while the app runs? | the mode file / the app | The app. A switch in the app also writes `~/.g3xn/mode.json`, and Claude's `pedal_mode` switches the app |
| Which screens work on bass? | all / tone tools only | Tone, Library, Save, Tuner, Backups, History and Claude. Gigs and Stage stay visible and use bass tones with their own gig folder |
| What does the release hold? | source only / an app that needs the repo / a self-contained app | A zip with the Electron app and a frozen daemon (PyInstaller). No Python and no repo needed. Voice (push to talk) is left out of the zip |
| Version | keep 0.1.0 and 0.2.0 apart / one number | One number, 0.3.0, for the Python package, the plugin, the app and the tag |

### Added on the same branch

The owner asked for three more changes while this was in progress. Each has its own issue and ships in this release.

| Request | Choice |
|---|---|
| "simplify the main app" (#4) | An agent audited every screen. Removed: macro knobs, morph, Shape the set, the tone hint, the Tone view's guitar box, the firmware number. Rack units show move, swap and remove only when open. The meters show only when the pedal is nearly full. Hold to talk shows only where speech to text is installed |
| "get rid of the chords" (#4) | Removed from the gig editor, Stage and the API types. Old gigs keep the field, and nothing reads it |
| "less strict about deleting and overwriting" (#4) | No tick boxes and no confirm dialogs. Save over and Load to pedal are one click. Every overwrite keeps the old patch or a backup first, and a deleted gig moves to a `deleted` folder. The daemon still refuses a full slot without `replace=true`, as Claude's guard |
| "gigs transfer between pedalboards/pcs" through GitHub, "default stuff", "other users login with their github" (#5) | Send and Get in the Gigs view, through the GitHub API (no git needed). Default: a private `<login>/g3xn-gigs` repo made on the first send. Sign in: the GitHub CLI's login, which the app starts for the user (#7), or a pasted token. The owner will not register a GitHub app. Send keeps this computer's version, Get keeps GitHub's. Off for a virtual pedal and refused on the phone |

## Design

**Daemon.** `g3xn-daemon --pedal KEY` picks the pedal (default: the mode). `run_modes` serves one pedal at a time: it builds the FastAPI app for that pedal, and `POST /api/mode {"pedal": KEY}` stops the server and builds it again for the other pedal on the same port. Each build pins the process to its pedal, so the catalog, patches and the Claude chat it starts use that pedal. The real daemon writes the mode file on a switch. A `--sim` daemon does not.

Each pedal has its own history, gigs, guitar notes and backups (`~/.g3xn/b1xfour/…` and `~/g3xn-backups-b1xfour/`). Recordings, the phone remote and footswitch bindings are shared.

`/api/status` gains `model` (key, name, kind, patches, bank_size, scratch_slot, chain rule and size, screen_offset) and `modes` (the pedals to pick from).

**MCP server and CLI.** With a daemon running, every tool goes through it, in either mode. `pedal_mode` reports the app's pedal and switches the app. `find_effects` and `effect_details` ask the daemon. Without a daemon nothing changes. `g3xn mode KEY` also tells a running daemon.

**App pages.** The status bar shows the pedal's name and a Guitar / Bass switch. Slot counts, bank size, chain size and the scratch slot come from `status.model`. On the B1X FOUR an effect costs one of 5 effect places whatever its size. Slot numbers show the way the pedal's screen shows them (slot n as n+9 on the B1X FOUR).

**Electron.** `main.js` starts the daemon bundled in the app's `resources/daemon` when it is there, else the repo's. `--bass` and `--guitar` pick the first pedal. `npm run release` freezes the daemon, packs the app and zips it. A release build holds no path of the computer that built it.

## Surfaces

The Electron app, the daemon's HTTP API, MCP tools, the CLI.

## Data and interfaces

New: `POST /api/mode`, `model` and `modes` in `/api/status`, `g3xn-daemon --pedal`, `~/.g3xn/b1xfour/history.json`, `~/.g3xn/b1xfour/gigs/`, `~/.g3xn/b1xfour/guitars.json`. Changed: `pedal_mode`, `find_effects` and `effect_details` go through a running daemon.

## Edge cases

- The app is in Guitar but the bass pedal is plugged in: the status bar shows the pedal's own refusal, and the switch fixes it.
- A switch while a job runs: the job ends or fails, then the pedal side restarts.
- A switch while a gig is locked: refused, with the reason.
- The Claude chat inside the app switches the pedal: the chat process restarts with the pedal side. The next message starts on the new pedal.
- An unknown pedal key: 400 with the choices.

## Out of scope

A new look for the app. Both pedals at the same time. Mac and Linux builds. Push to talk inside the release zip. Tempo on the B1X FOUR.

## Success check

Run the released `g3xn.exe`, pick Bass with the B1X FOUR plugged in, turn a knob, hear it, save it to an Empty slot.
