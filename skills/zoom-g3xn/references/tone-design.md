# Tone design notes for the G3Xn

Lessons from building and gig-testing real patches on this pedal.

## Routing decides the architecture

| Pedal output goes to | Chain | Notes |
|---|---|---|
| PA / interface / headphones / FRFR | pedals → **amp** → **cab** → time effects | The full simulation. Cab choice matters as much as the amp. |
| Real amp, front input | pedals only (drive, comp, mod, delay, reverb) | Stacking an amp sim into a real preamp is usually harsh. Only add an amp block if they ask. |
| Real amp FX return / power amp in | pedals → **amp** → time effects | The real speaker is the cab, so usually **no cab block**. |

Never assume a cab block belongs in the patch; ask about routing once and remember it (`~/.g3xn/rig.md`).

## Pickups change the levels

- Single coils (Strat/Tele) need more gain and usually **much more patch volume** to match humbucker patches. In one gig-tested bank, Strat patches sat near max volume and humbucker patches around 60.
- Tell them which pickup position the tone was built for.
- Level-match patches in a setlist against a reference patch they already like. Ask for one if they're building a bank.

## Loudness is not patch volume

Perceived level depends on gain staging: pickup output, compression, drive VOL, amp Gain, amp VOL, EQ, then patch volume. When the tone is right but the level is wrong, change **post-gain** levels (amp VOL, drive VOL, patch volume), never Gain.

## Choosing effects

- Research first; don't add a Tube Screamer just because the genre often has one. Find what the guitarist actually used.
- `find_effects` descriptions name the hardware each model is based on ("Mesa Boogie Mark I", "Ibanez TS808").
- Amps take 2 of the 7 positions and roughly 30% DSP each. A typical full chain: comp/drive → amp(2) → cab → mod → delay → reverb = 7.
- A song with separate rhythm and lead sounds: load the lead boost or extra drive **off** and tell them which footswitch enables it, or make two patches next to each other.

## Small changes when it's close

If they say a tone is "really close", only nudge (one knob, a few steps). Redesigning a 95% tone loses what they liked.

## Utility patches

Gigs often need a mute / tuner patch (`MuteSW`) and a clean "safe" patch. Offer them when building a setlist.
