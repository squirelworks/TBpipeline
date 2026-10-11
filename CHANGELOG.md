# Changelog

## 1.0.0r1

Cleanup of 1.0.0. Same reader.

- Removed generated files, caches, and the unused `host.py`.
- WinXP is the preferred VM. Win98 is fine and is the decompile machine. Win11 and Linux are the goal, and they do not run ToolBook yet.

## 1.0.0

First release. A book reader, not the ToolBook window.

- `python3 -m tbpipeline --b <bin> --c <book>` runs startup, launch, open, render.
- Each stage writes its file into `.debug/`. The last stage says the debug information is there.
- `runtime`, `nehost`, and `nedllhost` each run on their own.
- OPTLOADER unpacker credits moralrecordings' `optloader.py`.
- `USER.266` is `SetMessageQueue` and returns 1. The entry still dies before a book open.
- Using ToolBook without a VM is the next goal. WinXP is the preferred machine. Win98 is the decompile floor.
