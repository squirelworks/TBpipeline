# TBpipeline neww 0.1.0

First release of the `neww` tree. `bf` is unchanged and stays `1.0.0r6`. `newl` is unchanged.

**The tag is a proposal.** `documentation/future.md` says the next release number is a decision, not a side effect of a commit. `neww-v0.1.0` keeps the `v1.0.0rN` series for `bf`. To use another name, rename this file in the release PR before merging it.

## What neww does at this tag (main `94f2e0b`)

- Opens Logic Families under its long name and draws `P0`, with the Nida picture from `nida81.tbk`.
- Takes clicks and keys from `--input`. `Next` walks the LF pages and `Back` works.
- The long run (title page, then `Next` ×10 at 500 ms) ends on the named `idle:` stop instead of the 2,000,001-call limit (#205, roadmap #201 T1).
- `documentation/future.md` and `host.md` describe neww as it is today (#202, roadmap #201 T0).
- Test suite green on main (GitHub Actions `tests`), run plain, with `TBK_BIN`/`WINE_SRC`, and with a second book.

## Known gaps

- `nida81` with `--cap 20000` still ends at the call limit (roadmap T2).
- Spec rows with no handler answer `midiOutGetNumDevs`, `auxGetNumDevs`, `OleInitialize`, `CallNextHookEx` with 0 (T3).
- GDI shape calls draw nothing yet, so the LF chips are grey boxes (T7, PR #203 open). Text uses wider stand-in fonts (T8, PR #204 open).

## Next release point

`neww-v0.2.0` when T4 (Logic Families end to end, Pre-Test to the score page), T7 and T8 are merged: the course is readable and walkable start to finish.
