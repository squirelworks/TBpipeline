"""MMSYSTEM's timer calls, from Wine dlls/mmsystem.dll16 at WINE_COMMIT.

mmsystem.c forwards them to winmm, which forwards them to kernel32 sync.c. neww has no
audio drivers, so the device counts stay the spec defaults (0), as winmm answers with none.
"""

import struct

from .handlers import api
from . import gdi16

MMSYSTIME_MININTERVAL, MMSYSTIME_MAXINTERVAL = 1, 65535
TIMERR_NOCANDO = 97          # TIMERR_BASE + 1
MMSYSERR_INVALPARAM = 11


@api("MMSYSTEM", "timeGetTime")
def time_get_time(wine, arg):
    """timeGetTime16 -> kernel32 timeGetTime: milliseconds of the monotonic clock. neww has
    one clock, the one GetTickCount answers."""
    from .user_wnd import m_time
    t = m_time(wine)
    return t & 0xFFFF, t >> 16


@api("MMSYSTEM", "timeGetDevCaps")
def time_get_dev_caps(wine, arg, ptr, size):
    """timeGetDevCaps16: MMSYSERR_INVALPARAM for a null pointer, else kernel32 timeGetDevCaps
    (1 and 65535 ms), copied as TIMECAPS16, at most size bytes of it."""
    if not ptr:
        return MMSYSERR_INVALPARAM, 0
    caps = struct.pack("<HH", MMSYSTIME_MININTERVAL, MMSYSTIME_MAXINTERVAL)[:min(size, 4)]
    if caps:
        gdi16.write(wine, ptr, caps)
    return 0, 0


@api("MMSYSTEM", "timeBeginPeriod", "timeEndPeriod")
def time_period(wine, arg, period):
    """timeBeginPeriod16 / timeEndPeriod16 -> kernel32: TIMERR_NOCANDO outside 1..65535, else 0."""
    if period < MMSYSTIME_MININTERVAL or period > MMSYSTIME_MAXINTERVAL:
        return TIMERR_NOCANDO, 0
    return 0, 0


# ---------------------------------------------------------------- multimedia timers

TIME_PERIODIC = 0x0001
TIME_CALLBACK_EVENT_SET, TIME_CALLBACK_EVENT_PULSE = 0x0010, 0x0020
MM_TIMER_SLOTS = 16          # winmm time.c: static WINE_TIMERENTRY timers[16]


class MMTimer:
    def __init__(self, ident, delay, func, user, flags, due):
        self.id, self.delay, self.func, self.user, self.flags, self.due = ident, delay, func, user, flags, due


class MMTimers:
    """winmm's timer table: 16 slots, and the count of timers made, which picks the next id."""

    def __init__(self):
        self.slots = [None] * MM_TIMER_SLOTS
        self.created = 0


def mm_timers(wine):
    if getattr(wine, "mm", None) is None:
        wine.mm = MMTimers()
    return wine.mm


@api("MMSYSTEM", "timeSetEvent")
def time_set_event(wine, arg, delay, resol, func, user, flags):
    """timeSetEvent16. A callback function (TIME_CALLBACK_FUNCTION) goes to winmm timeSetEvent
    through timeCB3216. winmm answers 0 for a delay outside 1..65535 or with every slot taken;
    the id is 16 * (++timers_created) + slot, made again if that is 0. The first due time is
    timeGetTime() + delay on neww's clock. An event callback (SET or PULSE) needs a Win32 event
    handle, which neww does not have, and stops."""
    from .user_wnd import wm
    kind = flags & (TIME_CALLBACK_EVENT_SET | TIME_CALLBACK_EVENT_PULSE)
    if kind in (TIME_CALLBACK_EVENT_SET, TIME_CALLBACK_EVENT_PULSE):
        return 0, 0, f"timeSetEvent: flags {flags:#x} name a Win32 event, and neww has no Win32 events"
    if kind:
        return 0, 0   # timeSetEvent16's default case: id 0
    if delay < MMSYSTIME_MININTERVAL or delay > MMSYSTIME_MAXINTERVAL:
        return 0, 0
    mm = mm_timers(wine)
    free = [i for i, t in enumerate(mm.slots) if t is None]
    if not free:
        return 0, 0
    i = free[0]
    mm.created += 1
    ident = (MM_TIMER_SLOTS * mm.created + i) & 0xFFFF
    if not ident:
        mm.created += 1
        ident = (MM_TIMER_SLOTS * mm.created + i) & 0xFFFF
    mm.slots[i] = MMTimer(ident, delay, func, user, flags, wm(wine).clock + delay)
    return ident, 0


@api("MMSYSTEM", "timeKillEvent")
def time_kill_event(wine, arg, ident):
    """timeKillEvent16 -> winmm timeKillEvent: TIMERR_NOCANDO for an id not in its slot, else
    the slot is freed and the answer is TIMERR_NOERROR."""
    mm = mm_timers(wine)
    t = mm.slots[ident % MM_TIMER_SLOTS]
    if t is None or t.id != ident:
        return TIMERR_NOCANDO, 0
    mm.slots[ident % MM_TIMER_SLOTS] = None
    return 0, 0


def earliest(wine):
    mm = getattr(wine, "mm", None)
    if mm is None:
        return None
    live = [t for t in mm.slots if t is not None]
    return min(live, key=lambda t: t.due) if live else None


def callback_due(wine, waiting):
    """The 16-bit callback of the first multimedia timer that is due, as a GuestCalls that runs
    the waiting call again afterwards, or None.

    winmm's timer thread calls it through WOWCallback16Ex, which needs the Win16 lock, so the
    16-bit callback runs only while the tasks have let go of the lock: in GetMessage,
    PeekMessage and WaitMessage. neww runs it there, on the waiting task's stack (Wine uses
    the timer thread's own 16-bit stack), with DS = SS as WOWCallback16Ex sets it. With
    waiting (the task would wait and no other task can run), the clock first moves to the
    timer when it comes before every window timer."""
    from .guest import Call, GuestCalls
    from .user_wnd import wm
    from .tasks import earliest_timer
    t = earliest(wine)
    if t is None:
        return None
    m = wm(wine)
    if t.due > m.clock:
        if not waiting:
            return None
        # The first window timer: of any waiting task, or with one task, the task's own.
        window = earliest_timer(wine) if wine.tasks else None
        due = window[0] if window is not None else min(
            (timer[2] for timer in m.timers.values()), default=None)
        if due is not None and due <= t.due:
            return None
        m.clock = t.due
    # TIME_MMSysTimeCallback: a periodic timer's next due time is set before the call; a
    # one-shot timer's slot is freed after it, unless the callback killed or replaced it.
    if t.flags & TIME_PERIODIC:
        t.due += t.delay
    mm = wine.mm
    ss = wine.ss
    wine.trace.append(f"  mm timer {t.id:#x} -> {t.func >> 16:#x}:{t.func & 0xFFFF:#x}")
    call = Call(t.func >> 16, t.func & 0xFFFF, regs={"ds": ss, "es": ss},
                words=[t.id, 0, t.user >> 16, t.user & 0xFFFF, 0, 0, 0, 0])

    def finish(_results):
        if not t.flags & TIME_PERIODIC and mm.slots[t.id % MM_TIMER_SLOTS] is t:
            mm.slots[t.id % MM_TIMER_SLOTS] = None
        return 0, 0
    return GuestCalls([call], finish, retry=True)
