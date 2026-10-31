"""32-bit DLLs behind the Windows 95/NT generic thunks.

TB80W16 reaches TB80W32.DLL, a PE DLL, through KERNEL.513-517:
LoadLibraryEx32W, FreeLibrary32W, GetProcAddress32W, GetVDMPointer32W
and CallProc32W. This mixin loads the PE at its image base in the same
CPU, gives it a flat 32-bit code and data selector, a stack and a TEB,
and runs its code when the 16-bit side calls through the thunks.

Its imports from KERNEL32, USER32 and the rest bind to 8-byte stubs,
`mov edx, id; out 0xE1, al; ret`. The OUT is answered by name in
WIN32 below. A name with no answer stops the run and is quoted; it
never returns a made-up value.

Entering 32-bit code needs segment loads, and the host cannot load a
segment register in protected mode, so the switch is made in the guest:
Pass06._dispatch jumps to a gate whose far jump reaches ENTRY32, which loads
the selectors, takes ESP and the target from a parameter block, calls
the target, and ends in `out 0xE2, al`. The host saves the 16-bit
context before the jump and restores it at that OUT.
"""

import struct

from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DX, UC_X86_REG_EAX, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

from tbpipeline_bf.nehost.win16stack import POP

PORT_API32 = 0xE1
PORT_RETURN32 = 0xE2

# Linear layout of the 32-bit side. TB80W32's image base is 0x10000000.
STUBS32 = 0x0F000000      # 8 bytes per imported name
TEB = 0x0F010000
ENTRY32 = 0x0F011000
PARAMS32 = 0x0F011100     # ESP, target
LOW32 = 0x0F000000
LOW32_SIZE = 0x20000
STACK32 = 0x0F100000
STACK32_SIZE = 0x100000

DLL_PROCESS_ATTACH = 1

# (dll, name) -> (argument bytes popped, handler). handler(self, args)
# returns EAX. A name missing here stops the run, and so does a handler
# that raises Unanswered for arguments it has no documented answer for.
WIN32 = {}


class Unanswered(Exception):
    pass


# A handler returns PENDING when it has started a call whose completion
# sets EAX itself.
PENDING = object()


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


class PE:
    """The parts of a PE image the loader reads."""

    def __init__(self, data):
        self.data = data
        pe = _u32(data, 0x3C)
        opt = pe + 24
        self.base = _u32(data, opt + 28)
        self.size = _u32(data, opt + 56)
        self.headers = _u32(data, opt + 60)
        self.entry = _u32(data, opt + 16)
        self.dirs = [struct.unpack_from("<II", data, opt + 96 + 8 * i) for i in range(16)]
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        at = opt + struct.unpack_from("<H", data, pe + 20)[0]
        self.sections = []
        for i in range(nsec):
            vsize, va, rsize, raw = struct.unpack_from("<IIII", data, at + i * 40 + 8)
            self.sections.append((va, vsize, raw, rsize))

    def image(self):
        blob = bytearray(self.size)
        blob[:self.headers] = self.data[:self.headers]
        for va, vsize, raw, rsize in self.sections:
            chunk = self.data[raw:raw + min(rsize, vsize or rsize)]
            blob[va:va + len(chunk)] = chunk
        return blob

    @staticmethod
    def cstr(blob, at):
        return bytes(blob[at:blob.index(b"\x00", at)]).decode("latin1")

    def imports(self, blob):
        """(dll, name or ordinal, IAT rva) rows."""
        rva, _ = self.dirs[1]
        rows = []
        while rva:
            oft, _, _, name, ft = struct.unpack_from("<IIIII", blob, rva)
            if not name:
                break
            dll = self.cstr(blob, name).upper().rsplit(".", 1)[0]
            at = oft or ft
            n = 0
            while True:
                value = _u32(blob, at + 4 * n)
                if not value:
                    break
                what = value & 0xFFFF if value & 0x80000000 else self.cstr(blob, value + 2)
                rows.append((dll, what, ft + 4 * n))
                n += 1
            rva += 20
        return rows

    def exports(self, blob):
        """name -> rva and ordinal -> rva."""
        rva, _ = self.dirs[0]
        if not rva:
            return {}, {}
        base, nfunc, nname, funcs, names, ords = struct.unpack_from("<IIIIII", blob, rva + 16)
        by_ord = {base + i: _u32(blob, funcs + 4 * i) for i in range(nfunc)}
        by_name = {}
        for i in range(nname):
            name = self.cstr(blob, _u32(blob, names + 4 * i))
            by_name[name] = _u32(blob, funcs + 4 * struct.unpack_from("<H", blob, ords + 2 * i)[0])
        return by_name, by_ord


class Win32:
    """Mixin for Pass06. Needs arena, uc, the task loop's jump and stop."""

    def _win32_setup(self):
        if getattr(self, "pe32", None) is not None:
            return
        self.pe32 = {}
        self.api32 = []
        self.frames32 = []
        self.uc.mem_map(LOW32, LOW32_SIZE)
        self.uc.mem_map(STACK32, STACK32_SIZE)
        self.code32 = self.arena.alloc_selector(0x10000, 0x9A, fixed_base=0)
        self.data32 = self.arena.alloc_selector(0x10000, 0x92, fixed_base=0)
        for sel in (self.code32, self.data32):
            info = self.arena.segs[sel]
            # Base 0, 4 GB, 4K granularity, 32-bit.
            self.arena._write_descriptor(sel // 8, 0, 0xFFFFF, info["access"], 0xC)
        self.fs32 = self.arena.alloc_selector(0x1000, 0x92, fixed_base=TEB)
        # A 16-bit far jump cannot carry a 32-bit offset, so the dispatcher
        # jumps here first: jmp far code32:ENTRY32.
        self.code32_gate = self.arena.alloc_selector(
            0x10, 0x9A, bytes([0x66, 0xEA]) + struct.pack("<IH", ENTRY32, self.code32) + bytes(8))
        top = STACK32 + STACK32_SIZE
        # NT_TIB: no exception handler, the stack, and the TEB's own address.
        self.uc.mem_write(TEB, struct.pack("<III", 0xFFFFFFFF, top, STACK32) + bytes(12) + struct.pack("<I", TEB))
        d, f = self.data32, self.fs32
        self.uc.mem_write(ENTRY32, bytes([
            0x66, 0xB8, d & 0xFF, d >> 8, 0x8E, 0xD8, 0x8E, 0xC0, 0x8E, 0xD0,
            0x66, 0xB8, f & 0xFF, f >> 8, 0x8E, 0xE0,
            0x8B, 0x25]) + struct.pack("<I", PARAMS32) + bytes([
            0xFF, 0x15]) + struct.pack("<I", PARAMS32 + 4) + bytes([
            0xE6, PORT_RETURN32, 0xF4,
        ]))

    # -- loading -------------------------------------------------------

    def _pe_load(self, path):
        self._win32_setup()
        key = path.upper()
        if key in self.pe32:
            return self.pe32[key]
        pe = PE(open(path, "rb").read())
        blob = pe.image()
        for dll, what, iat in pe.imports(blob):
            struct.pack_into("<I", blob, iat, self._api32_stub(dll, what))
        size = (pe.size + 0xFFF) & ~0xFFF
        self.uc.mem_map(pe.base, size)
        self.uc.mem_write(pe.base, bytes(blob))
        names, ords = pe.exports(blob)
        mod = {"base": pe.base, "entry": pe.base + pe.entry, "names": names, "ords": ords, "path": path}
        self.pe32[key] = mod
        return mod

    def _api32_stub(self, dll, what):
        ident = len(self.api32)
        self.api32.append((dll, what))
        at = STUBS32 + 8 * ident
        self.uc.mem_write(at, bytes([0xBA]) + struct.pack("<I", ident) + bytes([0xE6, PORT_API32, 0xC3]))
        return at

    # -- the generic thunks -------------------------------------------

    def _fix_ret(self, ordinal):
        stub = getattr(self, "stub_module", {}).get(self.uc.reg_read(UC_X86_REG_CS))
        if stub == "KERNEL" and ordinal in (517, 518):
            # CallProc32W is Pascal with a variable count: it pops
            # 12 + 4 * nParams. CallProcEx32W is cdecl: it pops nothing.
            # The table's 12 for both is the fixed part.
            ss = self.uc.reg_read(UC_X86_REG_SS)
            sp = self.uc.reg_read(UC_X86_REG_SP)
            n = struct.unpack("<I", self.arena.read(ss, (sp + 4) & 0xFFFF, 4))[0] & 0x7FFFFFFF
            self._args32 = self.arena.read(ss, (sp + 4) & 0xFFFF, 12 + 4 * n)
            ret_ip, ret_cs = struct.unpack("<HH", self.arena.read(ss, sp, 4))
            self.callers[(ret_cs, ret_ip)] = ("KERNEL", ordinal)
            self.sites[(ret_cs, ret_ip)] = ("KERNEL", ordinal, 12 + 4 * n if ordinal == 517 else 0)
            stub_module, self.stub_module = self.stub_module, {}
            try:
                return super()._fix_ret(ordinal)
            finally:
                self.stub_module = stub_module
        return super()._fix_ret(ordinal)

    def _dword(self, n):
        return self._word(n) | (self._word(n + 1) << 16)

    def _linear(self, far):
        sel, off = far >> 16, far & 0xFFFF
        if not far or sel not in self.arena.segs:
            return 0
        return self.arena.segs[sel]["base"] + off

    def _kernel_proc(self, ordinal):
        if ordinal == 513:
            # LoadLibraryEx32W(lpszLibFile, hFile, dwFlags)
            name = self._string(self._word(5), self._word(4))
            stem = name.upper().rsplit("\\", 1)[-1].rsplit(".", 1)[0]
            if stem in SYSTEM_HANDLES:
                # A Win32 system DLL: its calls are the stubs WIN32 answers.
                self._win32_setup()
                self._dx_ax(SYSTEM_HANDLES[stem])
                return True
            path = self._task_file(name) if hasattr(self, "_task_file") else None
            if not path:
                return super()._kernel_proc(ordinal)
            mod = self._pe_load(path)
            if mod.get("attached"):
                self._dx_ax(mod["base"])
                return True
            mod["attached"] = True
            self.task_log.append(f"LoadLibraryEx32W {name!r} at {mod['base']:#x}")
            self._call32(mod["entry"], [mod["base"], DLL_PROCESS_ATTACH, 0],
                         lambda eax: self._dx_ax(mod["base"] if eax else 0))
            return True
        if ordinal == 514:
            self._dx_ax(1)
            return True
        if ordinal == 515:
            # GetProcAddress32W(hInst32, lpszProc)
            hinst = self._dword(2)
            mod = next((m for m in getattr(self, "pe32", {}).values() if m["base"] == hinst), None)
            noff, nseg = self._word(0), self._word(1)
            system = next((d for d, h in SYSTEM_HANDLES.items() if h == hinst), None)
            if system:
                self._dx_ax(self._api32_stub(system, noff if nseg == 0 else self._string(nseg, noff)))
                return True
            if mod is None:
                rva = None
            elif nseg == 0:
                rva = mod["ords"].get(noff)
            else:
                rva = mod["names"].get(self._string(nseg, noff))
            self._dx_ax(mod["base"] + rva if rva else 0)
            return True
        if ordinal == 516:
            # GetVDMPointer32W(lpvp, fMode)
            self._dx_ax(self._linear(self._dword(1)))
            return True
        if ordinal == 517:
            # CallProc32W(p1, ..., pn, lpProc32, fAddressConvert, nParams):
            # p1 was pushed first, and bit 0 of the mask is pn.
            raw = self._args32
            n, convert, proc = struct.unpack_from("<III", raw, 0)
            params = list(struct.unpack_from(f"<{n}I", raw, 12))[::-1]
            for i in range(n):
                if convert & (1 << (n - 1 - i)):
                    params[i] = self._linear(params[i])
            self._call32(proc, params, self._dx_ax)
            return True
        if ordinal == 518:
            # CallProcEx32W(nParams, fAddressConvert, lpProc32, p1, ..., pn),
            # cdecl: p1 is nearest the top, and bit 0 of the mask is p1.
            raw = self._args32
            n, convert, proc = struct.unpack_from("<III", raw, 0)
            n &= 0x7FFFFFFF
            params = list(struct.unpack_from(f"<{n}I", raw, 12))
            for i in range(n):
                if convert & (1 << i):
                    params[i] = self._linear(params[i])
            self._call32(proc, params, self._dx_ax)
            return True
        return super()._kernel_proc(ordinal)

    def _dx_ax(self, value):
        self.uc.reg_write(UC_X86_REG_AX, value & 0xFFFF)
        self.uc.reg_write(UC_X86_REG_DX, (value >> 16) & 0xFFFF)

    # -- running 32-bit code ------------------------------------------

    def _call32(self, target, params, done):
        """Stop, then run target(params) as stdcall and hand EAX to done."""
        self.jump = lambda: self._enter32(target, params, done)
        self.uc.emu_stop()

    def _enter32(self, target, params, done):
        uc = self.uc
        saved = uc.context_save()
        top = self.frames32[-1][2] - 0x40 if self.frames32 else STACK32 + STACK32_SIZE - 0x40
        esp = top - 4 * len(params)
        uc.mem_write(esp, b"".join(struct.pack("<I", p & 0xFFFFFFFF) for p in params))
        uc.mem_write(PARAMS32, struct.pack("<II", esp, target))
        self.frames32.append((saved, done, esp))
        return self._dispatch(self.code32_gate, 0)

    def _leave32(self):
        saved, done, _ = self.frames32.pop()
        eax = self.uc.reg_read(UC_X86_REG_EAX)
        self.uc.context_restore(saved)
        done(eax)
        return self.uc.reg_read(UC_X86_REG_EIP)

    def _on_out(self, uc, port, size, value, user):
        if port == PORT_RETURN32:
            self.jump = self._leave32
            uc.emu_stop()
            return
        if port == PORT_API32:
            self._api32(uc.reg_read(UC_X86_REG_EDX))
            return
        super()._on_out(uc, port, size, value, user)

    def _api32(self, ident):
        uc = self.uc
        dll, what = self.api32[ident]
        esp = uc.reg_read(UC_X86_REG_ESP)
        name = f"{dll}.{what}"
        self.last32 = name
        answer = WIN32.get((dll, what))
        if answer is None:
            self.fault = f"win32 {name}"
            uc.emu_stop()
            return
        pop, handler = answer
        args = struct.unpack("<8I", bytes(uc.mem_read(esp + 4, 32)))
        if pop:
            ret = bytes(uc.mem_read(esp, 4))
            uc.mem_write(esp + pop, ret)
            uc.reg_write(UC_X86_REG_ESP, esp + pop)
        try:
            eax = handler(self, args)
        except Unanswered as exc:
            self.fault = f"win32 {name} {exc}"
            uc.emu_stop()
            return
        if eax is PENDING:
            # The answer comes from 16-bit code the handler started; its
            # completion sets EAX in the restored context.
            return
        uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_EDX, 0)


# Win32 system DLLs. LoadLibraryEx32W hands out these handles, and
# GetProcAddress32W on them gives a stub that WIN32 answers by name.
SYSTEM_HANDLES = {"KERNEL32": 0x7FE00000, "USER32": 0x7FE10000, "GDI32": 0x7FE20000,
                  "ADVAPI32": 0x7FE30000, "WOW32": 0x7FE40000}

from . import win32api  # noqa: E402,F401  registers the answers

