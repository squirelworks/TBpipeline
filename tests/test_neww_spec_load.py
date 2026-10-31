"""Every pascal entry of the Win16 spec files is a contract. No binary needed.

spec_rows.py is the output of specgen.py over the Wine checkout at
WINE_COMMIT. A loaded row's pop is the spec's. With no handler written
for it, a word or a long answers 0, a void answers nothing and leaves AX,
and a -register entry stops before any pop. Nothing answers AX = 1 by
default. Set WINE_SRC to that checkout to regenerate and compare.
"""

import os
import subprocess
import tempfile
import unittest

from tests import neww_ne


def push_word(value):
    return bytes([0x68, value & 0xFF, (value >> 8) & 0xFF])


def run_one(module, ordinal, before, ax=0x1234):
    from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_SP
    from tbpipeline_neww.machine import Machine
    code = neww_ne.mov_ax(ax) + before + neww_ne.call_far() + bytes([0xA3, 0x00, 0x00])  # mov [0], ax
    with tempfile.TemporaryDirectory() as d:
        mods = (module, "KERNEL") if module != "KERNEL" else ("KERNEL",)
        neww_ne.exit_program_with(d, code, [(3, 1, len(code) - 3 - 4, 1, ordinal)], modules=mods)
        host = Machine(d)
        sp0 = host.box.exe.segments[host.box.exe.auto - 1].minsize + host.box.exe.stack
        host.run(limit=5000)
        stored = host.word(host.box.exe.segments[host.box.exe.auto - 1].selector, 0)
        return host, sp0, host.uc.reg_read(UC_X86_REG_SP), stored, host.uc.reg_read(UC_X86_REG_AX)


class Loaded(unittest.TestCase):
    def test_every_pascal_line_is_a_row(self):
        from tbpipeline_neww.spec_rows import SPEC_ROWS
        from tbpipeline_neww.wine import row_for
        total = 0
        for module, rows in SPEC_ROWS.items():
            for line, _void, _value in rows:
                row = row_for(module, int(line.split()[0]))
                self.assertIsNotNone(row, line)
                total += 1
        self.assertEqual(total, 1495)
        for module in ("KERNEL", "USER", "GDI"):
            self.assertIn(module, SPEC_ROWS)

    def test_hand_rows_win(self):
        from tbpipeline_neww.wine import KERNEL, USER, row_for
        for module, table in (("KERNEL", KERNEL), ("USER", USER)):
            for ordinal, row in table.items():
                self.assertIs(row_for(module, ordinal), row)
                self.assertFalse(row.default)

    def test_pop_is_the_spec_types(self):
        from tbpipeline_neww.wine import row_for
        row = row_for("GDI", 1)  # SetBkColor(word long)
        self.assertEqual((row.name, row.pop, row.ret, row.default), ("SetBkColor", 6, "long", True))
        row = row_for("USER", 32)  # GetWindowRect(word ptr), void
        self.assertEqual((row.pop, row.void), (6, True))

    def test_no_default_is_one(self):
        from tbpipeline_neww.wine import LOADED, Wine

        class Arg:
            def __call__(self, n):
                return 0

            def regs(self, name):
                return 0x5555

        wine = Wine(".")
        for table in LOADED.values():
            for row in table.values():
                if not wine.defaulted(row):
                    continue
                wine.trace.append("x")
                ax, dx, stop = wine._default(row, Arg())
                if row.ret == "register":
                    self.assertIsNotNone(stop)
                elif row.void:
                    self.assertEqual((ax, dx, stop), (0x5555, 0, None))
                else:
                    self.assertEqual((ax, dx, stop), (0, 0, None))

    def test_against_wine_checkout(self):
        root = os.environ.get("WINE_SRC")
        if not root:
            raise unittest.SkipTest("WINE_SRC is not set, so spec_rows.py is not regenerated")
        from tbpipeline_neww import specgen
        from pathlib import Path
        head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, specgen.WINE_COMMIT)
        self.assertEqual(specgen.render(specgen.generate(root)), Path(specgen.__file__).with_name("spec_rows.py").read_text())


class Gate(unittest.TestCase):
    def test_word_is_zero_and_pops_the_spec(self):
        # USER.71 ShowCursor(word), -ret16: 0 in AX, retf 2.
        host, sp0, sp, ax, dx = run_one("USER", 71, push_word(1))
        self.assertTrue(host.stop.startswith("dos exit"), host.stop)
        self.assertEqual((ax, sp), (0, sp0 - 4))
        self.assertIn(("USER", 71, "ShowCursor", "0"), host.box.wine.defaults)

    def test_long_is_zero_in_dx_ax(self):
        # GDI.1 SetBkColor(word long): DX:AX 0, retf 6.
        host, sp0, sp, ax, dx = run_one("GDI", 1, push_word(0) + push_word(0) + push_word(0))
        self.assertTrue(host.stop.startswith("dos exit"), host.stop)
        self.assertEqual((ax, sp), (0, sp0 - 4))

    def test_void_leaves_ax(self):
        # USER.124 UpdateWindow(word) returns void in Wine's window.c.
        host, sp0, sp, ax, dx = run_one("USER", 124, push_word(1), ax=0x4321)
        self.assertTrue(host.stop.startswith("dos exit"), host.stop)
        self.assertEqual((ax, sp), (0x4321, sp0 - 4))
        self.assertIn(("USER", 124, "UpdateWindow", "void"), host.box.wine.defaults)

    def test_register_stops_without_pop(self):
        # KERNEL.203 DebugBreak is -register and has no handler. The stub has no retf and the
        # run stops on the OUT.
        host, sp0, sp, stored, ax = run_one("KERNEL", 203, b"")
        self.assertIn("register KERNEL.203 DebugBreak", host.stop)
        self.assertEqual(sp, sp0 - 4)
        self.assertEqual(ax, 0x1234)
        stub = host.box.images["KERNEL"].segments[0].data[203 * 8:203 * 8 + 8]
        self.assertNotEqual(stub[5], 0xCA)


if __name__ == "__main__":
    unittest.main()
