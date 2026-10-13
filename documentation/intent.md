# Intent

ToolBook II 8.1 books have to be readable without a living ToolBook install as the only reader. The books in this work are the Navy CAI lessons (`nida81.tbk` and the course books) and the system books (`tb80r.sbk` and the others beside it).

Two questions got asked. They do not have the same answer, so they do not share one program.

**What is in the book?** Pages, field text, pictures, curves, and the script a click runs. That is the reader. It lives in `tbpipeline_bf/runtime/`. It does not need Windows, and it does not wait for the 16-bit host.

**What does the real runtime do?** `TB80RTM` and the ToolBook DLLs already contain the functions the reader has not reimplemented: where a widget sits, how a compressed picture becomes a bitmap, what a handler does when it is more than a quoted page id. The hosts exist to call those functions, not to become a second ToolBook.

An answer to the first question is a page you can open and a click you can follow. An answer to the second is one named function that runs far enough to return the fact that was missing. A crash log is not that answer. A stub that returns 1 and lets the CPU continue is not that answer either.

The reader is the product. The host is the instrument. A window that is ToolBook is the long goal in [future.md](future.md). It is not what a normal run is supposed to produce today.

Binaries come from `--b`, which is the ToolBook directory. `TBK_UNPACKED` is the same directory. The default, when neither is set, is `bin/` beside `tbpipeline_bf`. The host does not read `/Toolbook/`.
