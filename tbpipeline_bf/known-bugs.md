# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu1.DLL`, then parses the book name with `OpenFile(..., OF_PARSE)`. Every open is logged in `opens`. Only a `.tbk` or `.sbk` gets a handle. Nothing is rendered unless you pass `--dbgrender`.

## The wall: TB80W16 needs TB80W32.DLL through the generic thunks

This is where the bf host sequence of item 27 stops. TB80BAS segment 45 `0x32` starts the book file manager with `WinExec("TB80NET.exe ToolBook", 2)`, checks the result is above 32, and then requires the word at its `DS:0x37C` to be non-zero. That word is written only by TB80BAS segment 45 `0x68`, an entry the new task calls with its window. So the book file manager is a second Win16 task talking to the runtime through a shared DLL and window messages.

Pass 06 runs it. WinExec loads `TB80NET.EXE` from `TBK_UNPACKED` beside the runtime, binds its imports to the DLLs already loaded, and switches the CPU to it (`_run_tasks` in `nedllhost/pass06.py`). With `USER.471` `lstrcmpi` answered, TB80NET matches its command line `ToolBook`, creates its window, calls TB80BAS segment 45 `0x68` (which registers its window message), shows the window and blocks in `GetMessage`. WinExec then returns its instance to TB80BAS. `int 2Fh AX = 150Bh`, TB80BAS's MSCDEX drive check, finds no MSCDEX. The runtime then opens `C:\TOOLBOOK\fixture.tbk`. With the unpacked binaries, pass 06 now runs to the 4,000,000-instruction cap and says `returned`.

`LoadLibrary("KERNEL")` returns KERNEL's handle, as it does in Windows. The run still ends at the cap, in a loop of about 2,800 calls:

1. TB80W16 segment 8 `0x7C0` loads `KERNEL`. Segment 8 `0x836` then calls `GetProcAddress(hKernel, 513)`. `KERNEL.513` is `LoadLibraryEx32W`, the first of the Windows 95 and NT generic thunk calls (`513` `LoadLibraryEx32W`, `514` `FreeLibrary32W`, `515` `GetProcAddress32W`, `516` `GetVDMPointer32W`, `517` `CallProc32W`).
2. The host's KERNEL has no exports and answers 0, which is what Windows 3.1 answers.
3. TB80W16 reports the failure through TB80BAS segment 51. That report reaches segment 8 again, and the loop repeats.

TB80W16's data segment names the target: `TB80W32.DLL`, with `InitilizeW32to16`, `ShutdownW32to16`, `strlen32W`, `CreateMutex32`, `ReleaseMutex32`, `WaitForSingleObject32`, `StartTbkBreakThread`, `ShutdownTbkBreakThread` and the `OSSTRING32_*` conversions. It also asks `WOW32.DLL` for `WOWHandle16` and `WOWHandle32`. `TB80W32.DLL` is a 32-bit PE DLL in the bin directory, so ToolBook 8.1 expects Windows 95 or NT, and part of the runtime is 32-bit code.

The way past is a decision, not an ordinal. One option is to run `TB80W32.DLL` as 32-bit code in the same CPU, with a PE loader and a 32-bit code segment, and give it the KERNEL32 calls it imports. The other is to answer the `TB80W32` entries from the host by name, as the host answers the 16-bit ordinals.
