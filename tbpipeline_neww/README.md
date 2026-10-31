# tbpipeline_neww

A Win16 sandbox around TB80.

Every unpacked NE file in `--b` is loaded into one address space. A fixup inside `TB80RTM` that names `TB80W16` is written as that DLL's selector and offset, so the call is a real far call. `KERNEL`, `USER`, and the other system modules are not files. They are gates. The guest calls the gate, the sandbox answers, and the gate's `retf` pops the arguments.

An ordinal with no contract stops the run. The pop size is not guessed. The stop reads `unimplemented KERNEL.N: no contract, pop size not guessed`.

```
python3 -m tbpipeline_neww --b ~/TBK/bin
```

Needs `unicorn` (`pip install -r requirements.txt`) for a run. `--help`, and a missing `--b`, print the usage without it. This is not `tbpipeline_bf`. That tree answers each crash and keeps going. This one links the modules first, and Windows is only the calls that have a contract.

## Record

- When `TB80BAS` is in `--b`, startup prints one line: its exports stay in the DLL. The sandbox has no Python `CDB*`, `OBJ*`, `HEAP*`, `STACK*`, or `RESMGR*`. `tests/test_neww_bas_stays.py` holds both.
- A gate with no contract stops on its `OUT`. Its stub has no `retf`, so nothing is popped, and the sandbox writes neither `AX` nor `DX`. `tests/test_neww_gate_no_pop.py` sets `AX`, calls an unknown ordinal, and checks `SP` holds only the far return.
- A contract is a `Contract` row in `wine.py`: module, ordinal, name, argument sizes in bytes, return. The gate's `retf` pops `sum(args)`, and nothing else sets the pop. `tests/test_neww_contract_row.py`.
- Every `KERNEL` and `USER` row is built by `Contract.from_spec()` from the Wine line it cites: `dlls/krnl386.exe16/krnl386.exe16.spec` or `dlls/user.exe16/user.exe16.spec`, Wine commit `2528aff2`, by ordinal. The argument sizes come from the spec's types (`word`, `s_word` 2; `long`, `ptr`, `str`, `segptr`, `segstr` 4), not from pushes in the ToolBook binary. A row may record a `binary` pop size. If it differs from the spec, the row is not used: the gate stops and the message names both sizes. `tests/test_neww_wine_spec.py`; set `WINE_SRC` to a Wine checkout to compare every line with the file.
- The `__WINFLAGS` equate is not from Wine. Wine's `krnl386.exe16.spec:178` says `0x413`. neww keeps `0x0C25`, the value `bf` and `newl` use.
- `KERNEL.3` `GetVersion` is answered by its row alone: `value = (0x0A03, 0)`, Windows 3.10 in `AX`, `DX` 0, the same pair `newl` returns. There is no `GetVersion` branch in `_kernel`. `tests/test_neww_getversion.py`.
- `KERNEL.132` `GetWinFlags` is answered by its row alone: `value = (0x0C25, 0)`, the same word as the `__WINFLAGS` equate. `tests/test_neww_getwinflags.py`.
- `KERNEL.91` `InitTask` stops by name. It used to return `AX = 1` and nothing else. Wine's `InitTask16` (`dlls/krnl386.exe16/task.c`) also sets `CX`, `DX`, `SI`, `DI`, and `ES:BX`, which points at the command line in the PSP, and it pushes one zero word. neww has no PSP, so the gate stops and names the registers. Any stop now leaves the guest's registers as they were. `tests/test_neww_inittask.py`.
- Gate arguments come from the guest's memory. `Machine.word` and `Machine.string` used to read the loaded image, so a pushed argument read as whatever the file had at that offset, usually 0. `tests/test_neww_args_live.py`.
- `KERNEL.30` `WaitEvent` follows Wine's `WaitEvent16` (`task.c`). `hTask` 0 is the current task, a posted event is taken, and the call returns 0. The single starting event is the one `ne_module.c` `NE_CreateThread` posts. A second wait would block, so it stops. A nonzero `hTask` stops too, because neww has no task handle to match. `tests/test_neww_waitevent.py`.
- `KERNEL.15` `GlobalAlloc(flags, size)` reads `size` as the whole dword: `arg(0) | arg(1) << 16`, with `flags` in `arg(2)`. Before, it took `flags` as the size and kept a Python bytearray that the guest could not reach. Now it follows Wine `global.c`: the size is rounded up to 32 bytes, and the block is mapped behind consecutive data selectors 64K apart, so selector + `__AHINCR` is the next 64K. The handle is the selector, or selector − 1 with `GMEM_MOVEABLE`. Size 0 (Wine's discarded block) and anything over 1M (page-granular selectors) stop by name. `tests/test_neww_globalalloc.py`.
- `KERNEL.74` `OpenFile` has a file table. Handles start at 5, because DOS keeps 0–4. A path ending in `.tbk` or `.sbk` opens the book from `--c`, whatever its directory. Any other path is looked up by base name, without case, in `--b`, and nowhere else. A path that is not found returns `HFILE_ERROR` (`0xFFFF`) with `nErrCode` 2 in the OFSTRUCT. That is Wine `OpenFile16`'s answer for a missing file, and it is chosen for that reason, not copied from `bf`. A `.tbk` without `--c` is a missing file too. Any mode other than read stops by name. `_lopen`, `_lread`, `_llseek`, and `_lclose` use the same table, and the arguments are read in Pascal order. `tests/test_neww_openfile.py`.
- Linking two ToolBook modules is tested on original fixtures. A fixup by ordinal or by name into another NE file becomes that export's selector and offset, and the far call runs the other file's code with no gate. An additive fixup (flag 4) is one location whose word is an addend. It used to be followed as a chain link, which wrote the target into whatever word the addend pointed at. `tests/test_neww_link.py`.
- A ToolBook fixup with no target, because the DLL is not in `--b` or the export is not there, is never a gate. It is linked to a trap. When the guest calls it, the run stops with `not linked: TB80RTM -> TB80W16.7`. Wine is not asked. Before, the fixup was left unwritten and the call died as an anonymous CPU exception. `tests/test_neww_toolbook_not_gate.py`.
