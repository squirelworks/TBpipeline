# OpenScript

Handlers in a `.tbk` or `.sbk` are not stored as source. `TB80CMP` compresses them. The expander is `COMPILEREXPANDTEXT`, `FUN_1040_0970`. `tbpipeline_bf/runtime/expand.py` is that function. The keyword table is resource `0x77` from `TB80CMP`, shipped as `runtime/compat/res_77.bin`.

## The bytes

| Range | Meaning |
|---|---|
| `00`–`7F` | A literal byte |
| `80`–`BF` | A keyword. Bit 4 selects a two-byte index. Bit 5 clear means a trailing space |
| `C0`–`CF` | A short back-reference. Length is `(byte & 0xF) + 3` |
| `D0`–`DF` | A long back-reference. Length is `(byte & 0xF) + 4`. The next word is the distance |
| `E0`–`EF` | A newline and 0–15 spaces |
| `F0`–`FE` | 2–16 spaces |
| `FF` | The next byte, repeated |

A back-reference copies bytes from the compressed input, not from the output. The distance is often negative past the start of the handler. The copied bytes are a phrase that already sits in an earlier handler: `INT `, `linkDLL "`, `WORD `, a function name. The copy starts in the middle of that handler, not at `to handle`.

That is text reuse. It is not a call. OpenScript calls another handler by writing the name (`ASYM_BlockSuspend()`). The compressor stores the second copy of those letters by pointing at the first. The call, when there is one, is still the text.

Decoding a slice fails when the distance lands before the slice. The expander has to see the whole file. A copy that lands outside the whole file is still written as `?`, and `decompress(..., misses=[])` records where. `--open` lists those handlers under `unread`, so a handler the expander could not read is reported, not skipped. `origin` is where this handler starts. `span` is how far its own bytes go. The back-reference may read anywhere in the file.

A `?` left in the expanded text is the character `?`. It shows up in sentences (`Right?`), in character lists (`.,;:?!`), and in tests (`chr = "?"`). It is not a function marker. A handler that begins with a stray `?` and a newline was scanned one byte early.

## What `--open` does

```
python3 -m tbpipeline_bf --open book.tbk
python3 -m tbpipeline_bf --open book.tbk --page P20000
```

It loads the pages, finds `to handle` as plain text, and expands each one against the whole file. It prints the page map and, with `--page`, the handler source. Each `click` line is the page, the handler that ran and its offset in the file, and the page it landed on. It does not start Unicorn.

That search finds a handler whose name is still plain text, which is how a lesson is stored. A system book compresses the name too. Those streams start with the keyword opcodes for `to handle` (`80 81`) or `to get` (`80 90 AD`). `--open` expands those as well and lists them under `scripts` when they do not sit inside a page record. `--page scripts` prints the name and the offset, not the whole body.

## What still does not run

`runtime/engine.py` runs the navigation in that source. A `buttonClick` may set `name of this book` and `name of this page`, then `go to page "P"` or `go to page (nextpage)`. On `nida81.tbk`, clicking `P20000` lands on `P20001` because the handler says so. The same steps are what the buttons in `render.html` run. `next` and `back` do the same with a page's `to handle next` and `to handle previous` (or `back`); a page without one moves through the page list. Anything past that subset is still not executed.
