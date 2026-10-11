# runtime/debug

The debug route for the book reader. Stage 2a opens the book, stage 2b writes `render.html`, stage 2c says the files are there.

Off unless stage 2 failed to open the book, or you passed `--debug`.

```
python3 -m tbpipeline.runtime.debug --b ~/TBK/bin --c 9e954d01.tbk
```

Writes `_debug/` in the current directory.
