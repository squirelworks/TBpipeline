# Changelog

## Unreleased

Not a release. `1.0.0r6` stays the version.

- `KERNEL.166` `WinExec` of an EXE found in the unpacked directory loads it as a second Win16 task in the same CPU and returns its instance once that task yields (`GetMessage`, `PeekMessage`, `WaitMessage`, or `Yield`). A missing EXE is still the wall: the run stops and the command line is quoted.
- `USER.266` `SetMessageQueue` returns TRUE, as Wine's `SetMessageQueue` does for any size.
- `KERNEL.30` `WaitEvent` takes the start event Wine posts and returns FALSE. A wait with nothing pending stops the run.
- `GDI.87` `GetStockObject` returns `index + 32`, Wine's stock handle, and 0 for a bad index.
- `KERNEL.131` `GetDOSEnvironment` returns a far pointer to Wine's environment block layout, with no variables.
- `KERNEL.518` `CallProcEx32W` runs a 32-bit procedure with its parameters, maps each one its mask marks from 16:16 to linear, and returns EAX in DX:AX, as Wine's `CallProcEx32W16` does. A NULL procedure returns 0. It is cdecl, so it pops nothing: the pop table had 12. It used to fall through to `AX = 1`.
- `KERNEL32.FreeEnvironmentStringsA` and `W`, called by TB80W32, give back a block from `GetEnvironmentStrings`, as Wine's `HeapFree` does. NULL returns TRUE, and any other pointer returns FALSE with `ERROR_INVALID_PARAMETER`. They used to stop the run.
- `KERNEL32.GetEnvironmentStrings` (and its `A` name), called by TB80W32, returns a new ANSI copy of the environment block, converted as Wine's `GetEnvironmentStringsA` does. An empty environment is one NUL byte. It used to stop the run.
- `KERNEL32.GetEnvironmentStringsW`, called by TB80W32, returns a new copy of the process environment block, as Wine's does. The block is empty (one NUL WCHAR) because this host gives the guest no variables, which matches `KERNEL.131`. It used to stop the run.
- `KERNEL32.GetCommandLineA`, called by TB80W32, returns the command line Wine gives the winevdm process a 16-bit program runs in: `C:\windows\syswow64\winevdm.exe --app-name "C:\TOOLBOOK\TB80RTM.EXE" C:\TOOLBOOK\TB80RTM.EXE <book>`. It returns the same pointer every call. The task's file name is now one constant, `EXE_PATH`, shared with `KERNEL.49`. It used to stop the run.
- `KERNEL32.VirtualAlloc`, called by TB80W32, reserves (and commits) a 64K-aligned region when given no address. It commits inside an existing reservation when given one, and it fails with Wine's last errors otherwise: `ERROR_INVALID_PARAMETER` for a size of 0 or no allocation type, and `ERROR_INVALID_ADDRESS` for a commit outside any reservation. Reserving at a given address, and `MEM_RESET`, still stop the run. It used to stop the run in every case.
- `KERNEL32.HeapCreate`, called by TB80W32, reserves the region Wine's `RtlCreateHeap` would, rounded to 64K, and returns its base as the heap handle. When there is no room it returns NULL with `ERROR_NOT_ENOUGH_MEMORY`. It used to stop the run.
- `KERNEL32.GetProcAddress`, called by TB80W32, returns an export's address by name or by ordinal, as Wine's `get_proc_address` does. A missing export gives NULL and `ERROR_PROC_NOT_FOUND`, and an unknown handle gives NULL and `ERROR_MOD_NOT_FOUND`. A system DLL's export is a stub answered by name. A NULL handle, the process image, still stops the run. It used to stop the run in every case.
- `KERNEL32.GetModuleHandleA`, called by TB80W32, returns a loaded module's handle by its base name, adding `.dll` when there is no extension, as Wine's `LdrGetDllHandleEx` does. A module that isn't loaded gives NULL and `ERROR_MOD_NOT_FOUND`. NULL, the process image, still stops the run because this 16-bit process has no 32-bit image. It used to stop the run in every case.
- `KERNEL32.GetVersion`, called by TB80W32, returns `0x23F00206`: Windows 6.2 build 9200 on the NT platform, the version Wine reports to an application with no manifest, packed the way Wine's kernelbase `GetVersion` packs it. It used to stop the run as an unanswered Win32 call.
- `KERNEL.517` `CallProc32W` runs a 32-bit procedure with its parameters in Pascal order, maps each one its mask marks from 16:16 to linear, pops `12 + 4 * nParams` for the caller and returns EAX in DX:AX, as Wine's `CallProc32W16` does. A NULL procedure returns 0. The pop table had a fixed 12. It used to fall through to `AX = 1`.
- `KERNEL.25` `GlobalCompact` returns `0x00FF0000`, Wine's `GLOBAL_MAX_ALLOC_SIZE`.
- `KERNEL.198` `GlobalUnfix` is answered and returns nothing, as Wine's void `GlobalUnfix16` does.
- `KERNEL.515` `GetProcAddress32W` returns the address of a loaded 32-bit DLL's export, by name or by ordinal, or 0, as Wine's `GetProcAddress32W16` returns `GetProcAddress`. For a Win32 system DLL it returns an import stub that is answered by name. It used to fall through to `AX = 1`.
- `KERNEL.57` `GetProfileInt` reads a number from `WIN.INI`, the way Wine's `GetProfileInt16` calls `GetPrivateProfileInt16` on `"win.ini"`, or returns the default. It used to fall through to `AX = 1`.
- `KERNEL.58` `GetProfileString` copies a value from `WIN.INI`, the way Wine's `GetProfileString16` calls `GetPrivateProfileString16` on `"win.ini"`, or the default. It used to fall through to `AX = 1`.
- `KERNEL.353` `lstrcpyn` copies at most n - 1 characters and a NUL and returns dst, as Wine's `lstrcpyn16` over `lstrcpynA` does. It used to fall through to `AX = 1`, which copied nothing and returned `0000:0001`.
- `USER.421` `wvsprintf` formats into the caller's buffer with its arguments read from the `VA_LIST16` far pointer, as Wine's `wvsprintf16` does, and returns the length. It used to fall through to `AX = 1` and leave the buffer as it was.
- `KERNEL.29` `Yield` is answered and returns, as Wine's void `Yield16` does when there is no other task to run. TBWIN's `yieldApp` (TBWIN.16, linked by `tb80axf.sbk`) calls it, and TB80 calls it once before the WinExec wall. It used to fall through to `AX = 1`.
- `USER.5` `InitApp` is answered with TRUE, as Wine's `InitApp16` returns once the task has a message queue. The `AX = 1` default was the same value, but the call was logged as unanswered.
- `KERNEL.111` `GlobalWire` returns the block's 16:16 address in DX:AX and its selector in CX, and 0 for a handle that is not a block, as Wine's `GlobalWire16` (`WIN16_GlobalLock16`) does. TBFILE32's `CopyFile32` and `getShortFileName32`, which `tb80axf.sbk` links, call it. It used to fall through to `AX = 1`.
- `KERNEL.112` `GlobalUnWire` is answered with TRUE, as Wine's `GlobalUnWire16` (`!GlobalUnlock16`) is once no lock is left. This host keeps no lock counts. TBFILE32's `CopyFile32` and `getShortFileName32`, which `tb80axf.sbk` links, call it. It used to fall through to `AX = 1` unanswered.
- `SHELL.6` `RegQueryValue` answers the way Wine's `RegQueryValue16` does with an empty registry. A named subkey is `ERROR_FILE_NOT_FOUND`. A root's missing default value is `""` with `*count` 1 and `ERROR_SUCCESS`. Any other key is `ERROR_INVALID_HANDLE`. It pops 16. TBREG's `RegistryGetKey` (linked by `tb80axf.sbk`) calls it, and the runtime calls it twice before the WinExec wall. It used to fall through to `AX = 1`.
- `SHELL.3` `RegCloseKey` returns `ERROR_SUCCESS` for a predefined root (Win16 0 and 1 included) and `ERROR_INVALID_HANDLE` for any other key, in DX:AX, as Wine's `RegCloseKey16` does when no other key has been opened. It pops 4. TBREG's `RegistryGetKey` (linked by `tb80axf.sbk`) calls it. It used to fall through to `AX = 1`.
- `SHELL.1` `RegOpenKey` is answered the way Wine's `RegOpenKey16` answers with an empty registry. An empty name gives back the key itself, a named subkey is `ERROR_FILE_NOT_FOUND` with `*retkey` cleared, and a key that isn't a root is `ERROR_INVALID_HANDLE`, in DX:AX. It pops 12. TBREG's `RegistryGetKey` (linked by `tb80axf.sbk`) calls it, and the runtime calls it once before the WinExec wall. It used to fall through to `AX = 1`.
- `KERNEL.127` `GetPrivateProfileInt` reads the key's number from the INI `TBK_INI` supplies, the way Wine's `GetPrivateProfileInt16` does (`RtlUnicodeStringToInteger`, base 0, cast to INT16). A missing or empty value returns the default. It used to fall through to `AX = 1`, so every numeric key read as 1.
- `KERNEL.513` `LoadLibraryEx32W` maps a 32-bit DLL from `TBK_UNPACKED` at its image base, binds its imports to stubs, and runs its entry point with `DLL_PROCESS_ATTACH` as 32-bit code. It returns the image base, or 0 when the file is missing or `DllMain` says FALSE, as Wine's `LoadLibraryEx32W16` returns `LoadLibraryExA`'s handle. A Win32 system DLL returns its handle without a file. A Win32 import with no answer stops the run and is named. The real run never reaches it yet: `GetProcAddress(KERNEL, 513)` still returns 0.
- `KERNEL.516` `GetVDMPointer32W` returns the 32-bit linear address of a 16:16 pointer in DX:AX, as Wine's `GetVDMPointer32W16` (`K32WOWGetVDMPointer`) does: the selector's base plus the offset in protected mode, `seg * 16 + off` in real mode. It used to fall through to `AX = 1`.
- `USER.57` `RegisterClass` keeps the class (its window procedure, instance and extra bytes) and returns its atom, from the same table `RegisterWindowMessage` uses, as Wine's `RegisterClass16` returns `RegisterClassEx16`'s atom. A name the instance already registered returns 0. It used to fall through to `AX = 1`, so all 9 classes the runtime registers before the `WinExec` wall got atom 1.
- `USER.145` `RegisterClipboardFormat` returns a string atom from the same table as `RegisterWindowMessage`, as Wine's `RegisterClipboardFormatA` calls `NtUserRegisterWindowMessage`. It used to fall through to `AX = 1`, so every clipboard format got number 1.
- `KERNEL.96` `FreeLibrary` is answered and unloads nothing, as Wine's void `FreeLibrary16` only drops a usage count while other users remain. TB80W16 frees its `KERNEL` handle four times. It used to fall through to `AX = 1`.
- `GDI.80` `GetDeviceCaps` answers for the screen as Wine's `GetDeviceCaps16` over `nulldrv_GetDeviceCaps` does: 32 bits per pixel, 96 DPI, one plane, no palette, `NUMCOLORS` 2048, 800 by 600, and 0 for an unknown index. It used to fall through to `AX = 1`, one bit per pixel and one pixel per inch.
- `USER.180` `GetSysColor` returns Wine's default colour for the index in DX:AX, from `system_colors` in `win32u/sysparams.c`, and 0 out of range. It used to fall through to `AX = 1`, `RGB(1, 0, 0)` for every element.
- `KERNEL.36` `GetCurrentTask` returns one task handle, a zeroed block the host keeps, in AX and DX, as Wine's `WIN16_GetCurrentTask` returns the current and first task. It used to fall through to `AX = 1`, which TB80UTL and TB80LNL stored as the key of their per-task tables.
- `USER.118` `RegisterWindowMessage` returns one atom from `0xC000` per message name, compared without case, as Wine's `RegisterWindowMessageA` (`GlobalAddAtomA`) does. It used to fall through to `AX = 1`, so every registered message got message number 1.
- `KERNEL.128` `GetPrivateProfileString` copies the key's value from the INI `TBK_INI` supplies, or else the default without trailing blanks, cut to `size - 1`, and returns its length. It used to fall through to `AX = 1` and leave the buffer as it was. The runtime reads its `ToolBook startup` keys this way before the `WinExec` wall.
- `OpenFile` with `OF_DELETE` removes a file the guest created and returns 1. Any other path, the book included, returns `0xFFFF` with error 2.
- `_lwrite` (`KERNEL.86`) writes to a file the guest created, and `_lread` reads it back through any handle. The book and the INI files stay read-only: `_lwrite` to them returns `0xFFFF`.
- `OpenFile` with `OF_CREATE` creates or truncates a file the host keeps, never on disk. Later opens of the same path find it, and every handle shares its bytes.
- `OpenFile` with `OF_REOPEN` opens the `szPathName` the `OFSTRUCT` already holds and leaves it there. It used to qualify the NULL name and write `C:\TOOLBOOK\` over the path.
- `LoadLibrary` of a module Windows has loaded (KERNEL, USER, GDI, KEYBOARD, SYSTEM, SOUND, DISPLAY, MOUSE) returns that module's handle. It used to return 2, file not found, and TB80W16 asked for KERNEL again until the instruction cap.
- int 2Fh `AX = 150Bh`, the MSCDEX CD-ROM drive check, comes back with every register unchanged, as DOS does with nothing on the multiplex, so `BX` is not `ADADh`. Every other int 2Fh call still stops the run.
- `USER.471` `lstrcmpi` compares the two strings without case and returns -1, 0 or 1. It used to fall through to `AX = 1`, "greater" for every pair, so TB80NET never matched its command line "ToolBook".
- `KERNEL.21` `GlobalHandle` returns the handle in AX and the selector in DX; in this host they are the same value. TB80UTL's heap maker keeps DX as the new heap's selector, and DX = 0 gave TB80BAS a heap at selector 0.
- `USER.420` `wsprintf` formats into the caller's buffer, and its pop size is 0: it is cdecl, and the caller does `add sp, 0xE`. The table had 8. The message box the book open stops on now reads "A internal error has occurred in File 'Unknown' line 629." The `TB80enu` open was the unformatted buffer: the entry asks for `C:\TOOLBOOK\TB80enu1.DLL`.
- `USER.1` `MessageBox` stops the run, and the stop quotes the caption, the type and the text. It used to return `AX = 1`, which is `IDOK`: TB80UTL's internal-error box says "Press OK to continue", so the runtime ran past its own assertion and exited 0 without asking for the book.
- The compressed-picture status line under every page says the host probe stops at its first import, `KERNEL.36`, not at `0x1FCD`. The far call there is bound now (#42), and the stop is from the bf host's run (#75).
- `KERNEL.5` `LocalAlloc` grows a full automatic data segment toward 64K, the way Windows does, instead of returning 0. The segment keeps its selector and its bytes; `Arena.grow` moves it to new memory and rewrites the descriptor, and the call returns through a stub that reloads `DS` and `ES`. TB80BAS's small heap filled during the book open, and its fallback put a record in the task's DS that it then read through its own DS as zeros.
- `KERNEL.336` `IsBadCodePtr` answers from the descriptor: 0 for an offset inside a code segment the arena knows, 1 otherwise. `AX = 1` said every pointer was bad, so TB80BAS never called its file manager's handler and the runtime said "Failed initializing the book file manager".
- `KEYBOARD.6` `OemToAnsi` is the other half: OEM (437) to ANSI (1252), pop 8, returns `-1`. With both answered, the open TB80BAS makes is `fixture.tbk\r`: the name, with the command tail's carriage return still on it.
- `KEYBOARD.5` `AnsiToOem` copies the string into the destination, ANSI (1252) to OEM (437), and returns `-1`. Its pop, 8, is in the table. `AX = 1` copied nothing, so the book's path was whatever TB80BAS's stack buffer held.
- `InitTask` makes the PSP command tail ASCIIZ, the way Windows does: the carriage return after the book name becomes a NUL. TB80RTM's C startup passes the tail to WinMain as `lpCmdLine`, and its name parser stopped only at space, tab or NUL, so the book open asked for `fixture.tbk\r`.
- `OpenFile` fills the caller's `OFSTRUCT` (`cBytes` 136, `nErrCode`, the qualified `szPathName`) and honours two styles: `OF_PARSE` returns 0 and opens nothing, `OF_EXIST` closes the file again. A relative name is qualified with `C:\TOOLBOOK\`, the directory `GetModuleFileName` already reports.
- `KERNEL.166` `WinExec` stops the run and quotes the command line. It is the wall of item 27: TB80BAS starts its book file manager, `TB80NET.EXE`, as a second task, and `known-bugs.md` says what the way past would take.
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
- `render.html` marks its theme on `<body data-theme="…">`. An unknown `--theme` is drawn and marked as `default`.
- The reader no longer imports the host. `resolve()` and `new_debug_dir()` moved from `run.py` to `cli.py`, which imports neither `unicorn` nor pass 06. `python3 -m tbpipeline_bf.runtime` runs without `unicorn` installed. `run.py` imports them from there.
- A kind-04 polygon is placed by the bounds its record names, four twip words at `+0x12`: left, top, right, bottom. On `9e954d01.tbk` they equal the box of the points for all 95 polygons the reader keeps, and for the one on `nida81.tbk`. Kind-01 records do not carry bounds at those offsets. Fields and buttons are still not placed.

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
