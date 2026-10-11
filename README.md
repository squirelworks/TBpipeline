# TBpipeline 1.0.0r2

Reads a ToolBook II 8.1 book and writes a page reader. It does not need a VM. It is not the ToolBook window.

```
python3 -m tbpipeline --b ~/TBK/bin --c ~/TBK/bin/courses/9e954d01.tbk
```

`--b` is the ToolBook directory. `--c` is the book. A bare filename is looked up in `--b/courses/`.

```
python3 -m tbpipeline 9e954d01.tbk
python3 -m tbpipeline --b ~/TBK/bin --c 9e954d01.tbk --theme modern
python3 -m tbpipeline --b ~/TBK/bin --c 9e954d01.tbk --render old
```

`--theme default` is a Windows 95 window. `--theme modern` is the dark reader. `--debug` forces the reader even if stage 2 opened the book. `--render old` also writes `render-old.html`.

Needs Python 3. The 16-bit stage needs `unicorn` (`pip install -r requirements.txt`). Linux or Windows.

## Modules

`runtime/`, `runtime/debug/`, `nehost/`, and `nedllhost/` live inside this package. Each runs on its own.

```
python3 -m tbpipeline.runtime --b ~/TBK/bin --c 9e954d01.tbk
python3 -m tbpipeline.runtime.debug --b ~/TBK/bin --c 9e954d01.tbk
python3 -m tbpipeline.nehost --unpack TB80RTM.EXE -o unpacked.exe
python3 -m tbpipeline.nedllhost --b ~/TBK/bin
```

The OPTLOADER unpacker follows moralrecordings' `optloader.py`: https://github.com/moralrecordings/win16-debug

## Stages

Each run writes its own folder beside the script: `tbpipeline/_debug/db-YYYYMMDD-HHMMSS/`. Not the directory you ran the command from.

1. **Startup.** SoftICE load order. A module is on disk if its file is in `--b`.
2. **Launch.** `TB80RUN` hands off with `WinExec("TB80NET.EXE <book>")`. The 16-bit host enters `TB80RTM` at segment 2 offset `0x35A`. `USER.266` is `SetMessageQueue` and returns 1.
3. **2a. Open and process.** Debug route, in `runtime/debug`. Off unless stage 2 failed to open the book, or you passed `--debug`.
4. **2b. Render.** Off with 2a. Writes `render.html`. `--render old` also writes `render-old.html`.
5. **2c.** Says the debug folder is there.

| File | What it is |
|---|---|
| `01_startup.txt` | Modules on disk |
| `02_launch.txt` | Where the 16-bit entry stopped |
| `02a_process.txt` | Book magic, page count, first pages |
| `02b_render.txt` | Theme and the two readers |
| `02c.txt` | The prompt |
| `render.html` | Engine reader: `go`, `next`, `back`, `buttonClick` |
| `render-old.html` | Old index reader, only with `--render old` |
| `RUN.txt` | The whole run |

## Scope

This cut is the reader, split and polished. It does not draw the book.

`render.html` has the page text and the quoted `P…` jumps. It does not have the pictures, the polygons, or the widget bounds. Graphics are the next goal.

`2.0.0` is total functionality. It is not this release.

WinXP is the preferred VM. Win98 is fine and is the decompile machine. Win11 and Linux are where it should eventually run.

## What it will not do

- Open the book from the engine.
- Draw widget bounds or ToolBook compressed pictures.
- Execute a handler. Navigation is the quoted page id, not the bytecode.
- Pop the ToolBook GUI.
