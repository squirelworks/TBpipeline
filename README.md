# Pipeline host

Linux or Windows. This command does not need a VM. It needs Python 3 and `unicorn` for the 16-bit stage.

```
python3 -m tbpipeline --b ~/TBK/bin --c ~/TBK/bin/courses/9e954d01.tbk
```

`--b` is where the ToolBook executables are. `--c` is the book. A bare filename is looked up in `--b/courses/`.

```
python3 -m tbpipeline 9e954d01.tbk
```

That uses `bin/` under the repo root as `--b`, and opens `bin/courses/9e954d01.tbk`.

`runtime/`, `nehost/`, and `nedllhost/` live inside `tbpipeline/`. Nothing else has to sit beside it. Each one runs on its own. See its `README.md`.

```
python3 -m tbpipeline.runtime --b ~/TBK/bin --c 9e954d01.tbk
python3 -m tbpipeline.nehost --unpack TB80RTM.EXE -o unpacked.exe
python3 -m tbpipeline.nedllhost --b ~/TBK/bin
```

The OPTLOADER unpacker in `nehost/unpack_optloader.py` follows moralrecordings' `optloader.py`: https://github.com/moralrecordings/win16-debug

## What it writes

All three land in `tbpipeline/`.

Each stage writes its own file into `.debug/` as it finishes. The last stage only tells you the debug information is there.

| File | Stage |
|---|---|
| `.debug/01_startup.txt` | Modules on disk |
| `.debug/02_launch.txt` | Where the 16-bit entry stopped |
| `.debug/03_process.txt` | Book magic, page count, first pages |
| `.debug/04_render.txt` | Render note |
| `.debug/render.html` | The pages |
| `.debug/RUN.txt` | The whole run |

## The five stages

1. **Startup.** SoftICE load order. A module is on disk if its file is in `unpacked/`, or in `$TBK_UNPACKED`.
2. **Launch.** `TB80RUN` hands off with `WinExec("TB80NET.EXE <book>")`. The 16-bit host enters `TB80RTM` at segment 2 offset `0x35A`. `USER.266` is `SetMessageQueue` and returns 1.
3. **Open and process.** Book magic `0x22222222`, page count, first three pages with text. On `9e954d01.tbk` the magic is at `0x9EC`.
4. **Render.** Writes `.debug/render.html` and `.debug/04_render.txt`.
5. **Last.** Prompts that debug information is available in `.debug/`.

## What it will not do

- The engine does not open the book. After `SetMessageQueue` it skips a far call to `FFFF:0158`.
- It does not draw widget bounds or ToolBook compressed pictures.
- It does not execute a handler. Navigation is the quoted page id, not the bytecode.
- WineVDM is a separate Windows program. This command does not call it.
