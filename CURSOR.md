# Cursor handover, 2026-11-05 (takes effect Saturday 2026-11-08)

This note is for Cursor. It covers what changed since the last Cursor handoff (2026-10-31, `opentoolbook8` at `c260ae3`), what is on hold and why, what to pick up first, and how to run and check the work. The same file is `CURSOR.md` at the root of both `squirelworks/TBpipeline` and `squirelworks/opentoolbook8`. Your environment tarball also has a copy, with the project notes, the books and a ready `TBK_BIN`.

The GitHub issues are the live record. Tick boxes there as work merges:
- TBpipeline roadmap [#201](https://github.com/squirelworks/TBpipeline/issues/201) (complete) and the next item, [#221](https://github.com/squirelworks/TBpipeline/issues/221)
- opentoolbook8 roadmap [#117](https://github.com/squirelworks/opentoolbook8/issues/117) (complete, with open follow-ups)

## 1. State at a glance

| Repo | main | Last release | Suite at main |
|---|---|---|---|
| TBpipeline | `59f866b` | `neww-v0.5.0` (2026-11-04) | 814 OK plain (28 skipped); 814 OK with `TBK_BIN` + `TBK_BOOK` (16 skipped without `WINE_SRC`). Rerun 2026-11-05 |
| opentoolbook8 | `d0285f1` | `v0.3.0` (2026-11-04) | 414 OK plain (177 skipped, no tkinter); 414 OK with `OPENTOOLBOOK_TBK=9e954d01.tbk` (6 skipped). Rerun 2026-11-05 |

There are no open PRs in either repo. The only open issues are #201, #221 and #117.

## 2. What changed since the last Cursor handoff

### Process
- Work now runs as numbered roadmap items, one PR per item, on `claude/<item>` branches. A separate reviewer merged each one against `GUIDELINES.md`, which is in the tarball under `process/` with the worker and reviewer prompts. The reviewer's log is `project-notes/review/review-log.md`.
- Releases happen through a PR titled `Release <tag>` that adds `.github/release-notes/<tag>.md`. When that file reaches main, `release.yml` publishes the tag. **Only Squirrel merges `Release ...` PRs.**
- **opentoolbook8 release rule (Squirrel, 2026-11-04):** no release unless code changes have merged since the last tag. Check `git log v0.3.0..origin/main` first. Never open a release PR that only renumbers or fixes notes.

### opentoolbook8 (`c260ae3` → `d0285f1`, 308 → 414 tests)
- **2026-11-01, Cursor PRs #97–#116 (all merged):** the Pre-Test driver runs to the score page (zero-skipped, 90% with one wrong answer, OK back to the menu), along with the menu, TTL, Other ICs, Summary, Help and HelpNext walks. They also added the live Tk window (#114), class `0x11` arcs painted from prototype radii (#115) and the pie geometry slots (#116).
- **2026-11-04, roadmap #117:**
  - O0 #118: AGENTS.md describes the PR workflow
  - O1 #119: stale RESEARCH lines fixed
  - O2 #120: button captions
  - O3 #121: dotted lines draw dashed
  - O4 #123: `forward` pinned on the path, with SETTLED "Forward"
  - O5: stopped, no PR (see section 3)
  - O6 #126: Back sends `leavePage`, then `enterPage`, from a ToolBook 8 capture in Bochs
  - O7 #125: pie wedges, from an off-axis pie authored in ToolBook 8
  - Released as v0.1.0 to v0.3.0
- **The M1–M8 list in the 10-31 handoff is superseded** by #117 and SETTLED.md. Spot checks on 2026-11-05:
  - M1's `OPENTOOLBOOK_BOOKS` smoke test exists (`tests/test_books_smoke.py`)
  - M4's TB80.INI search and `sysBooks` get/set/push/pop are in SETTLED
  - M2's page size no longer uses fixed NIDA numbers
  - Not settled: M3, whether Preventing_Fraud.tbk is TB80 at all. RESEARCH "Preventing_Fraud.tbk (M3)" says the file was missing. It is in the tarball under `books/`, and `Walkthrough.tbk` is under `tbk_bin_raw/`, so M3 can now be done
  - For any other M item, check SETTLED before you start it

### TBpipeline / neww (was out of scope in the last handoff; now in scope)
Roadmap #201, T0 to T9, all merged on 2026-11-04 and released as neww-v0.1.0 to v0.5.0:
- T0 #202: the docs catch up
- T1 #205 and T2 #214: runs end on a named `idle:` stop instead of the call limit, with or without `--input`
- T3 #206/#207/#209/#210: Wine-cited `midiOutGetNumDevs`, `auxGetNumDevs`, `OleInitialize` and `CallNextHookEx`
- T4 #211/#212: Logic Families walks end to end, including the Pre-Test to P10303 with a fixed DOS clock
- T5 #220: a packed book picture reaches GDI through `SetMetaFileBits`. `TB80BMP` ordinal 3 has no caller
- T6 #219: `bf` draws P430's arcs at their record twips. `bf` stays `1.0.0r6`
- T7 #203: GDI shapes draw
- T8 #204: Liberation fonts stand in with ToolBook's widths
- T9 #215/#217: `Button`/`Static` controls and modal dialog boxes, so Lesson Exit shows its Yes/No box

On 2026-11-04 one NIDA ATT course was run from the Google Drive dump: `93952606.TBK`, "Parallel Resonance". P0 through P430 draw with no error box. The 7th Next stops in metafile playback. That stop is #221.

## 3. On hold, and why

| What | Why | Until |
|---|---|---|
| The other NIDA ATT courses (196 books in the Drive dump; one run so far) | Squirrel's call: fix what the first course found before sweeping | The week of 2026-11-09. Don't start a sweep before Squirrel says so |
| opentoolbook8 releases | The release rule above. Nothing has merged since v0.3.0 | Code merges after `d0285f1` |
| opentoolbook8 O5 (`enterSystemBook` for books seeded by the INI or the class table) | The TB80RTM trace on hand doesn't show it. Guessing is against AGENTS.md | A TB80RTM trace or Bochs capture of a book whose system book handles `enterSystemBook`, with `startupSysBooks` set |
| opentoolbook8 CI for non-`cursor/` branches | Offered as a fix (a `tests.yml` like TBpipeline's), not done | Squirrel's yes |
| `bf` past `1.0.0r6`, `newl` work, merging the three trees | Roadmap #201 "Not now" | Unchanged |
| Foolbook, FoolbookEditor, openscript_analysis, squirelworks.github.io | Out of scope for this work (GUIDELINES §Never) | Unchanged |

## 4. Pick up first

1. **TBpipeline #221: metafile playback.** It is the next piece of work and stops the only NIDA ATT course run so far. The checklist on the issue is the order, one PR per box:
   - `EnumMetaFile`, `PlayMetaFile` and `PlayMetaFileRecord`, following Wine `dlls/gdi.exe16/metafile.c`. Start with the `StretchDIB` records (8-bit DIBs, `SRCPAINT` then `SRCAND`) in the two pictures after P430
   - `GetMetaFileBits` and `DeleteMetaFile`
   - the `*Ex` window and viewport origin and extent handlers
   - `MM_ISOTROPIC` and `MM_ANISOTROPIC` in `gdi16._map_points` and the draw paths, with `GDI_ROUND`
   - Accept: the 7-Next run below gets past P430, and the §8.4 runs (section 5) don't regress

   Every return value cites Wine `2528aff2` by file:line.
2. **Known gaps, both repos:** Wingdings bullets draw as "w" (P100), and Symbol-font π draws as "p" (93952606 P430). Both come from one missing symbol-font mapping. Ship no fonts. In opentoolbook8, metafile pictures should also play from their records.
3. **opentoolbook8 follow-ups** listed on #117: Back across books (needs a capture), an unfilled pie (needs a sample), and M3 Preventing_Fraud.

## 5. How to run and check

### Environment from the tarball
```
tar xzf toolbook-cursor-2026-11-05.tar.gz && cd toolbook-cursor-2026-11-05
export TBK_BIN=$PWD/env/tbk_bin          # already unpacked, clean (see the traps below)
export TBK_BOOK=$TBK_BIN/nida81.tbk
export TBK_BOOK2=$PWD/env/books/LogicFamilies.tbk  # Logic Families (same file as 9e954d01.tbk), nida81 + system books beside it
export TBK_BOOK3=$PWD/env/books/93952606.TBK  # NIDA ATT Parallel Resonance
export OPENTOOLBOOK_TBK=$PWD/env/books/9e954d01.tbk
git clone https://gitlab.winehq.org/wine/wine.git wine-src && git -C wine-src checkout 2528aff26208
export WINE_SRC=$PWD/wine-src
pip install unicorn pillow     # neww/bf CPU and image deps; opentoolbook8 needs python3-tk for the window
```

### TBpipeline
```
python3 -m unittest discover -s tests -t .                 # plain
TBK_BIN=... WINE_SRC=... python3 -m unittest discover -s tests -t .   # with binaries (~400 s)
```
§8.4 regression runs (CLI, idle stop on). Values from the 2026-11-04 check at `9cbbeea`:

| Run | Screen hash | Page | Calls |
|---|---|---|---|
| LF 0 clicks | d293678ea7c41844 | P0 | 39,634 |
| LF 1 click | 9e35dc486b13cc0b | P10 | 48,752 |
| LF 2 clicks | d26c6351937fe35f | P100 | 61,434 |
| LF 3 clicks | 9e35dc486b13cc0b | P10 | 71,537 |
| long run | 8d9c65767cdc992d | P900 | 153,737 |
| nida81 `--cap 20000` | e21492b480d32db7 | P0 | 17,989 |

All of them end on an idle stop, with MessageBox 0 and 0 spec-row defaults. The #221 reproduction:
```
python3 -m tbpipeline_neww --b $TBK_BIN --c <dir>/93952606.TBK --cap 6000000 \
  --input "wait 15000; click 512,420; wait 8000; click 808,600; wait 8000; click 808,600; wait 8000; click 808,600; wait 8000; click 808,600; wait 8000; click 808,600; wait 8000; click 808,600; wait 8000; click 808,600; wait 8000"
# today: stopped 0x1dc0:0x31d GDI LPtoDP in map mode 8 ... calls 118463
```
The course book needs `nida81.tbk` and the nc81/tb80 system books in the same folder. `env/books/` is already laid out that way.

### opentoolbook8
```
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
python3 -m unittest discover -s tests
OPENTOOLBOOK_TBK=$OPENTOOLBOOK_TBK python3 -m unittest discover -s tests   # ~5 min
OPENTOOLBOOK_BOOKS=<folder of .tbk> python3 -m unittest tests.test_books_smoke
python3 -m opentoolbook $OPENTOOLBOOK_TBK              # window; Xvfb + xdotool headless
```

### Setup traps (from the 2026-11-04 verify report; none of them are regressions)
- **A packed DLL in `TBK_BIN` makes neww fail at startup.** The message is `packed image TB80OLE.DLL: 30 of 32 segments have the iterated flag`. Every NE must be unpacked first (`python3 -m tbpipeline_bf.nehost --unpack IN -o OUT`). `env/tbk_bin` is already unpacked. `env/tbk_bin_raw` is the original upload, so don't point `TBK_BIN` at it.
- **Stray files in `TBK_BIN` cause a false failure.** The raw upload also holds `TB80BAS_unpacked (1).dll`, `*.noentry`, `COUR*`, `courses*`, mingw DLLs and so on. Copying them in gives `unmapped 0x9d307d at TB80BAS LOOKUPSTDPROPBYNAME+0x95` at call 1,304. Keep only the TB80*/TB* modules, the `.sbk` books, nc81*, `nida.ttf` and the ini/lst files. That is exactly what `env/tbk_bin` holds.
- **The 20 s wall-clock cap makes §8.4 sensitive to load.** Under heavy CPU load, nida81 hit the cap at 12,009 calls. Run it alone to compare. In this container on 2026-11-05 it ended at 17,977 calls, on the same idle stop.

## 6. Rules that still hold

- One behavior per PR, linked to its roadmap item. Each PR needs a test that fails before the change and passes after, with both logs pasted. The full suite stays green in every environment you have.
- Never commit ToolBook or NIDA binaries, real `.tbk`/`.sbk` books, screenshots or `db-*` folders. Never record a serial number. The tarball's `env/` is for your machine only.
- opentoolbook8 is clean-room: no Foolbook, no Ghidra, no forced disassembly. A painted value comes from bytes that repeat across books. ToolBook 8 in Bochs is the ground truth.
- TBpipeline: one tree per PR. `newl`/`neww` never import `tbpipeline_bf`. No `AX = 1` defaults and no guessed pop sizes. Each Win16 value cites Wine `2528aff2`.
- **opentoolbook8 `cursor/*` branches are auto-merged by `.github/workflows/merge-cursor.yml` once the suite passes, with no review.** That is also the only test workflow in that repo. If you want review, use another branch prefix and ask Squirrel to merge.

## 7. Where things are

- Tarball (project files): `cursor-handoff/toolbook-cursor-2026-11-05.tar.gz`. Its `README.md` lists the layout.
- Windows 98 Bochs VM image: **not in the tarball** (178 MB). It is in the project files at `bochs/win98.zip`. `bochs/rebuild.sh` and `bochs/vm.sh` (both in the tarball) rebuild and drive it. Captures so far: `bochs/page-turn/`, `bochs/o6-back/` and `bochs/o7-pie/`.
- The earlier handoff, `handoff/opentoolbook8-cursor-handoff.md`, is in the tarball. It still holds the architecture map and the opentoolbook8 hard rules.
