"""Write spec_rows.py and spec32_rows.py from a Wine checkout. Not imported by a run.

    WINE_SRC=~/wine python3 -m tbpipeline_neww.specgen

Every `pascal` entry of each Win16 spec file in SPEC_FILES, except the
`-arch=win32` ones, becomes one row: the spec line as the file has it, and
whether the C function behind it returns `void`. The return type is read
from the function's definition or prototype in the Wine tree, never from
the ToolBook binary. A name with no definition found is not void.

spec32_rows.py has every entry of the Win32 spec files in WIN32_SPEC_FILES that
an i386 build has, as the file has it. Its argument list gives a stdcall
function's pop size. These are read with git show at WINE_COMMIT, so a sparse
checkout serves too.

The checkout must be at wine.WINE_COMMIT. The script refuses another one.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from .wine import WINE_COMMIT

# Module name as ToolBook imports it -> its spec file in the Wine tree.
SPEC_FILES = {
    "KERNEL": "dlls/krnl386.exe16/krnl386.exe16.spec",
    "USER": "dlls/user.exe16/user.exe16.spec",
    "GDI": "dlls/gdi.exe16/gdi.exe16.spec",
    "KEYBOARD": "dlls/keyboard.drv16/keyboard.drv16.spec",
    "SHELL": "dlls/shell.dll16/shell.dll16.spec",
    "COMMDLG": "dlls/commdlg.dll16/commdlg.dll16.spec",
    "TOOLHELP": "dlls/toolhelp.dll16/toolhelp.dll16.spec",
    "COMPOBJ": "dlls/compobj.dll16/compobj.dll16.spec",
    "OLE2": "dlls/ole2.dll16/ole2.dll16.spec",
    "OLE2DISP": "dlls/ole2disp.dll16/ole2disp.dll16.spec",
    "MMSYSTEM": "dlls/mmsystem.dll16/mmsystem.dll16.spec",
    "DDEML": "dlls/ddeml.dll16/ddeml.dll16.spec",
    "VER": "dlls/ver.dll16/ver.dll16.spec",
    "WIN87EM": "dlls/win87em.dll16/win87em.dll16.spec",
}

# Where a spec's C function may be defined, besides its own directory: the
# 32-bit DLLs a 16-bit spec forwards to, and the public headers.
ALSO = ("dlls/user32", "dlls/gdi32", "dlls/kernel32", "dlls/kernelbase", "dlls/win32u", "dlls/ole32",
        "dlls/oleaut32", "dlls/shell32", "dlls/comdlg32", "dlls/winmm", "dlls/version", "include")

# The Win32 modules neww's Win32 side answers for -> their spec files.
WIN32_SPEC_FILES = {
    "KERNEL32": "dlls/kernel32/kernel32.spec",
    "USER32": "dlls/user32/user32.spec",
    "GDI32": "dlls/gdi32/gdi32.spec",
    "ADVAPI32": "dlls/advapi32/advapi32.spec",
    "WOW32": "dlls/wow32/wow32.spec",
}

ENTRY32 = re.compile(r"^\s*(@|\d+)\s+(stdcall|cdecl|varargs)\b")

ENTRY = re.compile(r"^\s*(\d+)\s+pascal\b(.*)$")


def entries(path):
    """(ordinal, line, C name) for each pascal entry, the line stripped of its comment."""
    out = []
    for raw in Path(path).read_text(encoding="latin1").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        m = ENTRY.match(line)
        if not m or "-arch=win32" in line:
            continue
        head, _, rest = line.partition("(")
        name = head.split()[-1]
        after = rest.partition(")")[2].split()
        out.append((int(m.group(1)), " ".join(line.split()), after[0] if after else name))
    return out


def _sources(wine, spec):
    dirs = [Path(wine) / Path(spec).parent] + [Path(wine) / d for d in ALSO]
    files = []
    for d in dirs:
        if d.is_dir():
            files += sorted(d.rglob("*.c")) + sorted(d.rglob("*.h"))
    return files


def returns_void(texts, cname):
    """True when the first definition or prototype of cname in texts returns void."""
    pat = re.compile(r"(^|\n)[ \t]*(?:static\s+)?(?:extern\s+)?([A-Za-z_][\w \t\*]*?)\s+(?:WINAPI|CALLBACK|APIENTRY)\s+" + re.escape(cname) + r"\s*\(")
    for text in texts:
        m = pat.search(text)
        if m:
            words = m.group(2).split()
            return words[-1].upper() == "VOID" and "*" not in m.group(2)
    return False


# The constants a stub's `return` may name, with their values from the Wine headers.
CONSTANTS = {
    "TRUE": 1, "FALSE": 0, "NULL": 0, "S_OK": 0, "S_FALSE": 1, "E_NOTIMPL": 0x80004001,
    "E_FAIL": 0x80004005, "E_OUTOFMEMORY": 0x8007000E, "E_INVALIDARG": 0x80070057,
    "E_UNEXPECTED": 0x8000FFFF,
}


def constant_return(texts, cname):
    """The value when the C function's body is only logging (FIXME, TRACE, WARN, ERR) and one
    `return` of a number or of a name in CONSTANTS. None otherwise, or when no body is found."""
    head = re.compile(r"WINAPIV?\s+" + re.escape(cname) + r"\s*\([^)]*\)\s*\{")
    for text in texts:
        m = head.search(text)
        if not m:
            continue
        depth, j = 1, m.end()
        while depth and j < len(text):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        body = re.sub(r"/\*.*?\*/", "", text[m.end():j - 1], flags=re.S)
        body = re.sub(r"//[^\n]*", "", body)
        stmts = [x.strip() for x in body.split(";") if x.strip()]
        stmts = [x for x in stmts if not re.match(r"(FIXME|TRACE|WARN|ERR)\s*\(", x)]
        if len(stmts) != 1 or not stmts[0].startswith("return"):
            return None
        expr = stmts[0][len("return"):].strip()
        while expr.startswith("(") and expr.endswith(")"):
            expr = expr[1:-1].strip()
        if re.fullmatch(r"-?(0x[0-9a-fA-F]+|\d+)", expr):
            return int(expr, 0)
        return CONSTANTS.get(expr)
    return None


def generate(wine):
    rows = {}
    for module, spec in SPEC_FILES.items():
        texts = [p.read_text(encoding="latin1") for p in _sources(wine, spec)]
        rows[module] = [
            (line, returns_void(texts, cname), constant_return(texts, cname))
            for _ordinal, line, cname in entries(Path(wine) / spec)
        ]
    return rows


def render(rows):
    out = [
        '"""Every pascal entry of the Win16 spec files, generated by specgen.py. Do not edit.',
        "",
        f"Wine commit {WINE_COMMIT}. Each row is (spec line, void, value): the line as the spec",
        "file has it, True when Wine's C function for it returns void, and the constant the",
        "function returns when its body is only logging and that return, else None.",
        '"""',
        "",
        "SPEC_ROWS = {",
    ]
    for module, items in rows.items():
        out.append(f"    {module!r}: [")
        out += [f"        ({line!r}, {void}, {value!r})," for line, void, value in items]
        out.append("    ],")
    out.append("}")
    return "\n".join(out) + "\n"


def i386(line):
    """False for an entry an i386 build leaves out: -arch= without i386 or win32, or with !i386."""
    for word in line.split():
        if word.startswith("-arch="):
            arches = word[len("-arch="):].split(",")
            if any(a == "!i386" for a in arches):
                return False
            if arches[0].startswith("!"):
                return True
            return any(a in ("i386", "win32") for a in arches)
    return True


def entries32(text):
    """Each i386 stdcall, cdecl or varargs line, stripped of its comment and extra spaces."""
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if ENTRY32.match(line) and i386(line):
            out.append(" ".join(line.split()))
    return out


def generate32(wine):
    rows = {}
    for module, spec in WIN32_SPEC_FILES.items():
        text = subprocess.run(["git", "-C", wine, "show", f"{WINE_COMMIT}:{spec}"],
                              capture_output=True, text=True, encoding="latin1", check=True).stdout
        rows[module] = entries32(text)
    return rows


def render32(rows):
    out = [
        '"""Every i386 entry of the Win32 spec files, generated by specgen.py. Do not edit.',
        "",
        f"Wine commit {WINE_COMMIT}. Each row is the spec line as the file has it. A stdcall",
        "function pops its arguments, 4 bytes each and 8 for an int64 or double.",
        '"""',
        "",
        "SPEC32_ROWS = {",
    ]
    for module, items in rows.items():
        out.append(f"    {module!r}: [")
        out += [f"        {line!r}," for line in items]
        out.append("    ],")
    out.append("}")
    return "\n".join(out) + "\n"


def main():
    wine = os.environ.get("WINE_SRC")
    if not wine:
        print("set WINE_SRC to a Wine checkout at " + WINE_COMMIT, file=sys.stderr)
        return 2
    head = subprocess.run(["git", "-C", wine, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != WINE_COMMIT:
        print(f"{wine} is at {head or 'no commit'}, not {WINE_COMMIT}", file=sys.stderr)
        return 2
    target = Path(__file__).with_name("spec_rows.py")
    target.write_text(render(generate(wine)))
    print(f"wrote {target}")
    target = Path(__file__).with_name("spec32_rows.py")
    target.write_text(render32(generate32(wine)))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
