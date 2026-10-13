# The host

The reader cannot execute a handler, decode a compressed bitmap, or ask the runtime where a widget sits. Those functions are already in the unpacked DLLs. The host is there to call them.

It is not a virtual machine to ship. There is no DOS box and no Windows. Unicorn is a 16-bit protected-mode CPU (`UC_MODE_16`). The host maps a megabyte, builds a GDT, and far-jumps into the real code. The pop sizes, the thunk slot, the passes, and the stubs that could not stay `AX = 1` are written in [WHY.md](../tbpipeline_bf/WHY.md). This file is the map. That file is the contract.

## What bf actually runs

`TB80RTM.EXE` is a self-loading NE image, flag `0x0800`. Segment 1 is the unpacker. Windows would call `BootApp` there. This host does not. `unfold.py` executes that stub once, dumps the expanded segments, and stops. Pass 04 starts from the unpacked image and jumps to segment 2 offset `0x35A`, which is the entry after the unpacker. Pass 06 maps `TB80RCR`, `TB80LNL`, `TB80OLE`, `TB80W16`, `TB80UTL`, and `TB80BAS` first, calls each DLL entry, then jumps to the same address.

A far call into `KERNEL`, `USER`, `GDI`, or OLE is not emulated by running those DLLs. The reloc is patched to a slot that does `out 0xE0` and returns. The handler in Python is the Windows call. The default return is `AX = 1`, `DX = 0`. That default is why so many calls looked fine and were wrong. `AX = 1` is a plausible BOOL and a bad pointer.

The calls that could not stay that way are listed in WHY.md: the heap, file handles, string copies, resources, `LoadString`, `GetSystemMetrics` for `SM_PENWINDOWS` (it stays 0), OLE's `CreateDispTypeInfo` (HRESULT 0, not `S_FALSE`), and `DOS3Call` with `AH = 4Ch` (the DOS exit). `__WINFLAGS` is the constant `0x0C25`. Patching it to a thunk offset makes the C runtime believe it is in real mode, and startup exits.

The last recorded pass-06 run asks for `TB80.INI` and `TB80enu`, then takes DOS exit 0. Only a path ending in `.tbk` or `.sbk` gets a handle, and the bytes behind that handle are the book on the command line. An INI open returns `0xFFFF`. The entry never asks for the book. That is [known-bugs.md](../tbpipeline_bf/known-bugs.md). Nothing is drawn unless `--dbgrender` is passed, and that flag does not wait for the host to succeed.

The instruction cap is there because an uncapped run does not fail. It sits. Do not take it off.

## newl

`newl` uses the same idea and the opposite default. A call that is not in `layer.py` stops the run. The table is short on purpose: `InitTask`, `WaitEvent`, `GetWinFlags`, `GlobalAlloc`, `GlobalLock`, `OpenFile`, `GetCurrentTask`, `GetDOSEnvironment`, and a handful of others. `GetVersion` returns `0x0A03` (Windows 3.10). `__WINFLAGS` is the same `0x0C25`.

The CPU got through the early startup and died on bad data, not on a missing name.

`GetCurrentTask` used to return the DGROUP selector. Startup walked a table and treated that selector as a hit, then copied from a far pointer whose segment was the letters of a string (`uct.` from `product`). Returning a selector that is not DGROUP, and not a word that already sits in the static string table at `0x1B00`, gets past that copy.

The next fault was `GlobalAlloc`. The size is a dword. Using only the low word handed back a 4K block. A later `lodsw` scanned for `0x0012` from offset `0x1276` and walked off the end. Capping the size at `0x10000` made the block big enough to contain the scan. The block is still zeros. The scan runs to the segment limit and faults, because nothing wrote the record the runtime expected to find.

That is as far as `newl` has gone. The book is not open. The next useful change is the data those startup scans are looking for, or a stop that names the scan, not another guessed return value.

## neww

`neww` links the ToolBook modules to each other before it runs. A fixup from `TB80RTM` to `TB80W16` is that DLL's selector and offset. System modules are gates. An ordinal with no contract stops the run, and the number of bytes to pop is taken from the contract, never counted off the instruction stream.

It has not been pushed as far into startup as `newl`. It is the cleaner of the two instruments. If one of them is continued, this is the one whose rule should be kept: unknown call, stop, name it.

## What the host is not for

It is not how a page gets drawn. It is not how `--open` reads a handler. It is not a Wine port, and finishing Wine is not the milestone. A probe that calls one ordinal and stops (`dll_probe.py`, `scaffold.py`, `bmp_bitmap.py`) is the right shape when the question is one function. Booting `TB80RTM` is the long way to ask that question.
