# The three trees

They stay separate. A fix in one is not a fix in the others. Run a module from the repository root.

| Directory | Version | What it claims |
|---|---|---|
| `tbpipeline_bf` | 1.0.0r6 | The reader, plus a host that answers a missing call with `AX = 1` and keeps going |
| `tbpipeline_newl` | none | The same modules on a CPU. `KERNEL` and `USER` are a layer. A call the layer does not know stops the run |
| `tbpipeline_neww` | none | Every unpacked NE file in one address space. System calls are gates. An ordinal with no contract stops the run. The pop size is not guessed |

```
python3 -m tbpipeline_bf --open book.tbk
python3 -m tbpipeline_bf --b ~/TBK/bin --c book.tbk --dbgrender
python3 -m tbpipeline_newl --b ~/TBK/bin
python3 -m tbpipeline_neww --b ~/TBK/bin
```

## bf

Two programs in one package.

`runtime/` answers the book question. `tbk.py` loads pages. `engine.py` is the verb list the HTML reader calls: `go`, `next`, `back`, `buttonClick`. `runtime/openbook.py` expands handlers. `runtime/debug/` writes `render.html`, and only when `--dbgrender` is passed. A launch that exits does not draw a page.

`nehost/` and `nedllhost/` answer the runtime question. Pass 06 maps six DLLs, starts at segment 2 offset `0x35A`, and currently exits after asking for `TB80.INI`. The detail is [WHY.md](../tbpipeline_bf/WHY.md).

`--open` does not start the CPU. That split is the point. The book format is knowable without executing `TB80RTM`.

## newl

Bare Windows under the real code. ToolBook modules are loaded and call each other. `KERNEL`, `USER`, and `WIN87EM` are not files. They are the table in `layer.py`. Anything absent from that table raises `Gap` and the run ends.

`--list` prints the import report and does not start the CPU. The CPU is Unicorn in 16-bit protected mode. This tree does not return 1 for an unknown ordinal. That is the difference from `bf`.

It has not opened a book. The last wall was inside startup, before `OpenFile` of the `.tbk`. See [host.md](host.md).

## neww

The stricter sandbox. Fixups between ToolBook modules are real far calls, selector and offset. `KERNEL` and `USER` are gates: the guest calls the gate, the sandbox answers, and `retf` pops the arguments that the contract names.

An ordinal with no contract stops the run. Guessing the pop count was how `bf` walked off a stack. This tree refuses that. It is also the tree that has done the least of the actual startup. It is the shape to grow if the layer approach is the one that continues. It is not a reader.

## What is not a fourth tree

[openscript_analysis](https://github.com/squirelworks/openscript_analysis) is a sibling repository. It holds the expander, a small handler runner, and a separate path for SumTotal TBKX exports (plain-text `.script` files). `tbpipeline_bf/runtime/expand.py` is the expander the reader calls. It is not the whole of that repository, and that repository is not a TBpipeline module.
