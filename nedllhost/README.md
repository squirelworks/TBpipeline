# nedllhost

Binds `TB80RTM` ordinal imports to the unpacked ToolBook DLLs.

```
python3 -m tbpipeline.nedllhost --b ~/TBK/bin
```

`--b` is the directory with `TB80RTM.EXE`, `TB80BAS.DLL`, `TB80RCR.DLL`, `TB80LNL.DLL`, `TB80OLE.DLL`, `TB80UTL.DLL`, and `TB80W16.DLL`.

Prints each resolved `module.ordinal` as a segment and offset, and writes `BIND.txt` in the current directory. `USER`, `GDI`, and `KERNEL` stay unresolved. Those images are not in the set.
