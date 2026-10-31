"""Gate arguments are read from the guest's memory, not the loaded image. No binary needed."""

import tempfile
import unittest

from tests import neww_ne


class ArgsReadTheGuest(unittest.TestCase):
    def test_pushed_word_and_string(self):
        from tbpipeline_neww import wine
        from tbpipeline_neww.machine import Machine
        seen = []
        real = wine.Wine._kernel

        def spy(self, ordinal, arg):
            if ordinal == 17:
                seen.append(arg(0))
            if ordinal == 95:
                seen.append(arg.string(0))
            return real(self, ordinal, arg)

        # GlobalFree(0x1234). Then the guest writes "AB" at DS:0x10 and calls LoadLibrary(DS:0x10).
        code = bytearray()
        code += bytes([0x68, 0x34, 0x12])
        fixups = [(3, 1, len(code) + 1, 1, 17)]
        code += neww_ne.call_far()
        code += bytes([0xC7, 0x06, 0x10, 0x00, 0x41, 0x42])  # mov word [0x10], 'AB'
        code += bytes([0xC6, 0x06, 0x12, 0x00, 0x00])        # mov byte [0x12], 0
        code += bytes([0x1E, 0x68, 0x10, 0x00])              # push ds; push 0x10
        fixups.append((3, 1, len(code) + 1, 1, 95))
        code += neww_ne.call_far()
        wine.Wine._kernel = spy
        try:
            with tempfile.TemporaryDirectory() as d:
                neww_ne.exit_program_with(d, bytes(code), fixups)
                host = Machine(d).run()
        finally:
            wine.Wine._kernel = real
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual(seen, [0x1234, "AB"])


if __name__ == "__main__":
    unittest.main()
