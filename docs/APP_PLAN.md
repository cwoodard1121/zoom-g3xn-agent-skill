# g3xn desktop app: plan

Status: planning. Build after the agent skill has been tested on real tones.

The app is a full replacement for ToneLib / Guitar Lab, built on the `g3xn` library, with Claude built in. Everything the app does goes through the same library the agent uses, so a change made by hand, by voice, or from the phone shows up everywhere.

## Architecture

```
┌──────────────────────────── Desktop app (Tauri or Electron + React) ────────────────────────────┐
│  Patch editor · Librarian · Gigs · Tuner · Chat panel                                           │
└───────────────┬─────────────────────────────────────────────────────────────────────────────────┘
                │ local HTTP + WebSocket (localhost only)
┌───────────────▼─────────────────────────┐        ┌───────────────────────────────────────────┐
│ g3xn daemon (Python, one process)        │◄──────►│ Claude: chat panel (Agent SDK) or spawn a │
│ owns the MIDI port, the scratch slot,    │  MCP   │ Claude Code session with the g3xn plugin  │
│ backups, history, live state events      │        └───────────────────────────────────────────┘
└───────────────┬─────────────────────────┘
                │ USB-MIDI SysEx
           Zoom G3Xn
```

- **One daemon owns the pedal.** Windows MIDI ports are exclusive, so the app, the MCP server and the CLI all talk to a single long-running `g3xn` daemon instead of opening the port themselves. The daemon pushes events (patch changed, knob turned on the pedal, tuner reading) over WebSocket so every screen stays in sync.
- **The MCP server becomes a client of the daemon.** Claude Code, Claude Desktop, the in-app chat and the phone all see the same live state.
- Python daemon (reuses `g3xn` as-is) plus a web UI in a desktop shell. Tauri keeps it small; Electron is fine if we want Node tooling.

## Core screens

### Patch editor
- The chain as a row of pedal/amp cards in signal order. Drag to reorder, click to add from the effect browser, toggle on/off.
- Knobs show the pedal's own display values. Turning a knob in the app is heard instantly (live edit on scratch); turning a knob on the pedal moves it in the app (editor-mode events).
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
- Level-match helper: play the same riff through each patch and the app suggests volume changes so the set is even (uses the pedal's tuner/level data and the user's ears; later, an audio input).
- Print/export the setlist with patch names and slot numbers.

### Tuner
- Full-screen tuner using the pedal's tuner stream (note + meter), with a reference-pitch setting.
- Auto-open on the mute/tuner patch in stage view.

### Chat (Claude built in)
- A side panel that talks to Claude with the g3xn tools: "make it less fizzy", "build my Friday set", "what's on slot 112?".
- "Open in Claude Code" button: spawns a Claude Code session in the project with the g3xn plugin loaded, for deeper work (research, building a whole gig).
- Tone research mode: Claude uses web search / Claude in Chrome for rig rundowns, then proposes a chain, explains each choice, and auditions it.
- Every AI change is a normal edit with undo, shown in the history with the reason ("Treble 55 → 45: too ice-picky").

## Beyond the basics (brainstorm)

**Playing**
- Rhythm/looper control: start/stop the drum machine, pick patterns and tempo from the app; tap tempo.
- Tempo per song in the gig; sync delay time to the song BPM.
- Practice mode: loop a section with the pedal's looper; slow-down tips.

**Control from anywhere**
- Phone remote (web page served by the daemon on the LAN, or through a Claude session on the phone): switch patches, toggle effects, tuner, see the setlist on stage.
- External MIDI controllers: map any MIDI footswitch/expression pedal to patch changes, effect toggles, knob sweeps (the daemon translates).
- Hotkeys and a Stream Deck profile.

**Tone tools**
- "Make it like this": paste a YouTube/rig-rundown link, Claude researches and builds the tone.
- Tone variations: generate 3 alternatives around the current tone (brighter / darker / more gain) and A/B them.
- Pickup adapter: convert a humbucker patch to a single-coil version (gain/EQ/level compensation) and back.
- Rig profiles: guitar + pickups + output routing (PA, amp front, FX return), stored once; every tone adapts to it.
- Patch health check: flags clipping-level volumes, unused off effects eating DSP, cab blocks when going into a real amp.

**Sharing**
- Export a tone or gig as a share link / JSON gist; import someone else's.
- Convert patches between G3n/G3Xn/G5n/G1 Four (same effect family; different chain sizes).
- Community tone library (later).

**Pedal internals**
- Effect manager: see installed effects and DSP cost; swap effect sets (the G3Xn can hold different .ZD2 effects; zoom-zt2 shows how).
- Firmware/version info, global settings (autosave on/off, display, tuner reference).

## Build order

1. **Daemon**: wrap `g3xn.Pedal` in a long-running process with HTTP + WebSocket; move the MCP server onto it; editor-mode event stream (knob changes made on the pedal).
2. **App shell + librarian + patch editor** (the ToneLib replacement).
3. **Gigs + stage view + tuner.**
4. **Chat panel + spawn Claude Code.**
5. Phone remote, MIDI controller mapping, then the brainstorm list.

## Open questions

- Tauri (Rust shell, small) vs Electron (Node, bigger but more familiar)?
- Does editor mode report knob turns made on the pedal itself? (Likely, via `64 03` echoes; needs a test.)
- Expression pedal: does the G3Xn send its position over MIDI?
- Is there a whole-patch edit-buffer load we haven't found? (Would make auditions skip the scratch slot.)
