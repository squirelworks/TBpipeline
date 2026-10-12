# Planned milestones

## v1.0.1

The work that was waiting after r3.

- The 606 `TB80BAS` ordinals. Ordinal 1 is startup. The painters are later ordinals. Bind the ones that draw and call them the way ordinal 3 of `TB80BMP` is called.
- The RTM open. Pass 06 reaches DOS exit 0 after `TB80.INI` and does not open the book. `v1.0.1` gets a `.tbk` handle into `OpenFile`, or records the call that still refuses it.
- Widget bounds. The record-to-bounds step was never found. A page should know where a widget sits, not only that it exists.
- A handler that is more than a quoted `P…`. Navigation is the quoted page id. `v1.0.1` runs one real handler.
- Place the known polygons. P430 is decoded: `14 00 00`, `+0x0c = 04 00`, fill at `+4`, count at `+0x1a`, twip pairs at `+0x22`, screen is twips / 15. They are drawn into `render/` and not placed. `v1.0.1` puts them on the page.

## v2.0.0

Total functionality. Not a patch.

- The ToolBook window, without a VM. `TB80RUN` launches `TB80NET`, which loads `TB80RTM`, which opens the book.
- A `render.html` that reproduces a book: text, polygons, pictures, and widget bounds, in place.
- Pictures. `TB80BMP` decodes the ones that are not already Windows BMPs. The `0x1FCD` call is bound and a DIB comes out.
- OpenScript. A click runs the handler, not a quoted page id.
- Quizzes score. System books load. A lesson opens from the menu.
- WinXP is the preferred check. Win98 is the decompile machine. Win11 and Linux are where it runs.

`v2.0.0` is the goal. It is not scheduled.
