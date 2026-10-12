# runtime

Reads a ToolBook II 8.1 `.tbk`.

| File | What it is |
|---|---|
| `tbk.py` | The book loader. Stays here. |
| `engine.py` | The page walker. `render.html` uses its verbs. |
| `debug/` | Stage 2a, 2b, 2c. The HTML readers. |

```
python3 -m tbpipeline_bf.runtime --b ~/TBK/bin --c 9e954d01.tbk
```

That runs `runtime/debug`. It writes the reader only with `--dbgrender`, into `tbpipeline_bf/_debug/db-YYYYMMDD-HHMMSS/`.
