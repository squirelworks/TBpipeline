#!/usr/bin/env python3
"""Pass 06: pass 04's entry, with ToolBook ordinals bound to real DLL code.

Windows ordinals still return from the thunk. TB80BAS, TB80RCR, TB80LNL,
TB80OLE, TB80UTL and TB80W16 ordinals jump to the segment:offset bind.py
resolved. The thunk now has a stub in every slot, so USER.266 does not
fall through zeros.
"""

import os
import struct
import sys

from tbpipeline.nehost.pass04 import Pass04, API_PORT
from .bind import DLLS, exports, modules, segment_bytes

UNPACKED = "/workspace/artifacts/unpacked"


class Pass06(Pass04):
    def build(self):
        self.dlls = {}
        self.dll_segs = {}
        self.dll_calls = []
        for mod, filename in DLLS.items():
            blob = open(os.path.join(UNPACKED, filename), "rb").read()
            self.dlls[mod] = (exports(blob), blob)
        super().build()
        self.modnames = modules(self.file, self.ne)

    def _thunks(self):
        blob = bytearray(0x1000)
        for ordinal in range(1, 512):
            at = ordinal * 8
            if at + 8 > len(blob):
                break
            blob[at:at + 8] = bytes([
                0xBA, ordinal & 0xFF, (ordinal >> 8) & 0xFF,
                0xE6, API_PORT, 0xCA, 0x00, 0x00,
            ])
        self.arena.write(self.thunk, 0, bytes(blob))

    def _relocs(self):
        self.modnames = modules(self.file, self.ne)
        super()._relocs()

    def _import_stub(self, fl, module, target):
        if fl & 1 and 1 <= module <= len(self.modnames):
            name = self.modnames[module - 1]
            hit = self._dll_entry(name, target)
            if hit:
                return hit
        return super()._import_stub(fl, module, target)

    def _dll_entry(self, name, ordinal):
        if name not in self.dlls or ordinal not in self.dlls[name][0]:
            return None
        seg, offset = self.dlls[name][0][ordinal]
        key = (name, seg)
        if key not in self.dll_segs:
            raw, flags = segment_bytes(self.dlls[name][1], seg)
            alloc = max(len(raw), 1)
            blob = bytearray(alloc)
            blob[:len(raw)] = raw
            self.dll_segs[key] = self.arena.alloc_selector(alloc, 0x9A, bytes(blob))
        sel = self.dll_segs[key]
        self.dll_calls.append((name, ordinal, sel, offset))
        return offset, sel

    def _bind(self, sel, atype, fl, disp, t1, t2):
        info = self.arena.segs[sel]
        seen = set()
        while disp not in (0, 0xFFFF) and disp not in seen and disp + 4 <= info["size"]:
            seen.add(disp)
            nxt = int.from_bytes(self.arena.read(sel, disp, 2), "little")
            stub = self._import_stub(fl, t1, t2)
            if atype == 2 and not fl & 1:
                self.arena.write(sel, disp, struct.pack("<H", self.segs.get(t1, 0)))
            elif atype == 2 and fl & 1:
                target = stub[1] if isinstance(stub, tuple) else self.thunk
                self.arena.write(sel, disp, struct.pack("<H", target))
            elif atype == 3 and stub is not None:
                if isinstance(stub, tuple):
                    packed = struct.pack("<HH", stub[0], stub[1])
                else:
                    packed = struct.pack("<HH", stub, self.thunk)
                self.arena.write(sel, disp, packed)
            elif atype == 5 and stub is not None:
                off = stub[0] if isinstance(stub, tuple) else stub
                self.arena.write(sel, disp, struct.pack("<H", off))
            disp = nxt


def main():
    host = Pass06(os.path.join(UNPACKED, "TB80RTM.EXE"), "/workspace/artifacts/courses/9e954d01.tbk")
    cs, ip, raw = host.run()
    used = sorted(set(host.dll_calls))
    print(f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}")
    print(f"opens: {host.opens or 'none'}")
    print(f"dll entries bound {len(used)}")
    out = os.path.join(os.path.dirname(__file__), "..", "nehost", "rtm - pass 06")
    out = os.path.normpath(out)
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "PASS06.txt"), "w").write(
        f"book /workspace/artifacts/courses/9e954d01.tbk\n"
        f"stopped {cs:#x}:{ip:#x} {raw.hex()} {host.fault}\n"
        f"opens {host.opens}\n"
        f"dll entries bound {len(used)}\n"
        f"skipped {host.skipped[:12]}\n"
        f"calls {host.calls[:24]}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
