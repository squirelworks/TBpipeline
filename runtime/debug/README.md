# runtime/debug

The debug route for the book reader. Off unless stage 2 failed to open the book, or you passed `--debug`.

| File | What it is |
|---|---|
| `__init__.py` | 2a opens the book, 2b writes the readers, 2c says the folder is there |
| `play.py` | `render.html` is the engine reader. `render-old.html` is written only with `--render old`. |

```
python3 -m tbpipeline.runtime.debug --b ~/TBK/bin --c 9e954d01.tbk
```

Writes `tbpipeline/_debug/db-YYYYMMDD-HHMMSS/`, beside the package. Not the working directory.
