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
