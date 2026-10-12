# tbpipeline_newl

Bare Windows, with a CPU.

ToolBook modules are loaded and call each other. `KERNEL` and `USER` are not. Those calls go to the layer. A call the layer does not know stops the run.

```
python3 -m tbpipeline_newl --b ~/TBK/bin
```

`--list` prints the import report and does not start the CPU. Needs `unicorn`.
