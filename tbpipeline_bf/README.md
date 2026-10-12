# TBpipeline 1.0.0r6

Reads a ToolBook II 8.1 book and writes a page reader. It does not need a VM. It is not the ToolBook window. Why the 16-bit host exists anyway is `WHY.md`.

```
python3 -m tbpipeline_bf --b ~/TBK/bin --c ~/TBK/bin/courses/9e954d01.tbk
```

`--b` is the ToolBook directory. Default is `bin/` beside this package. `--c` is the book. A bare filename is looked up in `--b/courses/`.

```
python3 -m tbpipeline_bf 9e954d01.tbk
python3 -m tbpipeline_bf --b ~/TBK/bin --c 9e954d01.tbk --theme modern
python3 -m tbpipeline_bf --b ~/TBK/bin --c 9e954d01.tbk --render old
```

`--theme default` is a Windows 95 window. `--theme modern` is the dark reader. `--dbgrender` is the only way to write the reader. `--render old` also writes `render-old.html`.

Needs Python 3. The 16-bit stage needs `unicorn` (`pip install -r requirements.txt`). Linux or Windows.

## Modules

`runtime/`, `runtime/debug/`, `nehost/`, and `nedllhost/` live inside this package. Each runs on its own.

```
python3 -m tbpipeline_bf.runtime --b ~/TBK/bin --c 9e954d01.tbk
python3 -m tbpipeline_bf.runtime.debug --b ~/TBK/bin --c 9e954d01.tbk
python3 -m tbpipeline_bf.nehost --unpack TB80RTM.EXE -o unpacked.exe
python3 -m tbpipeline_bf.nedllhost --b ~/TBK/bin
```

The OPTLOADER unpacker follows moralrecordings' `optloader.py`: https://github.com/moralrecordings/win16-debug

## Stages

Each run writes its own folder beside the script: `tbpipeline_bf/_debug/db-YYYYMMDD-HHMMSS/`. Not the directory you ran the command from.

1. **Startup.** SoftICE load order. A module is on disk if its file is in `--b`.
2. **Launch.** `TB80RUN` hands off with `WinExec("TB80NET.EXE <book>")`. The 16-bit host enters `TB80RTM` at segment 2 offset `0x35A`. `USER.266` is `SetMessageQueue` and returns 1.
3. **2a. Open and process.** Only with `--dbgrender`.
4. **2b. Render.** Only with `--dbgrender`. Writes `render.html`. `--render old` also writes `render-old.html`.
5. **2c.** Only with `--dbgrender`. Says the debug folder is there.

| File | What it is |
|---|---|
| `01_startup.txt` | Modules on disk |
| `02_launch.txt` | Where the 16-bit entry stopped |
| `02a_process.txt` | Book magic, page count, first pages |
| `02b_render.txt` | Theme and the two readers |
| `02c.txt` | The prompt |
| `render.html` | Engine reader: `go`, `next`, `back`, `buttonClick` |
| `render-old.html` | Old index reader, only with `--render old` |
| `render/` | Shapes that can be drawn but are not placed in `render.html` |
| `resources/` | BMPs the book holds that the reader cannot place |
| `bmp_bitmap.txt` | The `TB80BMP` ordinal 3 stop |
| `dll_probe.txt` | Ordinal 1 of every DLL, `FFFF` bound |
| `scaffold.txt` | The ordinal walk. The big one. |

## Scope

This cut is 1.0.0r6. The reader is written only with `--dbgrender`. The host still exits before a book open.

`render/` holds shapes that can be drawn and are not placed, one file per curve. `resources/` holds the BMPs the book already has. Two buttons under the reader show them. The probe logs are copied into the debug run.


Known bugs are in `known-bugs.md`. The plan is `plannedmilestones.md`. `v1.0.1` is the work that was waiting. `v2.0.0` is total functionality.

WinXP is the preferred VM. Win98 is fine and is the decompile machine. Win11 and Linux are where it should eventually run.

## What it will not do

- Open the book from the engine.
- Draw widget bounds or ToolBook compressed pictures.
- Execute a handler. Navigation is the quoted page id, not the bytecode.
- Pop the ToolBook GUI.
