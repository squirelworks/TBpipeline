# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu1.DLL`, then parses the book name with `OpenFile(..., OF_PARSE)`. Every open is logged in `opens`. Only a `.tbk` or `.sbk` gets a handle. Nothing is rendered unless you pass `--dbgrender`.

## The wall: KERNEL.166 WinExec("TB80NET.exe ToolBook", 2)

This is where the bf host sequence of item 27 stops. With the unpacked binaries, pass 06 now stops on:

```
winexec 'TB80NET.exe ToolBook' show 2
```

TB80BAS segment 45 `0x32` starts the book file manager with that call, checks the result is above 32, and then requires the word at its `DS:0x37C` to be non-zero. That word is written only by TB80BAS segment 45 `0x68`, an entry the new task calls with its window, which then registers a window message. So the book file manager is a second Win16 task, `TB80NET.EXE`, talking to the runtime through a shared DLL and window messages. Answering `AX = 1` made it an error code and the runtime said "Failed initializing the book file manager. Make sure the file TB80NET.EXE is available in your PATH."

The way past a missing EXE is still a stop, not an ordinal answer. An EXE that is in the unpacked directory is loaded as a second task in this CPU, and `WinExec` returns its instance once that task yields. `SendMessage` calls that window's procedure. A missing `TB80NET.EXE` still stops here and quotes the command line.
