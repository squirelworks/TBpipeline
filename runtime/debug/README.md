# runtime/debug

The debug route for the book reader.

| File | Stage |
|---|---|
| `__init__.py` | 2a opens the book, 2b writes `render.html`, 2c says the files are there |
| `play.py` | `render_old` is the current reader. `render_new` walks the book with `engine.py`. |

Off unless stage 2 failed to open the book, or you passed `--debug`.

```
python3 -m tbpipeline.runtime.debug --b ~/TBK/bin --c 9e954d01.tbk
```

Writes `tbpipeline/_debug/db-YYYYMMDD-HHMMSS/`, beside the package. Not the working directory.
