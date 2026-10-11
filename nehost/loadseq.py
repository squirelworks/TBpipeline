#!/usr/bin/env python3
"""Follow the SoftICE load order from the 2026-10-10 06:57 boot.

The screenshots were taken latest-first. This host walks the other way:
Windows thunk, 32-bit launcher, OLE, the 16-bit engine, the picture
satellites, the TB80R/TB80ANM probes, then the book file layer.

It does not run the book. It opens each module that is on disk, reads the
NE or PE entry, and writes the same Load16/Load32/StartDLL lines SoftICE
printed. Selectors are assigned in that order. They are not the live VM
selectors.
"""

import os
import struct
import sys

UNPACKED = os.environ.get("TBK_UNPACKED", "/workspace/artifacts/unpacked")
OUT = os.path.join(os.path.dirname(__file__), "loadseq.txt")

# Oldest screenshot to newest. 32-bit rows are Load32. 16-bit rows are
# Load16 plus StartDLL. A free is the probe SoftICE logged.
ORDER = [
    ("32", "NETAPI32"),
    ("32", "NETBIOS"),
    ("32", "USER32"),
    ("32", "GDI32"),
    ("32", "ADVAPI32"),
    ("32", "WOW32"),
    ("32", "OLE32"),
    ("32", "TB80W32"),
    ("32", "TB80F32L"),
    ("32", "TB80RMT"),
    ("32", "SHELL32"),
    ("32", "COMCTL32"),
    ("32", "COMDLG32"),
    ("32", "SHLWAPI"),
    ("32", "VERSION"),
    ("16", "COMPOBJ"),
    ("16", "OLE2"),
    ("16", "OLE2NLS"),
    ("16", "OLE2DISP"),
    ("32", "RPCRT4"),
    ("32", "OLETHK32"),
    ("16", "TB80W16"),
    ("16", "TB80RTM"),
    ("16", "TB80UTL"),
    ("16", "TB80LNL"),
    ("16", "TB80RCR"),
    ("16", "TOOLHELP"),
    ("16", "WIN87EM"),
    ("16", "TB80BAS"),
    ("16", "TB80FLT"),
    ("16", "TB80JPG"),
    ("16", "TB80OLE"),
    ("16", "TB80ENU1"),
    ("16", "TB80NET"),
    ("probe", "TB80ANM"),
    ("probe", "TB80R"),
    ("16", "TBFILE32"),
    ("16", "TBWIN"),
    ("16", "TBCBT"),
    ("16", "TB80BMP"),
    ("16", "GDI"),
    ("16", "TB80MM"),
    ("16", "TB80CMP"),
]

FILES = {
    "TB80W32": "TB80W32.DLL",
    "TB80F32L": "TB80F32L.dll",
    "TB80RMT": "TB80RMT.DLL",
    "TB80W16": "TB80W16.DLL",
    "TB80RTM": "TB80RTM.EXE",
    "TB80UTL": "TB80UTL.DLL",
    "TB80LNL": "TB80LNL.DLL",
    "TB80RCR": "TB80RCR.DLL",
    "TB80BAS": "TB80BAS.DLL",
    "TB80FLT": "TB80FLT.DLL",
    "TB80JPG": "TB80JPG.DLL",
    "TB80OLE": "TB80OLE.DLL",
    "TB80ENU1": "TB80ENU1.DLL",
    "TB80NET": "TB80NET.EXE",
    "TBFILE32": "TBFILE32.DLL",
    "TBWIN": "TBWIN.DLL",
    "TBCBT": "TBCBT.DLL",
    "TB80BMP": "TB80BMP.DLL",
    "TB80MM": "TB80MM.DLL",
    "TB80CMP": "TB80CMP.DLL",
}


def ne_entry(blob):
    if blob[:2] != b"MZ":
        return None
    ne = struct.unpack_from("<H", blob, 0x3C)[0]
    if blob[ne:ne + 2] != b"NE":
        return None
    cs = struct.unpack_from("<H", blob, ne + 0x16)[0]
    ip = struct.unpack_from("<H", blob, ne + 0x14)[0]
    return cs, ip


def pe_entry(blob):
    if blob[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[pe:pe + 2] != b"PE":
        return None
    entry = struct.unpack_from("<I", blob, pe + 0x28)[0]
    return entry


def main():
    sel = 0x2200
    lines = []
    lines.append("load order from 06-58-17 (oldest) to 06-57-03 (newest)")
    for kind, name in ORDER:
        path = os.path.join(UNPACKED, FILES.get(name, ""))
        have = os.path.isfile(path)
        if kind == "32":
            entry = pe_entry(open(path, "rb").read()) if have else None
            lines.append(
                "WINICE: Load32 Mod=%s file=%s entry=%s"
                % (name, "yes" if have else "absent", hex(entry) if entry else "-")
            )
        elif kind == "probe":
            lines.append("WINICE: Load32 Mod=%s" % name)
            lines.append("WINICE: Free32 Mod=%s" % name)
        else:
            sel += 8
            entry = ne_entry(open(path, "rb").read()) if have else None
            lines.append(
                "WINICE: Load16 Sel=%04X Seg=0001 Mod=%s file=%s"
                % (sel, name, "yes" if have else "absent")
            )
            if entry:
                lines.append(
                    "WINICE: StartDLL CSIP=%04X:%04X Mod=%s"
                    % (sel, entry[1], name)
                )
            else:
                lines.append("WINICE: StartDLL Mod=%s entry=unread" % name)
    text = "\n".join(lines) + "\n"
    open(OUT, "w").write(text)
    print(text)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
