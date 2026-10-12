# tbpipeline_neww

A Win16 sandbox around TB80.

Every unpacked NE file in `--b` is loaded into one address space. A fixup inside `TB80RTM` that names `TB80W16` is written as that DLL's selector and offset, so the call is a real far call. `KERNEL`, `USER`, and the other system modules are not files. They are gates. The guest calls the gate, the sandbox answers, and the gate's `retf` pops the arguments.

An ordinal with no contract stops the run. The pop size is not guessed.

```
python3 -m tbpipeline_neww --b ~/TBK/bin
```

Needs `unicorn` (`pip install -r requirements.txt`). This is not `tbpipeline_bf`. That tree answers each crash and keeps going. This one links the modules first, and Windows is only the calls that have a contract.
