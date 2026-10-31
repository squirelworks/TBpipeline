# The book

A lesson file is not a PE image. It is a Click2learn shell.

| Offset | What |
|---|---|
| `0x000` | `0xC00` bytes of stub |
| `0xC00` | The book, if the dword there is `0x22222222` |
| marker | `ZZZTBKBOOKLOC` names that location |

`runtime/tbk.py` looks for the magic at `0xC00`, then for the magic anywhere if the stub is not the usual length. Pages are the records that start:

```
80 65 00 05 00 02 02
```

The page name is a C string at record offset `0x0B`. Widgets inside a page are `14 00 00` chunks. Field text is a `Text` property: the bytes `Text\0\0`, a length, then the characters. A quoted page id in the record (`"P1292"`) is a jump the reader can follow without running a handler.

`.tbk` and `.sbk` are the same container. The extension is the role, not the format. A lesson is a `.tbk`. A system book (`tb80r.sbk`, `tb80hyp.sbk`) is a `.sbk`. Both can carry the `0xC00` shell and the same page marker. System books also hold the shared handlers the lessons call.

`nida81.tbk`, opened with `--open`, is 43 pages and 100 handlers whose names are still plain text in the file. `P20000` is:

```
to handle buttonClick
  system lastbook
  lastbook = name of this book
  system nextpage
  nextpage = name of this page
  go to page "P20001" of book "nida81.tbk"
end
```

Many later pages do not name the next page. They say `go to page (nextpage) of book (lastbook)`. That is a return, not the lesson order. `--open` reports the quoted target when there is one, and `-` when the only jump is through those variables.

## What the reader can draw

Curves that are already decoded use marker `14 00 00`, a fill at `+4`, a count at `+0x1A`, and twip pairs at `+0x22`. The screen coordinate is twips divided by 15. Each curve is its own file under `render/`. A kind-04 polygon (`+0x0C = 04 00`) is also drawn in `render.html` as SVG at those twips / 15 from the page's top-left corner. The runs found by length, like P420's flame, are only files. The record-to-bounds step was never found, so a widget is known to exist and not known to sit anywhere.

`runtime/debug/resources.py` copies pictures that are already Windows bitmaps. ToolBook's own compressed pictures stay in the book. `TB80BMP` ordinal 3 (`TBKBITMAP`) is the decoder. The probe calls it and stops at the unbound far call `0x1FCD`. The reader does not call it.

Stage 2b says `render/ N pages with a drawing`. Stage 2c says `render/ M PNG files`. Stage 2b also says `placed K polygons on J pages, at record twips / 15`. On `nida81.tbk` those are 18 and 23, because P420 has four curves. The numbers differ and each line says which count it is.

`render.html` is written only with `--dbgrender`. `--theme default` is a Windows 95 window. `--theme modern` is the dark reader. `--render old` also writes `render-old.html`. Each run gets `tbpipeline_bf/_debug/db-YYYYMMDD-HHMMSS/` so a later run does not erase the log.
