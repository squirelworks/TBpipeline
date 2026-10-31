"""Proportional text: tmPitchAndFamily and the width of each character.

TB80BAS reads TMPF_FIXED_PITCH (bit 0) from GetTextMetrics. Windows named the bit backwards: set
means VARIABLE pitch. With it clear, TB80BAS gives every character the width of the break
character and never calls GetCharWidth, so the Logic Families copyright ran past its field and
"Click to continue." was clipped. With it set, TB80BAS fills its table from GetCharWidth and adds
those widths up, so TextOut must stop where that sum says.
"""

import struct
import unittest

from tests.test_neww_batch1_handlers import DATA, NUL, put
from tests.test_neww_batch2 import by_name
from tests.test_neww_batch6 import control_wine


def logfont(w, face, height=-11, weight=400, pitch_family=0x22):
    w.memory.write(DATA, 0x200, struct.pack("<hhhhhBBBBBBBB", height, 0, 0, 0, weight, 0, 0, 0, 0, 0, 0, 0,
                                             pitch_family) + face.encode() + b"\0")
    return (DATA, 0x200)


class TextPitch(unittest.TestCase):
    def setUp(self):
        self.w = control_wine()
        screen = self.call("CreateDC", put(self.w, 0x10, "DISPLAY"), NUL, NUL, NUL)
        self.dc = self.call("CreateCompatibleDC", screen)
        self.call("SelectObject", self.dc, self.call("CreateCompatibleBitmap", screen, 300, 40))

    def call(self, name, *a):
        return by_name(self.w, "GDI", name, *a)[0]

    def select(self, face, pitch_family=0x22):
        self.call("SelectObject", self.dc, self.call("CreateFontIndirect", logfont(self.w, face, pitch_family=pitch_family)))

    def pitch(self):
        self.assertEqual(self.call("GetTextMetrics", self.dc, (DATA, 0x400)), 1)
        return self.w.memory.read(DATA, 0x400 + 0x17, 1)[0]

    def test_a_proportional_face_sets_the_variable_pitch_bit(self):
        self.select("Arial")
        self.assertEqual(self.pitch() & 0x07, 0x07)   # TMPF_FIXED_PITCH | TMPF_VECTOR | TMPF_TRUETYPE

    def test_a_fixed_face_clears_it(self):
        self.select("Courier New", pitch_family=0x31)
        self.assertEqual(self.pitch() & 0x01, 0)

    def test_the_extent_is_the_sum_of_get_char_width(self):
        self.select("Arial")
        text = "Copyright Nida Corporation 1997 - 200"
        self.assertEqual(self.call("GetCharWidth", self.dc, 0, 0xFF, (DATA, 0x600)), 1)
        widths = struct.unpack("<256h", self.w.memory.read(DATA, 0x600, 512))
        self.assertGreater(widths[ord("W")], widths[ord("i")])
        self.w.memory.write(DATA, 0x300, text.encode())
        self.assertEqual(self.call("GetTextExtentPoint", self.dc, (DATA, 0x300), len(text), (DATA, 0x380)), 1)
        cx = struct.unpack("<h", self.w.memory.read(DATA, 0x380, 2))[0]
        self.assertEqual(cx, sum(widths[ord(c)] for c in text))


if __name__ == "__main__":
    unittest.main()
