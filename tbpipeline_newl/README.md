# tbpipeline_newl

Bare Windows, with a CPU.

ToolBook modules are loaded and call each other. `KERNEL` and `USER` are not. Those calls go to the layer. A call the layer does not know stops the run. The stop reads `gap KERNEL.999 far call at 0x8:0x5`: module, ordinal, the name when the layer or the import has one, and the CS:IP of the `call far`. When the call is not a direct `9A` call, the stop gives the return address instead and says `returning to`.

```
python3 -m tbpipeline_newl --b ~/TBK/bin --c book.tbk
```

When the guest calls `OpenFile` or `_lopen` on a path ending in `.tbk` or `.sbk`, the handle is the `--c` book. `_llseek` and `_lread` on that handle move through the book's bytes. Without `--c`, that open stops the run: `OpenFile NAME: no book on the command line (--c)`. Any other path still gets a handle with nothing behind it, and `_lread` on it returns 0.

`--list` prints the import report and does not start the CPU. It also counts the `TB80BAS` imports that have a name, by layer: `HEAP`, `STACK`, `RESMGR`, `CDB`, `OBJ`, or other. The name is the import's own, or the export name in `TB80BAS.DLL` when that file is in `--b`. An import with neither is counted as unnamed. The count does not answer the call. The export stays in the DLL.

Running the CPU needs `unicorn`. `--list` does not.

A run that ends without a gap says how it ended. `hlt at CS:IP` means a halt. `instruction cap 1000000 reached at CS:IP` and `time cap 15 s reached at CS:IP` mean the run hit one of the caps. A cap stop also says how many Windows calls were taken and which was last, or says `no Windows call taken`. The caps stay where they are.
