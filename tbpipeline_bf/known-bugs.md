# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu1.DLL`, then parses the book name with `OpenFile(..., OF_PARSE)`. Every open is logged in `opens`. Only a `.tbk` or `.sbk` gets a handle. Nothing is rendered unless you pass `--dbgrender`.

## The wall: int 0x2F AX = 0x150B in TB80BAS

This is where the bf host sequence of item 27 stops. TB80BAS segment 45 `0x32` starts the book file manager with `WinExec("TB80NET.exe ToolBook", 2)`, checks the result is above 32, and then requires the word at its `DS:0x37C` to be non-zero. That word is written only by TB80BAS segment 45 `0x68`, an entry the new task calls with its window. So the book file manager is a second Win16 task talking to the runtime through a shared DLL and window messages.

Pass 06 runs it. WinExec loads `TB80NET.EXE` from `TBK_UNPACKED` beside the runtime, binds its imports to the DLLs already loaded, and switches the CPU to it (`_run_tasks` in `nedllhost/pass06.py`). With `USER.471` `lstrcmpi` answered, TB80NET matches its command line `ToolBook`, creates its window, calls TB80BAS segment 45 `0x68` (which registers its window message), shows the window and blocks in `GetMessage`. WinExec then returns its instance to TB80BAS. With the unpacked binaries, pass 06 stops on:

```
stopped 0x760:0x57f 81fbadad74 int 0x2f
task: winexec 'TB80NET.exe ToolBook' started TB80NET instance 0x12e0
task: TB80NET yielded at USER.108
```

TB80BAS segment 2 `0x56B` asks MSCDEX whether a drive is a CD-ROM: `int 2Fh` with `AX = 0x150B`, `CX` the drive, and `BX = 0xADAD` back if MSCDEX is there. The host has no `int 2Fh`. The next behavior is that call.
