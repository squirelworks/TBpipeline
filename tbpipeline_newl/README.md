# tbpipeline_newl

Bare Windows, with a CPU.

ToolBook modules are loaded and call each other. `KERNEL` and `USER` are not. Those calls go to the layer. A call the layer does not know stops the run.

```
python3 -m tbpipeline_newl --b ~/TBK/bin
```

`--list` prints the import report and does not start the CPU. It also counts the `TB80BAS` imports that have a name, by layer: `HEAP`, `STACK`, `RESMGR`, `CDB`, `OBJ`, or other. The name is the import's own, or the export name in `TB80BAS.DLL` when that file is in `--b`. An import with neither is counted as unnamed. The count does not answer the call. The export stays in the DLL.

Running the CPU needs `unicorn`. `--list` does not.
