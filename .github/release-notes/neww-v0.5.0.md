# TBpipeline neww 0.5.0

Roadmap #201 is complete: every item from T0 to T9 is merged or settled.

## New since neww-v0.4.0

- **neww: a packed book picture reaches GDI as a metafile (T5, #220).** The item asked for `TB80BMP` ordinal 3 to be run on a compressed picture. That premise turned out not to hold: no module or book links `TBKBITMAP`, and hook runs found no entries into it. Instead, TB80RTM unpacks a packed class `0x19` picture itself and passes it to `GDI.160 SetMetaFileBits`. That call now returns the block handle, as Wine's `SetMetaFileBits16` does. Before, the spec row answered 0, so ToolBook got no metafile. On NIDA ATT `93952606.TBK`, the two blocks match, byte for byte, what opentoolbook8's clean-room unpacker gives for the same objects. That course still stops later, at `GDI LPtoDP in map mode 8`. The rest of the metafile path is a separate item.
- **bf reader: P430's curves are placed (T6, #219).** The eight class `0x11` arcs, the notches on the chip outlines, are now drawn in `render.html` at the twips in their own records, divided by 15, as SVG arcs. The record offsets come from opentoolbook8's SETTLED "Arc", and all 62 arcs in Logic Families match opentoolbook8's reading. This changes `bf` code, but the roadmap keeps `bf`'s version number at `1.0.0r6`.
- 814 tests OK, run plain and with the ToolBook binaries (reviewer's run).

## Next release point

`neww-v0.6.0` at the first milestone of the next TBpipeline roadmap that a person can see. The likely candidate is the metafile path (`EnumMetaFile`, the origin and extent calls, `MM_ANISOTROPIC`), so the NIDA ATT pictures draw.
