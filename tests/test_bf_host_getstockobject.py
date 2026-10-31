"""GDI.87 GetStockObject returns one handle per stock object.

Wine's GetStockObject16 (gdi.exe16/gdi.c) is HGDIOBJ_16(GetStockObject(obj)).
GetStockObject (gdi32/objects.c) returns 0 for an index below 0, above
STOCK_LAST + 1, or equal to 9, and otherwise the handle-table entry
obj + FIRST_GDI_HANDLE (32) at 96 DPI, whose low word is obj + 32.
TB80RTM asks for fourteen stock objects before it starts; the AX = 1 default
gave every pen, brush and font the same handle.
"""

import unittest

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX

from tests.bf_host_fake import fake_host, far_call


def stock(host, index):
    far_call(host, "GDI", 87, [index], pop=2)
    return host.uc.reg_read(UC_X86_REG_AX), host.uc.reg_read(UC_X86_REG_DX)


class GetStockObject(unittest.TestCase):
    def test_index_plus_first_gdi_handle(self):
        host = fake_host()
        for index in (0, 4, 5, 7, 8, 13, 14, 17, 19, 20):
            self.assertEqual(stock(host, index), (index + 32, 0), index)
        self.assertEqual(host.ax1, [], "GetStockObject fell through to AX = 1")

    def test_each_object_has_its_own_handle(self):
        host = fake_host()
        handles = {stock(host, index)[0] for index in (0, 2, 3, 4, 5)}
        self.assertEqual(len(handles), 5)

    def test_bad_index_is_zero(self):
        host = fake_host()
        for index in (9, 21, 0xFFFF):
            self.assertEqual(stock(host, index)[0], 0, index)


if __name__ == "__main__":
    unittest.main()
