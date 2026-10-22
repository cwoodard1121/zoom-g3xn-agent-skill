# g3xn desktop app: plan

Status: building. Done so far:
- Stage 1: `g3xn.sim` (virtual pedal), `g3xn/service.py`, the daemon (`g3xn-daemon`), MCP through the daemon.
- Stage 2, first cut: the app (`g3xn-app`) with the tone view (stompboxes, live knobs, footswitches, keep in a slot), the patch library (banks of three, tweak a copy, switch to it) and the tuner. Not yet: adding/removing/reordering effects, A/B, history, backups and import/export from the app.

The app is a full replacement for ToneLib / Guitar Lab, built on the `g3xn` library, with Claude built in. Everything the app does goes through the same library the agent uses, so a change made by hand, by voice, or from the phone shows up everywhere.

## Decisions

| Piece | Choice | Why |
|---|---|---|
| Daemon | Python, FastAPI + uvicorn (`pip install g3xn[app]`) | Reuses `g3xn` as-is. FastAPI writes readable API docs at `/docs` for free. |
| UI | React + TypeScript + Vite in `app/`, served by the daemon | One web UI for the desktop window, a browser tab and the phone. |
| Desktop window | pywebview (Edge WebView2, already on Windows) | No Rust or Electron needed. The UI is plain web, so Tauri/Electron stay possible later. |
| Phone | The same page on the LAN (opt-in, pairing code) | Phone remote comes for free. |
| No pedal | `g3xn.sim`, a virtual pedal that answers the real MIDI protocol | The app, the daemon and the tests run without hardware, and the real `Pedal` code is what gets tested. |
| Claude | Chat panel drives the user's own Claude Code with the g3xn plugin; "Open in Claude Code" spawns a full session | Uses the login they already have. Details at stage 4. |

## Architecture

```
┌──────────── UI (desktop window / browser tab / phone) ────────────┐
│  Patch editor · Librarian · Gigs · Tuner · Chat panel             │
└───────────────┬───────────────────────────────────────────────────┘
                │ HTTP + WebSocket (localhost; LAN only when paired)
┌───────────────▼──────────────────────────┐       ┌──────────────────────────────┐
│ g3xn daemon (one Python process)          │◄─────►│ g3xn-mcp (Claude Code /      │
│ one worker thread owns the MIDI port;     │ HTTP  │ Desktop) uses the daemon when│
│ every pedal action is queued through it   │       │ it runs, else opens the port │
│ events: patch changed, knob turned, tuner │       └──────────────────────────────┘
└───────────────┬──────────────────────────┘
                │ USB-MIDI SysEx            (or g3xn.sim: same bytes, no hardware)
           Zoom G3Xn
```

- **One process owns the pedal.** Windows MIDI ports are exclusive, so the app, the MCP server and the CLI go through the daemon instead of opening the port themselves. The daemon reconnects by itself when the pedal is unplugged or ToneLib lets go of it.
- **Pedal-busy light.** The daemon always says who holds the pedal and what it is doing ("writing slot 150"), so nobody has to wonder what is happening to it.
- **One set of operations.** The MCP tools and the HTTP API call the same functions (`g3xn/service.py`), so the safety rules live in one place: never write over a non-Empty slot without `replace`, auditions only on the scratch slot, back up before a gig load.

## Core screens

### Patch editor
- The chain as a row of pedal/amp cards in signal order. Drag to reorder, click to add from the effect browser, toggle on/off.
- Knobs show the pedal's own display values. Turning a knob in the app is heard instantly (live edit on scratch); turning a knob on the pedal moves it in the app (editor-mode events, if the pedal sends them).
- DSP meter and "positions used: 5/7", with a warning before it won't fit.
- A/B: snapshot the current tone, keep tweaking, flip between A and B with one key.
- Undo/redo history per editing session; "revert to saved".

### Librarian
- All 150 slots as a grid with names, chain icons, and "factory / mine / empty" tags.
- Drag to reorder slots, copy/paste patches, rename, bulk export/import (`.json`, `.zptc`, ToneLib `.zg3xn`).
- Local library of tones outside the pedal (unlimited), with tags (song, artist, guitar, pickup, gig).
- Automatic versioned backups: before every write, plus daily when connected. One-click restore of a slot or the whole pedal.
- Diff two patches ("what changed between v2 and v3 of Sultans?").

### Gigs
- A gig = an ordered setlist. Each song → a patch (or rhythm + lead pair), notes, key/tempo, which footswitch does what.
- "Load gig to pedal": shows the slot plan, flags overwrites, backs up, writes. Multiple gigs saved; switching gigs is one click.
- Stage view: huge text, current song / next song, big tuner, current patch name; follows the pedal as you switch patches.
- Level-match helper: play the same riff through each patch and the app suggests volume changes so the set is even.
- Print/export the setlist with patch names and slot numbers.

### Tuner
- Full-screen tuner using the pedal's tuner stream (note + meter), with a reference-pitch setting.
- Auto-open on the mute/tuner patch in stage view.

### Chat (Claude built in)
- A side panel that talks to Claude with the g3xn tools: "make it less fizzy", "build my Friday set", "what's on slot 112?".
- "Open in Claude Code" button: spawns a Claude Code session with the g3xn plugin loaded, for deeper work (research, building a whole gig).
- Tone research mode: Claude uses web search / Claude in Chrome for rig rundowns, then proposes a chain, explains each choice, and auditions it.
- Every AI change is a normal edit with undo, shown in the history with the reason ("Treble 55 → 45: too ice-picky").

## Ideas (brainstorm)

**Seeing the pedal**
- Pedal mirror: the app shows the pedal's own screens, with the text the pedal itself reports, so the app and the LCD always agree.
- Zoom demo browser: the 80 factory patches with Zoom's own descriptions, one-click "try it" on scratch, and "restore this factory patch to its slot".
- Demo mode: the whole app works on the virtual pedal with nothing plugged in.

**Shaping tones**
- Tone time machine: every audition and tweak is recorded; scrub back and replay any earlier version onto scratch.
- A/B two slots, or scratch vs a slot, with one key.
- Macro knobs: one app knob ("Gain", "Brightness", "Space") moves several real knobs at once and keeps the level even. Claude can make macros for a tone.
- Morph: glide from tone A to tone B over a few seconds with live edits (swells, build-ups).
- Tone variations: three alternatives around the current tone (brighter / darker / more gain) to A/B.
- "Make it like this": paste a YouTube/rig-rundown link, Claude researches and builds the tone.
- Pickup adapter: convert a humbucker patch to a single-coil version (gain/EQ/level) and back.
- Rig profiles: guitar + pickups + output (PA, amp front, FX return), stored once; every tone adapts to it.
- DSP fixer: when a chain won't fit, suggest cheaper effects that sound close.
- Patch health check: clipping-level volumes, unused effects eating DSP, cab blocks when going into a real amp.
- Name helper that fits names in 10 characters.

**Hands on the guitar**
- Voice: push-to-talk on a hotkey or a MIDI footswitch, so "more gain" doesn't mean putting the guitar down.
- Tap tempo → the patch's tempo, so delays follow the song; tempo stored per song in a gig.
- Rhythm/looper control: start/stop the drum machine, pick patterns and tempo from the app.
- Practice mode: loop a section with the pedal's looper.

**Gigs and safety**
- Batch edits across a gig: "every reverb down 10%", "boost all the solo patches", a venue EQ added to the whole set.
- Gig lock: no writes while playing; a panic button restores the gig from its backup.
- Session journal: what was tried and what you liked ("keep this for the bridge"), searchable later.
- Librarian smarts: near-duplicate finder, automatic tags from the chain (gain level, amp model, has delay).

**Control from anywhere**
- Phone remote: switch patches, toggle effects, tuner, setlist on stage.
- External MIDI controllers: map any footswitch/expression pedal to patch changes, effect toggles, knob sweeps.
- Hotkeys and a Stream Deck profile.

**Sharing and internals**
- Tone cards: share a tone as an image with a QR code; import someone else's tone or gig from JSON.
- Convert patches between G3n/G3Xn/G5n/G1 Four (same effect family; different chain sizes).
- Effect manager: installed effects and DSP cost; swap effect sets (zoom-zt2 shows how).
- Firmware/version info and global settings (autosave, display, tuner reference).

## Build order

1. **Daemon + virtual pedal**: `g3xn.sim`, `g3xn/service.py` (shared operations), FastAPI daemon with a pedal worker thread, WebSocket events, auto-reconnect, busy light; MCP server goes through the daemon when it runs.
2. **App shell + librarian + patch editor** (the ToneLib replacement), demo browser, A/B, time machine.
3. **Gigs + stage view + tuner.**
4. **Chat panel + spawn Claude Code**, voice push-to-talk.
5. Phone pairing, MIDI controller mapping, then the rest of the ideas.

## Open questions (need the pedal free to test)

- Does editor mode report knob turns and footswitch patch changes made on the pedal itself? (Likely `64 03 01` echoes and Program Change.)
- Does editor mode time out if the host goes quiet?
- Expression pedal: does the G3Xn send its position over MIDI?
- Is there a whole-patch edit-buffer load we haven't found? (Would make auditions skip the scratch slot.)
