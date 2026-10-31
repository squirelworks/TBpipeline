# TBpipeline

Three separate trees. The project record is [documentation/](documentation/).

| Directory | What it is |
|---|---|
| `tbpipeline_bf` | 1.0.0r6 reader. `python3 -m tbpipeline_bf` |
| `tbpipeline_newl` | Bare Windows layer, with a CPU |
| `tbpipeline_neww` | Wine-style Win16 sandbox |

Run a module from this directory. `tests/test_readme_commands.py` runs every `python3` line below, so a line here that stops working fails the tests.

Without ToolBook binaries:

```sh
python3 -m tbpipeline_bf --help
python3 -m tests.fixtures.book fixture.tbk
python3 -m tbpipeline_bf --open fixture.tbk
python3 -m tbpipeline_bf --open fixture.tbk --page P1
```

`fixture.tbk` is the original test book, not a lesson. Any `.tbk` works in its place.

With the ToolBook directory as `--b` (the tests read it from `TBK_BIN`, and skip these lines when it is unset):

```sh
python3 -m tbpipeline_newl --b ~/TBK/bin --list
python3 -m tbpipeline_newl --b ~/TBK/bin
python3 -m tbpipeline_neww --b ~/TBK/bin
```

The tests:

```
python3 -m unittest discover -s tests -t .
TBK_BIN=~/TBK/bin python3 -m unittest discover -s tests -t .
```
