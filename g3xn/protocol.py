"""Zoom G3n / G3Xn USB-MIDI SysEx protocol.

Every pedal message is `F0 52 00 6E <command...> F7` (Zoom, device 0x6E).
mido strips the F0/F7 framing, so everything here works on the inner bytes.

Verified on a G3Xn running firmware 2.20.

    Command                       Bytes after 52 00 6E          Reply
    ----------------------------  ----------------------------  ------------------------------
    Editor mode on / off          50 / 51                       none
    Patch storage info            44                            43 ... count, size, bank size
    Read stored patch             46 00 00 bk bk lc lc          47 ... len len <7-bit> crc5
    Write stored patch            45 00 00 bk bk lc lc len len <7-bit> crc5    00 00 (ok)
    Read edit buffer              64 13                         64 12 01 len len <7-bit> crc5
    Live edit                     64 03 00 slot param v0..v4    64 03 01 ... (echo)
    Tuner on / off                64 0B / 64 0C                 echo, then CC 98 note, CC 99 cents
    Read screen text              64 02 00 first last           64 01 ... display strings
    Current patch number          33                            CC0, CC32 (bank), Program Change
    File system (effects)         60 2x ...                     see Pedal.list_files / read_file

Patch selection is plain MIDI: CC0 = 0, CC32 = bank, Program Change = index
within the bank (3 patches per bank on the G3Xn).

Live edit targets (`64 03 00 <slot> <param> <value>`):
    slot 0..6      chain position. param 0 = on/off, 1 = effect id, 2.. = knob 1..
    slot 0x09      patch name; param = character index 0..9, value = ASCII code
    slot 0x0A      settings; param 0x00 = patch volume, 0x02 = tempo, 0x0F = autosave
Values are sent as five 7-bit groups, least significant first.

Not supported by the pedal: loading a whole patch into the edit buffer
(`64 12` is ignored), so auditions go through a scratch slot instead.
"""
import binascii

ZOOM = (0x52, 0x00, 0x6E)
DEVICE_ID = 0x6E
PORT_PREFIX = "ZOOM G"

EDITOR_ON = 0x50
EDITOR_OFF = 0x51
PATCH_INFO = 0x44
PATCH_WRITE = 0x45
PATCH_READ = 0x46
CURRENT_PROGRAM = 0x33

EDIT = 0x64
EDIT_PARAM = 0x03
EDIT_READ_BUFFER = 0x13
EDIT_BUFFER_DUMP = 0x12
EDIT_SCREEN = 0x02        # request: 64 02 <first> <last> 00
EDIT_SCREEN_REPLY = 0x01  # reply:   64 01 <screen> <param> <kind> 00 <text[10]> ...
TUNER_ON = 0x0B
TUNER_OFF = 0x0C

TARGET_NAME = 0x09
TARGET_SETTINGS = 0x0A
SETTING_VOLUME = 0x00
SETTING_TEMPO = 0x02
SETTING_AUTOSAVE = 0x0F

PARAM_ON_OFF = 0
PARAM_EFFECT = 1
PARAM_FIRST_KNOB = 2

TUNER_NOTE_CC = 98
TUNER_CENTS_CC = 99
TUNER_NOTES = ["A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]


def tuner_note(value):
    """The note in a tuner CC 98 value: 1 is A#, up to 12 for A (anything else: no note)."""
    return TUNER_NOTES[value % 12] if 1 <= value <= 12 else None


def tuner_value(note):
    """The CC 98 value the pedal sends for a note (the inverse of tuner_note)."""
    return TUNER_NOTES.index(note) or 12


def msg(*body):
    """Inner SysEx bytes for a pedal command."""
    return list(ZOOM) + [b for part in body for b in (part if isinstance(part, (list, tuple, bytes)) else [part])]


def pack7(data):
    """8-bit bytes -> MIDI-safe 7-bit groups: one byte of high bits, then up to 7 bytes."""
    out = bytearray()
    for i in range(0, len(data), 7):
        chunk = data[i:i + 7]
        high = 0
        for j, b in enumerate(chunk):
            if b & 0x80:
                high |= 0x40 >> j
        out.append(high)
        out.extend(b & 0x7F for b in chunk)
    return bytes(out)


def unpack7(packed):
    """Inverse of pack7."""
    out = bytearray()
    for i in range(0, len(packed), 8):
        high = packed[i]
        for j, b in enumerate(packed[i + 1:i + 8]):
            out.append(b | 0x80 if high & (0x40 >> j) else b)
    return bytes(out)


def u14(value):
    """Two 7-bit bytes, low first."""
    return [value & 0x7F, (value >> 7) & 0x7F]


def u35(value):
    """Five 7-bit bytes, low first (live-edit values and checksums)."""
    return [(value >> shift) & 0x7F for shift in (0, 7, 14, 21, 28)]


def from_u35(b):
    return b[0] | b[1] << 7 | b[2] << 14 | b[3] << 21 | (b[4] & 0x0F) << 28


def checksum(data):
    """Zoom's 5-byte checksum: inverted CRC-32 of the 8-bit payload."""
    return u35(binascii.crc32(data) ^ 0xFFFFFFFF)


def verify_checksum(data, tail):
    return from_u35(tail) ^ 0xFFFFFFFF == binascii.crc32(data)


def location_to_bank(location, bank_size):
    """1-based patch number -> (bank, index in bank)."""
    return divmod(location - 1, bank_size)
