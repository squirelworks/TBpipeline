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

## Roadmap

Tick a box when its PR merges. The issues hold the detail.

- [x] [Roadmap #201](https://github.com/squirelworks/TBpipeline/issues/201), T0 to T9. Complete, released as `neww-v0.5.0`
- [x] [#221](https://github.com/squirelworks/TBpipeline/issues/221): metafile playback and `MM_ANISOTROPIC`. The NIDA ATT course `93952606.TBK` now walks past P430 to its Lesson Menu
- [x] [#225](https://github.com/squirelworks/TBpipeline/issues/225): Wingdings and Symbol-font characters (bullets, π) through the symbol faces Wine installs and the course's own `nida.ttf`
- [x] [#226](https://github.com/squirelworks/TBpipeline/issues/226): the rest of `93952606.TBK`. The Final Quiz runs to its score page, the lesson opens from the menu, and Lesson Exit unloads ToolBook's DLLs
- [x] [#233](https://github.com/squirelworks/TBpipeline/issues/233): OLE automation objects and the 32-bit DLL unload. Lesson Exit now ends the task cleanly
- [ ] The other NIDA ATT courses: on hold until the week of 2026-11-09

[documentation/future.md](documentation/future.md) has the longer list. [CURSOR.md](CURSOR.md) is the handover note for Cursor (2026-11-08).
