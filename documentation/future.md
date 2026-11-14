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

Done for [#225](https://github.com/squirelworks/TBpipeline/issues/225):

- [x] Wingdings bullets draw as Wingdings bullets (LF P100), not as "w".
- [x] π on 93952606 P430 draws from the course's own symbol face, `nida.ttf`, not as "p".

Done for [#226](https://github.com/squirelworks/TBpipeline/issues/226): the rest of `93952606.TBK` from its Lesson Menu, P900.

- [x] The Final Quiz runs to its score page (P10303), and exit from there goes to the objectives to review (P10410).
- [x] "1. Parallel Resonance" opens the lesson (P1001).
- [x] Lesson Exit asks "Are you sure you want to Exit the Lesson?". Yes unloads ToolBook's DLLs (`FreeLibrary` at a module's last use calls its WEP).
- [x] Lesson Exit then ends the task: `TB80OLE` releases the automation object `CreateDispTypeInfo` and `CreateStdDispatch` make, and `FreeLibrary32W` detaches and unloads the 32-bit DLLs ([#233](https://github.com/squirelworks/TBpipeline/issues/233)).

## The book sweep (#227)

`python3 -m tbpipeline_neww.sweep` opens every TB80 book we have, one process per book. The findings table lives in the project files (`neww/sweep/findings.md`), not in the repo. Run 1 covered 78 unique books: 54 opened cleanly and 24 stopped.

- [x] Group A: the caret (`CreateCaret`, `SetCaretPos`, `ShowCaret`, `HideCaret`, and the blink through `WM_SYSTIMER`). The five NetClass system books.
- [x] Group C: `RegOpenKeyA`, `RegOpenKeyExA`, `RegCloseKey` (one registry with SHELL's) and `GetShortPathNameA`.
- [x] user32's OBM_ bitmaps for `LoadBitmap(0, id)`, read from `WINE_SRC` (new3_a, new3_b).
- [ ] `EnumFonts` / `EnumFontFamiliesEx` over the installed faces (tb80.sbk). Waiting on Squirrel's choice of font list ([HANDOFF.md](../HANDOFF.md#7-open-decisions-squirrels-call)).
- [x] `GetBitmapBits` on a 32-bit bitmap and `CreateIcon` (tb80acta).
- [x] Blocks over 1 MB: page-granular selectors, as `global.c:209` and `selector.c:66` give them (Walkthrough).
- [x] `DrawText` (single-line and plain multi-line, `DT_CALCRECT`, alignment) and `DrawFocusRect`. The mnemonic is underscored as `TEXT_DrawUnderscore` draws it. Word breaks, tabs and ellipses stop by name.
- [x] Page walking: the sweep chooses Go > Next from the runtime's menu (a `WM_COMMAND`, a menu click's last message). A pass also needs a main window that is not the runtime's "(Untitled)" one.
- [ ] The EDIT control (scrwalk) and the common file dialog.
- [x] OLE controls: `CoGetClassObject`, `StringFromGUID2`, `ProgIDFromCLSID`, `StringFromCLSID` and the IMalloc16 task allocator. The four books (actxexpl, Quizbldr, tb80x, tb80web) ask for the Internet Explorer control, which is not registered, then call `StringFromCLSID` before anything sets `compobj_malloc`. Wine faults there (its `OleInitialize16` goes to ole32 and never sets it), so neww stops by name. Decided: follow Wine.
- [x] Broadcast `SendMessage` across tasks, one-rectangle region unions and differences, and INT 21h 19h and 47h (tb80ftp opens and walks).
- [x] Not neww bugs: tb80a links `"tbfile32"` with no extension, which `OpenFile` does not add in Wine either; otb_cross_a is a fixture another project wrote by hand, and ToolBook calls it damaged.
- [ ] "Not a valid OpenScript term: ." (chewbyte, tb80actr): the handler calls `tbk_hasHyperlinks`, from the system book `TB80HYP.SBK`, which this book never opens. learn1 opens it after its `*TbxBase*` step; chewbyte never reaches that step.
- [x] Scroll bars are drawn as Wine draws them: arrows, the interior in the parent's `WM_CTLCOLORSCROLLBAR` brush (DefWindowProc's is the 0x55AA pattern) and the thumb. `SetScrollPos` and `SetScrollRange` with redraw draw at once.
- [x] The walk tries Go > Next, a Next text, the button pictures on the screen (NIDA's bitmap Next), a click on the page (title pages), then Ctrl+Right, and says when none of them turned a page.
- [x] The non-client hit test (`handle_nc_hit_test`): a click on the frame, caption or menu bar reaches `WM_SYSCOMMAND`.
- [ ] Menu tracking (`track_mouse_menu_bar`), moving and sizing: `WM_SYSCOMMAND` stops there by name.
- [ ] `SHELL.21 FindExecutable` (tb80hyp's hyperlink dialog, reached by the #239 walk): `SHELL_FindExecutable` searches the App Paths and the extension's registry class.
- [x] Regions of many rectangles (`REGION_RegionOp` for every `CombineRgn` mode), clip regions of several rectangles, `InvertRect`, `AnsiToOemBuff`, INT 21h 41h and `GetNextDlgGroupItem` (#239).
- [x] The 608 NIDA ATT courses on GwenTea2 (`~/TBK/bin/courses`). Run 2: 540 pass, then 605 after #236. Run 3 with the #238 walk: 607 open to idle, 1 stops (9395T903, the COMPOBJ Wine limit), and the walk turned no pages. The table is `neww/sweep/nida-findings.md` in the project files.
- [ ] Run 4: the 608 courses with the #239 button walk (`--pages 30`). Started on 2026-11-13; its results were never collected.

## Future work

Ideas for taking this further once Roadmap 2 (#230) is done, roughly in order of payoff. None of them is started. Each would be its own work stream, so each is one sizeable PR (or a short series), not one PR per behavior.

1. **A sweep report tool.** `python3 -m tbpipeline_neww.sweep_report run.jsonl [--against older.jsonl]` turns the JSON lines into the findings tables (pass, stuck and stop counts, top stop causes, books that got better or worse, screens per book). Today the tables are made by hand. Everything below leans on this.

2. **Real page-walk coverage across all 608 courses, with regression baselines.**
   - Measure coverage against the book itself: `tbpipeline_bf` already reads the page list from a `.tbk`, so a walk can report "reached 41 of 131 pages", not just "13 screens".
   - Explore, don't just walk forward: treat each screen hash as a node and each click (menu Next, button picture, hotword, page click, Back) as an edge, and search breadth-first with a call budget. Use the `Machine.on_idle` hook (#234) to answer quizzes generically (try each choice).
   - Keep baselines as hashes, not images: a per-book manifest of (step, screen hash, page label) in the project files. A run that reaches a different hash at the same step is a regression to look at. Write the differing screens as PNGs to the project files for review, never to the repo.

3. **CI that runs the sweep on merge.** The books can't go to GitHub, so this needs a self-hosted runner on the machine that has them (GwenTea2). On each push to `main`: the §8.4 runs, the 78-book sweep and a sample of the NIDA courses (all 608 nightly). Compare with the last baseline and fail when a book that passed now stops or reaches fewer screens. Post the summary as a comment on the PR and the full table to the project files. This replaces the hand-run "frozen checkout" comparisons every PR does now.

4. **A Win16 API coverage tracker driven by sweep failures.** From `spec_rows.py`/`spec32_rows.py` and the sweep's JSON: for each module, which ordinals have handlers, which are spec-row defaults, and which ones stopped how many books. Rank the missing calls by books unblocked. Publish it as a table in the project files (or keep one pinned issue updated). It turns "what next?" into a sorted list.

5. **Speed.** A course opens in about 7 s (median) and 30 walk steps take about a minute, so 608 courses take about 2 hours on 6 cores.
   - Profile first (`cProfile` on one course run) and fix the top items. Likely: the per-call hook path into Unicorn, selector and segment translation, and image work through Pillow per blit (move the screen to a numpy surface).
   - Snapshot after startup: the first ~20,000 calls (TB80RTM and its DLLs starting) are the same for every course. Save the machine state once and fork or restore it per book.
   - A faster sweep makes the CI and the coverage ideas above affordable.

6. **A deviations register.** Section 6 of [HANDOFF.md](../HANDOFF.md) lists where neww departs from Wine on purpose (16-bit OLE automation objects, the `GetTickCount` advance, unqueued `SetCursorPos`, the fixed DOS clock). Give each one a marker in the code (`# DEVIATION: ...`) and a test that pins it, and have a test check the list and the markers agree. Then a change of mind is one place to look.

7. **An interactive player.** neww already takes `--input` scripts and draws to an image. Show that image in a window (Tk is already used by opentoolbook8) and feed real mouse and keyboard events in, and NIDA courses become playable without a VM. This is the `v2.0.0` "ToolBook window" above, reached through the real runtime instead of a reimplementation.

8. **Reconcile neww with opentoolbook8.** The two answer different questions: neww runs the real ToolBook runtime, opentoolbook8 is a clean-room reader. Two concrete links:
   - Port what neww learned that is not ToolBook code: the symbol-font mapping (#232; the opentoolbook8 counterpart PR was never opened), metafile playback and map modes (#224).
   - Use neww's screens as a second oracle beside Bochs: render the same page in both and diff. Whether that fits opentoolbook8's clean-room rule is Squirrel's call, so ask before doing it.
   Don't merge the trees (see below).

9. **Package a release.** Release `neww-v0.7.0` now (#232, #234 to #239), and `neww-v0.8.0` when every book in the sweep passes its open (the roadmap's release point). After that: a `pyproject.toml` with a `tbk-run` entry point (`tbk-run --runtime DIR BOOK [--input ...] [--screens OUT]`), pinned dependencies (Pillow below 12 until the NEAREST resize issue is understood), and a short user guide on getting an unpacked runtime folder (`python3 -m tbpipeline_bf.nehost --unpack`).

10. **Wine version hygiene.** Every citation is to Wine `2528aff2`. A script that checks each cited `file:line` still holds the cited function in a newer Wine would make a later bump safe, and would catch citations that drifted when they were written.

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
