# nehost

16-bit host for the OPTLOADER images, plus the static unpacker. The reason for each pass is `WHY.md`.

The unpacker follows moralrecordings' `optloader.py`:
https://github.com/moralrecordings/win16-debug

```
python3 -m tbpipeline_bf.nehost --unpack TB80RTM.EXE -o unpacked.exe
python3 -m tbpipeline_bf.nehost TB80RTM.EXE -o rtm_out
```

`--unpack` runs the static unpacker. Without it, the module runs `BootApp` and dumps the segments the stub expands. `--book` puts a TBK name on the command tail.

The pass directories `rtm - pass 01` through `rtm - pass 07` are the runs. `PASS05.txt` and `PASS06.txt` are the machine logs. `NOTE.txt` beside them is the writeup that used to sit in TBdecompile. Segment `.bin` files are local dumps. They are not a second copy of this host, and they do not belong in TBdecompile.


```
python3 -m tbpipeline_bf.nehost.bmp_bitmap
```

Calls unpacked `TB80BMP` ordinal 3 (`TBKBITMAP`, segment 3 offset `0x3E0`) and stops at the first far call, `0x1FCD`. The selector there is a reloc and is not bound. The log is `nehost/bmp_bitmap.txt`.

```
python3 -m tbpipeline_bf.nehost.dll_probe
```

Calls ordinal 1 of every unpacked 16-bit DLL and stops at the first far call. 32-bit images are skipped. The log is `nehost/dll_probe.txt`.

```
python3 -m tbpipeline_bf.nehost.scaffold
```

The r3 scaffolding. Walks every ordinal of the working DLLs, binds `FFFF` imports, and records which ordinals do work. Ordinal 1 is startup. The log is `nehost/scaffold.txt`.
