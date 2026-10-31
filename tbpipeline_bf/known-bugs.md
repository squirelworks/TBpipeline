# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu1.DLL`, then parses the book name with `OpenFile(..., OF_PARSE)`. Every open is logged in `opens`. Only a `.tbk` or `.sbk` gets a handle. Nothing is rendered unless you pass `--dbgrender`.

## The wall: TB80W16 loops on LoadLibrary("KERNEL")

This is where the bf host sequence of item 27 stops. TB80BAS segment 45 `0x32` starts the book file manager with `WinExec("TB80NET.exe ToolBook", 2)`, checks the result is above 32, and then requires the word at its `DS:0x37C` to be non-zero. That word is written only by TB80BAS segment 45 `0x68`, an entry the new task calls with its window. So the book file manager is a second Win16 task talking to the runtime through a shared DLL and window messages.

Pass 06 runs it. WinExec loads `TB80NET.EXE` from `TBK_UNPACKED` beside the runtime, binds its imports to the DLLs already loaded, and switches the CPU to it (`_run_tasks` in `nedllhost/pass06.py`). With `USER.471` `lstrcmpi` answered, TB80NET matches its command line `ToolBook`, creates its window, calls TB80BAS segment 45 `0x68` (which registers its window message), shows the window and blocks in `GetMessage`. WinExec then returns its instance to TB80BAS. `int 2Fh AX = 150Bh`, TB80BAS's MSCDEX drive check, finds no MSCDEX. The runtime then opens `C:\TOOLBOOK\fixture.tbk`. With the unpacked binaries, pass 06 now runs to the 4,000,000-instruction cap and says `returned`.

The last 2,778 calls are one loop. TB80W16 segment 8 `0x7C0` calls `LoadLibrary("KERNEL")` (the name is at TB80W16 `0750:0x136`, next to `WOW32.DLL` and `WOWHandle16`). The host has no `KERNEL` file and returns 2, file not found. TB80W16 reports the failure through TB80BAS segment 51, and that report reaches the same `LoadLibrary` again. In Windows, `LoadLibrary` of a module that is already loaded, `KERNEL` included, returns its handle. The next behavior is that.
