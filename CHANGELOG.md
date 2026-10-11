# Changelog

## 1.0.0r3

The debugging, visible.

- Each run writes `render/` beside the reader: one PNG per page with drawable polygons, and a button under the reader shows the files for the current page.
- `TB80BMP` ordinal 3 is callable. It stops at the unbound far call at `0x1FCD`.
- `FFFF` imports bind to the ordinal they name. Six DLLs get past that wall.
- `nehost/scaffold.py` walks the later ordinals. Ordinal 1 is startup.

## 1.0.0r2

The reader, split and polished.

- Debug route is stage 2a, 2b, 2c, in `runtime/debug/`.
- Each run writes `tbpipeline/_debug/db-YYYYMMDD-HHMMSS/`, beside the script.
- `render.html` is the engine reader. `render-old.html` is written only with `--render old`.
- `--theme default` is a Windows 95 window. `--theme modern` is the dark reader.
- `--debug` forces the reader.
- Graphics are still the next goal. `2.0.0` is not this release.

## 1.0.0r1

Cleanup of 1.0.0. Same reader.

- Removed generated files, caches, and the unused `host.py`.
- WinXP is the preferred VM. Win98 is fine and is the decompile machine. Win11 and Linux are the goal, and they do not run ToolBook yet.

## 1.0.0

First release. A book reader, not the ToolBook window.

- `python3 -m tbpipeline --b <bin> --c <book>` runs startup, launch, open, render.
- Each stage writes its file into `.debug/`. The last stage says the debug information is there.
- `runtime`, `nehost`, and `nedllhost` each run on their own.
- OPTLOADER unpacker credits moralrecordings' `optloader.py`.
- `USER.266` is `SetMessageQueue` and returns 1. The entry still dies before a book open.
- Using ToolBook without a VM is the next goal. WinXP is the preferred machine. Win98 is the decompile floor.
