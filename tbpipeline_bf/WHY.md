# Why the code is this way

TBpipeline reads a ToolBook II 8.1 book and writes a page reader. It is not the ToolBook window. Two different programs live in the same tree, because two different questions got asked, and they do not have the same answer.

The reader asks: what is on the page? That is `runtime/`. The host asks: what does `TB80RTM` do when Windows loads it? That is `nehost/` and `nedllhost/`. r5 still answers the first question in Python. The second question is how far the real entry point gets before it gives up.

## The reader does not wait for the host

`python3 -m tbpipeline_bf` always runs stage 1 and stage 2. Stage 2a, the reader, runs only when you pass `--dbgrender`. A failed launch does not write `render.html`.

Stage 2 does not open the book. The last recorded pass-06 run asked for `TB80.INI` and `TB80enu`, then took DOS exit 0. Those names land in `host.opens` because every `OpenFile` and `_lopen` is logged before the stub decides whether the file exists. Only a path ending in `.tbk` or `.sbk` gets a handle, and the bytes behind that handle are the book you passed in. An INI open returns `0xFFFF`. That exit does not write a reader. `--dbgrender` does.

That split is deliberate. The book format is knowable without executing the runtime. The reader is opt-in. A launch that exits does not draw a page on its own.

## What a book is, on disk

`runtime/tbk.py` does not parse a PE. A lesson file is a Click2learn shell: `0xC00` bytes of stub, then the book. The loader looks for `ZZZTBKBOOKLOC` and for magic `0x22222222` at file offset `0xC00`. Pages are the records that start `80 65 00 05 00 02 02`. Widgets inside a page are `14 00 00` chunks. Field text is a `Text` property. A click target is a quoted page id copied out of the record, not a handler that ran.

`.tbk` and `.sbk` are the same shape on disk. The extension is not a different format. `nida81.tbk` and the course books share the `0xC00` shell and the same page marker.

`runtime/engine.py` is the verb list `render.html` calls: `go`, `next`, `back`, `buttonClick`. Navigation is the quoted id. There is no OpenScript interpreter in this tree. The compiled handlers are still bytes in the book.

`runtime/debug/shapes.py` draws curves it can already decode. P430 is the one with a known layout: marker `14 00 00`, fill at `+4`, count at `+0x1a`, twip pairs at `+0x22`, and the screen coordinate is twips divided by 15. Each curve is its own file under `render/`. A kind-04 polygon is also placed in `render.html`, at its own twips divided by 15, measured from the page's top-left corner. The curve runs found by length, like P420's flame, are only files. A kind-04 record names its own bounds: four twip words at `+0x12` (left), `+0x14` (top), `+0x16` (right), `+0x18` (bottom). On `9e954d01.tbk` all 95 polygons the reader keeps have bounds equal to the box of their points, and so does the one on `nida81.tbk`. The reader places each polygon by those bounds / 15. Other widgets are still not placed. In kind-01 records (`+0x0C = 01 00`) the same four words are not bounds: on P430 at page offset `0x89b` they read 2977, 3362, 4036, 2248, so bottom is above top. Fields and buttons have no bounds yet.

`runtime/debug/resources.py` copies BMPs that are already Windows bitmaps. ToolBook's own compressed pictures stay in the book. `TB80BMP` ordinal 3 is the decoder, and it is not called from the reader. See the probe below.

Stage 2b writes `render.html`. `--render old` also writes `render-old.html`. `--theme default` is a Windows 95 window. `--theme modern` is the dark reader. The debug folder is `tbpipeline_bf/_debug/db-YYYYMMDD-HHMMSS/`, beside the package, not the directory you launched from. Each run gets its own folder so a later run does not erase the log that explained the previous one.

The page-count line in stage 2c counts PNG stems. Stage 2b counts pages that had something to draw. P420 has four curves, so the two numbers disagree. Both are reported. `known-bugs.md` says so.

## Why there is a 16-bit host at all

The reader cannot execute a handler, decode a compressed bitmap, or ask the runtime where a widget sits. Those functions already exist inside the unpacked DLLs. The host is there to call them, not to replace them.

It is not a virtual machine you ship to a reader. `unfold.py` says this in one line: a 16-bit protected-mode CPU, the KERNEL ordinals the loader needs, and nothing else. `pass04.py` is the next question, which is the entry point of the unpacked `TB80RTM`. `pass06.py` is the question after that, which is the same entry with the ToolBook DLLs mapped for real.

Reimplementing Windows was not the goal. Letting the real code run, and answering the far calls it actually makes, was. The slow part of r4 and r5 was discovering those calls by crashing. The pop table and the named stubs are the part that should have been written down first. They are written down now.

## The passes

The names are the order the work happened. There is no pass 01 source file. The numbers are the notes.

**OPTLOADER.** `TB80RTM.EXE` and the other 16-bit binaries are self-loading NE images, flag `0x0800`. Segment 1 is a stub. Windows is supposed to call `BootApp` at segment 1 offset `0x169`. The stub unpacks itself, then `LoadAppSeg` expands the other segments. `unpack_optloader.py` is a standalone port of moralrecordings' `optloader.py`. It does not execute anything. `unfold.py` is the Unicorn host that does execute the stub, dumps the expanded segments, and stops. USER, GDI, and the universal thunk are absent there on purpose. That host is a packer unpacker. It is not a book runtime.

**Pass 03** died inside the packed loader. `GetProcAddress` fixups in the stub were the wall. The note is in the `pass04.py` docstring. The packed image is the wrong place to study the entry.

**Pass 04** starts from an already-unpacked `TB80RTM`. It reads the NE segment table itself, builds selectors, applies the reloc records, and jumps to segment 2 offset `0x35A`. That offset is the real entry after the unpacker, not `BootApp`. The book name is placed in a fake PSP command tail at `0x80`, the way DOS hands `WinExec` arguments across. Every guest read of `PSP:0x80` through `0xFF` is recorded in `tail_reads`, and `02_launch.txt` says how many there were. The recorded pass-06 run exits before asking for the book; until a run shows a read of the tail, the book was not requested, whatever the tail holds. `InitTask` hands the tail over as `ES:BX` = PSP:`0x80`. Unresolved far calls used to be skipped so the trace could show the next question. The current entry path does not skip the thunk calls. It answers them.

**Pass 05** is pass 04 run as a probe. The log is `nehost/rtm - pass 05/PASS05.txt`. The spaces in the directory name are the note's name. Leave them. The log is a record of one run: DOS exit 0, no book, and the ordinals the entry touched. `pass04` no longer rewrites that file.

**Pass 06** is pass 04 plus six DLLs mapped in: `TB80RCR`, `TB80LNL`, `TB80OLE`, `TB80W16`, `TB80UTL`, `TB80BAS`. `bind.py` reads each export table. A reloc whose module is one of those six becomes a real `segment:offset`. A reloc whose module is `KERNEL`, `USER`, `GDI`, or OLE stays a thunk. The log is `nehost/rtm - pass 06/PASS06.txt`: 580 DLL entries bound, the INI paths, DOS exit 0. `pass06` no longer rewrites that file.

The init order is not the SoftICE order. It is the order these six can be called without their own imports still being empty: RCR, LNL, OLE, W16, UTL, then BAS. Each DLL entry is called with `DI` = its DGROUP and `CX` = its heap size, which is what the Windows loader passes. Then the startup stub jumps to the EXE at `2:0x35A`.

`loadseq.py` is a different artifact. It walks the SoftICE screenshot order from the 2026-10-10 boot, oldest first, and prints `Load16` / `Load32` / `StartDLL` lines. The selectors it prints are assigned in that walk. They are not the selectors Unicorn uses. It does not run a book. Stage 1 of `run.py` uses its `ORDER` and `FILES` tables to say which of those modules are on disk in `--b`.

## Why Unicorn, and why the CPU starts at 0xF000

Unicorn is used as a 16-bit protected-mode CPU (`UC_MODE_16`). There is no DOS box and no Windows. The host maps one megabyte at linear 0, builds a GDT, and far-jumps into the real code.

The GDT has to sit at linear 0 because that is where the selectors' bases are computed from. An early build stored the GDTR image at linear `0x80`. Selector `0x80` is segment 14. The GDTR write destroyed that descriptor, and every later far call into segment 14 faulted. The GDTR image lives at `0xF0E0` for that reason.

Execution starts at `CS:IP = 0:0xF000`, in a flat selector, not at the EXE entry. Those bytes are a tiny real-mode prefix: `lgdt`, set the PE bit in CR0, then a far jump to `0xF020` in the flat selector. `0xF020` sets `DS` and `SS` to the EXE DGROUP, sets `SP` to the top of that segment, and jumps to `2:0x35A`. Pass 06 inserts the DLL entry calls between the stack setup and that jump.

`2:0x35A` is hardcoded because that is the unpacked entry this image uses. It is not read from the NE header on purpose: the NE header's entry is the packed stub, and this host is past that.

DGROUP for this EXE is segment 139. That number comes from the NE auto-data segment index, stored as `self.segs[139]` after the segment loop. Heap and stack sizes from the NE header are added onto that segment, capped at 64K, because a 16-bit segment cannot be larger.

The instruction cap is `count=2_000_000` and 20 seconds in pass 04, `4_000_000` and 30 seconds in pass 06. Those numbers are there because an uncapped run does not fail. It sits. Do not take them off.

## The thunk

A Windows ordinal is not emulated by decoding `INT 21h` inside USER. The reloc is patched to a slot in one shared code selector.

Each slot is 8 bytes:

```
mov dx, imm16     ; the ordinal
out 0xE0, al
retf 0
```

`OUT 0xE0` is the hypercall. Unicorn raises `UC_HOOK_INSN` for `OUT`. `_on_out` reads `DX`, fixes the return, and returns a value in `AX`/`DX`. Port `0xE0` is arbitrary. It only has to be an I/O instruction the book code does not already use as I/O.

The `retf 0` is a lie. Win16 APIs are Pascal: the callee pops the arguments. The real pop count is applied in `_fix_ret`, which rewrites the immediate of that `retf` before the `out` returns. The site is recorded when the reloc is applied, keyed by the return address, because the same ordinal number means different functions in different modules. `USER.176` is `LoadString`. `GDI.176` is `PlayMetaFileRecord`. `KERNEL.176` is `FreeSelector`. One thunk slot serves all three. The return address is what tells them apart.

The slot array runs from ordinal 1 through 511. It used to stop at 199. `USER.266` is `SetMessageQueue`. That call fell into the zero fill. A `RETF` byte (`0xCB`) got used as a frame, and the CPU came back at the `LES` in segment 13 offset `0xCBEA`. 511 is the whole selector (`0x1000` bytes, 8 bytes per slot) and it covers 266. Extending it was not an aesthetic choice.

`_fix_ret` only rewrites a `retf` it can see at the return site. If the site was not recorded, it counts the pushes in front of the `call far`. That counter stops at the first instruction that is not a push. A `LoadString` call is five pushes (`hinst`, id, segment, offset, count) but the middle of the compiler's output is an `LEA` between the first pushes and the last three. The backward walk then sees 6 bytes, not 10. The recorded pop size is the one that is right. The walk is the fallback for a call whose reloc was not classified.

## Pop sizes

`win16stack.py` is generated from Wine's 16-bit spec files. `word` and `s_word` are 2 bytes. `ptr`, `str`, `segptr`, and `long` are 4. The total is what `retf N` pops.

`USER.176` is `LoadString(word, word, ptr, s_word)` = 10. Every call site in `TB80OLE`, `TB80BAS`, `TB80W16`, `TB80LNL`, and `TB80RCR` pushes those 10 bytes. The table matches the sites. It is not 12. Twelve is `GDI.176`.

The OLE sizes were checked against the `TB80OLE` call sites, not taken from a spec the DLL does not use:

| Ordinal | Call | Bytes |
|---|---|---|
| `COMPOBJ.5` | `CoRegisterClassObject` | 20 |
| `COMPOBJ.6` | `CoRevokeClassObject` | 4 |
| `OLE2DISP.31` | `CreateDispTypeInfo` | 12 |
| `OLE2DISP.32` | `CreateStdDispatch` | 16 |
| `OLE2DISP.35` | `RegisterActiveObject` | 16 |
| `OLE2DISP.36` | `RevokeActiveObject` | 8 |
| `TB80UTL.3` | `GETSTRMGRSTRING` | 10 |

`TB80UTL.3` is in this table because a reloc in `TB80RTM` segment 22 at `0x8AA` names it. Treating that ordinal as `KERNEL.3` `GetVersion` returns `0x0A03` into a buffer the startup code treats as a product name. The first byte is then zero. A zero at `DS:0x41F2` is the check that jumps to the CRT exit. The ordinal has to be the string call, and the string has to be non-empty. The stand-in is `"ToolBook II"` for key `0x0FBD`, and `"ToolBook"` otherwise.

Anything the table does not name pops 0. The default return is `AX = 1`, `DX = 0`. That default is why so many calls looked fine and were wrong. `AX = 1` is a plausible BOOL and a bad pointer, a bad HRESULT, and a bad selector.

Every call that still takes that default is written to `02_launch.txt` as `ax=1 MODULE.ordinal from CS:IP stack w0 w1 w2 w3`. The module is the one the reloc named at that call site, even when the pop table has no size for it, and `?` when no reloc named it. `w0` is the last word pushed. The list is the inventory of answers that are still guesses.

The last call of a run, answered or not, is kept as `last_call` and written as `last call MODULE.ordinal from CS:IP stack w0 w1 w2 w3 -> ax=.. bx=.. cx=.. dx=.. si=.. di=.. ds=.. es=..`, tagged `(AX = 1 default)` when it fell through. That line is how a run names the call that still refuses the book. When it is an `AX = 1` call, the next change replaces that one ordinal with a real answer or a stop. When the same call is named twice, it goes into `known-bugs.md` as the wall.

## Relocs

NE relocations are chained. The word at the fixup address is the next offset, or `0xFFFF` for the end. The host saves that next pointer, writes the resolved value, and follows the saved pointer. Following the value it just wrote walks off into the address it patched in.

Flag bits 0 and 1 equal to 3 is an OSFIXUP. Those chains run through import sites. Writing a thunk into an OSFIXUP replaces the import the chain was passing through. They are skipped.

A type-3 reloc is a far address. A type-2 is a selector. A type-5 is a 16-bit offset. Type 5 is how the C runtime reads `__WINFLAGS`, `__AHSHIFT`, and `__AHINCR`. Those KERNEL exports are constants, not code. Patching them to a thunk offset makes the runtime believe it is in real mode. `EQUATES` in `pass06.py` writes the values instead:

| Export | Value | Why |
|---|---|---|
| `KERNEL.113` `__AHSHIFT` | 3 | selector arithmetic |
| `KERNEL.114` `__AHINCR` | 8 | the arena hands out selectors 8 apart |
| `KERNEL.178` `__WINFLAGS` | `0x0C25` | protected mode, 386, enhanced, 80x87, paging |

`KERNEL.132` `GetWinFlags` returns the same `0x0C25` when the call goes through the thunk. The CRT checks that word and then exits with `AH = 4Ch` through `KERNEL.102` `DOS3Call` instead of `INT 21h`. A stub return of 1 there falls into the C runtime's `R6021` path. `DOS3Call` with `AH = 4Ch` is handled as the DOS exit. That is the `dos exit 0x0` in the pass logs.

`InitTask` (`KERNEL.91`) is answered once, with `AX = 1`, `BX = 0x80` (the command tail), `DI` = DGROUP, `ES` = the fake PSP. A second `InitTask` is not special. The first one is the loader telling the EXE that Windows finished starting it.

DLL prologues are `mov ax, ds` (`8C D8 90`) or `mov ax, 0xFFFF` (`B8 FF FF`). Windows rewrites those to `mov ax, <dgroup>` at load time. The host does the same rewrite, including on the NE entry point, which is not in the export table. Without it the DLL runs with whatever `DS` the caller happened to have, and the first data reference is the wrong segment.

## What the stubs actually implement

The default is still `AX = 1`. These are the calls that could not stay that way.

**Heap.** `GlobalAlloc` / `GlobalLock` / `GlobalFree` and the local-heap ordinals. A pointer the runtime writes through has to be a selector the arena owns. Returning 1 makes the next instruction a write to selector 1.

**Files.** `KERNEL.74` `OpenFile` and `KERNEL.85` `_lopen` log the path and call `_take_file`. A `.tbk` or `.sbk` returns a handle whose bytes are the book passed on the command line. A name ending in `.ini` returns a handle only when `TBK_INI` is set and that directory holds a file of the same name; the bytes are that file. Without `TBK_INI` it is `0xFFFF`, as before. The same directory answers `TB80enu`, the extensionless name pass 06 opens from `C:\TOOLBOOK` between the two rounds of `TB80.INI` opens. What that file should hold is not known, so the host takes whatever the caller put there. `OpenFile`'s style word is kept beside the path in `open_styles`, so a run shows whether an open was an `OF_EXIST` probe. Anything else returns `0xFFFF` and stays in the `opens` list so the log shows what was asked for. `_lread`, `_lwrite`'s absence, and `_llseek` (`KERNEL.84`) use that handle. DOS `INT 21h` `AH=3Dh` is the same rule, and no longer overwrites the handle's bytes with the book after `_take_file` chose them. `AH=3Fh` reads, `AH=42h` seeks, `AH=30h` reports DOS 5, `AH=4Ch` stops the CPU.

**Strings.** `KERNEL.88` `lstrcpy`, `89` `lstrcat`, `90` `lstrlen` copy real bytes. Returning 1 from `lstrcpy` was being loaded as a selector. `KERNEL.49` `GetModuleFileName` writes `C:\TOOLBOOK\TB80RTM.EXE`. `134` and `135` write `C:\WINDOWS` and `C:\WINDOWS\SYSTEM`. `137` `FatalAppExit` prints the string and stops.

**Resources and LoadLibrary.** `FindResource`, `LoadResource`, `LockResource`, `FreeResource`, `SizeofResource`, `AccessResource` read the NE resource table of a module the host indexed. `LoadLibrary` looks in `TBK_UNPACKED` for the file. `TB80ENU` is an alias of `TB80ENU1.DLL`. The handle is that module's DGROUP selector, which is also how a Win16 DLL's `HINSTANCE` works. `USER.176` `LoadString` walks the string table: block `(id >> 4) + 1`, sixteen counted strings, copy into the caller's buffer, return the character count. The ids at the call sites that motivated it are `0xBB8` = `EXTENSIONS` in `TB80OLE`, and `0x69` / `0x6A` = `TB80CVT.DLL` and ` -TB300%s,%u,%u,%u` in `TB80BAS`. If the instance handle does not match, the search tries `DS`, then every loaded module. A missing string returns 0. It does not return 1.

**KERNEL.5** `LocalAlloc` grows the heap's segment when the heap ends at the segment's end and the request fits under 64K. On the real run, TB80BAS's DGROUP (`0xD88`) heap ran out: `LocalAlloc` returned 0 for `0xC8` and `0xDA` bytes. TB80BAS then allocated its `0xDA`-byte record in the task's DS (`0x468`) at `0x9B6C`, and its book open (segment 7 `0x2FC`) read `0x9B6C` through its own DS, found field `+4` zero, and asserted at line 629. A moveable DGROUP in Windows grows; the selector stays and the base moves, so the host maps new memory, copies the bytes, rewrites the descriptor, and reloads `DS`, `ES` or `SS` if they hold it. With the grow, the assertion is gone and the next stop is the runtime's own box: "Initialization failed. Not enough memory or the file is damaged."

**USER.179** `GetSystemMetrics` returns a small table. Metric `0x29` is `SM_PENWINDOWS`. A non-zero value makes startup call `RegisterPenApp` through a null pointer. It stays 0.

**USER.266** `SetMessageQueue` is the ordinal `run.py` prints by name. The return is 1. There is no queue.

**OLE.** `CreateDispTypeInfo` and `CreateStdDispatch` write a dummy `IUnknown` to the out-pointer and return HRESULT 0 in `DX:AX`. `AX = 1` is `S_FALSE`. The caller then drops the object and calls `Release` on a null pointer. `CoRegisterClassObject` and `RegisterActiveObject` write a cookie of 1 and return 0. `CoRevokeClassObject` and `RevokeActiveObject` return 0. The dummy vtable's methods are `mov ax, 1; retf`. That is enough for `AddRef` and `Release`. It is not a type library.

**Skip path.** An `INT` that is not `21h` and not `3`, whose next bytes are a far call, is logged and stepped over, at most 12 times. That is the old "show me the next question" behavior. It is still there for interrupts. Thunk calls are not skipped.

## The probes that are not the entry point

Three small hosts call one ordinal and stop. They exist because booting `TB80RTM` is the long way to ask what one function does.

`dll_probe.py` calls ordinal 1 of every unpacked `TB*.DLL` and `TB*.EXE`. Ordinal 1 is startup. The log is `dll_probe.txt`.

`scaffold.py` walks every later ordinal of the working DLLs, binds `FFFF` imports to a return stub, and records whether the ordinal returned, called Windows, stopped on a far call, or faulted. The log is `scaffold.txt`. Ordinal 1 being startup is why this file exists: the painters and the file functions are later ordinals.

`bmp_bitmap.py` calls `TB80BMP` ordinal 3, `TBKBITMAP`, at segment 3 offset `0x3E0`. The first version stopped at the far call at `0x1FCD` because the selector there is a reloc it did not apply. The probe now applies `TB80BMP`'s own relocations: a far call into another `TB80BMP` segment is followed, and a call to an imported ordinal or name is a gate that stops the run and names the module, the ordinal, and the stack. It does not answer the import. A return to the probe prints `AX:DX` and the object it was handed. The count stays 2000. `bmp_bitmap.txt` is the log of the first run and the probe no longer rewrites it; a new run prints to stdout. The reader does not call this. The probe is the contract for the bitmap work in `v1.0.1`.

Stage 2a copies those three logs into the debug folder so a run you can open still contains the probe that explained the pictures.

## Paths

`--b` is the ToolBook directory. `TBK_UNPACKED` is the same directory for the probes and for `LoadLibrary`. The default, when neither is set, is `bin/` beside this package. It used to be a hardcoded sandbox path, and one probe looked one directory above the repository. Both were wrong for a release. `binpath.py` is the single rule. `run.py` sets the environment from `--b` before it builds the host, because `LoadLibrary` reads the environment at the moment of the call, not at import.

`/Toolbook/` is an archive. The host does not read it.

## What r5 still does not do

- Open the `.tbk` from `TB80RTM`. The entry exits after the INI.
- Place a widget. Bounds are unknown.
- Draw a ToolBook-compressed picture. `TB80BMP` stops at `0x1FCD`.
- Run a handler. Navigation is the quoted page id.
- Implement Windows. The layer under the DLLs is the table in this file. Everything else returns 1.
- Pop the ToolBook GUI.

`plannedmilestones.md` is the rest of that list. `v1.0.1` is the open, the bounds, one real handler, and the polygons placed on the page. `v2.0.0` is the window. Neither of those is this release.
