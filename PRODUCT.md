# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

(The desktop app is the same web UI in a pywebview / WebView2 window; phones open it in their browser through the phone remote.)

## Users

One guitarist (the repo owner) who plays live gigs with a Zoom G3Xn multi-effects pedal. For now the app is only for them: no onboarding for strangers.

## Product Purpose

A replacement for ToneLib / Guitar Lab that the owner actually likes: see and shape the tone playing on the pedal, keep patches safe, and run gigs, with Claude built in so "make it less fizzy" or "every reverb down 10% for this venue" just happens on the pedal.

## Positioning

Everything goes through one local daemon that owns the pedal, so a change made by hand, by Claude (in the app or in Claude Code), from a phone, or from a MIDI footswitch shows up everywhere at once. Claude can audition and tweak tones live while the user plays.

## Operating Context

Distinct modes, in this order of importance:

1. **At the desk (primary):** computer next to the pedal, guitar in hand, shaping tones with the mouse and with Claude. Dense, precise editing.
2. **On stage:** the gig is loaded; the screen is glanced at between songs (current song, next song, notes), the pedal's own footswitches or a MIDI controller step through the set, and the gig can be locked so nothing overwrites it.
3. **Phone:** a paired phone on the local network as a remote (stage view, switching patches, tuner).

## Capabilities and Constraints

- G3Xn: 150 slots in banks of 3; slots 1-75 hold Zoom's demos; autosave is on; slot 150 is the scratch slot where all live editing happens. Chains are up to 7 positions with a DSP budget.
- Built (with screens): tone view (effect chain as stompboxes, knobs, on/off, add/swap/reorder/remove), A/B with morph, undo/redo and history, macro knobs (Gain, Brightness, Space), patch library, save to a slot (refuses to replace a patch without an explicit yes), tuner, gigs (setlists with tempo/key/notes, slot plan, load with backup), stage view.
- Built (API only, screens to design): gig batch edits, gig lock, check/restore changes made on the pedal, phone remote pairing (six-digit code), MIDI footswitch inputs/learn/bindings.
- Planned: Claude chat panel (headless Claude Code with the pedal tools), "Open in Claude Code" (same conversation in a terminal), voice on a footswitch (push-to-talk).
- Everything is tested on a virtual pedal; the app has not yet run against the real pedal.

## Brand Commitments

Name: g3xn. No other commitments yet; the visual direction is open (the owner hasn't seen the current first-cut look).

## Evidence on Hand

The owner's own patches (backed up locally, not in the repo) and Zoom's demo patches. No users, testimonials or screenshots beyond the owner's own.

## Product Principles

1. Never lose a patch: nothing of the user's is overwritten without an explicit yes, and big writes back up first.
2. What you see is what the pedal is playing, live, whoever changed it.
3. Hands are on the guitar: the important things work in one glance or one press.
4. The desk is for depth, the stage is for calm.
