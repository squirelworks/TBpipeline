"""Run the linked sandbox. A gate is a far call into Windows."""

import struct
import time
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED, UC_HOOK_INTR
from unicorn.x86_const import (
    UC_X86_INS_OUT, UC_X86_REG_EFLAGS, UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP,
    UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CS, UC_X86_REG_CX, UC_X86_REG_DI, UC_X86_REG_DS,
    UC_X86_REG_BP, UC_X86_REG_DX, UC_X86_REG_ES, UC_X86_REG_FPCW, UC_X86_REG_FPSW, UC_X86_REG_FPTAG, UC_X86_REG_IP, UC_X86_REG_LDTR, UC_X86_REG_SI, UC_X86_REG_SP, UC_X86_REG_SS,
)

REGISTERS = {
    "ax": UC_X86_REG_AX, "bx": UC_X86_REG_BX, "cx": UC_X86_REG_CX, "dx": UC_X86_REG_DX,
    "si": UC_X86_REG_SI, "di": UC_X86_REG_DI, "sp": UC_X86_REG_SP, "bp": UC_X86_REG_BP,
    "ds": UC_X86_REG_DS, "es": UC_X86_REG_ES, "ss": UC_X86_REG_SS,
    "fpcw": UC_X86_REG_FPCW, "fpsw": UC_X86_REG_FPSW, "fptag": UC_X86_REG_FPTAG,
}

from .guest import Call, GuestCalls
from .image import Sandbox
from .wine import SYSTEM, moveable_handle
from .ne import Segment
from . import tasks
from . import win32


# The GDT is at linear 0. Its copy, the LDT, is the next 64K.
LDT_BASE = 0x10000

# Where an INT 21h answer that sets ES or DS returns through, so the CPU loads the selectors.
# Its selector's GDT base is selector * 16, so it is the same block by either rule.
INT_TAIL_SEL = 0xFFF0
INT_TAIL = INT_TAIL_SEL << 4
# In the same block, where a task switch loads the next task's SS:SP, DS, ES and CS:IP from
# the words at SWITCH_DATA.
SWITCH_TAIL = 0x20
SWITCH_DATA = 0x40
# In the same block, where a call into 32-bit code goes from a gate's retf: it loads SS, ESP,
# DS, ES, FS and CS:EIP from ENTRY32_DATA. See win32.py.
ENTRY32_TAIL = 0x60
ENTRY32_DATA = 0x80
# The registers a task switch saves and loads directly. The segment registers go through the tail.
TASK_REGISTERS = ("ax", "bx", "cx", "dx", "si", "di", "bp", "fpcw")

# The cap stays. A run that ends on it says so.
TIMEOUT_US = 15_000_000

# PDB16 in Wine include/wine/winbase16.h, filled as task.c TASK_Create does.
PSP_SIZE = 0x110
# Fields Wine fills that neww has nothing for. A read of one stops the run.
PSP_UNFILLED = (
    (0x05, 0x0A, "dispatcher at 0x05, Wine's far call to KERNEL.DOS3Call"),
)

# Wine task.c GetDOSEnvironment16: the process's environment strings, a 0, WORD 1, then this name.
# neww copies nothing from the host. It has the two strings every Wine prefix sets (wine.inf's
# HKCU Environment TEMP and TMP), with neww's own directory for them: there is no user profile,
# so the folder is TEMP under neww's Windows directory.
ENV_STRINGS = (b"TEMP=C:\\WINDOWS\\TEMP", b"TMP=C:\\WINDOWS\\TEMP")
ENV_PROGRAM_NAME = b"C:\\WINDOWS\\SYSTEM\\KRNL386.EXE\x00"


def _descriptor(base, limit, access, flags=0):
    """flags is the high nibble of byte 6: 0x80 granularity, 0x40 a 32-bit segment."""
    raw = bytearray(8)
    raw[0] = limit & 0xFF
    raw[1] = (limit >> 8) & 0xFF
    raw[2] = base & 0xFF
    raw[3] = (base >> 8) & 0xFF
    raw[4] = (base >> 16) & 0xFF
    raw[5] = access & 0xFF
    raw[6] = ((limit >> 16) & 0x0F) | (flags & 0xF0)
    raw[7] = (base >> 24) & 0xFF
    return bytes(raw)


class Args:
    def __init__(self, machine):
        self.machine = machine

    def __call__(self, n):
        uc = self.machine.uc
        sp = uc.reg_read(UC_X86_REG_SP)
        ss = uc.reg_read(UC_X86_REG_SS)
        return self.machine.word(ss, sp + 4 + n * 2)

    def string(self, n):
        return self.machine.string(self(n + 1), self(n))

    def regs(self, name):
        # A register contract's stub leaves DX alone. Other stubs load the ordinal into DX.
        return self.machine.uc.reg_read(REGISTERS[name])

    def word(self, sel, offset):
        return self.machine.word(sel, offset)


class Machine:
    def __init__(self, root, book=None):
        self.box = Sandbox(root).load()
        self.box.wine.book = Path(book) if book else None
        self.uc = None
        self.stop = ""
        self.calls = 0
        self.pending = None
        # Gate calls before the run stops on "call limit". A cap, like the instruction cap.
        self.call_limit = 400

    def _read(self, seg, offset, size):
        # Once the CPU runs, the guest's memory is the truth, not the loaded image.
        if self.uc is not None:
            return bytes(self.uc.mem_read(seg.base + offset, size))
        return bytes(seg.data[offset:offset + size])

    def word(self, sel, offset):
        seg = self.box.selectors.get(sel)
        if seg is None or offset + 2 > len(seg.data):
            return 0
        return struct.unpack("<H", self._read(seg, offset, 2))[0]

    def string(self, sel, offset):
        seg = self.box.selectors.get(sel)
        if seg is None or offset >= len(seg.data):
            return ""
        raw = self._read(seg, offset, min(128, len(seg.data) - offset))
        return raw.split(b"\x00", 1)[0].decode("latin1", "replace")

    def run(self, limit=1_000_000):
        exe = self.box.exe
        if exe is None:
            self.stop = "no executable"
            return self
        for image in [exe] + [img for img in self.box.images.values() if img is not exe]:
            if image.packed:
                # An iterated segment loads as zeros here. Running it executes empty memory.
                self.stop = (
                    f"packed image {Path(image.path).name}: {len(image.packed)} of {len(image.segments)} "
                    f"segments have the iterated flag, first is segment {image.packed[0]}. "
                    "neww does not unpack. --b must hold the unpacked images"
                )
                return self
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, 0x100000)
        self.uc.reg_write(UC_X86_REG_LDTR, (0, LDT_BASE, 0xFFFF, 0x82))
        flat = self._selector(0, 0xFFFF, 0x9A)
        for seg in self.box.selectors.values():
            size = max((max(len(seg.data), 1) + 0xFFF) & ~0xFFF, seg.room)
            self.uc.mem_map(seg.base, size)
            self.uc.mem_write(seg.base, bytes(seg.data))
            access = 0x92 if seg.flags & 1 else 0x9A
            limit_b = 0xFFFF if len(seg.data) >= 0x10000 else max(len(seg.data) - 1, 0)
            self._write_descriptor(seg.selector, _descriptor(seg.base, limit_b, access))
        self.box.wine.allocate = self._allocate
        self.box.wine.size = self._size
        self.box.wine.owner = self._owner
        self.box.wine.write = self._write_guest
        self.box.wine.read = self._read_guest
        self.box.wine.linear = self._linear
        self.box.wine.write_linear = lambda addr, data: self.uc.mem_write(addr, bytes(data))
        self.box.wine.read_linear = lambda addr, n: bytes(self.uc.mem_read(addr, n))
        self.box.wine.resize = self._resize
        self.box.wine.is_code = self._is_code
        self.box.wine.is_dll = self._is_dll
        self.box.wine.instance_of = self._instance_of
        self.box.wine.entry_point = self._entry_point
        self.box.wine.gate_address = self._gate_address
        self.box.wine.load_module = self._load_module
        self.box.wine.reference_module = lambda name: self._reference(self.box.images[name])
        self.box.wine.release_module = lambda name: self._release(self.box.images[name])
        self.box.wine.alloc_code = self._alloc_code
        self.box.wine.exe_name = exe.name
        self.uc.hook_add(UC_HOOK_INSN, self._out, None, 1, 0, UC_X86_INS_OUT)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        self.uc.hook_add(UC_HOOK_INTR, self._interrupt)
        # DOSVM_GetPMHandler16's default vectors: int16_sel:5 * n, one stub per interrupt.
        # Each is OUT 0EBh ; IRET here, so a call to one stops and names the interrupt.
        stubs = self._alloc_code(256 * 5)
        self.uc.mem_write(self.box.selectors[stubs].base, bytes([0xE6, 0xEB, 0xCF, 0x90, 0x90]) * 256)
        self.box.wine.int_stubs = stubs
        self._write_descriptor(INT_TAIL_SEL, _descriptor(INT_TAIL, 0xFF, 0x9A))
        self.uc.mem_write(INT_TAIL, bytes([
            0x2E, 0x8E, 0x06, 0x10, 0x00,   # mov es, cs:[10h]
            0x2E, 0x8E, 0x1E, 0x12, 0x00,   # mov ds, cs:[12h]
            0x2E, 0xFF, 0x2E, 0x14, 0x00,   # jmp far cs:[14h]
        ]))
        self.uc.mem_write(INT_TAIL + SWITCH_TAIL, bytes([
            0x2E, 0x8E, 0x16, 0x40, 0x00,   # mov ss, cs:[40h]
            0x2E, 0x8B, 0x26, 0x42, 0x00,   # mov sp, cs:[42h]
            0x2E, 0x8E, 0x1E, 0x44, 0x00,   # mov ds, cs:[44h]
            0x2E, 0x8E, 0x06, 0x46, 0x00,   # mov es, cs:[46h]
            0x2E, 0xFF, 0x2E, 0x48, 0x00,   # jmp far cs:[48h]
        ]))
        d = ENTRY32_DATA
        self.uc.mem_write(INT_TAIL + ENTRY32_TAIL, bytes([
            0x2E, 0x8E, 0x16, d, 0x00,              # mov ss, cs:[80h]
            0x66, 0x2E, 0x8B, 0x26, d + 2, 0x00,    # mov esp, cs:[82h]
            0x2E, 0x8E, 0x1E, d + 6, 0x00,          # mov ds, cs:[86h]
            0x2E, 0x8E, 0x06, d + 6, 0x00,          # mov es, cs:[86h]
            0x2E, 0x8E, 0x26, d + 8, 0x00,          # mov fs, cs:[88h]
            0x66, 0x2E, 0xFF, 0x2E, d + 10, 0x00,   # jmp far dword cs:[8Ah]
        ]))
        self.flat32 = None
        self.call32 = None
        self.moved = False
        self.box.wine.map_linear = self._map_linear
        self.box.wine.setup32 = self._setup32
        code = exe.segments[exe.entry_seg - 1]
        data = exe.segments[exe.auto - 1]
        psp = self._psp(self.box.wine.book.name if self.box.wine.book else "")
        self._modules()
        self.referenced = set()
        self._reference(self.box.exe)
        self._task()
        # Wine ne_module.c NE_StartTask: a moveable DGROUP's instance is its handle.
        instance = moveable_handle(data.selector) if data.flags & 0x0010 else data.selector
        self.initialized = set()
        names, rows, why = self._dlls_to_init(exe)
        self.box.wine.task = {
            "psp": psp, "instance": instance, "dgroup": data.selector,
            "dlls": names, "dll_init": rows, "dll_stop": why, "show": 1,
            "trampoline": self._trampoline(rows) if rows else None,
        }
        self.initialized = set(names)
        wine = self.box.wine
        first = tasks.Task(wine.htask, exe.name, wine.task, wine.modules[exe.name], instance, events=wine.events)
        wine.tasks = [first]
        wine.current = first
        wine.first_task = wine.htask
        wine.spawn = self._spawn
        wine.images = lambda: self.box.images
        # pop ds ; pop es ; retf: how a finished guest-call request returns to its caller.
        self.guest = []
        self.tramp_free = []
        self.tramp_retired = []
        self.hook_serial = 0
        tail_base = self.box.linear
        self.box.linear += 0x1000
        self.uc.mem_map(tail_base, 0x1000)
        self.uc.mem_write(tail_base, bytes([0x1F, 0x07, 0xCB]))
        self.tail = self._selector(tail_base, 2, 0x9A)
        self.pending = None
        gdtr_at = 0xF0E0
        self.uc.mem_write(gdtr_at, struct.pack("<HI", 0xFFFF, 0))
        self.uc.mem_write(0xF000, bytes([
            0x0F, 0x01, 0x16, gdtr_at & 0xFF, (gdtr_at >> 8) & 0xFF,
            0x66, 0x0F, 0x20, 0xC0, 0x66, 0x83, 0xC8, 0x01, 0x66, 0x0F, 0x22, 0xC0,
            0xEA, 0x20, 0xF0, flat & 0xFF, (flat >> 8) & 0xFF,
        ]))
        # Wine ne_module.c NE_StartTask: SP is the header's, or the stack segment's
        # minsize plus the NE stack size, made even. The stack sits below the local heap.
        sp, why = self._initial_sp(exe)
        if why:
            self.stop = why
            return self

        def word(value):
            return [value & 0xFF, (value >> 8) & 0xFF]

        # Registers at entry are NE_StartTask's: AX 0, BX stack size, CX heap size,
        # SI previous instance (none), DI this instance, BP 0, ES the PSP, DS and SS DGROUP.
        blob = bytes([
            0xB8, *word(data.selector), 0x8E, 0xD8, 0x8E, 0xD0,
            0xBC, *word(sp),
            0xB8, *word(psp), 0x8E, 0xC0,
            0xBB, *word(exe.stack), 0xB9, *word(exe.heap),
            0x31, 0xF6, 0xBF, *word(instance), 0x31, 0xED, 0x31, 0xC0,
            0xEA, exe.entry_ip & 0xFF, (exe.entry_ip >> 8) & 0xFF,
            code.selector & 0xFF, (code.selector >> 8) & 0xFF,
        ])
        self.uc.mem_write(0xF020, blob)
        self.uc.reg_write(UC_X86_REG_CS, 0)
        self.uc.reg_write(UC_X86_REG_IP, 0xF000)
        started = time.monotonic()
        try:
            self.uc.emu_start(0xF000, 0, timeout=TIMEOUT_US, count=limit)
        except UcError as exc:
            if not self.stop:
                self.stop = f"{exc} {self.where()}"
        else:
            if not self.stop:
                # There is no address to return to, so a quiet end is a cap.
                cs = self.uc.reg_read(UC_X86_REG_CS)
                ip = self.uc.reg_read(UC_X86_REG_IP)
                if time.monotonic() - started >= TIMEOUT_US / 1e6:
                    cap = f"{TIMEOUT_US // 1_000_000} second cap"
                else:
                    cap = f"instruction cap {limit:,}"
                self.stop = f"{cap} {self.where()} with no gate call pending, after {self.calls} calls"
        return self

    def where(self, cs=None, ip=None):
        """CS:IP, then the module, segment, and nearest export at or below it."""
        if cs is None:
            cs = self.uc.reg_read(UC_X86_REG_CS)
            ip = self.uc.reg_read(UC_X86_REG_IP)
        text = f"at {cs:#x}:{ip:#x}"
        seg = self.box.selectors.get(cs)
        for image in self.box.images.values():
            if image.synthetic or seg not in image.segments:
                continue
            text += f" in {image.name} segment {seg.index} +{ip:#x}"
            best = None
            for ordinal, ent in image.entries.items():
                if ent.segment == seg.index and ent.offset <= ip and (best is None or ent.offset > best[1].offset):
                    best = (ordinal, ent)
            if best:
                ordinal, ent = best
                name = image.names.get(ordinal, f"@{ordinal}")
                text += f", {name}+{ip - ent.offset:#x} (ordinal {ordinal})"
            break
        else:
            if seg is self.box.trap:
                text += " in the trap segment"
        return text

    def _initial_sp(self, image):
        """Wine ne_module.c NE_StartTask: SP is the header's, or the stack segment's minsize plus
        the NE stack size, made even. Returns (sp, stop)."""
        data = image.segments[image.auto - 1]
        sp = image.sssp & 0xFFFF
        if not sp:
            ss_seg = image.segments[(image.sssp >> 16) - 1] if image.sssp >> 16 else data
            sp = ss_seg.minsize + image.stack
        sp &= ~1
        if not 0 < sp <= len(data.data):
            return 0, f"stack top {sp:#x} is outside DGROUP ({len(data.data):#x} bytes)"
        return sp, None

    # ------------------------------------------------------------ tasks

    def _spawn(self, image, cmdline, show):
        """ne_module.c NE_CreateThread -> TASK_SpawnTask -> TASK_Create, then NE_StartTask's
        registers for the first time the task runs. Returns the Task, or a stop.

        A module handle (NE_RegisterModule puts it at the head of the list), a PDB with the
        command line, a TDB, the instance (the DGROUP made by NE_CreateSegment at load), the
        DLLs InitTask will initialize (those no task initialized yet), and one event posted.
        """
        wine = self.box.wine
        if any(t.alive and t.exe_name == image.name for t in wine.tasks):
            return (f"{image.name} is already running: LoadModule16 would make a second instance "
                    "(NE_CreateInstance), which neww does not do")
        if any(t.exe_name == image.name for t in wine.tasks):
            return f"{image.name} ran and ended: loading it again would need its segments reloaded, which neww does not do"
        if not image.auto or not image.entry_seg:
            return f"{image.name} has no DGROUP or no entry point"
        if image.name not in wine.modules:
            sel = self._allocate(0x60)
            wine.modules[image.name] = sel
            base = self.box.selectors[sel].base
            self.uc.hook_add(UC_HOOK_MEM_READ, self._module_read, (image.name, base), base, base + 0x5F)
            wine.first_module = sel
        module = wine.modules[image.name]
        psp = self._psp(cmdline)
        htask = self._task_block()
        data = image.segments[image.auto - 1]
        code = image.segments[image.entry_seg - 1]
        instance = moveable_handle(data.selector) if data.flags & 0x0010 else data.selector
        sp, why = self._initial_sp(image)
        if why:
            return why
        names, rows, why = self._dlls_to_init(image)
        task = {
            "psp": psp, "instance": instance, "dgroup": data.selector,
            "dlls": names, "dll_init": rows, "dll_stop": why, "show": show,
            "trampoline": self._trampoline(rows) if rows else None,
        }
        self.initialized |= set(names)
        # PostEvent16(hTask) in NE_CreateThread: the startup WaitEvent(0) takes it.
        child = tasks.Task(htask, image.name, task, module, instance, events=1)
        # NE_StartTask: AX 0, BX stack size, CX heap size, SI previous instance (none),
        # DI the instance, BP 0, ES the PSP, DS = SS = DGROUP. IF is set.
        child.context = {
            "ax": 0, "bx": image.stack, "cx": image.heap, "dx": 0, "si": 0, "di": instance, "bp": 0,
            "sp": sp, "ss": data.selector, "ds": data.selector, "es": psp,
            "cs": code.selector, "ip": image.entry_ip, "eflags": 0x0202,
            "fpcw": self.uc.reg_read(UC_X86_REG_FPCW),
        }
        wine.tasks.append(child)
        self._reference(image)
        # TASK_LinkTask: the new task goes in before the tasks of its priority, so it is first.
        wine.first_task = htask
        return child

    def _capture(self, uc):
        ctx = {name: uc.reg_read(REGISTERS[name]) for name in TASK_REGISTERS}
        for name in ("sp", "ss", "ds", "es"):
            ctx[name] = uc.reg_read(REGISTERS[name])
        ctx["eflags"] = uc.reg_read(UC_X86_REG_EFLAGS)
        return ctx

    def _switch(self, uc, cs, ordinal, switch, ax, dx):
        """Save the current task at the gate stub and run switch.task. "retry" resumes at the
        stub's first byte, so the call runs again; "answer" at its retf, with DX:AX."""
        wine = self.box.wine
        cur = wine.current
        ctx = self._capture(uc)
        ctx["cs"] = cs
        if switch.kind == "retry":
            ctx["ip"] = ordinal * 8
        else:
            ctx["ip"] = ordinal * 8 + 5
            ctx["answer"] = switch.answer if switch.answer is not None else (ax, dx)
        cur.context = ctx
        cur.wait = switch.wait
        if switch.call is not None:
            self._inject(uc, switch.task, switch.call, switch.done)
            return
        self._resume(uc, switch.task, retf=True)

    def _to_tail(self, uc):
        """From a gate's OUT: the stub's retf goes to the switch tail (see _resume)."""
        ss, sp = uc.reg_read(UC_X86_REG_SS), uc.reg_read(UC_X86_REG_SP)
        self._write_guest(ss, (sp - 4) & 0xFFFF, struct.pack("<HH", SWITCH_TAIL, INT_TAIL_SEL))
        uc.reg_write(UC_X86_REG_SP, (sp - 4) & 0xFFFF)

    def _inject(self, uc, task, call, done):
        """Run one call in a waiting task, on its stack below where it waits, from a trampoline.
        Its OUT 0E8h hands the result to done(ax, dx), puts the task back where it waited, and
        runs the task done returns (_sent_result)."""
        wine = self.box.wine
        self._to_tail(uc)
        saved, wait = task.context, task.wait
        tasks.swap(wine, task)
        task.context = None
        task.wait = None
        self.hook_serial += 1
        ident = len(self.guest)
        self.guest.append({"sent": (task, saved, wait, done), "done": False})
        sel = self._trampoline_for(call, ident)
        for name in ("bp", "si", "di"):
            uc.reg_write(REGISTERS[name], saved[name])
        uc.reg_write(UC_X86_REG_EFLAGS, saved["eflags"])
        uc.mem_write(INT_TAIL + SWITCH_DATA, struct.pack(
            "<HHHHHH", saved["ss"], saved["sp"], saved["ds"], saved["es"], 0, sel))
        wine.trace.append(f"-- task {task.exe_name} {task.htask:#x}, for a sent message")

    def _sent_result(self, uc, state):
        state["done"] = True
        self.hook_serial += 1
        self.tramp_retired.append((state["slots"].pop(), self.hook_serial))
        task, saved, wait, done = state["sent"]
        ax, dx = uc.reg_read(UC_X86_REG_AX), uc.reg_read(UC_X86_REG_DX)
        nxt = done(ax, dx)
        self.box.wine.trace.append(f"  <- reply {dx << 16 | ax:#x}")
        # The task goes back to waiting where it was.
        task.context, task.wait = saved, wait
        self._resume(uc, nxt, retf=True)

    def _resume(self, uc, task, retf):
        """Load a task's saved registers, then go to the switch tail, which loads SS:SP, DS and
        ES through the CPU and jumps to the task's CS:IP.

        From an INT hook a write of CS:IP takes effect. From a gate's OUT it does not, as the
        stub's next instruction address is fixed, so the stub's retf goes there instead: a far
        pointer to the tail under the old task's SP, which its saved context does not include.
        """
        wine = self.box.wine
        if retf:
            self._to_tail(uc)
        tasks.swap(wine, task)
        ctx = dict(task.context)
        task.context = None
        task.wait = None
        answer = ctx.pop("answer", None)
        if callable(answer):
            answer = answer()
        if answer is not None:
            ctx["ax"], ctx["dx"] = answer[0] & 0xFFFF, answer[1] & 0xFFFF
        for name in TASK_REGISTERS:
            uc.reg_write(REGISTERS[name], ctx[name])
        uc.reg_write(UC_X86_REG_EFLAGS, ctx["eflags"])
        uc.mem_write(INT_TAIL + SWITCH_DATA, struct.pack(
            "<HHHHHH", ctx["ss"], ctx["sp"], ctx["ds"], ctx["es"], ctx["ip"], ctx["cs"]))
        if not retf:
            uc.reg_write(UC_X86_REG_CS, INT_TAIL_SEL)
            uc.reg_write(UC_X86_REG_IP, SWITCH_TAIL)
        wine.trace.append(f"-- task {task.exe_name} {task.htask:#x}")

    def _exit_task(self, uc, code, retf=False):
        """INT 21h AH=4Ch in a task: Wine's ExitThread -> TASK_ExitTask. The first task's exit
        ends the run, as before. Another task's ends that task: its queue and timers go, its
        module's count drops (NE_FreeModule frees it at 0), and another task runs."""
        wine = self.box.wine
        cur = wine.current
        if cur is wine.tasks[0] or len(wine.tasks) < 2:
            wine.exit = code
            self.stop = f"dos exit {code:#x}"
            uc.emu_stop()
            return
        from .user_wnd import wm
        m = wm(wine)
        left = [w.hwnd for w in m.windows.values() if w.task == cur.htask and not w.destroyed]
        if left:
            self.stop = (f"{cur.exe_name} exits with {len(left)} windows ({left[0]:#x} first): Wine's "
                         "WIN_DestroyThreadWindows destroys them, which neww does not do yet")
            uc.emu_stop()
            return
        wine.exit = code
        cur.alive = False
        m.queues.pop(cur.htask, None)
        # TASK_ExitTask frees the task's module: NE_FreeModule, which frees what it imported.
        exe_image = next((img for img in self.box.images.values() if img.name == cur.exe_name), None)
        if exe_image is not None:
            wine.usage[cur.module] = 1
            self._release(exe_image)
        wine.usage[cur.module] = 0
        wine.modules.pop(cur.exe_name, None)
        if wine.first_module == cur.module:
            wine.first_module = wine.modules[wine.tasks[0].exe_name]
        if wine.first_task == cur.htask:
            wine.first_task = next((t.htask for t in reversed(wine.tasks) if t.alive), 0)
        wine.trace.append(f"-- task {cur.exe_name} {cur.htask:#x} exits {code:#x}")
        nxt = tasks.next_ready(wine)
        if nxt is None:
            found = tasks.earliest_timer(wine, include_current=False)
            if found is not None:
                m.clock = max(m.clock, found[0])
                nxt = found[1]
        if nxt is None:
            self.stop = f"{cur.exe_name} exited {code:#x}, and every other task waits for input, and neww has none"
            uc.emu_stop()
            return
        self._resume(uc, nxt, retf)

    def _is_code(self, sel):
        """selector.c IsBadCodePtr16's test, (ldt_get_bits(sel).type & 0x18) == 0x18: the
        descriptor is a code segment. That covers a module's code segments, and the blocks
        neww allocates as code (MakeProcInstance thunks, procedure thunks), as Wine's are."""
        if self.box.selectors.get(sel) is None:
            return False
        access = self.uc.mem_read((sel & ~7) + 5, 1)[0]
        return access & 0x18 == 0x18

    def _alloc_code(self, size):
        """A code block: one segment, readable and executable, in the selector table."""
        span = (size + 0xFFF) & ~0xFFF
        base = self.box.linear
        self.box.linear += span
        self.uc.mem_map(base, span)
        seg = Segment(0, 0, bytearray(size))
        sel = self.box._selector()
        seg.selector = sel
        seg.base = base
        self.box.selectors[sel] = seg
        self._write_descriptor(sel, _descriptor(base, size - 1, 0x9A))
        return sel

    def _load_module(self, base):
        """LoadLibrary of an NE file in --b that has no module handle yet. Returns the handle and
        the LibMain calls, the DLLs it imports first (NE_InitializeDLLs order), each once."""
        image = next((img for img in self.box.images.values()
                      if not img.synthetic and Path(img.path).name.upper() == base.upper()), None)
        if image is None:
            image = self.box.images.get(base.rsplit(".", 1)[0].upper())
        if image is None or image.synthetic:
            return None, []
        calls = []
        seen = set()

        def visit(img):
            # NE_InitializeDLLs clears dlls_to_init before it walks them, so a cycle of
            # imports (A imports B, B imports A) visits each module once.
            if img.name in seen:
                return
            seen.add(img.name)
            for dep in img.modules:
                other = self.box.images.get(dep)
                if other is None or other.synthetic or other is self.box.exe:
                    continue
                visit(other)
            if img.name not in self.box.wine.modules:
                sel = self._allocate(0x60)
                self.box.wine.modules[img.name] = sel
                self.box.wine.first_module = sel
            if img.name in self.initialized or img is self.box.exe:
                return
            self.initialized.add(img.name)
            if img.entry_seg and img.flags & 0x8000 and img.flags & 0x0001 and img.auto:
                seg = img.segments[img.auto - 1]
                inst = moveable_handle(seg.selector) if seg.flags & 0x0010 else seg.selector
                code = img.segments[img.entry_seg - 1]
                call = Call(code.selector, img.entry_ip, frame=True, regs={
                    "cx": img.heap, "di": inst, "ds": seg.selector, "es": seg.selector,
                    "ax": 0, "bx": 0, "dx": 0, "si": 0,
                })
                call.name = img.name
                calls.append(call)

        visit(image)
        self._reference(image)
        return self.box.wine.modules[image.name], calls

    def _gate_address(self, module, ordinal):
        image = self.box.images.get(module)
        if image is None or not image.synthetic:
            return None
        offset = getattr(image, "variables", {}).get(ordinal)
        if offset is not None:
            # A variable export: GetProcAddress16 answers its address in the module's data.
            return image.segments[1].selector, offset
        seg = image.segments[0]
        if (seg.selector, ordinal) not in self.box.gates:
            return None
        return seg.selector, ordinal * 8

    def _image_at(self, path):
        for image in self.box.images.values():
            if not image.synthetic and image.path == path:
                return image
        return None

    def _instance_of(self, path):
        """NE_GetInstance: the DGROUP's handle (moveable handle if DGROUP is moveable), else 0."""
        image = self._image_at(path)
        if image is None or not image.auto:
            return 0
        seg = image.segments[image.auto - 1]
        return moveable_handle(seg.selector) if seg.flags & 0x0010 else seg.selector

    def _entry_point(self, path, name):
        """NE_GetOrdinal and NE_GetEntryPoint over the loaded image: (selector, offset) or None."""
        image = self._image_at(path)
        if image is None:
            return None
        ordinal = name
        if isinstance(name, str):
            want = name.upper()
            ordinal = next((o for o, n in image.names.items() if n.upper() == want), None)
            if ordinal is None:
                return None
        ent = image.entries.get(ordinal)
        if ent is None or not 1 <= ent.segment <= len(image.segments):
            return None
        return image.segments[ent.segment - 1].selector, ent.offset

    def _is_dll(self, path):
        for image in self.box.images.values():
            if not image.synthetic and image.path == path:
                return bool(image.flags & 0x8000)
        return False

    def _resize(self, sel, size, oldsize):
        """GlobalReAlloc's move: a new linear block of size, the old bytes copied, the selector's
        descriptor pointed at it. A block that needs more selectors than it has stops."""
        seg = self.box.selectors.get(sel)
        if seg is None:
            return "not a block"
        if size > 0x10000 or oldsize > 0x10000:
            return "a block over 64K would need its selector tiles moved, which neww does not do"
        if size <= getattr(seg, "room", 0):
            # Room reserved at this base: the block grows or shrinks where it is.
            if size > len(seg.data):
                self.uc.mem_write(seg.base + len(seg.data), bytes(size - len(seg.data)))
            seg.data = bytearray(size)
            self._write_descriptor(sel & ~7, _descriptor(seg.base, size - 1, 0x92))
            return None
        data = self._read(seg, 0, min(len(seg.data), size))
        # A segment register holding this selector keeps the old base until it is loaded
        # again. Wine's 16-bit relay loads DS and ES from its frame on the way back; the gate
        # does too, through the INT tail (_out).
        self.moved = True
        span = (size + 0xFFF) & ~0xFFF
        base = self.box.linear
        self.box.linear += span
        self.uc.mem_map(base, span)
        self.uc.mem_write(base, data)
        seg.base = base
        seg.room = span
        seg.data = bytearray(size)
        self._write_descriptor(sel & ~7, _descriptor(base, size - 1, 0x92))
        return None

    def _linear(self, sel):
        """The linear base of a selector's block, or None. A huge block's tiles follow it in order."""
        seg = self.box.selectors.get(sel)
        return seg.base if seg is not None else None

    def _read_guest(self, sel, offset, size):
        """size bytes at sel:offset, b"" when sel is no block. Reads across a huge block's tiles."""
        seg = self.box.selectors.get(sel)
        if seg is None or size <= 0:
            return b""
        try:
            return bytes(self.uc.mem_read(seg.base + offset, size))
        except UcError:
            return b""

    def _write_guest(self, sel, offset, data):
        seg = self.box.selectors.get(sel)
        if seg is None or offset + len(data) > len(seg.data):
            return
        self.uc.mem_write(seg.base + offset, data)

    def _owner(self, sel):
        """The NE file a selector's block belongs to, as GetExePtr finds a module from a handle.

        A segment of the file, or its module handle.
        """
        for image in self.box.images.values():
            if image.synthetic:
                continue
            if any(seg.selector == sel for seg in image.segments) or self.box.wine.modules.get(image.name) == sel:
                return image.path
        return None

    def _modules(self):
        """A module handle per NE file, in Wine's load order: the executable, then each DLL as loaded.

        Wine's handle is the selector of the NE_MODULE block build_module makes. neww makes
        the block but not its contents, so a guest read of it stops.
        """
        order = [self.box.exe]
        seen = set()

        def walk(image):
            for name in image.modules:
                dll = self.box.images.get(name)
                if dll is None or dll.synthetic or dll is self.box.exe or name in seen:
                    continue
                seen.add(name)
                order.append(dll)
                walk(dll)

        walk(self.box.exe)
        for image in order:
            sel = self._allocate(0x60)
            self.box.wine.modules[image.name] = sel
            base = self.box.selectors[sel].base
            self.uc.hook_add(UC_HOOK_MEM_READ, self._module_read, (image.name, base), base, base + 0x5F)
        # The gate modules get module handles too, as Wine's builtins have NE_MODULEs.
        for image in self.box.images.values():
            if image.synthetic and image.name in SYSTEM:
                self.box.wine.system_modules[image.name] = self._allocate(0x60)
        # NE_RegisterModule puts each new module at the head of the list.
        self.box.wine.first_module = self.box.wine.modules[order[-1].name]

    def _reference(self, image):
        """A module's count, as Wine keeps it: NE_LoadModule gives a newly loaded module 1, and
        NE_LoadDLLs adds 1 to each module it imports that is already loaded, or loads it (1),
        and so on down. LoadLibrary16 of a loaded module adds 1 as well (NE_LoadModule's
        "second instance"). GetModuleUsage16 answers the count."""
        wine = self.box.wine
        handle = wine.modules.get(image.name)
        if image.name in self.referenced:
            if handle is not None:
                wine.usage[handle] = wine.usage.get(handle, 1) + 1
            return
        self.referenced.add(image.name)
        if handle is not None:
            wine.usage[handle] = 1
        for name in image.modules:
            dll = self.box.images.get(name)
            if dll is None or dll.synthetic:
                continue
            self._reference(dll)

    def _release(self, image):
        """NE_FreeModule: 1 less; at 0 Wine unloads the module and frees what it imported.
        Returns the count left."""
        wine = self.box.wine
        handle = wine.modules.get(image.name)
        if handle is None:
            return 1
        left = wine.usage.get(handle, 1) - 1
        wine.usage[handle] = max(left, 0)
        if left <= 0:
            self.referenced.discard(image.name)
            for name in image.modules:
                dll = self.box.images.get(name)
                if dll is not None and not dll.synthetic and dll.name in self.referenced:
                    self._release(dll)
        return left

    def _task(self):
        """The first task's handle. The exe's task is linked after the main task at the same
        priority, so TASK_LinkTask puts it first, and it is hFirstTask too."""
        self.box.wine.htask = self._task_block()

    def _task_block(self):
        """A task handle: Wine TASK_Create's GlobalAlloc16(GMEM_FIXED, sizeof(TDB)), 0x200 bytes.
        neww makes the block but not the TDB in it."""
        sel = self._allocate(0x200)
        base = self.box.selectors[sel].base
        self.uc.hook_add(UC_HOOK_MEM_READ, self._task_read, base, base, base + 0x1FF)
        return sel

    def _task_read(self, uc, access, address, size, value, base):
        if self.stop:
            return
        self.stop = (
            f"task database read at +{address - base:#x} {self.where()}: "
            "Wine's TDB is filled by TASK_Create, and neww has only the handle"
        )
        uc.emu_stop()

    def _size(self, sel):
        """GlobalSize16 of the block behind a selector."""
        seg = self.box.selectors.get(sel)
        return len(seg.data) if seg is not None else None

    def _allocate(self, size):
        """Map size bytes behind consecutive data selectors, 64K apart in linear memory.

        Returns the first selector. Selector i covers base + i * 0x10000, the
        __AHINCR tiling Wine's SELECTOR_AllocBlock gives a block over 64K.
        """
        span = (size + 0xFFF) & ~0xFFF
        base = self.box.linear
        self.box.linear += span
        self.uc.mem_map(base, span)
        first = None
        for i in range((size + 0xFFFF) // 0x10000):
            left = size - i * 0x10000
            seg = Segment(0, 1, bytearray(min(left, 0x10000)))
            sel = self.box._selector()
            seg.selector = sel
            seg.base = base + i * 0x10000
            self.box.selectors[sel] = seg
            self._write_descriptor(sel, _descriptor(seg.base, left - 1, 0x92))
            first = sel if first is None else first
        return first

    def _dlls_to_init(self, exe):
        """ToolBook DLLs an executable loads, with init code, in Wine NE_InitializeDLLs order.
        A DLL another task already initialized is not initialized again.

        Returns (names, rows, stop). A row is (name, cs, ip, ds, heap, instance), the
        registers ne_segment.c NE_InitDLL and NE_GetDLLInitParams give LibMain.
        """
        names, seen = [], set()

        def walk(image):
            for name in image.modules:
                dll = self.box.images.get(name)
                # System modules are gates, not DLLs neww loaded.
                if dll is None or dll is exe or name in seen or name in SYSTEM or dll.synthetic:
                    continue
                seen.add(name)
                walk(dll)
                # NE_InitDLL: only a library with an entry point is called.
                if dll.entry_seg and dll.flags & 0x8000 and name not in self.initialized:
                    names.append(name)

        walk(exe)
        rows = []
        for name in names:
            dll = self.box.images[name]
            if not (dll.flags & 0x0001 and dll.auto):
                return names, [], (
                    f"KERNEL.91 InitTask: {name} has no SINGLEDATA DGROUP, so Wine NE_GetDLLInitParams "
                    "passes its module handle in DI. neww has no module handles"
                )
            seg = dll.segments[dll.auto - 1]
            instance = moveable_handle(seg.selector) if seg.flags & 0x0010 else seg.selector
            code = dll.segments[dll.entry_seg - 1]
            rows.append((name, code.selector, dll.entry_ip, seg.selector, dll.heap, instance))
        return names, rows, None

    def _trampoline(self, rows):
        """Code that calls each LibMain with Wine NE_InitDLL's registers, then OUT 0xE6.

        CX heap, DI instance, DS = ES = the DLL's DGROUP, the rest 0. Wine points BP at
        the saved BP in its relay frame. Here BP points at the caller's BP, pushed.
        """
        code = bytearray()
        for _name, cs, ip, ds, heap, instance in rows:
            code += bytes([0xB9, heap & 0xFF, heap >> 8, 0xBF, instance & 0xFF, instance >> 8])
            code += bytes([0xB8, ds & 0xFF, ds >> 8, 0x8E, 0xD8, 0x8E, 0xC0])
            code += bytes([0x31, 0xC0, 0x31, 0xDB, 0x31, 0xD2, 0x31, 0xF6])
            code += bytes([0x55, 0x89, 0xE5, 0x9A, ip & 0xFF, ip >> 8, cs & 0xFF, cs >> 8, 0x5D])
        # OUT 0xE6, then pop es ; pop ds ; retf from the frame _dlls_done builds.
        code += bytes([0xE6, 0xE6, 0x07, 0x1F, 0xCB])
        base = self.box.linear
        self.box.linear += 0x1000
        self.uc.mem_map(base, 0x1000)
        self.uc.mem_write(base, bytes(code))
        return self._selector(base, len(code) - 1, 0x9A)

    # ------------------------------------------------------------ guest calls

    REG_MOV = {"ax": 0xB8, "cx": 0xB9, "dx": 0xBA, "bx": 0xBB, "si": 0xBE, "di": 0xBF}

    def _call_code(self, call, ident):
        """One call of a trampoline, ending in mov cx, ident ; out 0E8h."""
        code = bytearray()
        for seg_reg, op in (("ds", 0xD8), ("es", 0xC0)):
            if seg_reg in call.regs:
                v = call.regs[seg_reg] & 0xFFFF
                code += bytes([0xB8, v & 0xFF, v >> 8, 0x8E, op])
        for word in call.words:
            code += bytes([0x68, word & 0xFF, (word >> 8) & 0xFF])
        for name in ("ax", "bx", "cx", "dx", "si", "di"):
            if name in call.regs:
                v = call.regs[name] & 0xFFFF
                code += bytes([self.REG_MOV[name], v & 0xFF, v >> 8])
        if call.frame:
            code += bytes([0x55, 0x89, 0xE5])
        code += bytes([0x9A, call.ip & 0xFF, call.ip >> 8, call.cs & 0xFF, call.cs >> 8])
        if call.frame:
            code += bytes([0x5D])
        code += bytes([0xB9, ident & 0xFF, ident >> 8, 0xE6, 0xE8, 0xCB])
        return code

    # Trampoline slots: TRAMP_SLOT bytes each, with a selector of their own, reused.
    TRAMP_SLOT = 0x200
    TRAMP_BLOCK = 0x10000

    def _trampoline_for(self, call, ident):
        """A code block that makes one call and reports it.

        A slot is taken back once its call has returned and the hook that saw OUT 0E8h has
        ended, because the trampoline's retf still runs after that OUT.
        """
        code = self._call_code(call, ident)
        if len(code) > self.TRAMP_SLOT:
            raise ValueError(f"trampoline of {len(code)} bytes")
        serial = self.hook_serial
        keep = []
        for slot, retired in self.tramp_retired:
            if retired < serial:
                self.tramp_free.append(slot)
            else:
                keep.append((slot, retired))
        self.tramp_retired = keep
        if not self.tramp_free:
            base = self.box.linear
            self.box.linear += self.TRAMP_BLOCK
            self.uc.mem_map(base, self.TRAMP_BLOCK)
            for off in range(0, self.TRAMP_BLOCK, self.TRAMP_SLOT):
                self.tramp_free.append((self._selector(base + off, self.TRAMP_SLOT - 1, 0x9A), base + off))
        sel, base = self.tramp_free.pop()
        self.uc.mem_write(base, bytes(code))
        # Unicorn keeps translated code by address: a reused slot must not run the old call.
        self.uc.ctl_remove_cache(base, base + self.TRAMP_SLOT)
        self.guest[ident].setdefault("slots", []).append((sel, base))
        return sel

    def _start_guest(self, uc, request, pop):
        """The gate answered with a GuestCalls. Its retf (pop bytes) goes to the first call's
        trampoline instead of the caller."""
        self.hook_serial += 1
        ss = uc.reg_read(UC_X86_REG_SS)
        sp = uc.reg_read(UC_X86_REG_SP)
        ident = len(self.guest)
        self.guest.append({
            "request": request, "ss": ss, "after_sp": sp + 4 + pop, "ret": self._read(self.box.selectors[ss], sp, 4),
            "ds": uc.reg_read(UC_X86_REG_DS), "es": uc.reg_read(UC_X86_REG_ES), "bp": uc.reg_read(UC_X86_REG_BP),
            "si": uc.reg_read(UC_X86_REG_SI), "di": uc.reg_read(UC_X86_REG_DI),
            "queue": list(request.calls), "results": [], "done": False,
        })
        self._next_guest(uc, ident, sp, pop)

    def _next_guest(self, uc, ident, sp=None, pop=None):
        state = self.guest[ident]
        call = state["queue"].pop(0)
        sel = self._trampoline_for(call, ident)
        if sp is not None:
            # Replace the gate's return address: its retf lands on the trampoline.
            self._write_guest(state["ss"], sp, struct.pack("<HH", 0, sel))
        else:
            # From OUT 0E8h: the trampoline's retf takes this far pointer, with SP back where
            # the gate's retf left it.
            self._write_guest(state["ss"], state["after_sp"] - 4, struct.pack("<HH", 0, sel))
            uc.reg_write(UC_X86_REG_SP, state["after_sp"] - 4)

    def _guest_result(self, uc):
        """OUT 0E8h: one guest call returned. Run the next, or finish the request."""
        ident = uc.reg_read(UC_X86_REG_CX)
        if ident >= len(self.guest) or self.guest[ident]["done"]:
            self.stop = f"out 0xe8 for no pending guest call {self.where()}"
            uc.emu_stop()
            return
        state = self.guest[ident]
        if "sent" in state:
            self._sent_result(uc, state)
            return
        self.hook_serial += 1
        slot = state["slots"].pop()
        self.tramp_retired.append((slot, self.hook_serial))
        ax, dx = uc.reg_read(UC_X86_REG_AX), uc.reg_read(UC_X86_REG_DX)
        index = len(state["results"])
        state["results"].append((ax, dx))
        request = state["request"]
        if uc.reg_read(UC_X86_REG_SS) != state["ss"]:
            self.stop = f"guest call returned on another stack segment {self.where()}"
            uc.emu_stop()
            return
        if request.after is not None:
            more = request.after(index, ax, dx)
            if isinstance(more, str):
                self.stop = more
                uc.emu_stop()
                return
            if more:
                state["queue"][0:0] = list(more)
        if state["queue"]:
            self._next_guest(uc, ident)
            return
        state["done"] = True
        out = request.finish(state["results"])
        if len(out) == 3 and out[2]:
            self.stop = out[2]
            uc.emu_stop()
            return
        # Back to the original caller: the registers a Pascal callee keeps (DS, ES, SI, DI, BP),
        # the answer in DX:AX, and SP past the popped arguments. The trampoline's retf goes to
        # the tail, which pops DS and ES and returns.
        uc.reg_write(UC_X86_REG_AX, out[0] & 0xFFFF)
        uc.reg_write(UC_X86_REG_DX, out[1] & 0xFFFF)
        for name in ("bp", "si", "di"):
            uc.reg_write(REGISTERS[name], state[name])
        sp = state["after_sp"] - 12
        frame = struct.pack("<HHHH", 0, self.tail, state["ds"], state["es"]) + state["ret"]
        self._write_guest(state["ss"], sp, frame)
        uc.reg_write(UC_X86_REG_SP, sp)

    def _dlls_done(self, uc):
        """OUT 0xE6: every LibMain returned. Answer InitTask and return to its caller."""
        saved = self.pending
        self.pending = None
        if saved is None:
            self.stop = f"out 0xe6 with no InitTask pending {self.where()}"
            uc.emu_stop()
            return
        if uc.reg_read(UC_X86_REG_SS) != saved["ss"]:
            self.stop = f"LibMain returned on another stack segment {self.where()}"
            uc.emu_stop()
            return
        ax, dx, _why = self.box.wine.init_task_answer(self.word)
        registers = dict(self.box.wine.registers)
        registers.pop("push")
        es = registers.pop("es")
        uc.reg_write(UC_X86_REG_AX, ax)
        uc.reg_write(UC_X86_REG_DX, dx)
        for name, value in registers.items():
            uc.reg_write(REGISTERS[name], value & 0xFFFF)
        uc.reg_write(UC_X86_REG_BP, saved["bp"])
        # The guest pops ES and the caller's DS, then the retf returns to the caller with
        # one zero word pushed, as InitTask16's stack16_push leaves it.
        sp = saved["sp"]
        frame = struct.pack("<HH", es, saved["ds"]) + saved["ret"] + b"\x00\x00"
        self._write_guest(saved["ss"], sp - 6, frame)
        uc.reg_write(UC_X86_REG_SP, sp - 6)

    def _psp(self, cmdline):
        """The task's PDB16, as Wine task.c TASK_Create fills it. Returns its selector."""
        sel = self._allocate(PSP_SIZE)
        pdb = bytearray(PSP_SIZE)
        struct.pack_into("<H", pdb, 0x00, 0x20CD)
        pdb[0x18:0x2C] = b"\xFF" * 20
        struct.pack_into("<H", pdb, 0x32, 20)
        struct.pack_into("<HH", pdb, 0x34, 0x18, sel)
        # TASK_Create: environment = SELECTOROF(GetDOSEnvironment16()).
        struct.pack_into("<H", pdb, 0x2C, self._environment())
        # The command line is what follows the program name: for the first task the book from
        # --c, by name; for one WinExec started, what followed the file name.
        line = cmdline.encode("latin1", "replace")[:127]
        pdb[0x80] = len(line)
        pdb[0x81:0x81 + len(line)] = line
        self._write_guest(sel, 0, bytes(pdb))
        base = self.box.selectors[sel].base
        for start, end, _what in PSP_UNFILLED:
            self.uc.hook_add(UC_HOOK_MEM_READ, self._psp_read, (base, start, end), base + start, base + end - 1)
        return sel

    def _environment(self):
        """The DOS environment block, a GMEM_FIXED block whose handle is its selector."""
        if self.box.wine.environment is None:
            block = b"".join(text + b"\x00" for text in ENV_STRINGS) + b"\x00" + struct.pack("<H", 1) + ENV_PROGRAM_NAME
            sel = self._allocate((len(block) + 0x1F) & ~0x1F)
            self._write_guest(sel, 0, block)
            self.box.wine.environment = sel
        return self.box.wine.environment

    def _module_read(self, uc, access, address, size, value, user):
        name, base = user
        if self.stop:
            return
        self.stop = (
            f"module database of {name} read at +{address - base:#x} {self.where()}: "
            "Wine's NE_MODULE block is built by build_module, and neww has only the handle"
        )
        uc.emu_stop()

    def _psp_read(self, uc, access, address, size, value, user):
        base, start, end = user
        if self.stop or not (base + start <= address < base + end):
            return
        what = next(text for s, e, text in PSP_UNFILLED if s == start)
        self.stop = f"PSP {what}, read {self.where()}: neww has nothing to put there"
        uc.emu_stop()

    def _selector(self, base, limit, access):
        sel = self.box._selector()
        self._write_descriptor(sel, _descriptor(base, limit, access))
        return sel

    def _write_descriptor(self, sel, descriptor):
        """The GDT entry, and the same entry in the LDT, so a moveable handle loads as its selector."""
        self.uc.mem_write(sel, descriptor)
        self.uc.mem_write(LDT_BASE + sel, descriptor)

    def _out(self, uc, port, size, value, user):
        if port == 0xE6:
            self._dlls_done(uc)
            return
        if port == 0xE8:
            self._guest_result(uc)
            return
        if port == 0xEC:
            self._return32(uc)
            return
        if port == 0xED:
            self._import32(uc)
            return
        if port == 0xEB:
            n = (uc.reg_read(UC_X86_REG_IP) - 2) // 5
            self.stop = (f"INT {n:#x}: the guest called the default vector DOSVM_GetPMHandler16 gave it, "
                         "Wine's builtin handler stub, which neww does not run")
            uc.emu_stop()
            return
        if port == 0xE5:
            slot = uc.reg_read(UC_X86_REG_DX)
            traps = self.box.traps
            text = traps[slot] if slot < len(traps) else f"trap {slot}"
            self.stop = f"not linked: {text}. A ToolBook call with no target is a stop, not a gate"
            uc.emu_stop()
            return
        if port not in (0xE4, 0xE7):
            return
        cs = uc.reg_read(UC_X86_REG_CS)
        if port == 0xE7:
            # A register contract's stub: the OUT is the stub's first instruction.
            ordinal = uc.reg_read(UC_X86_REG_IP) // 8
        else:
            ordinal = uc.reg_read(UC_X86_REG_DX)
        module = self.box.gates.get((cs, ordinal))
        if module is None:
            self.stop = f"out {cs:#x} dx={ordinal:#x}"
            uc.emu_stop()
            return
        self.calls += 1
        self.box.wine.registers = None
        ax, dx, why = self.box.wine.answer(module, ordinal, Args(self))
        if self.box.wine.usable(module, ordinal) is None:
            # No usable contract: stop on the OUT. Nothing is popped, AX and DX keep the guest's values.
            self.stop = why
            uc.emu_stop()
            return
        if why:
            # A stop answers nothing. The guest's registers stay as the call left them.
            self.stop = why
            uc.emu_stop()
            return
        registers = dict(self.box.wine.registers or {})
        if "exit_task" in registers:
            self._exit_task(uc, registers["exit_task"], retf=True)
            return
        if "call32" in registers:
            row = self.box.wine.usable(module, ordinal)
            if self.box.slots.get((module, ordinal)) is not None:
                self.stop = f"{module}.{ordinal}: a register contract cannot call 32-bit code"
                uc.emu_stop()
                return
            self._start32(uc, registers["call32"], row.pop)
            return
        if "switch" in registers:
            if self.box.slots.get((module, ordinal)) is not None:
                self.stop = f"{module}.{ordinal}: a register contract cannot switch tasks"
                uc.emu_stop()
                return
            self._switch(uc, cs, ordinal, registers["switch"], ax, dx)
            if self.calls > self.call_limit:
                self.stop = "call limit"
                uc.emu_stop()
            return
        uc.reg_write(UC_X86_REG_AX, ax & 0xFFFF)
        slot = self.box.slots.get((module, ordinal))
        if slot is None:
            uc.reg_write(UC_X86_REG_DX, dx & 0xFFFF)
        if slot is not None:
            # A register contract sets DX only when it names it.
            # The stub's tail loads ES and DS from these words. Unchanged unless the contract sets them.
            es = registers.pop("es", uc.reg_read(UC_X86_REG_ES))
            ds = registers.pop("ds", uc.reg_read(UC_X86_REG_DS))
            self._write_guest(cs, slot, struct.pack("<HH", es, ds))
        request = registers.pop("guest", None)
        if isinstance(request, GuestCalls):
            row = self.box.wine.usable(module, ordinal)
            if slot is not None:
                self.stop = f"{module}.{ordinal}: a register contract cannot call the guest"
                uc.emu_stop()
                return
            self._start_guest(uc, request, row.pop)
            return
        if "init_dlls" in registers:
            # The gate's retf goes to the trampoline instead of the caller.
            ss = uc.reg_read(UC_X86_REG_SS)
            sp = uc.reg_read(UC_X86_REG_SP)
            self.pending = {
                "ss": ss, "sp": sp, "ds": uc.reg_read(UC_X86_REG_DS), "bp": uc.reg_read(UC_X86_REG_BP),
                "ret": self._read(self.box.selectors[ss], sp, 4),
            }
            self._write_guest(ss, sp, struct.pack("<HH", 0, self.box.wine.task["trampoline"]))
            registers = {}
        frame = registers.pop("frame", None)
        if "eflags_cf" in registers:
            # A DOS function's carry flag. The stub's retf leaves the flags as set here.
            flags = uc.reg_read(UC_X86_REG_EFLAGS) & ~1
            uc.reg_write(UC_X86_REG_EFLAGS, flags | (registers.pop("eflags_cf") & 1))
        for name, value in registers.items():
            if name != "push":
                uc.reg_write(REGISTERS[name], value & 0xFFFF)
        if frame is not None:
            # A register contract that moves the stack (Throw): the stub's retf returns to the
            # frame's CS:IP from the new SS:SP.
            ss = uc.reg_read(UC_X86_REG_SS)
            self._write_guest(ss, uc.reg_read(UC_X86_REG_SP), struct.pack("<HH", *frame))
        if "push" in registers:
            # A word under the return address: after the retf, SS:SP points at it.
            ss = uc.reg_read(UC_X86_REG_SS)
            sp = uc.reg_read(UC_X86_REG_SP)
            ret = self._read(self.box.selectors[ss], sp, 4)
            self._write_guest(ss, sp - 2, ret + struct.pack("<H", registers["push"]))
            uc.reg_write(UC_X86_REG_SP, sp - 2)
        if self.moved and slot is None:
            # A block moved: the stub's retf goes to the INT tail, which loads ES and DS again
            # and jumps to the caller, as Wine's relay pops them from its frame.
            self.moved = False
            ss, sp = uc.reg_read(UC_X86_REG_SS), uc.reg_read(UC_X86_REG_SP)
            ip, cs = struct.unpack("<HH", self._read(self.box.selectors[ss], sp, 4))
            uc.mem_write(INT_TAIL + 0x10, struct.pack(
                "<HHHH", uc.reg_read(UC_X86_REG_ES), uc.reg_read(UC_X86_REG_DS), ip, cs))
            self._write_guest(ss, sp, struct.pack("<HH", 0, INT_TAIL_SEL))
        if self.calls > self.call_limit:
            self.stop = "call limit"
            uc.emu_stop()

    # ------------------------------------------------------------ 32-bit code

    def _map_linear(self, base, size):
        """Map [base, base + size) rounded out to pages. Pages already mapped stay as they are."""
        start = base & ~0xFFF
        end = (base + size + 0xFFF) & ~0xFFF
        mapped = [(b, e) for b, e, _p in self.uc.mem_regions()]
        page = start
        while page < end:
            if any(b <= page <= e for b, e in mapped):
                page += 0x1000
                continue
            run = page
            while run < end and not any(b <= run <= e for b, e in mapped):
                run += 0x1000
            self.uc.mem_map(page, run - page)
            page = run

    def _setup32(self):
        """The flat 32-bit code and data selectors, the thread's stack and TEB, and the stub
        page (win32.py). Made when the first Win32 module loads."""
        if self.flat32 is not None:
            return self.flat32
        code = self._selector_flags(0, 0xFFFFF, 0x9A, 0xC0)
        data = self._selector_flags(0, 0xFFFFF, 0x92, 0xC0)
        self._map_linear(win32.STACK32_TOP - win32.STACK32_SIZE, win32.STACK32_SIZE)
        self._map_linear(win32.TEB_BASE, 0x2000)
        teb = self._selector_flags(win32.TEB_BASE, 0xFFF, 0x92, 0x40)
        self._map_linear(win32.STUB_BASE, win32.STUB_SIZE)
        # The return stub: OUT 0ECh, then jmp far dword [STUB_BASE + 8], which the hook points
        # at the next 32-bit call or at the 16-bit switch tail.
        self.uc.mem_write(win32.STUB_BASE, bytes([0xE6, 0xEC, 0xFF, 0x2D]) + struct.pack("<I", win32.STUB_BASE + 8))
        self.flat32 = {"code": code, "data": data, "teb": teb}
        return self.flat32

    def _selector_flags(self, base, limit, access, flags):
        sel = self.box._selector()
        self._write_descriptor(sel, _descriptor(base, limit, access, flags))
        return sel

    def _push32_call(self, uc, proc, args, from16):
        """Lay out a stdcall call to proc with args on the 32-bit stack, returning to the
        return stub, and point the CPU's next far jump at it."""
        esp = win32.STACK32_TOP - 4 * len(args) - 4
        uc.mem_write(esp, struct.pack("<I", win32.STUB_BASE) + b"".join(struct.pack("<I", a & 0xFFFFFFFF) for a in args))
        flat = self.flat32
        if from16:
            uc.mem_write(INT_TAIL + ENTRY32_DATA, struct.pack(
                "<HIHHIH", flat["data"], esp, flat["data"], flat["teb"], proc, flat["code"]))
        else:
            uc.mem_write(win32.STUB_BASE + 8, struct.pack("<IH", proc, flat["code"]))
            uc.reg_write(UC_X86_REG_ESP, esp)

    def _start32(self, uc, request, pop):
        """A gate's handler asked for 32-bit calls (win32.Call32). The gate's retf goes to the
        entry tail, which loads the flat selectors and jumps to the first call."""
        if self.call32 is not None:
            self.stop = f"a 32-bit call from 16-bit code that 32-bit code called {self.where()}: neww does not nest them"
            uc.emu_stop()
            return
        ss, sp = uc.reg_read(UC_X86_REG_SS), uc.reg_read(UC_X86_REG_SP)
        state = {
            "request": request, "ss": ss, "after_sp": sp + 4 + pop + request.pop,
            "ret": self._read(self.box.selectors[ss], sp, 4),
            "ds": uc.reg_read(UC_X86_REG_DS), "es": uc.reg_read(UC_X86_REG_ES),
            "bp": uc.reg_read(UC_X86_REG_BP), "si": uc.reg_read(UC_X86_REG_SI), "di": uc.reg_read(UC_X86_REG_DI),
        }
        step = request.step(None)
        if step[0] == "done":
            # No 32-bit code ran: the gate returns with the answer, past request.pop more bytes.
            ax, dx, why = step[1]
            if why:
                self.stop = why
                uc.emu_stop()
                return
            uc.reg_write(UC_X86_REG_AX, ax & 0xFFFF)
            uc.reg_write(UC_X86_REG_DX, dx & 0xFFFF)
            new_sp = state["after_sp"] - 4 - pop
            self._write_guest(ss, new_sp, state["ret"])
            uc.reg_write(UC_X86_REG_SP, new_sp)
            return
        self.call32 = state
        self._setup32()
        self._push32_call(uc, step[1], step[2], from16=True)
        self._write_guest(ss, sp, struct.pack("<HH", ENTRY32_TAIL, INT_TAIL_SEL))

    def _return32(self, uc):
        """OUT 0ECh in the return stub: a 32-bit call returned EAX. Make the next, or go back
        to the 16-bit caller through the switch tail with the answer in DX:AX."""
        state = self.call32
        if state is None:
            self.stop = f"out 0xec with no 32-bit call pending {self.where()}"
            uc.emu_stop()
            return
        step = state["request"].step(uc.reg_read(UC_X86_REG_EAX))
        if step[0] == "call":
            self._push32_call(uc, step[1], step[2], from16=False)
            return
        ax, dx, why = step[1]
        if why:
            self.stop = why
            uc.emu_stop()
            return
        self.call32 = None
        uc.reg_write(UC_X86_REG_EAX, ax & 0xFFFF)
        uc.reg_write(UC_X86_REG_EDX, dx & 0xFFFF)
        for name in ("bp", "si", "di"):
            uc.reg_write(REGISTERS[name], state[name])
        ip, cs = struct.unpack("<HH", state["ret"])
        uc.mem_write(INT_TAIL + SWITCH_DATA, struct.pack(
            "<HHHHHH", state["ss"], state["after_sp"], state["ds"], state["es"], ip, cs))
        uc.mem_write(win32.STUB_BASE + 8, struct.pack("<IH", SWITCH_TAIL, INT_TAIL_SEL))
        uc.reg_write(UC_X86_REG_ESP, 0)

    def _import32(self, uc):
        """OUT 0EDh in an import stub: EDX is the stub's number. The arguments are above the
        return address. The answer goes in EAX (EDX:EAX for a 64-bit one), and the stub's
        ret pops what the spec says."""
        self.calls += 1
        esp = uc.reg_read(UC_X86_REG_ESP)
        wine = self.box.wine
        out = win32.call_stub(wine, uc.reg_read(UC_X86_REG_EDX), esp,
                              lambda addr, n: bytes(uc.mem_read(addr, n)))
        if isinstance(out, str):
            self.stop = out
            uc.emu_stop()
            return
        uc.reg_write(UC_X86_REG_EAX, out & 0xFFFFFFFF)
        if out >> 32:
            uc.reg_write(UC_X86_REG_EDX, (out >> 32) & 0xFFFFFFFF)
        if self.calls > self.call_limit:
            self.stop = "call limit"
            uc.emu_stop()

    def _interrupt(self, uc, intno, user):
        """INT n in 16-bit code. Wine's INSTR_EmulateInstruction sends INT 21h to
        DOSVM_Int21Handler, the handler DOS3Call uses. Any other interrupt stops."""
        cs = uc.reg_read(UC_X86_REG_CS)
        ip = uc.reg_read(UC_X86_REG_IP)
        wine = self.box.wine
        if self._read_guest(cs, (ip - 2) & 0xFFFF, 2) != bytes([0xCD, intno]):
            # Unicorn reports a CPU fault here too. Its IP is the faulting instruction.
            self.stop = f"Unhandled CPU exception (UC_ERR_EXCEPTION) {self.where()}, exception {intno:#x}"
            uc.emu_stop()
            return
        if intno in wine.pm_vectors:
            seg, off = wine.pm_vectors[intno]
            self.stop = (f"INT {intno:#x} {self.where()}: the guest set this vector to {seg:#x}:{off:#x}, "
                         "and DOSVM_EmulateInterruptPM would call it, which neww does not do yet")
            uc.emu_stop()
            return
        if intno not in (0x21, 0x2F):
            self.stop = f"INT {intno:#x} {self.where()}: Wine's builtin handler for it is not in neww"
            uc.emu_stop()
            return
        self.calls += 1
        handler = wine.int21 if intno == 0x21 else wine.int2f
        sets, why = handler(lambda name: uc.reg_read(REGISTERS[name]))
        if why:
            self.stop = why
            uc.emu_stop()
            return
        if "exit_task" in sets:
            self._exit_task(uc, sets["exit_task"])
            return
        es, ds = sets.pop("es", None), sets.pop("ds", None)
        if "eflags_cf" in sets:
            # The handler's carry flag. IRET does not run: the INT hook returns past the INT.
            flags = uc.reg_read(UC_X86_REG_EFLAGS) & ~1
            uc.reg_write(UC_X86_REG_EFLAGS, flags | (sets.pop("eflags_cf") & 1))
        for name, value in sets.items():
            uc.reg_write(REGISTERS[name], value & 0xFFFF)
        if es is not None or ds is not None:
            # Unicorn's register write gives ES or DS the real-mode base, selector * 16, not the
            # descriptor's. So the CPU loads them: CS:IP goes to INT_TAIL, whose selector's
            # descriptor base is its selector * 16, and the tail does mov es ; mov ds ; jmp far back.
            tail = struct.pack("<HHHH", es if es is not None else uc.reg_read(UC_X86_REG_ES),
                               ds if ds is not None else uc.reg_read(UC_X86_REG_DS), ip, cs)
            uc.mem_write(INT_TAIL + 0x10, tail)
            uc.reg_write(UC_X86_REG_CS, INT_TAIL_SEL)
            uc.reg_write(UC_X86_REG_IP, 0)

    def _unmapped(self, uc, access, address, size, value, user):
        self.stop = f"unmapped {address:#x}"
        return False
