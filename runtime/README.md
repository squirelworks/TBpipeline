# runtime

Reads a ToolBook II 8.1 `.tbk` and writes an HTML reader. It does not run OpenScript.

```
python3 -m tbpipeline.runtime --b ~/TBK/bin --c ~/TBK/bin/courses/9e954d01.tbk
```

A bare filename is looked up in `--b/courses/`. Default `--b` is `bin/` under the current directory.

Writes `render.html` in the current directory.
