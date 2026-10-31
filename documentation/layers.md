# Layers

`newl` and `neww` both put Windows under the real ToolBook code as a table of calls. Neither imports the other, and neither imports `tbpipeline_bf`. When the two answer one ordinal differently, both answers stay in their own tree, and this file names the difference. A later PR may pick one, with the reason. A PR that makes them match without a reason is wrong.

## Where newl and neww disagree

- `KERNEL.91` `InitTask`: `newl` returns `AX = 1`, `ES` = its PSP, `BX = 0x80`, `CX = 0x1000`, `DX = 1`, `SI = 0`, `DI` = DGROUP, and pushes nothing, while `neww` follows Wine's `InitTask16`: it builds Wine's local heap when `CX` is not 0, runs each ToolBook DLL's LibMain, and then returns `CX` = the stack top it writes into INSTANCEDATA, `BX` past leading blanks in the PSP command line, and pushes one zero word.
- `KERNEL.74` `OpenFile` and `KERNEL.85` `_lopen` of a file that is not there: `newl` returns a new handle for any path, while `neww` returns `HFILE_ERROR` (`0xFFFF`) with `nErrCode` 2, Wine's `OpenFile16` answer.
- `KERNEL.15` `GlobalAlloc`: `newl` rounds the dword size up to 4K, clamps it at `0x10000`, and gives size 0 a 4K block, while `neww` rounds to 32 bytes, tiles blocks up to 1M across selectors 8 apart, and stops on size 0 and on more than 1M.
- `KERNEL.18` `GlobalLock`: `newl` returns the SEGPTR in `DX:AX` (selector, 0) as Wine's `WIN16_GlobalLock16` does, while `neww` still returns the handle in `AX` with `DX = 0`.
- `KERNEL.30` `WaitEvent` with a nonzero `hTask`: `newl` ignores the argument and takes the event, while `neww` stops, because it has no task handle to compare.
- `KERNEL.102` `DOS3Call` with `AH = 30h`: `newl` returns 5, while `neww` returns 0.

`GetVersion` (`0x0A03`), `GetWinFlags` and `__WINFLAGS` (`0x0C25`, not Wine's `0x413`) agree.
- `KERNEL.131` `GetDOSEnvironment`: `newl` returns a 256-byte block of zeros, while `neww` returns Wine's layout with no strings: one 0, `WORD 1`, and `C:\WINDOWS\SYSTEM\KRNL386.EXE`, also named at PSP:`0x2C`.
