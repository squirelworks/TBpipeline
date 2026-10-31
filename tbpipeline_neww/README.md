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
