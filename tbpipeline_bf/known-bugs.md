# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu1.DLL`, then parses the book name with `OpenFile(..., OF_PARSE)`. Every open is logged in `opens`. Only a `.tbk` or `.sbk` gets a handle. Nothing is rendered unless you pass `--dbgrender`.

## The wall: SendMessageTimeoutA to TB80NET's window

This is where the bf host sequence of item 27 stops. TB80BAS segment 45 `0x32` starts the book file manager with `WinExec("TB80NET.exe ToolBook", 2)`, checks the result is above 32, and then requires the word at its `DS:0x37C` to be non-zero. That word is written only by TB80BAS segment 45 `0x68`, an entry the new task calls with its window. So the book file manager is a second Win16 task talking to the runtime through a shared DLL and window messages.

Pass 06 runs it. WinExec loads `TB80NET.EXE` from `TBK_UNPACKED` beside the runtime, binds its imports to the DLLs already loaded, and switches the CPU to it (`_run_tasks` in `nedllhost/pass06.py`). With `USER.471` `lstrcmpi` answered, TB80NET matches its command line `ToolBook`, creates its window, calls TB80BAS segment 45 `0x68` (which registers its window message), shows the window and blocks in `GetMessage`. WinExec then returns its instance to TB80BAS. `int 2Fh AX = 150Bh`, TB80BAS's MSCDEX drive check, finds no MSCDEX. The runtime then opens `C:\TOOLBOOK\fixture.tbk`. With the unpacked binaries, pass 06 now runs to the 4,000,000-instruction cap and says `returned`.

TB80W16 gets the Windows 95/NT generic thunks with `GetProcAddress(LoadLibrary("KERNEL"), 513..518)`: `LoadLibraryEx32W`, `FreeLibrary32W`, `GetProcAddress32W`, `GetVDMPointer32W`, `CallProc32W` and `CallProcEx32W`. With them it reaches `TB80W32.DLL`, a 32-bit PE DLL in the bin directory, at the very start of the run, before the `TB80.INI` opens. It names `InitilizeW32to16`, `strlen32W`, `CreateMutex32`, `StartTbkBreakThread` and the `OSSTRING32_*` conversions, and it uses `WOW32.DLL`.

Pass 06 runs it (`nedllhost/win32.py`). `LoadLibraryEx32W` maps the PE at its image base, `0x10000000`. It binds each import to a stub that the host answers by name, and it runs the entry point as 32-bit code on a flat code and data selector, with its own stack and TEB. `CallProc32W` and `CallProcEx32W` run an export the same way and return `EAX` in `DX:AX`. A Win32 call the host has no answer for stops the run, and the stop names it. With the unpacked binaries and `TB80W32.DLL` in `TBK_UNPACKED`, pass 06 used to stop at `win32 KERNEL32.GetVersion`, the first call of TB80W32's C runtime start-up.

`nedllhost/win32api.py` answers the start-up and the calls after it the way Windows 98 does: the C runtime's heap, environment, command line, code pages and locale, the `WOW32` pointer and handle maps, the string calls, the temp-file name, and the mutexes (one thread, so a wait is satisfied at once). An unknown locale type stops the run. The runtime goes on past the `TB80enu1.DLL` and `fixture.tbk` opens, starts TB80NET, and stops on:

```
win32 USER32.SendMessageTimeoutA
```

TB80W32 sends the book file manager its first request: `SendMessageTimeoutA(hwnd 1, msg 1, 0xA, 1178:0550, SMTO_BLOCK, INFINITE, ...)`. Both `1`s come from `AX = 1`. TB80NET's `CreateWindow` (`USER.41`) and TB80BAS's `RegisterWindowMessage` (`USER.118`) still fall through to it, as do `RegisterClass` (`USER.57`) and the 16-bit `SendMessage`. The next behavior is a window table: classes with their window procedures, windows with their task, registered message numbers from `0xC000`, and a send that calls the target window's procedure.
