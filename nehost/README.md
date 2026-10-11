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

```
python3 -m tbpipeline.nehost.bmp_bitmap
```

Calls unpacked `TB80BMP` ordinal 3 (`TBKBITMAP`, segment 3 offset `0x3E0`) and stops at the first far call, `0x1FCD`. The selector there is a reloc and is not bound. The log is `nehost/bmp_bitmap.txt`.

```
python3 -m tbpipeline.nehost.dll_probe
```

Calls ordinal 1 of every unpacked 16-bit DLL and stops at the first far call. 32-bit images are skipped. The log is `nehost/dll_probe.txt`.

```
python3 -m tbpipeline.nehost.scaffold
```

The r3 scaffolding. Walks every ordinal of the working DLLs, binds `FFFF` imports, and records which ordinals do work. Ordinal 1 is startup. The log is `nehost/scaffold.txt`.
