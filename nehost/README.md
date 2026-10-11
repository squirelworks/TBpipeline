# nehost

16-bit host for the OPTLOADER images, plus the static unpacker.

The unpacker follows moralrecordings' `optloader.py`:
https://github.com/moralrecordings/win16-debug

```
python3 -m tbpipeline.nehost --unpack TB80RTM.EXE -o unpacked.exe
python3 -m tbpipeline.nehost TB80RTM.EXE -o rtm_out
```

`--unpack` runs the static unpacker. Without it, the module runs `BootApp` and dumps the segments the stub expands. `--book` puts a TBK name on the command tail.

Needs `unicorn` for the live host. The unpacker does not.
