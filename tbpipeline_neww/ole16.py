"""OLE2's calls, from Wine dlls/ole2.dll16 at WINE_COMMIT.

ole2.c forwards them to ole32. A 16-bit task is a thread there, so per-thread state
(COM_CurrentInfo) is kept per task here.
"""

from .handlers import api

S_OK, S_FALSE = 0, 1


@api("OLE2", "OleInitialize")
def ole_initialize(wine, arg, reserved):
    """ole2.c:71-74 OleInitialize16 -> ole32/ole2.c:162-183 OleInitialize. CoInitializeEx
    (COINIT_APARTMENTTHREADED) succeeds, then S_OK while the thread's ole_inits is 0 and
    S_FALSE once it is not. ole32/ole2.c:193 counts the call."""
    counts = wine.__dict__.setdefault("ole_inits", {})
    inits = counts.get(wine.htask, 0)
    counts[wine.htask] = inits + 1
    return (S_FALSE if inits else S_OK), 0


E_FAIL = 0x80004005


@api("OLE2", "OleFlushClipboard")
def ole_flush_clipboard(wine, arg):
    """ole2.c:270 OleFlushClipboard16 -> ole32/clipboard.c:2277 OleFlushClipboard: E_FAIL while
    the thread's ole_inits is 0 (:2288); else, with no source data object (:2296), S_OK.
    neww has no OleSetClipboard, which is what sets one (it stops by name), so there is never
    one here. The spec's -ret16 keeps the low word."""
    if not wine.__dict__.get("ole_inits", {}).get(wine.htask, 0):
        return E_FAIL & 0xFFFF
    return S_OK
