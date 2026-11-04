# TBpipeline neww 0.3.0

Neither neww run ends on a call limit or on a handler-less spec row any more. `bf` is unchanged and stays `1.0.0r6`.

## New since neww-v0.2.0

- **nida81 ends on a named stop (roadmap #201 T2, #214).** `python3 -m tbpipeline_neww` now ends a run with no input script on the named idle stop, after the first idle tick. A run that only waits on timers is the exception: it keeps running to the call limit, as before. With nida81 the run ends at call 17,989 on `idle: no input script, TB80RTM waiting in PeekMessage`, with `P0` drawn and no MessageBox, where before it ran into the 20,001-call limit. The library default (`Machine(..., idle_stop=False)`) and `--timers` keep the old behaviour. Source: Wine `2528aff2` `dlls/win32u/message.c:3640-3643`.

## Correction: already in neww-v0.2.0

The neww-v0.2.0 notes listed T3 as open, but it had merged before that tag was cut. Each of these is now answered from Wine rather than by a spec row with no handler:

- `midiOutGetNumDevs` returns 0 (#206).
- `auxGetNumDevs` returns 0 (#207).
- `OleInitialize` returns S_OK, then S_FALSE (#209).
- `CallNextHookEx` walks Wine's chain, which is empty for a 16-bit task (#210).

## Still open

- T5: one bitmap through `TB80BMP`.
- T6: widget placement.
- T9: modal dialog boxes, so that Lesson Exit on P900 shows ToolBook's request box. T9a (#215, `Button` and `Static`) is in review, and T9b (`DialogBoxIndirectParam` and the modal loop) follows.

## Next release point

`neww-v0.4.0` when T9a and T9b are both merged, so Lesson Exit shows its box and a click ends it.
