# Future

`v2.0.0` in [plannedmilestones.md](../tbpipeline_bf/plannedmilestones.md) is still the goal: the ToolBook window, without a VM, a page with text and pictures and bounds in place, a click that runs the handler, quizzes that score, a lesson that opens from the menu. It is not scheduled. Nothing in the current trees is that window.

`v1.0.1` was the list of work waiting after r3. Part of it has moved. The rest has not.

| Item | Now |
|---|---|
| One real handler | A click runs the page's `buttonClick`. `P20000` goes to `P20001` because the handler says so, and the next click comes back through `nextpage`. The rest of OpenScript is still not executed |
| The RTM open | Pass 06 still exits after `TB80.INI`. `newl` dies earlier, inside startup, on a scan of an empty block |
| Widget bounds | Still unknown. Curves are decoded and not placed |
| Polygons on the page | Kind-04 polygons are on the page in `render.html` at their twips / 15. Curve runs are still files under `render/` |
| The 606 `TB80BAS` ordinals | Still not bound. Ordinal 1 is startup. The painters are later ordinals |
| Pictures | Windows BMPs are copied. `TB80BMP` ordinal 3 still stops at `0x1FCD` |

## Do this next

In this order. Each one is a fact a person can check.

1. **Place one widget.** P430's curve is decoded. The missing step is the record that says where it sits. Done means that curve is on the page, at the twips the record names, not in a file of its own.

2. **Stop or finish the RTM open.** Either pass 06 reaches `OpenFile` on the `.tbk` and the handle is the book, or the run stops on the call that refuses it and that call is named. Another `AX = 1` that happens to pass the INI check is not the item.

3. **One bitmap.** Bind the far call at `TB80BMP` `0x1FCD` and return a DIB. Done means a compressed picture from a book becomes a bitmap the reader can show.

`newl` and `neww` do not take a turn in that list until one of them opens a book or returns a fact the reader does not already have. Growing the layer by guessing the next return value is how `bf` spent r4 and r5. `neww`'s rule stands: a call with no contract stops the run.

## Do not do this

- Do not merge the three trees. They answer different questions, and a shared Windows table will make a lie in one of them look like a fix in the others.
- Do not reimplement Windows. Add a contract when a real call needs a real answer. The list of those answers is WHY.md. The default is not 1.
- Do not make the host the way a page is drawn. `--dbgrender` stays opt-in. A launch that exits does not write `render.html`.
- Do not treat a back-reference as a function call, or a `?` in expanded source as a missing opcode, unless a decode was aimed at a slice.
- Do not bump a release number for this work. `1.0.0r6` is the reader. The next release number is a decision, not a side effect of a commit.

## Where the future actually is

The book is already open enough to read. `nida81.tbk` has pages, field records, and handlers whose source comes back clean. The future of the reader is the items above, in that order.

The future of the host is narrower than it looks. It is `TB80BMP` ordinal 3, the record that places a widget, and a startup that either opens the book or names the call that will not. It is not a Wine-class Win16. `neww` is the place to keep that instrument honest. `bf`'s pass 06 is the place that already has the DLLs mapped, and it is also the place that returns 1 too often to trust past the INI.

If those three host questions get answered, the reader can show a page that is the page. That is `v1.0.1`. The window in `v2.0.0` comes after, and only if the page is already true.
