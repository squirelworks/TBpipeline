"""Calls from a gate back into guest code: LibMain, a window procedure, a callback.

Wine makes these with WOWCallback16Ex from inside the 16-bit call. neww's gate
cannot run the CPU from inside its own hook, so a handler that needs guest
code returns a GuestCalls. The gate's retf goes to a trampoline that makes
each call in turn, reports each result with OUT 0E8h, and with OUT 0E9h hands
the results to `finish`, whose (ax, dx) is the answer the original caller
gets. The trampoline then returns to that caller.
"""


class Call:
    """One far call: cs:ip, registers to set first (ax bx cx dx si di ds es), Pascal words to push
    (first argument first), and whether to push BP and point BP at it, as NE_InitDLL does."""

    def __init__(self, cs, ip, regs=None, words=(), frame=False):
        self.cs = cs
        self.ip = ip
        self.regs = dict(regs or {})
        self.words = list(words)
        self.frame = frame


class GuestCalls:
    """calls run in order. after(i, ax, dx) may return more Call objects to run next, or a stop
    string. finish(results) returns (ax, dx) for the original caller, or (ax, dx, stop)."""

    def __init__(self, calls, finish, after=None):
        self.calls = list(calls)
        self.finish = finish
        self.after = after


def _answer(value):
    if value is None:
        return 0, 0, None
    if isinstance(value, int):
        value &= 0xFFFFFFFF
        return value & 0xFFFF, value >> 16, None
    if len(value) == 2:
        return value[0] & 0xFFFF, value[1] & 0xFFFF, None
    return value


def drive(gen):
    """Run a generator handler. It yields a Call to run in the guest and gets back (ax, dx),
    or yields a string to stop the run there. What it returns is the answer: an int (DX:AX),
    (ax, dx) or (ax, dx, stop). With no Call yielded, the answer comes back directly."""
    try:
        first = gen.send(None)
    except StopIteration as done:
        return _answer(done.value)
    if isinstance(first, str):
        return 0, 0, first
    box = {}

    def after(_index, ax, dx):
        try:
            nxt = gen.send((ax, dx))
        except StopIteration as done:
            box["answer"] = _answer(done.value)
            return None
        if isinstance(nxt, str):
            return nxt
        return [nxt]

    def finish(_results):
        return box["answer"]

    return GuestCalls([first], finish, after)
