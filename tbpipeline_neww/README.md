# tbpipeline_neww

A Win16 sandbox around TB80.

Every unpacked NE file in `--b` is loaded into one address space. A fixup inside `TB80RTM` that names `TB80W16` is written as that DLL's selector and offset, so the call is a real far call. `KERNEL`, `USER`, and the other system modules are not files. They are gates. The guest calls the gate, the sandbox answers, and the gate's `retf` pops the arguments.

An ordinal with no contract stops the run. The pop size is not guessed.

```
python3 -m tbpipeline_neww --b ~/TBK/bin
```

Needs `unicorn` (`pip install -r requirements.txt`). This is not `tbpipeline_bf`. That tree answers each crash and keeps going. This one links the modules first, and Windows is only the calls that have a contract.

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
