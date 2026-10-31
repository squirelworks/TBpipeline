"""A spec `variable` export is data: a fixup to its ordinal points at the values, not at a stub.

COMPOBJ.37 is _GUID_NULL(0 0 0 0) in Wine's compobj.dll16.spec. TB80BAS compares a class's
GUID with it to choose between a lookup by name and one by GUID. neww linked the ordinal as a
gate, so the comparison read the gate's stub bytes, never matched, and the book's *TbxBase*
class was looked up by GUID, missed, and added again: ToolBook then said "Bad extension or
extension not found in path" and, later, "internal error ... line 10115".

One original NE file. No ToolBook bytes.
"""

import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import neww_ne

MODULES = ("KERNEL", "COMPOBJ")


def program(directory, target):
    """A far pointer to COMPOBJ.target, stored after a jump the code takes."""
    code = bytearray([0xEB, 0x04])                 # jmp over the pointer
    at = len(code)
    code += bytes([0xFF, 0xFF, 0x00, 0x00])        # the far pointer the fixup fills
    fixups = [(3, 1, at, 2, target)]
    return neww_ne.exit_program_with(directory, bytes(code), fixups, modules=MODULES)


def linked(target):
    from tbpipeline_neww.machine import Machine
    d = tempfile.mkdtemp()
    program(d, target)
    host = Machine(d)
    host.run()
    off, sel = struct.unpack_from("<HH", host.box.exe.segments[0].data, 2)
    return host, sel, off


class SpecVariables(unittest.TestCase):
    def test_compobj_guids_are_their_spec_values(self):
        from tbpipeline_neww.wine import VARIABLES
        self.assertEqual(VARIABLES["COMPOBJ"][37], ("_GUID_NULL", bytes(16)))
        # IID_IUnknown {00000000-0000-0000-C000-000000000046}, as the four dwords lay it out.
        self.assertEqual(VARIABLES["COMPOBJ"][38][1], bytes.fromhex("00000000" "0000" "0000" "c000000000000046"))

    def test_kernel_variables_are_not_served(self):
        # Wine fills THHOOK at run time, so the spec's zeros are not its value.
        from tbpipeline_neww.wine import Wine
        self.assertIsNone(Wine.variable("KERNEL", 332))
        self.assertIsNone(Wine.variable("KERNEL", 342))

    def test_spec_variables_is_specgen_output(self):
        root = os.environ.get("WINE_SRC")
        if not root:
            raise unittest.SkipTest("WINE_SRC is not set, so spec_variables.py is not regenerated")
        from tbpipeline_neww import specgen
        head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, specgen.WINE_COMMIT)
        self.assertEqual(specgen.render_variables(specgen.generate_variables(root)),
                         Path(specgen.__file__).with_name("spec_variables.py").read_text())


class LinkedVariable(unittest.TestCase):
    def test_fixup_points_at_the_values_in_the_module_data(self):
        host, sel, off = linked(37)
        compobj = host.box.images["COMPOBJ"]
        self.assertEqual(sel, compobj.segments[1].selector)
        self.assertNotEqual(sel, compobj.segments[0].selector)
        self.assertEqual(host._read_guest(sel, off, 16), bytes(16))

    def test_iid_iunknown_reads_as_its_guid(self):
        host, sel, off = linked(38)
        self.assertEqual(host._read_guest(sel, off, 16), bytes.fromhex("00000000" "0000" "0000" "c000000000000046"))

    def test_a_variable_gets_no_gate(self):
        host, _sel, _off = linked(37)
        stubs = host.box.images["COMPOBJ"].segments[0]
        self.assertNotIn((stubs.selector, 37), host.box.gates)

    def test_get_proc_address_answers_the_data(self):
        host, sel, off = linked(37)
        self.assertEqual(host._gate_address("COMPOBJ", 37), (sel, off))

    def test_a_function_ordinal_is_still_a_gate(self):
        # COMPOBJ.1 CoBuildVersion is a function: its fixup is the gate stub, as before.
        host, sel, off = linked(1)
        stubs = host.box.images["COMPOBJ"].segments[0]
        self.assertEqual((sel, off), (stubs.selector, 8))
        self.assertIn((stubs.selector, 1), host.box.gates)


class RealBook(unittest.TestCase):
    def test_book_classes_pass_and_no_error_box_shows(self):
        # TBK_BIN and TBK_BOOK: TB80BAS matches the book's *TbxBase* class by name, so the
        # class check passes, no error box shows, and ToolBook goes on to make its windows.
        from tests.binpath import bin_or_skip
        root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL")
        book = os.environ.get("TBK_BOOK")
        if not book:
            raise unittest.SkipTest("TBK_BOOK is not set")
        from tbpipeline_neww.machine import Machine
        host = Machine(str(root), book)
        host.call_limit = 7000
        host.run(limit=7000 * 1000)
        trace = host.box.wine.trace
        print(f"\nneww stop: {host.stop} after {len(trace)} trace lines")
        boxes = [t for t in trace if t.startswith("USER.1 MessageBox")]
        self.assertEqual(boxes, [])
        self.assertTrue(any(t.startswith("USER.41 CreateWindow") for t in trace[1700:]))


if __name__ == "__main__":
    unittest.main()
