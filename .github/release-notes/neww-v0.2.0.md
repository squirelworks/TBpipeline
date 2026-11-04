# TBpipeline neww 0.2.0

Logic Families can be walked from start to finish in neww. `bf` is unchanged and stays `1.0.0r6`. `newl` is unchanged.

## New since neww-v0.1.0

- **The whole course walks (roadmap #201 T4).** `tests/test_neww_lf_walk.py` drives Logic Families with `--input` scripts and checks the page after every click. Selection 1 goes to TTL and Selection 2 to Other ICs. Back on TTL Discussion returns to P1040, P1082 and P1140, and on Other ICs to P2040, P2070 and P2130. Each walk uses up its input script and ends on the idle stop with no MessageBox (#211).
- **The Pre-Test runs to the score page.** A run can fix the DOS clock (`Machine(..., host_time=...)`, from Wine `int21.c` GET SYSTEM DATE/TIME). The quiz then asks its questions in the same order on every run, and the walk answers all 10 and reaches P10303, "The test is complete and your score is 10%." The default still reads the host clock (#212).

## Already in neww-v0.1.0

The v0.1.0 notes listed these two as open. They had both merged before that tag was cut:

- GDI shape calls draw. `Ellipse`, `RoundRect`, `Polygon`, `Polyline`, `Arc`, `Pie` and `Chord` paint with the DC's brush, pen and ROP2, so the LF P410 chips have pins and notches (T7, #203).
- Liberation Sans, Serif and Mono stand in for Arial, Times New Roman and Courier New because they have the same metrics, so labels are no longer cut short (T8, #204).

## Still open

- T2: `nida81` with `--cap 20000` still ends at the call limit.
- T3: four calls (`midiOutGetNumDevs`, `auxGetNumDevs`, `OleInitialize`, `CallNextHookEx`) are answered 0 by a spec row with no handler.
- T5 (one bitmap through `TB80BMP`) and T6 (widget placement).

## Next release point

`neww-v0.3.0` when T2 and T3 are merged, so that neither run stops on a call limit or a handler-less spec row.
