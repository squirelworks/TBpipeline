# Changelog

## Unreleased

Not a release. `1.0.0r6` stays the version.

- Stage 2b says `render/ N pages with a drawing`. Stage 2c says `render/ M PNG files, drawn and not placed`. The known bug that they disagreed without saying why is gone.

## 1.0.0r6

The reader is opt-in.

- `render.html` is written only with `--dbgrender`. A launch that exits no longer draws a page.

## 1.0.0r5

The host, explained, and pointed at `--b`.

- `WHY.md` is why the reader, the passes, the thunk, the pop sizes, and the stubs are shaped this way.
- `TB80RTM` reaches DOS exit 0 after asking for `TB80.INI`. It still does not open the book. The reader still runs.
- `USER.176` `LoadString` copies the resource string. `TB80UTL.3` is `GETSTRMGRSTRING`, and an empty product name was the check that exited startup.
- OLE `CreateDispTypeInfo` returns HRESULT 0 and a dummy `IUnknown`. `AX = 1` was `S_FALSE`, and the caller then released a null pointer.
- `KERNEL.102` with `AH = 4Ch` is `DOS3Call`. `__WINFLAGS` is the constant `0x0C25`, not a thunk offset.
- Binaries come from `--b` or `TBK_UNPACKED`. The default is `bin/` beside the package. The sandbox paths are gone. The pass 05 and pass 06 logs are records and are not rewritten.

## 1.0.0r4

Debug improvements.

- Book BMPs are extracted into `resources/`. A **Resources extracted** button shows them.
- Curve runs are drawn. The P420 flame is one. Each curve is its own file.
- The probe logs, `bmp_bitmap.txt`, `dll_probe.txt`, and `scaffold.txt`, are copied into each debug run.
- Stages 2a, 2b, and 2c are not reached when stage 2 opens the book, unless `--debug` is passed.
- Known bugs are in `known-bugs.md`.

## 1.0.0r3

The debugging, visible.

- Each run writes `render/` beside the reader: one PNG per page with drawable polygons, and a button under the reader shows the files for the current page.
- `TB80BMP` ordinal 3 is callable. It stops at the unbound far call at `0x1FCD`.
- `FFFF` imports bind to the ordinal they name. Six DLLs get past that wall.
- `nehost/scaffold.py` walks the later ordinals. Ordinal 1 is startup.

## 1.0.0r2

The reader, split and polished.

- Debug route is stage 2a, 2b, 2c, in `runtime/debug/`.
- Each run writes `tbpipeline_bf/_debug/db-YYYYMMDD-HHMMSS/`, beside the script.
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

- `python3 -m tbpipeline_bf --b <bin> --c <book>` runs startup, launch, open, render.
- Each stage writes its file into `.debug/`. The last stage says the debug information is there.
- `runtime`, `nehost`, and `nedllhost` each run on their own.
- OPTLOADER unpacker credits moralrecordings' `optloader.py`.
- `USER.266` is `SetMessageQueue` and returns 1. The entry still dies before a book open.
- Using ToolBook without a VM is the next goal. WinXP is the preferred machine. Win98 is the decompile floor.
