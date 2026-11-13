# TBpipeline neww 0.6.0

NIDA ATT pictures draw: metafiles and map modes (#221, merged in #224).

## New since neww-v0.5.0

- **neww: map modes.** Points now go through Wine's window-to-viewport transform (`construct_window_to_viewport`, `GDI_ROUND`), so these work in every map mode: `LPtoDP`/`DPtoLP`, `GetClipBox`, the shapes, `Rectangle`, the blits (`BitBlt`, `StretchBlt`, `StretchDIBits`) and the clip rectangles. `SetMapMode` takes the metric modes' extents from the display, and `MM_ISOTROPIC` keeps a logical unit square. The window and viewport calls are in, in both forms (`SetWindowExt`/`SetWindowExtEx`, `Offset…`, `Scale…`, `Get…Ex`), and so is `OffsetClipRgn`. Pen widths are mapped to the device. Text drawn through a scaling transform stops by name, because font heights aren't mapped yet.
- **neww: metafile playback.** `EnumMetaFile` calls its callback for each record, with a zeroed `HANDLETABLE16`. `PlayMetaFileRecord` and `PlayMetaFile` play each record as the GDI call it names, following Wine's `PlayMetaFileRecord`. `GetMetaFileBits`, `DeleteMetaFile` and `IsValidMetaFile` follow `gdi.exe16` `metafile.c`. A record neww can't play yet stops by name.
- **Result.** The NIDA ATT course `93952606.TBK` ("Parallel Resonance") used to stop leaving P430, at `GDI LPtoDP in map mode 8`. It now draws P440's two packed pictures (a TV and a radio, each an 8-bit DIB drawn `SRCPAINT` then `SRCAND`) and walks on through P450 to its Lesson Menu, P900. The Logic Families runs and the nida81 run are byte-identical to 0.5.0.
- 833 tests OK, run plain and with the ToolBook binaries and three books. CI is green.

## Next release point

`neww-v0.7.0` when roadmap #230's "Now" items have merged: symbol-font mapping (#225) and the rest of Parallel Resonance (#226).
