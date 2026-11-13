# Future

`v2.0.0` in [plannedmilestones.md](../tbpipeline_bf/plannedmilestones.md) is still the goal: the ToolBook window, without a VM, a page with text and pictures and bounds in place, a click that runs the handler, quizzes that score, a lesson that opens from the menu. It is not scheduled. Nothing in the current trees is that window.

`v1.0.1` was the list of work waiting after r3. Part of it has moved. The rest has not.

| Item | Now |
|---|---|
| One real handler | A click runs the page's `buttonClick`. `P20000` goes to `P20001` because the handler says so, and the next click comes back through `nextpage`. The rest of OpenScript is still not executed |
| The RTM open | Pass 06 still exits after `TB80.INI`. `newl` dies earlier, inside startup, on a scan of an empty block |
| Widget bounds | Kind-04 polygons: `+0x12`..`+0x18`, checked against their points on two books, and placed. Fields, buttons, and kind-01 records: still unknown |
| Polygons on the page | Kind-04 polygons are on the page in `render.html` at their twips / 15. P430's class `0x11` arcs are placed at their record twips too (#219, roadmap #201 T6). Other curve runs are still files under `render/` |
| The 606 `TB80BAS` ordinals | Still not bound. Ordinal 1 is startup. The painters are later ordinals |
| Pictures | Windows BMPs are copied. `TB80BMP` ordinal 3 still stops at `0x1FCD` in `bf`, but nothing calls it: a packed book picture goes from TB80RTM to `GDI.160 SetMetaFileBits` instead, and neww returns that block (#220, roadmap #201 T5) |

## Do this next

Each one is a fact a person can check. Tick a box when its PR merges.

- [x] **Place one widget.** P430's curve is decoded. The missing step is the record that says where it sits. Done means that curve is on the page, at the twips the record names, not in a file of its own. Done in #219 (roadmap #201 T6): the eight class `0x11` arcs are drawn in `render.html` at their record twips.
- [ ] **Stop or finish the RTM open.** Either pass 06 reaches `OpenFile` on the `.tbk` and the handle is the book, or the run stops on the call that refuses it and that call is named. Another `AX = 1` that happens to pass the INI check is not the item. Not started: `bf` takes bug fixes only.
- [x] **One bitmap.** Bind the far call at `TB80BMP` `0x1FCD` and return a DIB. Done means a compressed picture from a book becomes a bitmap the reader can show. Settled differently in #220 (roadmap #201 T5): `TB80BMP` ordinal 3 has no caller. TB80RTM unpacks a packed picture itself and hands it to `GDI.160 SetMetaFileBits`, which neww now answers. Drawing it needs metafile playback, #221.

`neww` now opens a book. It opens Logic Families, draws `P0` with the picture from `nida81.tbk`, and walks pages from `--input` clicks ([host.md](host.md#neww) names the tests). `newl` still has not, so it does not take a turn. Growing the layer by guessing the next return value is how `bf` spent r4 and r5. `neww`'s rule stands: a call with no contract stops the run.

### neww next

[Roadmap #201](https://github.com/squirelworks/TBpipeline/issues/201) is complete (neww-v0.5.0). Tick a box when its PR merges.

- [x] **T0.** These docs describe neww as it is (#202).
- [x] **T1.** The long run (title page, then `Next` ×10 at 500 ms) ends on the named `idle:` stop, not the 2,000,001-call limit (#205, [host.md](host.md#neww)).
- [x] **T2.** A run with no `--input` also ends on the idle stop. nida81 ends at about call 17,989 with `P0` drawn and no error box (#214).
- [x] **T3.** `midiOutGetNumDevs`, `auxGetNumDevs`, `OleInitialize` and `CallNextHookEx` each have a handler cited to Wine `2528aff2` (#206, #207, #209, #210).
- [x] **T4.** Logic Families walks end to end: the menu, the Discussion Back cases, and the Pre-Test to P10303 (#211, #212).
- [x] **T5.** A packed book picture reaches GDI through `SetMetaFileBits` (#220).
- [x] **T6.** P430's arcs are placed at their record twips in `bf` (#219).
- [x] **T7.** The GDI shape calls draw (#203).
- [x] **T8.** Liberation fonts stand in for Arial, Times New Roman and Courier New (#204).
- [x] **T9.** `Button` and `Static` controls (#215), and modal dialog boxes (#217).

Done for [#221](https://github.com/squirelworks/TBpipeline/issues/221), in one PR. These stopped the NIDA ATT course `93952606.TBK` after P430; it now walks on to the Lesson Menu, P900:

- [x] Metafile playback: `EnumMetaFile`, `PlayMetaFile` and `PlayMetaFileRecord` (Wine `dlls/gdi.exe16/metafile.c`, `dlls/gdi32/metafile.c`).
- [x] `GetMetaFileBits` and `DeleteMetaFile`.
- [x] The `*Ex` window and viewport origin and extent calls.
- [x] `MM_ISOTROPIC` / `MM_ANISOTROPIC` in `_map_points` and the drawing paths.

Left over from #221: text through a scaling transform stops by name (font heights are not mapped yet), and the records neww does not play yet (`META_POLYPOLYGON`, `META_EXTTEXTOUT`, the region and bitmap records) stop by name.

Known gaps with no item yet:

- [ ] Wingdings bullets draw as "w" (LF P100): there is no symbol-font mapping.
- [ ] The Symbol font is unmapped the same way: π draws as "p" (93952606 P430).

The other NIDA ATT courses are on hold until the week of 2026-11-09.

## Do not do this

- Do not merge the three trees. They answer different questions, and a shared Windows table will make a lie in one of them look like a fix in the others.
- Do not reimplement Windows. Add a contract when a real call needs a real answer. The list of those answers is WHY.md. The default is not 1.
- Do not make the host the way a page is drawn. `--dbgrender` stays opt-in. A launch that exits does not write `render.html`.
- Do not treat a back-reference as a function call, or a `?` in expanded source as a missing opcode, unless a decode was aimed at a slice.
- Do not bump a release number for this work. `1.0.0r6` is the reader. The next release number is a decision, not a side effect of a commit.

## Where the future actually is

The book is already open enough to read. `nida81.tbk` has pages, field records, and handlers whose source comes back clean. The future of the reader is the items above, in that order.

The future of the host is narrower than it looks. It is `TB80BMP` ordinal 3, the record that places a widget, and a startup that either opens the book or names the call that will not. It is not a Wine-class Win16. `neww` is the place to keep that instrument honest, and it is the tree that now gets furthest: it opens the book and takes input, and its open stop is `nida81` above. `bf`'s pass 06 is the place that already has the DLLs mapped, and it is also the place that returns 1 too often to trust past the INI.

If those three host questions get answered, the reader can show a page that is the page. That is `v1.0.1`. The window in `v2.0.0` comes after, and only if the page is already true.
