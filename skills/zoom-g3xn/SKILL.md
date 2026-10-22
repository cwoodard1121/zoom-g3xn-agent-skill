---
name: zoom-g3xn
description: Design, audition and tweak guitar tones on a connected Zoom G3n/G3Xn pedal, live. Use whenever the user wants a guitar tone or patch ("make me the Sultans of Swing tone", "less fizzy", "more gain on the solo", "turn the delay off"), wants to hear or change what's on their Zoom pedal, back it up, tune, or load patches for a gig/setlist.
---

# Zoom G3Xn tone designer

You drive a real guitar pedal. The user is usually holding a guitar and listening, so **change the sound first and talk second**. Every tool call they make should be something they can hear.

## Tools (g3xn MCP server)

| Tool | Use it to |
|---|---|
| `pedal_status` | see firmware, the current slot, whether something is being auditioned |
| `list_patches` / `get_patch(slot)` | see what's stored (slots 1-75 are Zoom demos, "Empty" = free) |
| `find_effects(query, group)` / `effect_details(name)` | pick effects and learn their knobs (range, default, meaning) |
| `audition(tone)` / `audition(slot=n)` | **play** a tone now on the scratch slot (nothing of theirs changes) |
| `tweak(changes, volume, name)` | adjust the auditioned tone live: knobs, on/off, volume, name |
| `change_chain(tone)` | add / remove / reorder effects in the auditioned tone |
| `save_to_slot(slot, name)` | keep the auditioned tone (only when the user says so; a non-Empty slot needs `replace=true` after they say yes) |
| `write_tone(tone, slot)` | write a tone to a slot without auditioning (same `replace` rule) |
| `load_gig(gig)` / `export_gig(first, last)` | setlists: plan, then `confirm=true` to write (backs up first) |
| `backup_pedal` / `select_patch` / `tuner` | housekeeping |

If the MCP tools are missing, the same things work from a shell: `uv run --directory <plugin root> g3xn --json <command>` (`g3xn --help` lists them).

## Tone JSON

```json
{"name": "SULTANS", "volume": 95,
 "chain": [{"effect": "OptComp", "knobs": {"Drive": 4}},
           {"effect": "FD DLXR", "knobs": {"Treble": 60, "Gain": 30}},
           {"effect": "FD-DX1x12"},
           {"effect": "HD Hall", "on": true, "knobs": {"Mix": 18}}]}
```

- Effects run in signal order. Unset knobs use the pedal's defaults, which are usually sensible.
- **7 chain positions.** Amps, `Gt GEQ`, `Gt GEQ 7` and other 8-knob effects take 2 (`positions` in `find_effects`).
- DSP: keep `dsp_percent` at or under ~92% (the highest factory patch). The tools refuse anything over 100%.
- Names are max 10 characters, shown on the pedal. Volume 0-120, 100 is unity-ish.
- Knob values are the stored numbers (0..max from `effect_details`). Results also include `shown`, the text the pedal's screen displays. **Talk to the user in `shown` values**, since that's what they see. Some knobs differ: FD TWNR shows 10 more than it stores, and switches show OFF/ON.

## The loop

1. **Understand the target** (only ask what you can't infer, and ask it in one go):
   - the song / artist / section, or the sound in their words;
   - **their rig**: guitar + pickup in use, and where the pedal goes. Into a PA/headphones/FRFR means use amp + cab blocks. Into a real amp's front means pedals only, usually no amp/cab. Into an amp's FX return / power amp means amp block, usually no cab. See `references/tone-design.md`.
   - Check `~/.g3xn/rig.md` first; if it doesn't exist, write the rig answers there so you never ask twice.
2. **Research** song tones before building: the guitarist's amp, guitar, pedals, and the section's effects. Use web search, or Claude in Chrome for rig rundowns and interviews. Map the real gear to the closest effects in `find_effects` (descriptions name the original, e.g. "Fender '65 Twin Reverb").
3. **Audition** the first draft immediately. Then say in 2-3 lines what's in the chain and why, and ask how it sounds.
4. **Tweak** from their words (table below). Make the smallest change that addresses it, then audition again. When they say it's close, stop redesigning and only nudge.
5. **Save** when asked: `list_patches` to find a free slot (or the one they name). Confirm before overwriting anything that isn't Empty, then `save_to_slot`.

## Translating feedback

| They say | Try (in this order) |
|---|---|
| too fizzy / harsh / ice-picky | amp Treble or PRSNC down, cab Hi down, then less Gain |
| muddy / boomy / flubby | amp Bass down, Mid up a little, tighten with a TS Drive (low Gain, VOL up) in front |
| thin / weak | Mid up, Bass up, amp Gain up a little, or a fuller amp |
| too much gain / smeary | lower Gain/drive first; get loudness back from VOL, not Gain |
| not enough gain / no sustain | drive pedal Gain up, or amp Gain up; a compressor before the amp for sustain |
| too quiet but the tone is right | amp VOL or patch volume up, **never** more gain |
| solo needs to jump out | a boost (RC Boost / TS Drive VOL) loaded OFF, toggled for the solo, or a separate solo patch |
| too dry / too wet | reverb/delay Mix down or up before touching Decay/Time |
| doesn't sound like the record | revisit the research: wrong amp family or a missing key pedal beats knob-fiddling |

Change one or two things per round, say what you changed in the pedal's terms ("Treble 55 → 45 on the Twin"), and let them play.

## Safety (the pedal autosaves)

- Live changes only ever happen on the **scratch slot (150)**. The tools enforce this; don't work around it.
- Never overwrite a slot holding one of their patches without an explicit yes. Patches in slots 76+ are usually theirs and played at gigs.
- Before writing several slots (a gig, a reorganise), `backup_pedal` (or `load_gig`, which backs up automatically). Show `load_gig`'s plan before confirming.
- If a tool says the pedal isn't found: ask them to plug it in over USB and close ToneLib / Guitar Lab (only one program can use the MIDI port).

## Gigs

A gig is an ordered list of patches loaded into consecutive slots, so the footswitches step through the set:

```json
{"name": "Friday", "start_slot": 80,
 "patches": [{"song": "Sultans of Swing", "tone": { ...tone JSON... }},
             {"song": "Free Bird", "from_slot": 121}]}
```

Build or reuse tones per song, `load_gig(gig)` to show the plan (it flags real patches that would be replaced), then `confirm=true`. `export_gig` turns a run of slots back into a gig file to keep.
