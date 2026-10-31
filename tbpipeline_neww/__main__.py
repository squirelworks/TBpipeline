"""python3 -m tbpipeline_neww --b ~/TBK/bin

Links every NE module in the directory, then enters TB80RTM.
Windows ordinals are gates. ToolBook calls land in the other DLL.
"""

import sys
from pathlib import Path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__.strip())
        return 0
    root = None
    for i, arg in enumerate(argv):
        if arg in ("--b", "--bin") and i + 1 < len(argv):
            root = Path(argv[i + 1]).expanduser()
    if root is None or not root.is_dir():
        print("usage: python3 -m tbpipeline_neww --b ~/TBK/bin", file=sys.stderr)
        return 2
    from .machine import Machine

    host = Machine(root)
    box = host.box
    if box.exe is None:
        print(f"no NE executable in {root}", file=sys.stderr)
        return 2
    code = box.exe.segments[box.exe.entry_seg - 1]
    print(f"sandbox {box.exe.name} {box.exe.entry_seg}:{box.exe.entry_ip:#x} sel {code.selector:#x}")
    print(f"  modules {len(box.images)}  linked {box.linked}  equates {box.equates}  gaps {len(box.gaps)}")
    for line in box.gaps[:12]:
        print(f"  gap {line}")
    host.run()
    from unicorn.x86_const import UC_X86_REG_CS, UC_X86_REG_IP
    cs = host.uc.reg_read(UC_X86_REG_CS) if host.uc else 0
    ip = host.uc.reg_read(UC_X86_REG_IP) if host.uc else 0
    print(f"  stopped {cs:#x}:{ip:#x} {host.stop}")
    print(f"  calls {host.calls}")
    for line in host.box.wine.trace[:24]:
        print(f"  {line}")
    if len(host.box.wine.trace) > 24:
        print(f"  ... {len(host.box.wine.trace) - 24} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
