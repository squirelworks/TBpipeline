"""Item 27: KERNEL.336 IsBadCodePtr answers from the descriptor.

On the real run, TB80BAS seg 7 checks its file manager's handler with
IsBadCodePtr before it calls it (0x788:0xB09). AX = 1 means "bad", so the
handler never ran, the open returned 0, and the runtime said "Failed
initializing the book file manager".
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX

from tests.bf_host_fake import fake_host, far_call


class IsBadCodePtr(unittest.TestCase):
    def ask(self, host, sel, off):
        far_call(host, "KERNEL", 336, [off, sel], pop=4)
        return host.uc.reg_read(UC_X86_REG_AX)

    def test_code_inside_its_segment_is_good(self):
        host = fake_host()
        self.assertEqual(self.ask(host, host.code, 0x10), 0)
        self.assertEqual(host.ax1, [], "IsBadCodePtr fell through to AX = 1")

    def test_data_segment_is_bad(self):
        host = fake_host()
        self.assertEqual(self.ask(host, host.data, 0x10), 1)

    def test_past_the_limit_is_bad(self):
        host = fake_host()
        self.assertEqual(self.ask(host, host.code, 0x1000), 1)

    def test_unknown_or_null_selector_is_bad(self):
        host = fake_host()
        self.assertEqual(self.ask(host, 0, 0), 1)
        self.assertEqual(self.ask(host, 0x7FF8, 0), 1)


if __name__ == "__main__":
    unittest.main()
