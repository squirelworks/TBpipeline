"""A pass 06 host with no ToolBook binary behind it.

The real Unicorn CPU and the real arena, one code selector that stands in
for a caller, and one stack. A "far call" is the return address and the
argument words laid on that stack, then the same OUT 0xE0 handler the
thunk reaches. No DLL is read.
"""

import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_16
from unicorn.x86_const import UC_X86_REG_DX, UC_X86_REG_SP, UC_X86_REG_SS, UC_X86_REG_DS

from tbpipeline_bf.nedllhost.pass06 import Pass06
from tbpipeline_bf.nehost.pass04 import API_PORT
from tbpipeline_bf.nehost.unfold import Arena

STACK_TOP = 0x0F00


def fake_host(cls=Pass06, book=b""):
    host = cls.__new__(cls)
    host.book = "fixture.tbk"
    host.book_bytes = book
    host.opens, host.skipped, host.misses, host.named, host.calls = [], [], [], [], []
    host.open_styles = []
    host._args = b""
    host.files, host.pos, host.heap, host.local, host.mods, host.hrsrc = {}, {}, {}, {}, {}, {}
    host.next_hrsrc = 1
    host.next_handle = 4
    host.exe_inst = 0
    host.last = (0, 0, b"")
    host.startup = 1
    host.fault = ""
    host.uc = Uc(UC_ARCH_X86, UC_MODE_16)
    host.uc.mem_map(0, 0x100000)
    host.arena = Arena(host.uc, 0)
    host.flat = host.arena.alloc_selector(0x10000, 0x9A, fixed_base=0)
    host.thunk = host.arena.alloc_selector(0x1000, 0x9A)
    host.code = host.arena.alloc_selector(0x1000, 0x9A)
    host.stack = host.arena.alloc_selector(0x1000, 0x92)
    host.data = host.arena.alloc_selector(0x1000, 0x92)
    host.segs = {139: host.data}
    host.sites, host.callers = {}, {}
    host.caller = None
    host.ax1 = []
    host.pending = None
    host.modnames = []
    host.uc.reg_write(UC_X86_REG_SS, host.stack)
    host.uc.reg_write(UC_X86_REG_DS, host.data)
    return host


def far_call(host, module, ordinal, words, ret_ip=0x105, pop=None):
    """Lay a Pascal far call on the stack and run the thunk's OUT handler.

    words are in the order _word(n) reads them: words[0] is the last push.
    module None leaves the call site unnamed, the way an unclassified reloc is.
    """
    if module is not None:
        host.callers[(host.code, ret_ip)] = (module, ordinal)
        if pop is not None:
            host.sites[(host.code, ret_ip)] = (module, ordinal, pop)
    sp = STACK_TOP - 4 - 2 * len(words)
    frame = struct.pack("<HH", ret_ip, host.code) + b"".join(struct.pack("<H", w) for w in words)
    host.arena.write(host.stack, sp, frame)
    host.uc.reg_write(UC_X86_REG_SP, sp)
    host.uc.reg_write(UC_X86_REG_DX, ordinal)
    host._on_out(host.uc, API_PORT, 1, 0, None)
    return host
