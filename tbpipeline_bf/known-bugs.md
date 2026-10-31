# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu1.DLL`, then parses the book name with `OpenFile(..., OF_PARSE)`. Every open is logged in `opens`. Only a `.tbk` or `.sbk` gets a handle. Nothing is rendered unless you pass `--dbgrender`.

## The wall: TB80NET exits after USER.471 lstrcmpi

This is where the bf host sequence of item 27 stops. TB80BAS segment 45 `0x32` starts the book file manager with `WinExec("TB80NET.exe ToolBook", 2)`, checks the result is above 32, and then requires the word at its `DS:0x37C` to be non-zero. That word is written only by TB80BAS segment 45 `0x68`, an entry the new task calls with its window. So the book file manager is a second Win16 task talking to the runtime through a shared DLL and window messages.

Pass 06 now runs it. WinExec loads `TB80NET.EXE` from `TBK_UNPACKED` beside the runtime, binds its imports to the DLLs already loaded, and switches the CPU to it (`_run_tasks` in `nedllhost/pass06.py`). WinExec returns its instance to TB80BAS when the new task first blocks in `GetMessage`, `PeekMessage`, `WaitMessage` or `Yield`. With the unpacked binaries, pass 06 stops on:

```
TB80NET: dos exit 0x0
```

TB80NET's InitTask, heap and class registration run. Its WinMain then compares its command line with `ToolBook`, `ToolBook32` and `ToolBook16or32` (its `DS:0x28`, `0x31`, `0x3C`) through `USER.471` `lstrcmpi`. That call falls through to `AX = 1`, "not equal", for all three, so TB80NET never creates its window and exits 0. The next behavior is `lstrcmpi`.
