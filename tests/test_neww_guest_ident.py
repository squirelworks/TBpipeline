"""A guest-call ident is a word. Past 0xFFFF finished entries are reused.

On main, the next request is len(self.guest) and _call_code raises
ValueError once that no longer fits in the byte _call_code shifts.
"""

import unittest

from unicorn.x86_const import (
    UC_X86_REG_BP, UC_X86_REG_DI, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SI, UC_X86_REG_SP,
    UC_X86_REG_SS,
)

from tbpipeline_neww.guest import Call, GuestCalls
from tbpipeline_neww.machine import Machine

SS = 0x57
SP = 0x40


class Seg:
    def __init__(self):
        self.base = 0x8000
        self.data = bytearray(0x200)


class FakeUc:
    def __init__(self):
        self.regs = {
            UC_X86_REG_SS: SS, UC_X86_REG_SP: SP,
            UC_X86_REG_DS: 0x3F, UC_X86_REG_ES: 0x3F,
            UC_X86_REG_BP: 0, UC_X86_REG_SI: 0, UC_X86_REG_DI: 0,
        }
        self.stopped = False
        self.writes = []

    def reg_read(self, reg):
        return self.regs.get(reg, 0)

    def reg_write(self, reg, value):
        self.regs[reg] = value

    def emu_stop(self):
        self.stopped = True

    def mem_read(self, _addr, size):
        return b"\x00" * size

    def mem_write(self, addr, data):
        self.writes.append((addr, bytes(data)))

    def ctl_remove_cache(self, _start, _end):
        return None


class FakeBox:
    def __init__(self):
        self.selectors = {SS: Seg()}


def host_with(entries):
    host = Machine.__new__(Machine)
    host.box = FakeBox()
    host.uc = FakeUc()
    host.stop = ""
    host.guest = entries
    host.tramp_free = [(0x100, 0x2000)]
    host.tramp_retired = []
    host.hook_serial = 0
    return host


def one_call():
    return GuestCalls([Call(0x200, 0x10)], lambda _results: (0, 0))


class GuestIdent(unittest.TestCase):
    def test_a_finished_entry_is_reused_past_a_word(self):
        host = host_with([{"done": True} for _ in range(0x10000)])
        host._start_guest(host.uc, one_call(), 0)
        self.assertFalse(host.uc.stopped)
        self.assertEqual(host.stop, "")
        self.assertEqual(len(host.guest), 0x10000)
        self.assertFalse(host.guest[0]["done"])
        self.assertEqual(host.guest[0]["request"].calls[0].cs, 0x200)
        written = host.uc.writes[0][1]
        self.assertEqual(written[-6:], bytes([0xB9, 0x00, 0x00, 0xE6, 0xE8, 0xCB]))

    def test_every_live_ident_stops_by_name(self):
        host = host_with([{"done": False} for _ in range(0x10000)])
        host._start_guest(host.uc, one_call(), 0)
        self.assertTrue(host.uc.stopped)
        self.assertEqual(host.stop, "guest-call ident exhausted")
        self.assertEqual(len(host.guest), 0x10000)
        self.assertFalse(host.guest[0].get("request"))


if __name__ == "__main__":
    unittest.main()
