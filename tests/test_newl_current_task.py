"""newl GetCurrentTask is not DGROUP and not a word in the string table at 0x1B00."""

import struct
import tempfile
import unittest
from pathlib import Path

from tests.newl_fixture import BY_ORDINAL, FAR, Seg, build

try:
    import unicorn  # noqa: F401
    from unicorn.x86_const import UC_X86_REG_AX
except ImportError:
    unicorn = None


def _rtm(root, table=b""):
    code = b"\x9a\xff\xff\x00\x00\xf4"
    data = bytearray(0x2000)
    data[0x1B00:0x1B00 + len(table)] = table
    build(root / "TB80RTM.EXE", "TB80RTM",
          [Seg(code, [(FAR, BY_ORDINAL, 1, 1, 36)]), Seg(bytes(data), flags=1)],
          modules=["KERNEL"], auto=2, stack=0x200)


@unittest.skipIf(unicorn is None, "unicorn is not installed, so the newl CPU cannot run the fixture")
class CurrentTask(unittest.TestCase):
    def _task(self, table=b""):
        from tbpipeline_newl.cpu import Cpu

        with tempfile.TemporaryDirectory() as tmp:
            _rtm(Path(tmp), table)
            host = Cpu(tmp)
            host.run(limit=100)
        self.assertEqual(host.layer.trace[-1][:3], ("KERNEL", 36, "GetCurrentTask"))
        return host.uc.reg_read(UC_X86_REG_AX), host.dgroup

    def test_not_dgroup(self):
        task, dgroup = self._task()
        self.assertNotEqual(task, dgroup)

    def test_not_a_word_in_the_string_table(self):
        plain, _ = self._task()
        # The fixture's table holds the selector the task would otherwise get,
        # spelled the way letters would spell it, past the count at 0x1B02.
        table = b"SA\x00\x00" + struct.pack("<H", plain) + b"product"
        task, dgroup = self._task(table)
        self.assertNotEqual(task, dgroup)
        words = {struct.unpack_from("<H", table, i)[0] for i in range(0, len(table) - 1, 2)}
        self.assertNotIn(task, words)


if __name__ == "__main__":
    unittest.main()
