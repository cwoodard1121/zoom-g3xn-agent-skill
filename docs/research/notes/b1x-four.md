# Zoom B1X FOUR (and B1 FOUR) over USB-MIDI: how it differs from the G3Xn

Researched 2026-11-15. No B1X FOUR was on hand. Every fact below comes from a published source.

The B1X FOUR speaks the same SysEx protocol as the G3Xn. The device byte is the same (0x6E). The patch format is the same PTCF format. Four things differ. The identity model byte is 0x0F (B1 FOUR: 0x0E). A patch is 760 bytes, not 736. The PTCF target field is 0x80 (B1 FOUR: 0x40). The pedal holds 50 patches in 5 banks of 10.

## Evidence tags

Each fact carries one tag. The tag says what kind of evidence backs it.

| Tag | Meaning |
|---|---|
| [Zoom] | Zoom's own manual, effect list, patch list or version history. |
| [B1X] | Scripts and SysEx dumps from shooking, who owns a real B1X FOUR. |
| [GCE-B1X] | A Guitar Lab USB capture of a Zoom GCE-3 set to emulate a B1X FOUR (or B1 FOUR). This is not a real B1X FOUR. |
| [G1] | Shown on a G1 FOUR or a GCE-3 only (mungewell). Not shown on a B1X FOUR. |
| [Code] | Parser code only. No raw capture is published. |
| [Derived] | I decoded a published dump myself. The method is stated. |

## 1. Port name, device byte, identity reply

| Fact | Value | Tag | Source |
|---|---|---|---|
| SysEx header | `F0 52 00 6E ...`. The 4th byte is 0x6E, the same as the G3Xn. | [B1X] | [B1XFour/EditorOn.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/EditorOn.sh), [B1XFour_09_PTCF.cpp](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/B1XFour_09_PTCF.cpp) (comment "B1XFour my pedal") |
| 0x6E is a family code, not a model code | MS-50G+, MS-60B+, G2 FOUR, B2 FOUR and GCE-3 all reply with family `6E 00`. The model byte tells them apart. | [Code] | [zoom-explorer miditools.ts](https://github.com/thammer/zoom-explorer/blob/main/src/miditools.ts) |
| Model byte, B1X FOUR | `0F` (B1 FOUR `0E`, G1 FOUR `0C`, G1X FOUR `0D`, G3n `02`, G3Xn `03`, B3n `04`, G5n `00`) | [Code] for the identity reply. [GCE-B1X] for the `58 02` reply. | [zoomzt2_shooking.py](https://github.com/shooking/ZoomPedalFun/blob/main/python/zoomzt2_shooking.py), [GCE-3/README.md](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/README.md) |
| Identity request | `F0 7E 00 06 01 F7` | [B1X] | [B1XFour/Identify.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/Identify.sh) |
| Identity reply layout | `F0 7E <dev> 06 02 52 6E 00 0F 00 <4 ASCII version chars> F7`. The parser reads family at reply bytes 5 and 6, model at byte 7, version text at bytes 9 to 12 (counted without F0). | [Code] | [zoomzt2_shooking.py](https://github.com/shooking/ZoomPedalFun/blob/main/python/zoomzt2_shooking.py) (connect method) |
| GCE-3 model query `F0 52 00 6E 58 02 F7` | Reply `F0 52 00 6E 58 01 6E 00 0F 00 F7` in B1X FOUR mode, `... 6E 00 0E 00 ...` in B1 FOUR mode. This is a GCE-3 command. A real B1X FOUR is not shown to answer it. | [GCE-B1X] | [ChangeToB1XFour.txt](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1XFour.txt) line 352, [ChangeToB1Four.txt](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1Four.txt) |
| USB-MIDI port name | Starts with "ZOOM G". shooking's B1X FOUR tool opens the first port whose name starts with "ZOOM G", on Linux and on Windows. The full string is not published. The G3Xn in this repo shows "ZOOM G Series". | [B1X] for the prefix. Full string unknown. | [python/b1xfour001.py](https://github.com/shooking/ZoomPedalFun/blob/main/python/b1xfour001.py) line 436, [zoomzt2_shooking.py](https://github.com/shooking/ZoomPedalFun/blob/main/python/zoomzt2_shooking.py) line 244 |

Consequence for the library: the port prefix and the device byte do not tell a G3Xn from a B1X FOUR. Only the identity model byte does.

## 2. Patch memory

| Fact | Value | Tag | Source |
|---|---|---|---|
| User patches | 50 | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), p. 5 and Specifications |
| Banks | 5 banks of 10 patches. The display numbers patches 10 to 59. Bank 1 holds 10 to 19, bank 5 holds 50 to 59. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), "Memory overview" |
| Footswitches and bank buttons | In MEMORY mode the effect/bank buttons change bank. Two footswitches step down and up. BANK HOLD keeps stepping inside one bank. PRESELECT picks a patch while the old tone keeps playing. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), pp. 13, 31, 34 |
| Factory patches | Patches 10 to 49 are factory tones. Patches 50 to 59 are empty. | [Zoom] | [B1X FOUR patch list](https://zoomcorp.com/media/documents/E_B1XFOUR_Patchlist.pdf) |
| `44` patch info reply | `F0 52 00 6E 43 32 00 78 05 32 00 0A 00 00 00 01 00 00 00 01 01 00 ... F7`. Count = 0x32 = 50. Patch size = 0x78 + 0x05 x 128 = 760. Bank size = 0x0A = 10. Same reply in B1 FOUR mode. | [GCE-B1X] | [ChangeToB1XFour.txt](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1XFour.txt) lines 34 and 35 |
| Patch size | 760 bytes. I decoded all 100 of shooking's real B1X FOUR dumps: 50 in the `45` form (patch_00.bin to patch_49.bin, 888 bytes each) and 50 in the `08` form (patch_00_00.bin to patch_04_09.bin, 885 bytes each). All 100 carry length 760, a valid CRC32 and PTCF target 0x80. | [B1X], [Derived] | [B1XFour/DerivedData/Patches](https://github.com/shooking/ZoomPedalFun/tree/main/B1XFour/DerivedData/Patches) |
| Patch format | PTCF, version 1. Chunks: PTCF header, TXJ1, TXE1, EDTB, PPRM (12 bytes), then filler to 760. The filler is not always zero. patch_00_00.bin and patch_23.bin hold stale EDTB and PPRM tags after the first PPRM. A parser stops at the first PPRM. No NAME chunk and no PRM2 chunk. This is the layout `g3xn/patch.py` already parses. | [B1X], [Derived] | patch_00.bin decoded with the zoom-zt2 7-bit unpack. Layout per [decode_preset.py](https://github.com/mungewell/zoom-zt2/blob/master/decode_preset.py). thammer confirms G1 FOUR patches have PPRM, not PRM2, and no NAME: [zoom-explorer issue 7](https://github.com/thammer/zoom-explorer/issues/7) |
| PTCF target field | 0x00000080 for B1X FOUR. 0x00000040 for B1 FOUR. The G3Xn uses 0x04. | [B1X] and [GCE-B1X] for 0x80. [GCE-B1X] for 0x40. | Bit names in [decode_preset.py](https://github.com/mungewell/zoom-zt2/blob/master/decode_preset.py) ("b1four 0x40", "b1xfour 0x80"). 0x80 is in all 100 real dumps and all 50 Guitar Lab writes in the B1X capture. 0x40 is in the first Guitar Lab write of the [B1 FOUR capture](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1Four.txt). I checked only that one. |
| Patch name | 10 ASCII characters at PTCF offset 0x1A, space padded. Live rename is per character, positions 0 to 9. | [B1X] | [B1XFour_09_PTCF.cpp](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/B1XFour_09_PTCF.cpp), [SetPatchChar.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/SetPatchChar.sh) |
| Chain records per patch | Guitar Lab's factory patches carry 5 to 7 EDTB records. A two-screen effect adds a continuation record with id 0x00000001, as on the G3Xn. Example: "CLmelody" has 7 records for 5 effects. | [GCE-B1X], [Derived] | I decoded the 50 `45` writes in [ChangeToB1XFour.txt](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1XFour.txt). |

## 3. SysEx commands

The byte layouts match the G3Xn commands in `g3xn/protocol.py`. Every message starts `F0 52 00 6E` and ends `F7`.

| Action | Bytes after `F0 52 00 6E` | Tag | Source |
|---|---|---|---|
| Editor mode on / off | `50` / `51` | [B1X] | [EditorOn.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/EditorOn.sh), [EditorOff.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/EditorOff.sh) |
| PC mode on / off | `52` / `53` | [B1X] | [PCModeOn.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/PCModeOn.sh), [PCModeOff.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/PCModeOff.sh) |
| Ask current bank and program | `33`. The pedal answers with CC0, CC32 (bank) and a Program Change. | [B1X] for the request. [G1] for the reply form. | [CurrentBankNumber.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/CurrentBankNumber.sh), [zoom-zt2 readme](https://github.com/mungewell/zoom-zt2/blob/master/readme.md) |
| Select patch | MIDI, not SysEx: `B0 00 00  B0 20 <bank 0..4>  C0 <program 0..9>` | [B1X] | [LoadPatchB1XFour.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/LoadPatchB1XFour.sh), [b1xfour001.py](https://github.com/shooking/ZoomPedalFun/blob/main/python/b1xfour001.py) LoadPatch |
| Patch info | `44`. Reply opcode `43`. Layout in section 2. | [GCE-B1X] | see section 2 |
| Read patch by slot (new form) | `46 00 00 <bank lo> <bank hi> <prog lo> <prog hi>`. Reply `45 00 00 <bank 2 bytes> <prog 2 bytes> <len lo> <len hi> <packed data> <CRC32 as 5 bytes>`. | [B1X] | [GetPatch.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/GetPatch.sh), [zoomzt2.py](https://github.com/mungewell/zoom-zt2/blob/master/zoomzt2.py) patch_download |
| Slot encoding | bank = (index) div 10, prog = (index) mod 10, index 0..49. shooking sent bank 0 with prog 23. The pedal replied with bank 2, prog 3 ("TalkToMe", display patch 33). So the pedal accepts a flat index in the prog field for reads. | [B1X], [Derived] | header of [patch_23.bin](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/DerivedData/Patches/patch_23.bin) |
| Write patch by slot | `45 00 00 <bank 2 bytes> <prog 2 bytes> <len lo> <len hi> <packed 760 bytes> <CRC32 5 bytes>`. Guitar Lab sends bank 0..4 and prog 0..9. | [GCE-B1X] | 50 writes in [ChangeToB1XFour.txt](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1XFour.txt), [zoomzt2.py](https://github.com/mungewell/zoom-zt2/blob/master/zoomzt2.py) patch_upload |
| Read patch by slot (old form) | `09 00 <bank> <prog>`. Reply `08 <bank> 00 <prog> <len lo> <len hi> <packed data> <CRC32 5 bytes>`. Observed for bank 2, prog 3: `08 02 00 03 78 05 ...`. | [B1X], [Derived] | [GetPatchBankPgm.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/GetPatchBankPgm.sh), [zoomzt2.py](https://github.com/mungewell/zoom-zt2/blob/master/zoomzt2.py) patch_download_old |
| Read current patch | `29`. The reply opcode is not published. zoom-zt2 unpacks the reply from byte 4 with no length field or CRC check. | [B1X] for the request. [Code] for the reply. | [GetCurrentPatch.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/GetCurrentPatch.sh), [zoomzt2.py](https://github.com/mungewell/zoom-zt2/blob/master/zoomzt2.py) patch_download_current_old |
| Read current patch (new form) | `64 13`. zoom-zt2 reads a length at reply bytes 6 and 7 and checks a CRC32. The reply opcode is not stated there. `g3xn/protocol.py` names it `64 12` on the G3Xn. | [G1] | [zoomzt2.py](https://github.com/mungewell/zoom-zt2/blob/master/zoomzt2.py) patch_download_current |
| Live edit, generic | `64 03 00 <slot> <param> <v0> <v1> <v2> <v3> <v4>`. The value is 7-bit little-endian over 5 bytes. | [B1X] | [FXM_PN.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/FXM_PN.sh) |
| Effect on/off | `64 03 00 <slot 0..4> 00 <0 or 1> 00 00 00 00` | [B1X] | [FXM_OnOff.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/FXM_OnOff.sh) |
| Effect type | `64 03 00 <slot> 01 <id as 5 x 7 bits>`. Example: 0x01000030 (SlowATTCK) is `30 00 00 08 00`. Bypass is all zero. | [B1X] | [FXM_ID.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/FXM_ID.sh), [FXM_Delete.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/FXM_Delete.sh) |
| Knob value | `64 03 00 <slot> <knob + 1> <lo> <hi> 00 00 00`. Knob 1 is param 2. | [B1X] | [FXM_PN.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/FXM_PN.sh) |
| Patch name character | `64 03 00 09 <pos 0..9> <ASCII> 00 00 00 00` | [B1X] | [SetPatchChar.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/SetPatchChar.sh) |
| Patch volume | `64 03 00 0A 00 <value> 00 00 00 00`. mungewell calls the same bytes "master volume" in one note and "patch volume" in another. | [B1X] | [SetPatchVolume.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/SetPatchVolume.sh), [zoom-zt2 issue 16](https://github.com/mungewell/zoom-zt2/issues/16) |
| Screen text dump | `64 02 <first screen> <last screen> 00`. The reply form `64 01 ...` is the one `g3xn/protocol.py` parses on the G3Xn. It is not shown on a B1X FOUR. thammer saw a G1 FOUR ignore the ranged form and answer `64 02` with no range. | [B1X] for the request. [G1] for the quirk. | [FX_M1_M2_Values.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/FX_M1_M2_Values.sh), [zoom-explorer issue 7](https://github.com/thammer/zoom-explorer/issues/7) |
| List installed effect files | `64 05`, repeated. Each reply `64 06` holds one file name (BYPASS.ZD2, SLWATK.ZD2, ...). Guitar Lab sent it 101 times. | [GCE-B1X] | [ChangeToB1XFour.txt](https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1XFour.txt) lines 142 to 343 |
| Store | No dedicated store command is published. Guitar Lab writes a whole slot with `45`. AUTO SAVE writes front-panel edits. | none | none |

Two read forms give different patch bytes for the same slot. For "Sans Clean", `09`/`08` gave 5 EDTB records with no 0x00000001 continuation after the two-screen Bass DRV. `46`/`45` gave 6 records with the continuation. I decoded both from [patch_00_00.bin](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/DerivedData/Patches/patch_00_00.bin) and [patch_00.bin](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/DerivedData/Patches/patch_00.bin). Across all 100 dumps, every `08` dump has exactly 5 records. The `45` dumps have 5, 6 or 7 records. The source does not say which firmware made each dump. Guitar Lab and `g3xn` both use `46`/`45`. Use that pair.

## 4. Effect chain and effects

| Fact | Value | Tag | Source |
|---|---|---|---|
| Effects per patch | 5 | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), Specifications |
| Wide effects | An 8-knob effect takes 2 chain records. On a G1 FOUR, 5 wide effects ran at once at 84% DSP load. | [G1] | [ZoomPedalFun issue 7](https://github.com/shooking/ZoomPedalFun/issues/7) |
| DSP limit | The pedal shows "PROCESS OVERFLOW" and bypasses the effect. No numeric budget is published by Zoom. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), p. 20 and Troubleshooting |
| Per-effect load | Each ZD2 file carries a "dspload" field. zoom-zt2 prints dspload / 2.5 as a percent. Values are in the table below. | [Code] | [decode_effect.py](https://github.com/mungewell/zoom-zt2/blob/master/decode_effect.py) line 145 |
| Pedal effects | Only one PEDAL category effect per patch. The expression pedal drives it. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), p. 53 |
| Effect ids | 32-bit ids with the category in the top byte, as on the G3n. Same ZD2 file format as the G3n and G5n. Not the MultiStomp ZDL format. | [Code] | [zoom-zt2 readme](https://github.com/mungewell/zoom-zt2/blob/master/readme.md), "Effects" |
| 1U and 3S files | "1U" files page 8 knobs over one screen. "3S" files cap delay at 3000 ms. The G1/B1/A1 FOUR family uses these. Full G3n versions are blocked by GUARDZDL.ZT2. | [Code] | [zoom-zt2 readme](https://github.com/mungewell/zoom-zt2/blob/master/readme.md), "Effects" |
| B1X only effects | The B1 FOUR online list lacks PDL Vol, BassWah, PDL Reso, Ba PDLPit, Ba PDLMnP and Output VP. The B1X FOUR list has them. | [Code] | [B1 FOUR list](https://github.com/mungewell/zoom-zt2/blob/master/zoom_fx_AllZDL7/B1%20FOUR/unzipped/list_sorted.txt), [B1X FOUR list](https://github.com/mungewell/zoom-zt2/blob/master/zoom_fx_AllZDL7/B1X%20FOUR/unzipped/list_sorted.txt) |
| Default-installed set | Unknown for the B1X FOUR. mungewell's B1 FOUR FLST_SEQ.sh has 93 entries and marks 19 as not installed (-N). The file does not state its origin. 16 of those 19 files are present in shooking's B1X FOUR dump, so the B1 FOUR flags do not describe the B1X FOUR. Zoom's own page says "over 60 built-in effects". | [Code] | [B1 FOUR FLST_SEQ.sh](https://github.com/mungewell/zoom-zt2/blob/master/zoom_fx_AllZDL7/B1%20FOUR/unzipped/FLST_SEQ.sh), [zoom.co.jp](https://www.zoom.co.jp/taxonomy/term/7) |
| Categories | DYNAMICS, FILTER, DRIVE, AMP, CABINET, MODULATION, SFX, DELAY, REVERB, PEDAL | [Zoom] | [Effects list](https://zoomcorp.com/media/documents/E_B1FOUR_FX-list.pdf), contents page |

The B1 FOUR "not installed" entries are DUAL_CMP, A_FILTER, STBGEQ1U, LOW_EQ, ENV_FLTR, RCBOOST, B_OD, BA_FZSML, BA_METAL, THEVIBE, HPS, BASS_PHA, LPROLL3S, STDSYN, RVRSDL3S, MODDELAY, DUALDL3S, AIR and HALL.

### Effect catalogue, firmware 2.00

The list comes from shooking's dump of a fresh B1X FOUR on firmware 2.00 ([allfx.json](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/DerivedData/2.00/allfx.json), [README](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/DerivedData/2.00/README.md)). It holds 95 effects plus Bypass. Which of these are installed by default is unknown. The effect ids and load figures come from mungewell's [B1X FOUR list](https://github.com/mungewell/zoom-zt2/blob/master/zoom_fx_AllZDL7/B1X%20FOUR/unzipped/list_sorted.txt), joined by file name. That list describes the files on Zoom's download server. Their version numbers can be newer than the built-in files. I mapped category numbers to names by matching effect names to Zoom's effects list.

Counts: DYNAMICS 10, FILTER 13, DRIVE 18, AMP 9, CABINET 10, MODULATION 14, SFX 6, DELAY 3, REVERB 6, PEDAL 6.

| Category | Name | File | Effect id | Screens | dspload/2.5 (%) |
|---|---|---|---|---|---|
| DYNAMICS | SlowATTCK | SLWATK.ZD2 | 0x01000030 | 1 | 5.41 |
| DYNAMICS | ZNR | ZNR.ZD2 | 0x01000040 | 1 | 4.35 |
| DYNAMICS | OptComp | OPTCOMP.ZD2 | 0x01000080 | 1 | 12.72 |
| DYNAMICS | BlackOpt | BLACKOPT.ZD2 | 0x01800010 | 1 | 14.27 |
| DYNAMICS | LMT-76 | LMT1176.ZD2 | 0x01800020 | 1 | 13.45 |
| DYNAMICS | 160 Comp | 160_COMP.ZD2 | 0x01800030 | 1 | 12.63 |
| DYNAMICS | DualComp | DUAL_CMP.ZD2 | 0x01800040 | 1 | 8.12 |
| DYNAMICS | MB Comp | MB_COMP.ZD2 | 0x01800050 | 1 | 20.84 |
| DYNAMICS | DYN Comp | DCOMP.ZD2 | 0x01800060 | 1 | 5.66 |
| DYNAMICS | Glam Comp | GLAMCOMP.ZD2 | 0x01800070 | 1 | 12.72 |
| FILTER | SeqFLTR | SEQFLTR.ZD2 | 0x02000040 | 1 | 8.53 |
| FILTER | Exciter | EXCITER.ZD2 | 0x020000b0 | 1 | 8.70 |
| FILTER | BassA-Wah | B_ATWAH.ZD2 | 0x02800010 | 1 | 7.10 |
| FILTER | Z Tron | Z_TRON.ZD2 | 0x02800020 | 1 | 6.40 |
| FILTER | A-Filter | A_FILTER.ZD2 | 0x02800030 | 1 | 7.22 |
| FILTER | Bass Cry | BA_CRY.ZD2 | 0x02800040 | 1 | 9.68 |
| FILTER | BassGEQ | BA_GEQ1U.ZD2 | 0x02800051 | 2 | 5.41 |
| FILTER | St Ba GEQ | STBGEQ1U.ZD2 | 0x02800061 | 2 | 7.34 |
| FILTER | BassPEQ | BA_PEQ.ZD2 | 0x02800070 | 1 | 4.18 |
| FILTER | Splitter | SPLITTER.ZD2 | 0x02800080 | 1 | 5.58 |
| FILTER | Low EQ | LOW_EQ.ZD2 | 0x02800090 | 1 | 4.43 |
| FILTER | High EQ | HIGH_EQ.ZD2 | 0x02800095 | 1 | 3.32 |
| FILTER | EnvFilter | ENV_FLTR.ZD2 | 0x028000a0 | 1 | 13.12 |
| DRIVE | EP Stomp | EP_STOMP.ZD2 | 0x03000020 | 1 | 12.96 |
| DRIVE | RC Boost | RCBOOST.ZD2 | 0x03000030 | 1 | 15.09 |
| DRIVE | NYC Muff | NYC_MUFF.ZD2 | 0x030000d0 | 1 | 13.94 |
| DRIVE | Squeak | SQUEAK.ZD2 | 0x03000130 | 1 | 12.55 |
| DRIVE | Bass DRV | BA_DRV1U.ZD2 | 0x03800011 | 2 | 14.93 |
| DRIVE | D.I Plus | DIPLUS1U.ZD2 | 0x03800021 | 2 | 14.76 |
| DRIVE | Dark Pre | DRKPRE1U.ZD2 | 0x03800031 | 2 | 25.43 |
| DRIVE | Bass BB | BASS_BB.ZD2 | 0x03800040 | 1 | 13.78 |
| DRIVE | DI-5 | DI5.ZD2 | 0x03800050 | 1 | 17.22 |
| DRIVE | Bass Pre | BA_PRE.ZD2 | 0x03800060 | 1 | 17.55 |
| DRIVE | Bass OD | B_OD.ZD2 | 0x03800070 | 1 | 13.78 |
| DRIVE | BassTsDRV | BA_TSDRV.ZD2 | 0x03800080 | 1 | 16.08 |
| DRIVE | Dark OD | DARK_OD.ZD2 | 0x03800090 | 1 | 21.33 |
| DRIVE | BlueB BOD | BBB_OD.ZD2 | 0x038000a0 | 1 | 18.70 |
| DRIVE | VooDoo-B | VOODOO_B.ZD2 | 0x038000b0 | 1 | 18.66 |
| DRIVE | BaFzSmile | BA_FZSML.ZD2 | 0x038000c0 | 1 | 12.63 |
| DRIVE | BassMetal | BA_METAL.ZD2 | 0x038000d0 | 1 | 11.98 |
| DRIVE | BassOctFZ | BA_OCTFZ.ZD2 | 0x038000e0 | 1 | 25.92 |
| AMP | AMPG SVT | SVT_1U.ZD2 | 0x04800011 | 2 | 21.98 |
| AMP | BMAN100 | BMN1001U.ZD2 | 0x04800021 | 2 | 32.40 |
| AMP | SMR400 | SWR4001U.ZD2 | 0x04800031 | 2 | 24.61 |
| AMP | AG 750 | AG750_1U.ZD2 | 0x04800041 | 2 | 23.30 |
| AMP | TE400SMX | TE400_1U.ZD2 | 0x04800051 | 2 | 18.78 |
| AMP | AC 370 | AC370_1U.ZD2 | 0x04800061 | 2 | 26.74 |
| AMP | Mini MkB | MINIMARK.ZD2 | 0x04800070 | 1 | 11.56 |
| AMP | EBH360 | EBH3601U.ZD2 | 0x04800081 | 2 | 21.82 |
| AMP | FlipTop | B15N_1U.ZD2 | 0x04800091 | 2 | 17.55 |
| CABINET | SVT8x10 | SVT_8X10.ZD2 | 0x05800010 | 1 | 13.29 |
| CABINET | SVT4x10TW | SV4X10TW.ZD2 | 0x05800018 | 1 | 13.29 |
| CABINET | FD-B4x12 | FD_B4X12.ZD2 | 0x05800020 | 1 | 13.29 |
| CABINET | SMR4x10TW | SWR_4X10.ZD2 | 0x05800030 | 1 | 13.29 |
| CABINET | AG4x10TW | AG4X10TW.ZD2 | 0x05800040 | 1 | 13.29 |
| CABINET | TE4x10 | TE_4X10.ZD2 | 0x05800050 | 1 | 13.29 |
| CABINET | AC1x18 | AC_1X18.ZD2 | 0x05800060 | 1 | 13.29 |
| CABINET | MkB2x8TW | MKB2X8TW.ZD2 | 0x05800070 | 1 | 17.14 |
| CABINET | EB4x10TW | EB4X10TW.ZD2 | 0x05800080 | 1 | 13.29 |
| CABINET | AM1x15 | AM1X15.ZD2 | 0x05800090 | 1 | 13.29 |
| MODULATION | Tremolo | TREMOLO.ZD2 | 0x06000010 | 1 | 8.78 |
| MODULATION | Phaser | PHASER.ZD2 | 0x06000040 | 1 | 7.46 |
| MODULATION | TheVibe | THEVIBE.ZD2 | 0x06000060 | 1 | 9.76 |
| MODULATION | PitchSHFT | PITCHSHF.ZD2 | 0x060000b0 | 1 | 6.89 |
| MODULATION | HPS | HPS.ZD2 | 0x060000d0 | 1 | 6.64 |
| MODULATION | CloneCho | CLONECHO.ZD2 | 0x06000100 | 1 | 10.25 |
| MODULATION | SuperCho | SUPERCHO.ZD2 | 0x06000110 | 1 | 8.45 |
| MODULATION | CoronaTri | CRNTRI3S.ZD2 | 0x06000131 | 1 | 21.00 |
| MODULATION | BassStCho | B_ST_CHO.ZD2 | 0x06800020 | 1 | 6.89 |
| MODULATION | BaVinFLNG | B_VFLNG.ZD2 | 0x06800040 | 1 | 7.38 |
| MODULATION | Ba Octave | B_OCTAVE.ZD2 | 0x06800050 | 1 | 7.46 |
| MODULATION | Ba Detune | B_DETUNE.ZD2 | 0x06800060 | 1 | 12.14 |
| MODULATION | BaMnPitch | B_PITCH.ZD2 | 0x06800070 | 1 | 10.50 |
| MODULATION | BassPhase | BASS_PHA.ZD2 | 0x06800080 | 1 | 9.84 |
| SFX | LoopRoll | LPROLL3S.ZD2 | 0x07000041 | 1 | 6.36 |
| SFX | StdSyn | STDSYN.ZD2 | 0x07800010 | 1 | 20.18 |
| SFX | SynTlk | SYNTLK.ZD2 | 0x07800020 | 1 | 20.10 |
| SFX | Z-Syn | Z_SYN_1U.ZD2 | 0x07800031 | 2 | 17.22 |
| SFX | Defret | DEFRET.ZD2 | 0x07800040 | 1 | 7.06 |
| SFX | PH+Dist | PH_DIST.ZD2 | 0x07800050 | 1 | 17.72 |
| DELAY | Delay | DELAY_3S.ZD2 | 0x08000011 | 1 | 5.50 |
| DELAY | AnalogDly | ANDLY_3S.ZD2 | 0x08000021 | 1 | 5.50 |
| DELAY | TapeEcho | TAPEECHO.ZD2 | 0x08000030 | 1 | 6.97 |
| REVERB | Air | AIR.ZD2 | 0x09000010 | 1 | 6.40 |
| REVERB | Room | ROOM.ZD2 | 0x09000020 | 1 | 9.84 |
| REVERB | Hall | HALL.ZD2 | 0x09000030 | 1 | 10.83 |
| REVERB | HD Hall | HD_HALL.ZD2 | 0x09000040 | 1 | 25.92 |
| REVERB | Spring | SPRING.ZD2 | 0x09000050 | 1 | 9.27 |
| REVERB | Plate | PLATEREV.ZD2 | 0x09000070 | 1 | 20.51 |
| PEDAL | PDL Vol | PDL_VOL.ZD2 | 0x0b000010 | 1 | 3.65 |
| PEDAL | BassWah | BASSWAH.ZD2 | 0x0b800010 | 1 | 7.55 |
| PEDAL | PDL Reso | PDL_RESO.ZD2 | 0x0b800020 | 1 | 5.74 |
| PEDAL | Ba PDLPit | B_PDLPIT.ZD2 | 0x0b800030 | 1 | 6.15 |
| PEDAL | Ba PDLMnP | B_PDLMNP.ZD2 | 0x0b800040 | 1 | 6.32 |
| PEDAL | Output VP | OUT_VP.ZD2 | 0x0bfffff0 | 1 | 3.28 |

Note: the "fxid" and "gid" numbers in allfx.json do not rebuild the 32-bit id for every effect. Output VP loses bits. Use the ids in this table, which match the ids inside the decoded patches.

## 5. Hardware features

| Feature | Fact | Tag | Source |
|---|---|---|---|
| USB | "USB MIDI, USB Micro-B". The pedal runs on USB bus power. The specification lists USB MIDI only. It lists no USB audio. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), Specifications |
| Audio | 44.1 kHz, 24-bit A/D and D/A, 32-bit processing. Mono INPUT jack, AUX IN mini jack, one stereo OUTPUT jack that doubles as headphones. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), Specifications |
| Tuner | CHROMATIC or BASS. BASS shows string numbers for B E A D G C, from low B (LB) to high C (HC). Output BYPASS or MUTE. Reference 435 to 445 Hz. Flat tunings down 1 to 3 semitones. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), pp. 39 to 42 |
| Tuner over SysEx | shooking's B1X scripts send `64 0B` (named "toggle" and "BypassModeOn") and `64 0C` ("BypassModeOff"). One script sends `64 0B` followed by `B0 62 0C B0 63 00`. The pedal's reply is not published. mungewell states `64 0B` on and `64 0C` off for the G1 FOUR. | [B1X] for the bytes. [G1] for on/off meaning. | [BypassModeOn.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/BypassModeOn.sh), [BypassModeOff.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/BypassModeOff.sh), [TunerModeToggle.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/TunerModeToggle.sh) |
| Tuner note stream | In editor mode the pedal sends CC 0x62 (note: 1 = A ... 0x0B = G#, 0x0C = none) and CC 0x63 (cents step). Tuning reference arrives as `64 03 00 0A 0C <n>`. | [G1] | [zoom-zt2 readme](https://github.com/mungewell/zoom-zt2/blob/master/readme.md), "Turn tuner on/off" |
| Expression pedal | B1X FOUR only. It controls the PEDAL category effect. Pressing the toe end switches that effect on or off, and the pedal does not save that state. Calibration and torque screw on the unit. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), pp. 53 to 55 |
| Looper | Mono, 1.5 to 30 seconds. MANUAL or 1 to 64 quarter notes. Stop modes Instant, Finish, Fade Out. AUX IN is not recorded. Firmware 2.00 added a Pre/Post position. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), pp. 47 to 52, [v2.0 supplement](https://zoomcorp.com/media/documents/E_G1FOUR_v2_supplement_0.pdf) |
| Looper and rhythm over SysEx | `64 03 00 0A 01 ...` primes, `64 03 00 0A 03 01 ...` steps record/play/overdub, `64 03 00 0A 04 01 ...` stops and clears. Shown on a GCE-3 only. | [G1] | [looper_it.sh](https://github.com/mungewell/zoom-zt2/blob/master/util_scripts/looper_it.sh), [rhythm_it.sh](https://github.com/mungewell/zoom-zt2/blob/master/util_scripts/rhythm_it.sh) |
| Rhythm | 68 patterns, from "GUIDE" to "Metro". Precount on or off. Volume 0 to 100. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), pp. 43 to 46 |
| Tempo | One master tempo for effects, rhythm and looper. Range 40 to 250 BPM. It is global, not per patch. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), p. 27 |
| Tempo over SysEx | `64 03 00 0A 02 <lo> <hi> 00 00 00`. Example: 117 BPM is `75 00`. | [B1X] | [SetTempo.sh](https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/SetTempo.sh) |
| AUTO SAVE | On by default. With it off, the pedal asks to save when you change patch. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), pp. 21, 28 |
| AUTO SAVE over SysEx | `64 03 00 0A 0F <0 or 1> 00 00 00 00` | [G1] | [zoom-zt2 readme](https://github.com/mungewell/zoom-zt2/blob/master/readme.md), "Change Autosave" |
| Firmware | 1.00 (March 2019), 1.10 (May 2019, fixes USB dropping out), 2.00 (November 2019, looper Pre/Post and a new rhythm screen). 2.00 is the current download. | [Zoom] | [Version history](https://zoomcorp.com/documents/3424/B1FOUR_B1XFOUR_System_Software_Version_History_200_en.pdf), [support page](https://zoomcorp.com/en/us/multi-effects/bass-effects/b1-four-b1x-four/b1b1x-four-support/) |
| Other editors | ToneLib-Zoom supports the B1 FOUR and B1X FOUR on firmware 1.00, 1.10 and 2.00. Guitar Lab 7.3 is Zoom's editor. | [Zoom] for Guitar Lab | [ToneLib supported devices](https://tonelib.net/tonelib-zoom-supported-devices.html), [support page](https://zoomcorp.com/en/us/multi-effects/bass-effects/b1-four-b1x-four/b1b1x-four-support/) |
| Power | 9 V AD-16 adapter, 4 AA batteries (about 18 hours), or USB bus power. | [Zoom] | [Operation manual](https://zoomcorp.com/media/documents/E_B1FOUR.pdf), Specifications |

## 6. What breaks or differs from the G3Xn code

What breaks:

1. Detection. The B1X FOUR has the same device byte (0x6E) and the same "ZOOM G" port prefix as the G3Xn. The library must read the identity reply model byte: 0x03 for G3Xn, 0x0F for B1X FOUR, 0x0E for B1 FOUR.
2. Slot size. The G3Xn code used a fixed 736-byte slot. The B1X FOUR uses 760. Take the size from the `44` reply, not a constant.
3. PTCF target. The G3Xn writes target 4. A B1X FOUR patch carries 0x80 (B1 FOUR 0x40). Guitar Lab writes 0x80. What the pedal does with a patch that carries 4 is unknown.
4. Slot count and banks. 50 patches in banks of 10, against 150 on the G3Xn. Display numbers run 10 to 59, so display number minus 10 gives the index.
5. Chain length. 5 effect positions, against 7 on the G3Xn. Factory patches still carry up to 7 EDTB records, because a two-screen effect adds a 0x00000001 continuation record.
6. Effect catalogue. The ids are bass effects and "1U"/"3S" variants. G3Xn guitar effect ids are not in the B1X FOUR list. Loading a G3n-only file onto this pedal is blocked by GUARDZDL.ZT2.
7. No USB audio. Any feature that records or plays audio through the pedal's USB port does not exist on this model.
8. Expression pedal. The B1X FOUR has one, like the G3Xn. The B1 FOUR does not. The PEDAL category (group 0x0B) is B1X only.

What stays the same:

1. Header `F0 52 00 6E`, editor mode `50`/`51`, PC mode `52`/`53`.
2. 7-bit packing: one high-bit byte, then 7 data bytes, MSB first. Same as `pack7`/`unpack7`.
3. CRC32 on `45` and `08` patch data: the 5-byte 7-bit form of CRC32 XOR 0xFFFFFFFF. My decode validated it on all 50 Guitar Lab writes and all 100 of shooking's real dumps.
4. `46`/`45` slot read and write with 14-bit bank and program fields.
5. `64 03` live edit, slot 0x09 for the name, slot 0x0A for settings (volume 0x00, tempo 0x02).
6. PTCF version 1 with PPRM (12 bytes). EDTB records of 24 bytes with the same bit layout. No NAME chunk.
7. Program select with CC0, CC32 and Program Change.

## Unknown / needs a hardware test

1. The exact Windows port string. Only the "ZOOM G" prefix is published for this pedal.
2. A raw identity reply from a real B1X FOUR. The model byte 0x0F comes from parser code and a GCE-3 emulation.
3. The `44` reply from a real B1X FOUR. The published reply comes from a GCE-3 in B1X mode.
4. Whether a real B1X FOUR answers `64 13` (read edit buffer). It is shown on a G1 FOUR only.
5. Whether the AUTO SAVE setting `64 03 00 0A 0F` works on the B1X FOUR.
6. Whether any dedicated "store edit buffer to slot" command exists.
7. The highest EDTB record count the pedal accepts in a written patch, and the numeric DSP budget.
8. What the pedal does with a patch whose PTCF target is 4 (G3Xn) instead of 0x80.
9. The tuner note stream format on the B1X FOUR, and whether MUTE vs BYPASS is settable by SysEx.
10. Looper and rhythm control by SysEx. It is shown on a GCE-3 only.
11. Whether the expression pedal position is readable or settable over MIDI.
12. Which effects in the firmware 2.00 catalogue are installed by default on a B1X FOUR. Zoom's effects list PDF marks "Guitar Lab additional effects" with an icon. Text extraction drops that icon, so read the PDF pages by eye.
13. Why `09`/`08` and `46`/`45` return different record counts for the same patch.
14. The meaning of the replies to `55` (`54 ...`), `48` (`47 ...`), `64 0A` (`64 09 78 00 01 00 05 00 00 01 01 32 06 00`) and `64 11` (`64 10 66 01 04 01 01`). Guitar Lab sends all four at connect time.
15. Whether the "ZOOM G Series" port is shared between two apps at once on Windows 11 25H2, as for the G3Xn.

## Sources

Zoom:

1. B1 FOUR / B1X FOUR support page: https://zoomcorp.com/en/us/multi-effects/bass-effects/b1-four-b1x-four/b1b1x-four-support/
2. Operation manual (Z2I-3612-01): https://zoomcorp.com/media/documents/E_B1FOUR.pdf
3. Version 2.0 supplementary manual: https://zoomcorp.com/media/documents/E_G1FOUR_v2_supplement_0.pdf
4. Effects list: https://zoomcorp.com/media/documents/E_B1FOUR_FX-list.pdf
5. B1X FOUR patch list: https://zoomcorp.com/media/documents/E_B1XFOUR_Patchlist.pdf
6. System software version history: https://zoomcorp.com/documents/3424/B1FOUR_B1XFOUR_System_Software_Version_History_200_en.pdf
7. Zoom product overview ("over 60 built-in effects"): https://www.zoom.co.jp/taxonomy/term/7

shooking/ZoomPedalFun (real B1X FOUR and GCE-3):

8. B1XFour scripts and decoders: https://github.com/shooking/ZoomPedalFun/tree/main/B1XFour
9. B1XFour_09_PTCF.cpp: https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/B1XFour_09_PTCF.cpp
10. B1X FOUR patch dumps: https://github.com/shooking/ZoomPedalFun/tree/main/B1XFour/DerivedData/Patches
11. B1X FOUR firmware 2.00 effect dump: https://github.com/shooking/ZoomPedalFun/blob/main/B1XFour/DerivedData/2.00/allfx.json
12. zoomzt2_shooking.py (model detection): https://github.com/shooking/ZoomPedalFun/blob/main/python/zoomzt2_shooking.py
13. b1xfour001.py (B1X FOUR editor): https://github.com/shooking/ZoomPedalFun/blob/main/python/b1xfour001.py
14. GCE-3 model table: https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/README.md
15. Guitar Lab capture, B1X FOUR mode: https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1XFour.txt
16. Guitar Lab capture, B1 FOUR mode: https://github.com/shooking/ZoomPedalFun/blob/main/GCE-3/InitialModeChangingExperiments/ChangeToB1Four.txt
17. Issue 7, max effects per patch: https://github.com/shooking/ZoomPedalFun/issues/7

mungewell/zoom-zt2:

18. readme (MIDI command notes, G1 FOUR): https://github.com/mungewell/zoom-zt2/blob/master/readme.md
19. zoomzt2.py: https://github.com/mungewell/zoom-zt2/blob/master/zoomzt2.py
20. decode_preset.py (PTCF layout, target bits): https://github.com/mungewell/zoom-zt2/blob/master/decode_preset.py
21. decode_effect.py (dspload): https://github.com/mungewell/zoom-zt2/blob/master/decode_effect.py
22. B1X FOUR online effect list: https://github.com/mungewell/zoom-zt2/blob/master/zoom_fx_AllZDL7/B1X%20FOUR/unzipped/list_sorted.txt
23. B1 FOUR online effect list: https://github.com/mungewell/zoom-zt2/blob/master/zoom_fx_AllZDL7/B1%20FOUR/unzipped/list_sorted.txt
24. B1 FOUR FLST_SEQ.sh (installed flags): https://github.com/mungewell/zoom-zt2/blob/master/zoom_fx_AllZDL7/B1%20FOUR/unzipped/FLST_SEQ.sh
25. looper_it.sh and rhythm_it.sh: https://github.com/mungewell/zoom-zt2/blob/master/util_scripts/looper_it.sh and https://github.com/mungewell/zoom-zt2/blob/master/util_scripts/rhythm_it.sh
26. Issue 16, parameter and volume notes: https://github.com/mungewell/zoom-zt2/issues/16

thammer/zoom-explorer:

27. miditools.ts (identity family and model map): https://github.com/thammer/zoom-explorer/blob/main/src/miditools.ts
28. Issue 7, G1 FOUR patch chunks and `64 02` quirk: https://github.com/thammer/zoom-explorer/issues/7

ToneLib:

29. ToneLib-Zoom supported devices: https://tonelib.net/tonelib-zoom-supported-devices.html
