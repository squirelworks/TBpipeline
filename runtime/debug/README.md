# runtime/debug

The debug route for the book reader.

| File | Stage |
|---|---|
| `__init__.py` | 2a opens the book, 2b writes `render.html`, 2c says the files are there |
| `play.py` | The HTML reader, with the page dropdown |

Off unless stage 2 failed to open the book, or you passed `--debug`.

```
python3 -m tbpipeline.runtime.debug --b ~/TBK/bin --c 9e954d01.tbk
```

Writes `_debug/` in the current directory.
