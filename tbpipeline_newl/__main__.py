"""python3 -m tbpipeline_newl --b ~/TBK/bin [--c book.tbk]

Runs TB80RTM. Windows calls go to the layer. --list prints the import
report and does not start the CPU.
"""

import sys
from pathlib import Path

from .bas import LAYERS, count as bas_count
from .layer import EQUATES, Layer
from .ne import exported_names, imports


def _arg(argv, *flags):
    for i, arg in enumerate(argv):
        if arg in flags and i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser()
    return None


def _bin(argv):
    return _arg(argv, "--b", "--bin")


def _report(root):
    exe = next((p for name in ("TB80RTM.EXE", "TB80RTM.exe") if (p := root / name).is_file()), None)
    if exe is None:
        print(f"no NE executable in {root}", file=sys.stderr)
        return 2
    layer = Layer()
    rows = imports(exe)
    known, gap, other = [], [], []
    for item in rows:
        mod = item.module.upper()
        label = layer.name_of(mod, item.ordinal, item.name)
        shown = f"{item.module}.{item.ordinal or item.name}"
        if label and label.upper() not in shown.upper():
            shown += f" {label}"
        if mod in EQUATES or mod in ("KERNEL", "USER", "GDI", "SHELL", "KEYBOARD", "COMMDLG", "TOOLHELP", "COMPOBJ", "OLE2", "WIN87EM"):
            (known if layer.knows(mod, item.ordinal, item.name) else gap).append(shown)
        else:
            other.append(shown)
    print(f"layer {exe.name}")
    print(f"  answered {len(known)}  gap {len(gap)}  other {len(other)}")
    bas = next((p for name in ("TB80BAS.DLL", "TB80BAS.dll") if (p := root / name).is_file()), None)
    counts, unnamed = bas_count(rows, exported_names(bas) if bas else None)
    shown = "  ".join(f"{layer} {counts[layer]}" for layer in LAYERS + ("other",))
    print(f"TB80BAS by layer  {shown}  unnamed {unnamed}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _bin(argv)
    if root is None or not root.is_dir():
        print("usage: python3 -m tbpipeline_newl --b ~/TBK/bin", file=sys.stderr)
        return 2
    if "--list" in argv:
        return _report(root)
    from unicorn.x86_const import UC_X86_REG_CS, UC_X86_REG_IP

    from .cpu import Cpu

    host = Cpu(root, book=_arg(argv, "--c"))
    if host.exe is None:
        print(f"no NE executable in {root}", file=sys.stderr)
        return 2
    exe = host.exe
    print(f"cpu {exe['name']} {exe['entry_seg']}:{exe['entry_ip']:#x}  linked {host.linked}")
    host.run()
    cs = host.uc.reg_read(UC_X86_REG_CS) if host.uc else 0
    ip = host.uc.reg_read(UC_X86_REG_IP) if host.uc else 0
    print(f"  stopped {cs:#x}:{ip:#x} {host.stop}")
    for module, ordinal, label, _args in host.layer.trace[:24]:
        print(f"  {module}.{ordinal} {label}")
    if len(host.layer.trace) > 24:
        print(f"  ... {len(host.layer.trace) - 24} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
