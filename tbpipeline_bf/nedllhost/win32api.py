"""The Win32 calls TB80W32.DLL makes, answered by name.

Each answer is the documented Win32 behavior for the arguments seen, on
a Windows 98 machine with ToolBook in C:\\TOOLBOOK. A call with no
documented answer for its arguments raises Unanswered and the run stops.
"""

from .win32 import WIN32


def _api(dll, name, pop):
    def register(fn):
        WIN32[(dll, name)] = (pop, fn)
        return fn
    return register
