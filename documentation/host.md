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

That `GlobalAlloc` reading was wrong, and the cap only hid it. Wine's spec is `pascal16 GlobalAlloc(word long)`: the flags word is pushed first, so the low word of the size is on top of the stack and the high word is under it. The old code took the high word as the low word and the flags as the high word. Any flags with a bit set made the size look larger than 64K, and the cap turned every such block into exactly `0x10000`. `newl` now reads the size the spec names. A request over 64K still gets one 64K segment, because one selector cannot address more and this layer does not tile selectors by `__AHINCR`. Those requests are listed in `Layer.capped` with the size that was asked. The block the `0x1276` scan walks may now be smaller than before. Nobody has rerun startup since this change, so the size that scan was given is not known yet.

What is written down about that scan: it starts at offset `0x1276`, it wants the word `0x0012`, and the block is one `GlobalAlloc` handed back. The selector was never recorded. The bytes the runtime would have found there on a real Windows boot are not in any note, so `newl` does not plant them. Instead, a `lods`, `scas`, or `cmps` that reads `GlobalAlloc` memory nothing has written ends the run at that first read: `scan lodsw at CS:IP read SEL:0x1276, GlobalAlloc block H that nothing wrote, looking for 0x0012`. The wanted word is taken from a `cmp ax` right after the string instruction, when there is one. The stop can fire earlier than the old fault did, if startup string-reads zeroed memory on purpose. If it does, the stop names that read too.

That is as far as `newl` has gone. The book is not open. The next useful change is the data those startup scans are looking for, or a stop that names the scan, not another guessed return value.

## neww

`neww` links the ToolBook modules to each other before it runs. A fixup from `TB80RTM` to `TB80W16` is that DLL's selector and offset. System modules are gates. An ordinal with no contract stops the run, and the number of bytes to pop is taken from the contract, never counted off the instruction stream.

It has not been pushed as far into startup as `newl`. It is the cleaner of the two instruments. If one of them is continued, this is the one whose rule should be kept: unknown call, stop, name it.

## What the host is not for

It is not how a page gets drawn. It is not how `--open` reads a handler. It is not a Wine port, and finishing Wine is not the milestone. A probe that calls one ordinal and stops (`dll_probe.py`, `scaffold.py`, `bmp_bitmap.py`) is the right shape when the question is one function. Booting `TB80RTM` is the long way to ask that question.
