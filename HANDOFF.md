# Handoff, 2026-11-14

This note is for whoever picks TBpipeline up next (Cursor, Codex or a person) with no other context. It replaces [CURSOR.md](CURSOR.md) (2026-11-05) as the starting point. CURSOR.md still holds the setup traps and the opentoolbook8 notes, and they still apply.

The GitHub issues are the live record. Start at [Roadmap 2, #230](https://github.com/squirelworks/TBpipeline/issues/230). Every open item there has a pointer to the code, a command to reproduce it, and what "done" means. Tick a box when its PR merges.

## 1. State at a glance

| | |
|---|---|
| main | `7be3963` (PR #239 merged, 2026-11-13) |
| Last release | `neww-v0.6.0` (2026-11-13). PRs #232 and #234 to #239 merged after it and are **not released yet** |
| Open PRs | none |
| Open issues | #230 (roadmap), #227 (the sweep), #228 (leftovers from #221), #229 (`bf`, parked) |
| Plain suite at main | 978 tests OK, 43 skipped (2026-11-14, Python 3, no binaries). CI runs the same |
| 78-book sweep (Run 8, PR #239) | **63 pass, 15 stop.** 418 distinct screens |
| 608 NIDA ATT courses (Run 3, PR #238) | 607 open to idle, 1 stops (9395T903, OLE, a Wine limit). The walk turned **0** pages, because #238 could not find NIDA's bitmap Next button. #239 fixes that; the rerun with #239 (Run 4) was started on GwenTea2 and **its results were never collected** (see section 5) |

What a person can see working today, headless:
- Logic Families (`9e954d01.tbk`) and Parallel Resonance (`93952606.TBK`) walk 13 screens each in the sweep, and the scripted runs go all the way: Pre-Test to the score page, the Lesson Menu (P900), the Final Quiz to P10303, the lesson (P1001), and Lesson Exit to a clean `dos exit 0x0`.
- Wingdings bullets and Symbol π draw from real symbol faces (#232).
- Metafile pictures play, with `MM_ISOTROPIC`/`MM_ANISOTROPIC` (#224).

## 2. Rules

- **PRs are sizeable: batch related changes into one PR per repo per work stream.** Never open one PR per behavior. Small PRs conflict with each other after every merge. (Squirrel, 2026-11-13; this replaces the "one behavior per PR" line in CURSOR.md section 6.)
- Each behavior still gets a test that fails before the change and passes after.
- Every Win16/Win32 return value cites Wine `2528aff2` by `file:line`. A call with no contract stops the run by name. No `AX = 1` defaults and no guessed pop sizes. Where neww departs from Wine on purpose, say so in the PR and add it to section 6 below.
- No binaries, real `.tbk`/`.sbk` books, screenshots, logs or sweep output in the repo. Results go in the project files (section 4).
- No regressions in the §8.4 runs or the Parallel Resonance walk (section 3).
- Only Squirrel merges `Release ...` PRs.
- `newl`/`neww` never import `tbpipeline_bf`. `bf` is frozen at `1.0.0r6` (bug fixes only).

## 3. How to run

### Environment
Use the tarball `cursor-handoff/toolbook-cursor-2026-11-05.tar.gz` from the project files. It has an unpacked `TBK_BIN` and the books. CURSOR.md section 5 has the full recipe and the setup traps (packed DLLs, stray files in `TBK_BIN`).

```sh
export TBK_BIN=$PWD/env/tbk_bin                  # unpacked runtime: TB80RTM.EXE, TB80*.DLL, system books, nida.ttf
export TBK_BOOK=$TBK_BIN/nida81.tbk
export TBK_BOOK2=$PWD/env/books/LogicFamilies.tbk
export TBK_BOOK3=$PWD/env/books/93952606.TBK     # Parallel Resonance
git clone https://gitlab.winehq.org/wine/wine.git wine-src && git -C wine-src checkout 2528aff26208
export WINE_SRC=$PWD/wine-src                    # OBM_ bitmaps, Wine's symbol fonts, citations
python3 -m venv .venv && . .venv/bin/activate
pip install -r tbpipeline_neww/requirements.txt "pillow<12"
```

**Pillow 12.1.1 breaks NEAREST resizes** (`SystemError` in `gdi16` `_stretch`), so three Logic Families books fail on a host that has it. Use Pillow 11.x in a venv. The requirements file does not pin it yet (a one-line fix, listed in #230).

### Unit tests
```sh
python3 -m unittest discover -s tests -t .                                   # plain, about a minute
TBK_BIN=... TBK_BOOK=... TBK_BOOK2=... TBK_BOOK3=... WINE_SRC=... \
  python3 -m unittest discover -s tests -t .                                 # with binaries, several minutes
```
CI (`.github/workflows/tests.yml`) runs the plain suite on every PR. It has no binaries, so the book tests skip there.

### §8.4 regression runs
These are the fixed CLI runs every PR compares against main: **c0 to c3** (Logic Families with 0 to 3 clicks), **long** (title page, then Next ×10), **nida81** (`--cap 20000`, no input) and **pr7** (Parallel Resonance, title click then Next ×7). The commands and the 2026-11-04 hashes are in CURSOR.md section 5. Those hashes are out of date now (c2's screen changed with #232 when `WINE_SRC` is set), so **compare against main at the time, not against the table**: run each on main and on your branch, and the screen hash, last page, stop line, MessageBox count and spec-row defaults must match. Call counts can move by a few with the date, because the books format the clock into strings. The nida81 run has a 20 s wall-clock cap, so run it alone.

### The sweep
`python3 -m tbpipeline_neww.sweep` runs each book in its own process with a time limit, walks up to `--pages` steps, and prints one line per book. With `--out` it appends one JSON object per book.

```sh
python3 -m tbpipeline_neww.sweep --bin "$TBK_BIN" --out /tmp/sweep/run.jsonl --pages 10 --jobs 6 BOOK...
```

- Keep `--out` outside the repo.
- **Pass book paths as a list, not through word-splitting.** Some names have spaces. In bash: `mapfile -d '' books < <(find DIR -iname '*.tbk' -print0); python3 -m tbpipeline_neww.sweep ... "${books[@]}"`.
- Set `WINE_SRC`, or the OBM_ bitmaps and the symbol fonts are missing and more books stop.
- A course book needs `nida81.tbk` and the nc81/tb80 system books beside it, or in the `--bin` folder.
- Each result has `pass`, `cause`, `stop`, `calls`, `screens`, `walk` (one letter per step: m menu, t Next text, p picture, c page click, k Ctrl+Right; upper case when the step reached a new screen), `moved`, `stuck`, `text_clicks`, `picture_clicks`, `centre_clicks`, `clicked`, MessageBox texts and spec-row defaults.
- A **pass** is a book that opened (idle, no MessageBox while opening, no spec-row default, a main window that is not "(Untitled)") and whose walk ended idle, or in the book's own exit after a click. `sweep.opened()` is the definition.
- There is no table generator yet. The tables in the findings files were made by hand from the JSON lines (a small script is a listed item in #230).

**The 78-book set** is every unique TB80 book in the project files, the uploads, the Instructor 8.1 samples and the tarball's `env/`, deduplicated by SHA-256: 58 `.tbk` and 20 `.sbk`. Run them with `--pages 10`.

**The 608 NIDA ATT courses** are on Squirrel's machine GwenTea2 in `~/TBK/bin/courses` (611 files, 608 unique). They are 3 to 6 MB each and are not in the container or the repo. The runs so far used an unpacked runtime folder and symlinks to the books in a lab folder outside the repo (`~/Claude/labs/nida-sweep-2026-11-13/`), `--jobs 6`, and `--pages 10` (Run 3) or `--pages 30` (Run 4). A run of all 608 takes about 40 minutes opening only, and about 2 hours walking 30 pages.

## 4. Where results live

All of these are in the **project files**, not the repo:

| File | What |
|---|---|
| `neww/sweep/findings.md` | The 78-book sweep: Run 1 (open only), Run 6 (page walk, #238), Run 8 (button walk, #239) |
| `neww/sweep/nida-findings.md` | The 608 NIDA courses: Run 2 (open only), "After #236", Run 3 (page walk, #238). A copy of `findings-20261113T142847-ed18.md` at the top level |
| `findings.md` (top level) | An older copy of the NIDA file, without Run 3 |
| GwenTea2 `~/Claude/labs/nida-sweep-2026-11-13/` | The NIDA JSON lines and the Run 4 output, if it finished |
| `cursor-handoff/`, `bochs/` | The environment tarball and the Windows 98 Bochs VM (ToolBook 8 as ground truth) |

## 5. Open work, in order

The detail (pointers, repro, acceptance) is on [#230](https://github.com/squirelworks/TBpipeline/issues/230) and the issues it links. In short:

1. **Collect or redo Run 4** (608 NIDA courses with the #239 button walk, `--pages 30`). It was started on GwenTea2 on 2026-11-13 at about 15:00 UTC, and the session went offline before it reported. Baseline: LogicFamilies and Parallel Resonance reach 13 screens each. Add a "Run 4" table to `neww/sweep/nida-findings.md` with pass, stuck and stop counts and the top stop causes.
2. **Release `neww-v0.7.0`** for #232 and #234 to #239. Open a `Release neww-v0.7.0` PR that adds `.github/release-notes/neww-v0.7.0.md`. Squirrel merges it.
3. **The four still-open 78-book stops** (#227): `EnumFonts` for tb80.sbk (waiting on a decision, section 7), the EDIT control (scrwalk), `TB80HYP.SBK` never opening (chewbyte), `FindExecutable` (tb80hyp).
4. **Whatever Run 4 finds** in the NIDA courses, grouped by cause, one PR per group.
5. **Menu tracking** (`track_mouse_menu_bar`), moving and sizing, which stop by name in `handle_sys_command`.
6. **#228** when a book hits it: text through a scaling map mode, the unplayed metafile records, symbol-font bytes cp1252 leaves undefined.
7. **#229** stays parked.

## 6. Places neww departs from Wine on purpose

Keep this list current. Each one is a candidate for a test that pins it and a note in the code.

- **16-bit OLE automation objects (PR #235).** Wine's 16-bit `CreateDispTypeInfo` is `E_NOTIMPL` and its `CreateStdDispatch` leaves the out pointer NULL (`dlls/ole2disp.dll16/ole2disp.c:477`, `:489`). `TB80OLE` keeps the object and releases it at exit, which faults in Wine. neww makes real objects the way 32-bit `oleaut32` does (`typelib.c:8669`, `dispatch.c:450`), with methods as `OLE2DISP` cdecl rows from 500 up, following Wine's own 16-bit COM convention (`compobj.dll16.spec:210`). This is what lets Lesson Exit end cleanly.
- **The `GetTickCount` clock advance (PR #239).** neww's clock moves 1 ms for each `GetTickCount` call that comes right after another, so a program that waits by polling it (qb_corpr, sales2) sees time pass. Wine reads the host clock. This is a modelling choice for a deterministic, headless run. A different rule (for example, advancing by a fixed step per N instructions, or per idle) would change call counts and maybe pages, so any change needs the §8.4 runs and the sweep rerun.
- **`SetCursorPos` is not queued in time order (PR #234).** Wine queues the move (`server/queue.c:576`). Doing that moved where every scripted click lands, so it was left out.
- **The fixed DOS clock (roadmap #201 T4).** Runs use a fixed date so book output is repeatable. Call counts still drift by a few with the real date in some books.

And one place it follows Wine where Windows would do better, by Squirrel's choice (2026-11-13):
- **The four ActiveX books** (actxexpl, Quizbldr, tb80x, tb80web) and the NIDA course 9395T903 stop by name at `COMPOBJ.19 StringFromCLSID: compobj_malloc is NULL`. Wine's `OleInitialize16` goes to ole32 and never sets the 16-bit task allocator, so Wine faults there too. They are a **Wine limit, not a neww bug**. Even with Windows behavior they ask for the Internet Explorer control, which is not registered.

## 7. Open decisions (Squirrel's call)

- **tb80.sbk's font list.** When a book asks Windows for the installed fonts (`EnumFonts`, `EnumFontFamiliesEx`), what should neww list? Options posted 2026-11-13, not answered yet: (a) Wine's own fonts from `WINE_SRC` plus any `.ttf` in the book folder (recommended: it matches what Wine would answer, and neww already reads Wine's symbol fonts this way); (b) only the Liberation/DejaVu faces neww draws with; (c) keep stopping by name. Don't implement until it is answered.

## 8. Future work

The longer list of ideas for taking this further is in [documentation/future.md](documentation/future.md#future-work).
