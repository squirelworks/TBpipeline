# runtime

Reads a ToolBook II 8.1 `.tbk`.

| File | What it is |
|---|---|
| `tbk.py` | The book loader. Stays here. |
| `engine.py` | The page walker. `render.html` uses its verbs. |
| `debug/` | Stage 2a, 2b, 2c. The HTML readers. |

Nothing here imports `run.py`, `nehost/`, `nedllhost/`, `unicorn`, `tbpipeline_newl`, or `tbpipeline_neww`. The arguments come from `../cli.py`. A test reads every import.

```
python3 -m tbpipeline_bf.runtime --b ~/TBK/bin --c 9e954d01.tbk
```

That runs `runtime/debug`. It writes the reader only with `--dbgrender`, into `tbpipeline_bf/_debug/db-YYYYMMDD-HHMMSS/`.
