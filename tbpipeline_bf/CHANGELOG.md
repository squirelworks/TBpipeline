# Changelog

## Unreleased

Not a release. `1.0.0r6` stays the version.

- Stage 2b says `render/ N pages with a drawing`. Stage 2c says `render/ M PNG files`. The known bug that they disagreed without saying why is gone.
- Every far call that falls through to `AX = 1` is a line in the debug folder's `02_launch.txt`: module, ordinal, call site, and the first four argument words. It is written on every launch, not only when the run dies.
- Kind-04 polygons are placed in `render.html` as SVG, at the record's twips / 15 from the page's top-left corner. Stage 2b says how many. Curve runs are still only files.
- `TBK_INI` names a directory the host may answer an `.ini` open from. `TB80.INI` there gets a handle whose bytes are that file. Unset, an INI open is still `0xFFFF`. No INI is committed.
- A page with text says, under the text, that its position is unknown. Field records do not yet name where the text sits, so it is listed, not placed. The payload carries `textAt: null` until those words are found.
- A Windows BMP that sits inside a page is drawn on that page in `render.html`, in book order, with a line saying its position is unknown. It is still copied into `resources/`.
- The same `TBK_INI` directory answers the extensionless `TB80enu` open. `OpenFile`'s style word is recorded beside each path.
- Guest reads of the PSP command tail at `0x80` are recorded, and `02_launch.txt` counts them. The fake PSP is built in one place for pass 04 and pass 06.
- A status line under every page says compressed ToolBook pictures are not drawn, that the decoder is `TB80BMP` ordinal 3, and that the host stops at `0x1FCD`. The reader does not decode them.
- `--open`'s `click` lines name the handler that ran and its offset, then the page it landed on: `P20000 buttonClick 0x… -> P20001`. A page whose click ran nothing says `no buttonClick`.
- No host change: a test pins the `.tbk` / `.sbk` rule. `OpenFile`, `_lopen`, and DOS `3Dh` on such a path return a handle whose bytes are the command-line book, and the magic at `0xC00` reads back through it. A `0xFFFF` there fails the test.
- Each run keeps its last Windows call with the registers it returned. `02_launch.txt` and `pass06` print it as `last call ...`.
- `--open` lists `unread` handlers: ones whose expansion copied bytes from outside the book. Each line gives the page, the handler, its offset, and how many bytes were written as `?` for that reason. A real `?` in the source is not counted.
- `next` and `back` run the page's `to handle next` or `to handle previous` / `back` when it has a jump the engine can compile, in `engine.py` and in `render.html`. Without one they use the page list, as before.
- `bmp_bitmap.py` applies `TB80BMP`'s relocs, so the far call at `0x1FCD` is bound. An internal target runs; an import stops and is named. It prints instead of rewriting `bmp_bitmap.txt`.
- `python3 -m tbpipeline_bf.runtime` and `python3 -m tbpipeline_bf.runtime.debug` run again. They died unpacking `resolve()`, which had grown to seven values. Without `--dbgrender` they still write no `render.html`.

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
