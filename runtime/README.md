# runtime

Reads a ToolBook II 8.1 `.tbk`.

| File | What it is |
|---|---|
| `tbk.py` | The book loader. Stays here. Debug and the real path both use it. |
| `engine.py` | A page walker for later OpenScript. Unused. Not debug. |
| `debug/` | The fallback reader: stage 2a, 2b, 2c, and `play.py`. |

```
python3 -m tbpipeline.runtime --b ~/TBK/bin --c 9e954d01.tbk
```

That runs `runtime/debug` and writes `_debug/render.html`.
