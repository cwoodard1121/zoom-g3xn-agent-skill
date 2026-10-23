---
name: g3xn
description: A rack of gear for a Zoom G3Xn, read from IN to OUT, every readout on amber VFD glass.
colors:
  vfd: "#ffb000"
  vfd-bright: "#ffd27a"
  vfd-dim: "#b07a00"
  vfd-ghost: "#3a2700"
  vfd-glow: "rgba(255, 176, 0, 0.55)"
  glass: "#120c00"
  night: "#050403"
  stage-plate: "#1a1200"
  stage-rule: "#2a1d00"
  led: "#e0362c"
  go: "#5ee07a"
  focus: "#ff7a00"
  alu-ground: "#c6c9cd"
  key-face: "#f3f4f6"
  key-face-lo: "#d8dbde"
  edge: "#7d8186"
  field: "#f6f7f8"
  ink: "#1c1d1f"
  ink-dim: "#43464b"
  ink-faint: "#5f6267"
  plate-black: "#1d1f22"
  plate-black-2: "#2a2c30"
  plate-ink: "#e4e6e9"
  plate-dim: "#a3a6ab"
  rack-well: "#121314"
  plate-default: "#d2d5d9"
  plate-blank: "#b9bdc1"
  plate-amp: "#26282c"
  plate-cabinet: "#75664f"
  plate-drive: "#4a6a43"
  plate-dynamics: "#2f5379"
  plate-filter: "#c9992c"
  plate-modulation: "#574876"
  plate-sfx: "#8b3450"
  plate-delay: "#d9dce0"
  plate-reverb: "#2d5764"
  plate-pedal: "#a3a7ac"
  plate-looper: "#9a2f2a"
typography:
  display:
    fontFamily: "VT323, ui-monospace, monospace"
    fontSize: "clamp(76px, 10vw, 170px)"
    fontWeight: 400
    lineHeight: 0.88
    letterSpacing: "0.01em"
  readout-lg:
    fontFamily: "VT323, ui-monospace, monospace"
    fontSize: "58px"
    fontWeight: 400
    lineHeight: 0.95
    letterSpacing: "0.04em"
  readout:
    fontFamily: "VT323, ui-monospace, monospace"
    fontSize: "21px"
    fontWeight: 400
    lineHeight: 1
    fontFeature: "\"tnum\""
  headline:
    fontFamily: "Michroma, Eurostile, sans-serif"
    fontSize: "22px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "0.18em"
  title:
    fontFamily: "Michroma, Eurostile, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: "0.1em"
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.45
  control:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "13.5px"
    fontWeight: 600
    lineHeight: 1.2
  label:
    fontFamily: "Michroma, Eurostile, sans-serif"
    fontSize: "9.5px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "0.18em"
rounded:
  none: "0"
  hairline: "1px"
  sm: "2px"
  pill: "14px"
  round: "50%"
spacing:
  seam: "3px"
  xs: "6px"
  sm: "8px"
  md: "14px"
  lg: "20px"
  xl: "28px"
  ear: "26px"
  face-inset: "40px"
components:
  button-alu:
    backgroundColor: "{colors.key-face}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "8px 14px"
  button-alu-pressed:
    backgroundColor: "{colors.plate-black}"
    textColor: "{colors.vfd}"
  button-primary:
    backgroundColor: "{colors.plate-black}"
    textColor: "{colors.vfd}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "8px 14px"
  button-primary-on-dark:
    backgroundColor: "{colors.vfd}"
    textColor: "{colors.glass}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "8px 14px"
  button-primary-on-dark-hover:
    backgroundColor: "{colors.vfd-bright}"
  button-stage-step:
    backgroundColor: "{colors.stage-plate}"
    textColor: "{colors.vfd}"
    rounded: "{rounded.sm}"
    height: "64px"
    padding: "0 28px"
  button-stage-step-primary:
    backgroundColor: "{colors.vfd}"
    textColor: "{colors.glass}"
    width: "200px"
  input-alu:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 11px"
  input-glass:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.vfd}"
    rounded: "{rounded.none}"
    padding: "7px 10px 5px"
  rail-link:
    textColor: "{colors.ink}"
    rounded: "{rounded.hairline}"
    padding: "11px 10px"
  rail-link-current:
    backgroundColor: "{colors.plate-black}"
    textColor: "{colors.vfd}"
  unit-face:
    backgroundColor: "{colors.plate-default}"
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    height: "60px"
    padding: "0 40px"
  unit-drawer:
    backgroundColor: "{colors.plate-black}"
    textColor: "{colors.plate-ink}"
    padding: "16px 20px 18px"
  knob:
    size: "58px"
  knob-lcd:
    backgroundColor: "{colors.glass}"
    textColor: "{colors.vfd}"
    typography: "{typography.readout}"
    padding: "3px 6px 2px"
  slot:
    backgroundColor: "{colors.key-face}"
    textColor: "{colors.ink}"
    typography: "{typography.control}"
    rounded: "{rounded.sm}"
    padding: "7px 9px 8px"
  chip:
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    height: "30px"
    padding: "0 12px"
  badge:
    backgroundColor: "{colors.vfd}"
    textColor: "{colors.glass}"
    typography: "{typography.label}"
    padding: "4px 6px 3px"
---

# Design System: g3xn

## Overview

**Creative North Star: "The Amber Rack"**

The tone is a rack of gear in a studio, read top to bottom from IN to OUT. Every effect is a brushed-aluminium or anodized faceplate bolted in with rack ears and two screws a side; the master unit sits at the top, a blank vented panel fills each free position, and the save bar is the OUT jack at the bottom. One unit at a time pulls out its black drawer to show every knob. Whatever the pedal reports (patch name, slot numbers, knob values, levels, the tuner) glows amber on dark VFD glass, so the number on screen reads like the number on the hardware.

The desk is dense and precise: small engraved legends, tight 3px seams between units, machined depth from 1px black borders and inset highlights rather than soft shadows. The stage is the same world with the room lights off: the aluminium disappears and only amber on near-black is left, at sizes readable from a pedalboard. The system rejects two forms outright: the row of stompboxes (the pedal's own metaphor, and Guitar Lab's) and the dashboard of rounded cards.

The build landed slightly off the contract in one place: the contract named the aluminium as `#c7cace`; the build paints the room in `alu-ground` and the keys in a lighter top-lit pair (`key-face` to `key-face-lo`). The stylesheet also declares `--alu`, `--alu-hi` and `--alu-lo`, but nothing consumes them, so they are not recorded. The frontmatter records the build.

**Key Characteristics:**
- A vertical rack of full-width units, IN at the top, OUT at the bottom, with 3px black seams.
- Rack ears with screw heads on every faceplate (master unit and effect units).
- Anodized plate colour per effect group, carried from the unit face to the chip to the effect browser's swatch.
- Pedal readouts in VT323 on amber VFD glass; engraved legends in Michroma; prose and controls in Archivo.
- Machined depth: hard 1px black borders, inset highlight/shadow pairs, a 3px bezel lip under black units.
- Stage mode: amber on black, nothing else.

## Colors

Cool brushed aluminium and black anodizing as the hardware, one amber phosphor as the only light, and a set of anodized plate colours that identify effect groups.

### Primary
- **VFD Amber** (`vfd`): the phosphor. Every readout on glass, the active rail link, pressed toggles, the lit knob ticks, the current history item, the drop marker in the rack, and the fill of the primary action on dark surfaces.
- **Bright Phosphor** (`vfd-bright`): emphasis inside glass (the stage slot number, the next song, meters near the limit) and the hover of amber-filled buttons.
- **Dim Phosphor** (`vfd-dim`): labels inside a readout (`GAIN` before its value), secondary stage facts, the state line under the patch name. Never glows.
- **Unlit Segment** (`vfd-ghost`): the dark segments behind a meter or tuner bar, so an empty meter still shows its scale.
- **Phosphor Glow** (`vfd-glow`): text-shadow and drop-shadow halo on lit amber only.
- **VFD Glass** (`glass`): the dark warm-black window every amber readout sits in.

### Secondary
- **Clip Red** (`led`): effect-on LEDs, meters over the limit, the current patch's underline in the library, error toasts.
- **In-Tune Green** (`go`): the connected status light, the in-tune tuner note and centre segment, the "on pedal" badge.
- **Focus Orange** (`focus`): the 2px focus outline, everywhere.

### Neutral
- **Room Aluminium** (`alu-ground`): the page background, under a fine vertical brushed grain and a light top-to-bottom falloff.
- **Key Aluminium** (`key-face`, `key-face-lo`): the top-lit gradient on aluminium buttons, A/B keys and the power lever. Slots and gig items use a slightly dimmer version of the same gradient; the nav rail is a darker horizontal brush of the same metal.
- **Machined Edge** (`edge`): 1px borders on aluminium controls and fields, the rail's right edge, scrollbars.
- **Field White** (`field`): inset text fields and selects on aluminium.
- **Engraving Ink** (`ink`), **Dim Ink** (`ink-dim`), **Faint Ink** (`ink-faint`): text on aluminium. Faint ink is for placeholders and empty slots only; it is too light for running text.
- **Black Anodized** (`plate-black`, `plate-black-2`): the master unit, knob drawers, the patch detail, gig plan, dialogs, drawers, toasts, the header, and pressed/primary controls on aluminium. `plate-black-2` is the hover row inside those.
- **Plate Ink** (`plate-ink`), **Plate Dim** (`plate-dim`): text on black anodizing.
- **Rack Well** (`rack-well`): the dark cavity behind the units, and the power switch's track.
- **Stage Black** (`night`), **Stage Plate** (`stage-plate`), **Stage Rule** (`stage-rule`): the stage's background, its button and hover fills, and its borders and dividers.

### Anodized group plates
One plate colour per effect group, set as a `--plate` custom property (with `--face-ink` and `--face-dim` for its legend colours) under `[data-group]`: AMP (`plate-amp`), CABINET (`plate-cabinet`), DRIVE (`plate-drive`), DYNAMICS (`plate-dynamics`), FILTER (`plate-filter`), MODULATION (`plate-modulation`), SFX (`plate-sfx`), DELAY (`plate-delay`), REVERB (`plate-reverb`), PEDAL (`plate-pedal`), LOOPER and RHYTHM (`plate-looper`), anything else (`plate-default`); free positions use `plate-blank`. Light plates take `ink` legends; dark plates take a near-white tinted toward the plate's hue.

### Named Rules
**The Emitted Amber Rule.** Amber text is light, so it only appears where light can be seen: on VFD glass or on black anodizing. Amber ink never sits on aluminium. Where amber is a fill (badges, the primary action on dark surfaces), its text is `glass`.

**The Group Plate Rule.** An effect group's colour is its identity: the same `--plate` paints the unit face, the patch detail's chain chip and the effect browser's group swatch. Never use a plate colour for anything that isn't that group.

**The Lights Down Rule.** On stage the aluminium goes away: the rail and the main column turn `night`, every surface in them a warm black (`glass`, `stage-plate`), every legend amber or dim amber. No grey, no white, no group colours below the header; the black status header stays as it is.

## Typography

**Display / Readout Font:** VT323 (with ui-monospace, monospace)
**Engraved Label Font:** Michroma (with Eurostile, sans-serif)
**Body Font:** Archivo (with system-ui, sans-serif)

All three are self-hosted through @fontsource (Michroma 400, VT323 400, Archivo 400/500/600/700).

**Character:** VT323 is the pedal's own screen made large, Michroma is the wide engraved legend on a faceplate, and Archivo is the plain workshop voice for sentences and buttons. Three jobs, never swapped.

### Hierarchy
- **Display** (VT323 400, `clamp(76px, 10vw, 170px)`, 0.88): the current song on stage. The tuner note uses the same face larger (`clamp(150px, 24vw, 300px)`, 0.85).
- **Readout Large** (VT323 400, 58px, 0.95, uppercase): the patch name in the master unit's glass; 44px under 760px.
- **Readout** (VT323 400, 18-24px, 1, tabular figures): unit readouts, knob values, slot numbers, meters, the status line, stage facts (26-34px).
- **Headline** (Michroma 400, 22px, 1.2, 0.18em, uppercase): view titles (Patches, Gigs, Stage).
- **Title** (Michroma 400, 13-16px, 1.15-1.3, 0.1-0.14em, uppercase): unit names, drawer, dialog and patch-detail titles, gig names.
- **Body** (Archivo 400, 15px, 1.45): sentences, notes, hints, empty states (17px, max 46ch). Stage notes run 20-25px at 1.4, max 42ch.
- **Control** (Archivo 600, 13.5px, 1.2): button and slot names.
- **Label** (Michroma 400, 8.5-10.5px, 0.14-0.3em, uppercase): engraved legends: knob names, field labels, table heads, the IN/OUT rail labels, the vertical MACROS legend, the effect's group under its name, badges, nav links.

### Named Rules
**The Readout Rule.** A value the pedal reports (patch name, slot number, knob value, level, tuner note, tempo and key on stage) is set in VT323 on `glass` in amber. App-side counts and metadata in prose (patch counts, gig meta) stay in Archivo.

**The Engraved Legend Rule.** Michroma is always uppercase, always tracked (at least 0.08em), always weight 400, and always names a control, a field or a section of hardware. It is never used for sentences.

## Layout

A two-column shell: a 136px aluminium nav rail at left and the main column (padding 22px 28px), under a sticky black status header carrying the wordmark, a status light and the status line on glass. The tone view caps at 1160px and stacks top to bottom: the master unit (name, meters, volume, macros), the IN rail (A/B, morph, undo/redo, history), the rack, then a sticky OUT rail with the save action that stays in reach however long the chain is.

Units inside the rack are full width and separated by a 3px seam of rack-well black. A unit face is 60px tall (96px for an effect that takes two positions, 40px for a blank panel), with 40px of side padding to clear its 26px rack ears. The open unit's drawer is inset 26px from each side (it slides out between the ears) and lays its knobs on an auto-fill grid of 86px minimum columns.

Other views keep the same grammar: the patch library is banks of three slots (3px seams) in an auto-fill grid of 330px minimum, with a sticky 300px black detail panel; gigs are a 290px list beside an editor; stage is the song column beside a 330px setlist.

Spacing steps that recur: 3px seams, 6 and 8px gaps inside controls, 14px between knobs and toolbar groups, 20px panel padding, 28px page gutter.

Under 760px the rail becomes a sticky bottom bar of equal links, the status line wraps to its own row, the master unit stacks, unit readouts drop below the name, the ears narrow to 20px, the drawer's knob grid drops to 72px columns, and every two-column view stacks.

## Elevation & Depth

Depth is machined, not lit from a lamp. Surfaces at rest are joined with hard 1px borders (`#000` on black, `edge` on aluminium) and inset highlight/shadow pairs that make plates look milled and fields look recessed. Black units sit on a 3px hard bezel lip. Only the things that genuinely float above the rack (the side drawer, dialogs, toasts) cast a soft shadow. Glow belongs to light sources: lit amber, LEDs and status lights.

### Shadow Vocabulary
- **Faceplate bevel** (`box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45), inset 0 -1px 0 rgba(0, 0, 0, 0.35)`): every unit face.
- **Button lift** (`box-shadow: inset 0 1px 0 #fff, 0 1px 0 rgba(0, 0, 0, 0.18)`): aluminium buttons, slots, A/B keys, gig items.
- **Pressed in** (`box-shadow: inset 0 2px 4px #000`): toggled-on keys and buttons; `inset 0 1px 3px rgba(0, 0, 0, 0.25)` plus a 1px drop while an aluminium button is held.
- **Recessed field** (`box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.18)`): text fields on aluminium.
- **VFD glass** (`box-shadow: inset 0 2px 7px rgba(0, 0, 0, 0.95), inset 0 0 0 1px #000`): every glass window.
- **Rack well** (`box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04), inset 0 12px 26px rgba(0, 0, 0, 0.7)`): the cavity behind the units.
- **Bezel lip** (`box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1), 0 3px 0 rgba(0, 0, 0, 0.3)`): the master unit and patch detail; the tuner uses a 4px lip.
- **Floating** (`box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55)` dialog, `-18px 0 40px rgba(0, 0, 0, 0.4)` drawer, `0 10px 24px rgba(0, 0, 0, 0.35)` toast): only overlays.
- **Phosphor glow** (`text-shadow: 0 0 7px rgba(255, 176, 0, 0.55)`; LEDs `0 0 8px` of their own colour): lit things only.

### Named Rules
**The Bolted-In Rule.** Every faceplate in the rack, and the master unit, carries rack ears with two screw heads (26px each side, 20px under 760px). A faceplate without ears is not in the rack.

**The Only Overlays Float Rule.** Soft, blurred drop shadows are reserved for the drawer, dialogs and toasts. Everything else gets its depth from borders, bevels, insets and the 3px lip.

## Shapes

Hardware corners: almost square. Buttons, fields, slots and keys are 2px; glass windows and nav links 1px; dialogs and the rack 0. Round is reserved for things that are round on real gear: knobs and LEDs (50%) and the power switch (a 14px-radius pill with a round lever). Free positions in a bank or A/B slot are drawn with a dashed border. Icons are inline 16px line SVGs at a 1.6 stroke with round caps.

## Components

### Buttons
Tactile aluminium keys that press in.
- **Shape:** near-square (2px).
- **Default (on aluminium):** a top-lit aluminium gradient (`#f3f4f6` to `#d8dbde`), `edge` border, `ink` Archivo 600 at 13.5px, padding 8px 14px, with the button-lift shadow. Hover brightens the gradient; active drops 1px and goes inset.
- **Primary (on aluminium):** black anodized (`plate-black`) with amber text and a black border.
- **Primary (on dark surfaces: drawer, dialog, patch detail, gig plan):** solid amber fill with `glass` text; hover goes to `vfd-bright`. Secondary buttons there are a dark-grey gradient with `plate-ink` text.
- **Pressed / toggled:** black with amber text and a deep inset (A/B keys glow).
- **Danger:** text in deep red; hover turns the border `led`.
- **Disabled:** 45% opacity.
- **Focus:** a 2px `focus` outline at 2px offset, on every control.

### Power switch
A rocker in a black track (66 x 28px) with a round aluminium lever; on, the lever slides right in 0.18s and the legend lights amber.

### Inputs / Fields
- **On aluminium:** `field` white, `edge` border, 2px corners, a recessed inset, Archivo at body size. Labels above in the engraved label style.
- **On dark surfaces:** the field becomes glass: `glass` background, amber VT323 at 22px, a deep inset and an amber caret. Placeholders are `vfd-dim`.

### Navigation
The nav rail is an aluminium strip of engraved links (Michroma 10.5px, 0.18em, uppercase) each with a small LED. Hover lightens the row; the current page turns black with amber legend and a lit amber LED. On stage the rail goes warm-black with dim amber legends. Under 760px it becomes a bottom bar of equal links with the LED above the label.

### Chips
Effect chips in the patch detail are small anodized plates in their group colour (`--plate`), 30px tall, with an engraved label; bypassed chips drop to 45% opacity.

### Badges
Small amber tags with `glass` text in the engraved label style (8.5px); green (`go`) marks a gig that is on the pedal.

### Rack Unit (signature)
A full-width faceplate in its group's anodized colour, bolted in with ears: a red LED, the effect name in Michroma with its group in smaller dim legend beneath, a glass readout of its first four knobs (dim label, amber value), move/swap/remove tools at 60% opacity until hovered, and the power switch at the right end. Clicking the name or the readout opens its drawer: a black chassis that slides down (0.26s clip reveal) between the ears with every knob on it. A bypassed unit dims its readout to 40%.

### Knob (signature)
A machined aluminium knob (58px) on black: a grey skirt, a knurled ring, a light cap and a black pointer, swept through 270 degrees, ringed by eleven amber ticks that light up to the current value. Below it, the value in a small glass window and the knob's name as an engraved label. Drag vertically (Shift for fine), scroll, or use the arrow keys; double-click resets it.

### Master Unit (signature)
The black unit at the top of the rack: the patch name in large glass (editable in place), the state line, segmented amber level meters (red when over), then volume and the macro knobs separated by a milled divider with a vertical MACROS legend.

### Slot
A library slot is a small aluminium key: a slot number in glass, the patch name in Archivo 600, an LED. Empty slots are dashed and transparent; the picked slot gets a 2px black outline; the slot the pedal is on gets a red underline.

## Do's and Don'ts

### Do:
- **Do** read the tone top to bottom from IN to OUT, one full-width unit per effect, with 3px rack-well seams between them.
- **Do** bolt every faceplate in with rack ears (26px, two screws) and give it its group's anodized `--plate` colour.
- **Do** put every value the pedal reports on VFD glass: VT323, amber `#ffb000` on `#120c00`, with the phosphor glow.
- **Do** keep engraved legends in Michroma, uppercase, tracked, weight 400.
- **Do** flip the primary action with its surface: black with amber text on aluminium, amber with glass text on black.
- **Do** give depth with 1px black borders, bevels, insets and the 3px bezel lip; keep soft shadows for overlays.
- **Do** turn the lights down on stage: amber on black, large readouts, 64px step buttons.
- **Do** honour reduced motion: the drawer, side drawer and toasts appear without animation, and the busy light stops blinking.

### Don't:
- **Don't** lay effects out as a row of stompboxes, and don't build a dashboard of rounded cards.
- **Don't** put amber text on aluminium.
- **Don't** use a group's plate colour for anything other than that group.
- **Don't** round corners past 2px except on things that are round on real gear (knobs, LEDs, the power pill).
- **Don't** set sentences in Michroma or VT323, and don't set pedal values in Archivo.
- **Don't** use `ink-faint` for running text; it is for placeholders and empty slots.
- **Don't** bring grey, white or group colours into the stage view's rail or main column.
