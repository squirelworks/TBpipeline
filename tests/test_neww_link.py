"""Item 64. A fixup into another ToolBook module is that module's selector and offset.

Two original NE files. No binary and no Windows gate.
"""

import tempfile
import unittest

from tests import neww_ne

MODULES = ("KERNEL", "TB80W16")
IMPORTS = ("W16THREE",)


def w16(directory):
    # Export 1 at 0: three bytes, then retf. Export 2 at 4, by name: inc ax twice... then retf.
    code = bytes([0xB8, 0x42, 0x42, 0xCB]) + bytes([0x40, 0x40, 0x40, 0xCB])
    blob = neww_ne.build(
        "TB80W16", [(0x0000, code, [])],
        entries=[(1, 1, 0, "W16STUB"), (2, 1, 4, "W16THREE")], exe=False,
    )
    return neww_ne.write(directory, "TB80W16.DLL", blob)


def program(directory, by_name):
    code = bytearray()
    fixups = []
    if by_name:
        code += neww_ne.mov_ax(0x0100)
        target = (3, 2, len(code) + 1, 2, neww_ne.name_offset(MODULES, IMPORTS, "W16THREE"))
    else:
        target = (3, 1, len(code) + 1, 2, 1)
    fixups.append(target)
    code += neww_ne.call_far()
    fixups.append((3, 1, len(code) + 1, 1, 999))
    code += neww_ne.call_far()
    return neww_ne.exit_program_with(directory, bytes(code), fixups, modules=MODULES, imports=IMPORTS)


def run(by_name):
    from unicorn.x86_const import UC_X86_REG_AX
    from tbpipeline_neww.machine import Machine
    d = tempfile.mkdtemp()
    w16(d)
    program(d, by_name)
    host = Machine(d)
    host.run()
    return host, host.uc.reg_read(UC_X86_REG_AX)


class LinkTwoModules(unittest.TestCase):
    def test_fixup_is_the_export_selector_and_offset(self):
        host, _ax = run(by_name=False)
        rtm = host.box.exe.segments[0]
        dll = host.box.images["TB80W16"].segments[0]
        self.assertEqual(bytes(rtm.data[0:5]), bytes([0x9A, 0, 0, dll.selector & 0xFF, dll.selector >> 8]))

    def test_far_call_runs_the_other_module_by_ordinal(self):
        host, ax = run(by_name=False)
        self.assertIn("KERNEL.999", host.stop)
        self.assertEqual(ax, 0x4242)
        self.assertEqual(host.box.wine.trace, ["KERNEL.999 999"])
        self.assertEqual(host.box.gaps, [])

    def test_far_call_runs_the_other_module_by_name(self):
        host, ax = run(by_name=True)
        self.assertIn("KERNEL.999", host.stop)
        self.assertEqual(ax, 0x0103)
        self.assertEqual(host.box.gaps, [])


if __name__ == "__main__":
    unittest.main()


class AdditiveFixup(unittest.TestCase):
    def test_addend_is_added_not_chased(self):
        from tbpipeline_neww.machine import Machine
        d = tempfile.mkdtemp()
        w16(d)
        # mov ax, offset W16STUB + 4 (additive offset fixup, addend 4 in place), then a marker word at 4.
        code = bytearray(bytes([0xB8, 0x04, 0x00]))
        code += bytes([0x90]) + bytes([0xAA, 0xBB])  # offsets 3, 4-5: the word an addend of 4 would point at
        fixups = [(5, 1 | 4, 1, 2, 1)]
        fixups.append((3, 1, len(code) + 1, 1, 999))
        code += neww_ne.call_far()
        neww_ne.exit_program_with(d, bytes(code), fixups, modules=MODULES, imports=IMPORTS)
        host = Machine(d)
        seg = host.box.exe.segments[0]
        # Export 1 is at offset 0, so the result is the addend: 0 + 4.
        self.assertEqual(bytes(seg.data[1:3]), bytes([0x04, 0x00]))
        self.assertEqual(bytes(seg.data[4:6]), bytes([0xAA, 0xBB]))

    def test_addend_on_a_nonzero_export(self):
        from tbpipeline_neww.machine import Machine
        d = tempfile.mkdtemp()
        w16(d)
        code = bytearray(bytes([0xB8, 0x02, 0x00]))
        fixups = [(5, 1 | 4, 1, 2, 2), (3, 1, len(code) + 1, 1, 999)]
        code += neww_ne.call_far()
        neww_ne.exit_program_with(d, bytes(code), fixups, modules=MODULES, imports=IMPORTS)
        host = Machine(d)
        seg = host.box.exe.segments[0]
        # Export 2 is at offset 4. 4 + 2 = 6.
        self.assertEqual(bytes(seg.data[1:3]), bytes([0x06, 0x00]))
