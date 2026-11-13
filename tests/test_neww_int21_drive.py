"""INT 21h GET CURRENT DEFAULT DRIVE (19h), which tb80ftp asks after its broadcast (#227).
Wine 2528aff2 dlls/krnl386.exe16/int21.c:3966 sets AL to INT21_GetCurrentDrive (:289), the
drive letter of GetCurrentDirectoryW as a number (0 is A:). neww's current directory is
C:\\TBK (wine.BIN_DIR), so it is 2."""

import unittest

from tests.test_neww_batch1_handlers import wine


class CurrentDrive(unittest.TestCase):
    def test_al_is_drive_c(self):
        regs, stop = wine().int21(lambda name: {"ax": 0x19FF}.get(name, 0))
        self.assertIsNone(stop)
        self.assertEqual(regs["ax"], 0x1902)


if __name__ == "__main__":
    unittest.main()


class CurrentDirectory(unittest.TestCase):
    """int21.c:4463 GET CURRENT DIRECTORY: INT21_GetCurrentDirectory (short form) into DS:SI,
    with no drive letter, colon or leading backslash; CF clear. A drive with no root is
    ERROR_INVALID_DRIVE (15) in AX with CF set (:4834)."""

    def call(self, dl):
        from tests.test_neww_batch1_handlers import DATA
        w = wine()
        w.memory.write(DATA, 0x100, b"\xff" * 16)
        regs, stop = w.int21(lambda name: {"ax": 0x4700, "dx": dl, "ds": DATA, "si": 0x100}.get(name, 0))
        return w.memory.read(DATA, 0x100, 8), regs, stop

    def test_current_and_c_drive(self):
        for dl in (0, 3):
            text, regs, stop = self.call(dl)
            self.assertIsNone(stop)
            self.assertEqual(text[:4], b"TBK\0")
            self.assertEqual(regs["eflags_cf"], 0)

    def test_drive_a_is_invalid(self):
        _text, regs, stop = self.call(1)
        self.assertIsNone(stop)
        self.assertEqual((regs["ax"], regs["eflags_cf"]), (15, 1))
