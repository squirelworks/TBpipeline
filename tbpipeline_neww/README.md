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
