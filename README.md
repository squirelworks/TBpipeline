# TBpipeline 1.0.0r1

Reads a ToolBook II 8.1 book and writes a page reader. It does not need a VM. It is not the ToolBook window.

```
python3 -m tbpipeline --b ~/TBK/bin --c ~/TBK/bin/courses/9e954d01.tbk
```

`--b` is the ToolBook directory. `--c` is the book. A bare filename is looked up in `--b/courses/`.

```
python3 -m tbpipeline 9e954d01.tbk
```

Needs Python 3. The 16-bit stage needs `unicorn` (`pip install -r requirements.txt`). Linux or Windows.

## Modules

`runtime/`, `nehost/`, and `nedllhost/` live inside this package. Each runs on its own.

```
python3 -m tbpipeline.runtime --b ~/TBK/bin --c 9e954d01.tbk
python3 -m tbpipeline.nehost --unpack TB80RTM.EXE -o unpacked.exe
python3 -m tbpipeline.nedllhost --b ~/TBK/bin
```

The OPTLOADER unpacker follows moralrecordings' `optloader.py`: https://github.com/moralrecordings/win16-debug

## Stages

Each stage writes its file into `.debug/` as it finishes. The last stage tells you the debug information is there.

1. **Startup.** SoftICE load order. A module is on disk if its file is in `--b`.
2. **Launch.** `TB80RUN` hands off with `WinExec("TB80NET.EXE <book>")`. The 16-bit host enters `TB80RTM` at segment 2 offset `0x35A`. `USER.266` is `SetMessageQueue` and returns 1.
3. **Open and process.** Book magic `0x22222222`, page count, first pages with text.
4. **Render.** Writes `.debug/render.html`.
5. **Last.** Prompts that debug information is available in `.debug/`.

| File | Stage |
|---|---|
| `.debug/01_startup.txt` | Modules on disk |
| `.debug/02_launch.txt` | Where the 16-bit entry stopped |
| `.debug/03_process.txt` | Book magic, page count, first pages |
| `.debug/04_render.txt` | Render note |
| `.debug/render.html` | The pages |
| `.debug/RUN.txt` | The whole run |

## Scope of 1.0.0r1

This release reads a book and writes a page reader. It does not draw the book.

`render.html` has the page text and the quoted `P…` jumps. It does not have the pictures, the polygons, or the widget bounds.

2.0.0 is total functionality. We are not there. The next goal is a `render.html` that faithfully reproduces a book, especially the graphics. That needs more of the book format and more of the decompile.

WinXP is the preferred VM. Win98 is fine and is the decompile machine. Win11 and Linux are where it should eventually run.

## What 1.0.0r1 will not do

- Open the book from the engine.
- Draw widget bounds or ToolBook compressed pictures.
- Execute a handler. Navigation is the quoted page id, not the bytecode.
- Pop the ToolBook GUI.
