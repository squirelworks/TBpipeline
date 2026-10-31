"""32-bit DLLs behind the Windows 95/NT generic thunks.

TB80W16 reaches TB80W32.DLL, a PE DLL, through the KERNEL generic thunks
(krnl386.exe16.spec 513 to 518). This mixin answers KERNEL.513
LoadLibraryEx32W and KERNEL.515 GetProcAddress32W. LoadLibraryEx32W
maps the PE at its image base in the same CPU, gives it a flat 32-bit
code and data selector, a stack and a TEB, and runs its entry point
with DLL_PROCESS_ATTACH, as Wine's LoadLibraryEx32W16
(dlls/krnl386.exe16/thunk.c:2495) does through LoadLibraryExA.

Its imports from KERNEL32, USER32 and the rest bind to 8-byte stubs,
`mov edx, id; out 0xE1, al; ret`. The OUT is answered by name from
WIN32. A name with no answer stops the run and is quoted; it never
returns a made-up value. WIN32 is empty here: each answer is its own
change.

Entering 32-bit code needs segment loads, and the host cannot load a
segment register in protected mode, so the switch is made in the guest.
Slot 0 of the selector the call came through is never an ordinal; it
becomes a far jump to ENTRY32, which loads the selectors, takes ESP and
the target from a parameter block, calls the target, and ends in
`out 0xE2, al`. The host saves the 16-bit context before the jump and
restores it at that OUT. Both transfers stop the CPU and hand the run
loop a `jump`.
"""

import os
import struct

from unicorn.x86_const import (
    UC_X86_REG_AX, UC_X86_REG_CS, UC_X86_REG_DX, UC_X86_REG_EAX, UC_X86_REG_EDX,
    UC_X86_REG_ESP, UC_X86_REG_IP, UC_X86_REG_SP, UC_X86_REG_SS,
)

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

# Win32 system DLLs. Windows has them mapped before any task runs, so
# LoadLibraryEx32W returns their handle without a file. Their calls are
# the stubs WIN32 answers.
SYSTEM_HANDLES = {"KERNEL32": 0x7FE00000, "USER32": 0x7FE10000, "GDI32": 0x7FE20000,
                  "ADVAPI32": 0x7FE30000, "WOW32": 0x7FE40000}

# (dll, name) -> (argument bytes popped, handler). handler(self, args)
# returns EAX. A name missing here stops the run, and so does a handler
# that raises Unanswered for arguments it has no documented answer for.
WIN32 = {}


class Unanswered(Exception):
    pass


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
    """Mixin for Pass06. Needs arena, uc, and the run loop's jump."""

    jump = None

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

    def _pe_path(self, name):
        """The file LoadLibraryEx32W names, from the unpacked directory."""
        base = name.replace("/", "\\").rsplit("\\", 1)[-1]
        low = base.lower()
        wanted = {low} if "." in low else {low + ".dll"}
        root = os.environ.get("TBK_UNPACKED", "")
        try:
            listing = os.listdir(root)
        except OSError:
            return None
        hit = next((f for f in listing if f.lower() in wanted), None)
        return os.path.join(root, hit) if hit else None

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

    # -- KERNEL.513 ----------------------------------------------------

    def _kernel_proc(self, ordinal):
        if ordinal == 518:
            return self._call_proc_ex32()
        if ordinal == 515:
            return self._get_proc_address32()
        if ordinal != 513:
            return super()._kernel_proc(ordinal)
        # LoadLibraryEx32W(lpszLibFile, hFile, dwFlags), Pascal, pops 12.
        # Wine returns LoadLibraryExA's HMODULE, the image base, or 0.
        name = self._string(self._word(5), self._word(4))
        stem = name.upper().replace("/", "\\").rsplit("\\", 1)[-1].rsplit(".", 1)[0]
        if stem in SYSTEM_HANDLES:
            self._win32_setup()
            self._dx_ax(SYSTEM_HANDLES[stem])
            return True
        path = self._pe_path(name)
        if not path:
            self._dx_ax(0)
            return True
        mod = self._pe_load(path)
        if mod.get("attached"):
            self._dx_ax(mod["base"])
            return True

        def attached(eax):
            # DllMain returning FALSE fails the load, and Wine returns 0.
            mod["attached"] = bool(eax)
            self._dx_ax(mod["base"] if eax else 0)

        self._call32(mod["entry"], [mod["base"], DLL_PROCESS_ATTACH, 0], attached)
        return True

    def _call_proc_ex32(self):
        # CallProcEx32W(nParams, fAddressConvert, lpProc32, p1, ..., pn).
        # Wine's spec line (dlls/krnl386.exe16/krnl386.exe16.spec:426) is
        # `518 varargs _CallProcEx32W(long long long) CallProcEx32W16`: it is
        # cdecl, so it pops nothing and the caller cleans up. Its
        # CallProcEx32W16 reads the parameters left to right, maps p(i+1)
        # with MapSL when bit i of the mask is set, calls lpProc32 (stdcall,
        # or cdecl with CPEX_DEST_CDECL, the top bit of nParams) and
        # returns EAX in DX:AX.
        ss = self.uc.reg_read(UC_X86_REG_SS)
        sp = self.uc.reg_read(UC_X86_REG_SP)
        n, convert, proc = struct.unpack("<III", self.arena.read(ss, (sp + 4) & 0xFFFF, 12))
        n &= 0x7FFFFFFF
        params = list(struct.unpack(f"<{n}I", self.arena.read(ss, (sp + 16) & 0xFFFF, 4 * n)))
        for i in range(n):
            if convert & (1 << i):
                params[i] = self._linear(params[i])
        self._call32(proc, params, self._dx_ax)
        return True

    def _linear(self, far):
        """MapSL: a 16:16 pointer's linear address. NULL stays NULL."""
        if not far:
            return 0
        info = self.arena.segs.get(far >> 16)
        return (info["base"] if info else 0) + (far & 0xFFFF)

    def _get_proc_address32(self):
        # GetProcAddress32W(hModule, lpszProc), Pascal, pops 8. Wine's
        # GetProcAddress32W16 is GetProcAddress: the export's address, by
        # name or by an ordinal in the low word, or 0. A Win32 system DLL
        # has no image here; its export is a stub WIN32 answers by name.
        noff, nseg = self._word(0), self._word(1)
        hmod = self._word(2) | (self._word(3) << 16)
        what = noff if nseg == 0 else self._string(nseg, noff)
        system = next((d for d, h in SYSTEM_HANDLES.items() if h == hmod), None)
        if system:
            self._win32_setup()
            self._dx_ax(self._api32_stub(system, what))
            return True
        mod = next((m for m in getattr(self, "pe32", {}).values() if m["base"] == hmod), None)
        if mod is None:
            rva = None
        elif nseg == 0:
            rva = mod["ords"].get(noff)
        else:
            rva = mod["names"].get(what)
        self._dx_ax(mod["base"] + rva if rva else 0)
        return True

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
        cs = uc.reg_read(UC_X86_REG_CS)
        saved = uc.context_save()
        top = self.frames32[-1][2] - 0x40 if self.frames32 else STACK32 + STACK32_SIZE - 0x40
        esp = top - 4 * len(params)
        uc.mem_write(esp, b"".join(struct.pack("<I", p & 0xFFFFFFFF) for p in params))
        uc.mem_write(PARAMS32, struct.pack("<II", esp, target))
        self.frames32.append((saved, done, esp))
        # Slot 0 of the call's selector: jmp far code32:ENTRY32.
        self.arena.write(cs, 0, bytes([0x66, 0xEA]) + struct.pack("<IH", ENTRY32, self.code32))
        return 0

    def _leave32(self):
        saved, done, _ = self.frames32.pop()
        eax = self.uc.reg_read(UC_X86_REG_EAX)
        self.uc.context_restore(saved)
        done(eax)
        return self.uc.reg_read(UC_X86_REG_IP)

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
        try:
            eax = handler(self, args)
        except Unanswered as exc:
            self.fault = f"win32 {name} {exc}"
            uc.emu_stop()
            return
        if pop:
            ret = bytes(uc.mem_read(esp, 4))
            uc.mem_write(esp + pop, ret)
            uc.reg_write(UC_X86_REG_ESP, esp + pop)
        uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_EDX, 0)
