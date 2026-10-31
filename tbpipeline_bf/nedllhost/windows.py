"""A window table: classes, windows, registered messages, and sends.

TB80BAS and TB80W32 talk to the book file manager, TB80NET, by sending a
registered message to its window. This mixin keeps what USER keeps for
that: each class's window procedure and instance, each window's class and
task, and one atom per registered message name, from 0xC000 as Windows
numbers them. A send calls the window procedure and returns its DX:AX.

A send to a window of another task runs on that task's stack, with its
context restored, the way Win16 switches to the receiving task. The
procedure is entered through Pass06._dispatch with DS = the window's
instance, as USER does for an exported procedure, and returns to a trap,
`out 0xE3, al`, where the host restores the sender.
"""

import struct

from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_DX, UC_X86_REG_EIP, UC_X86_REG_SP, UC_X86_REG_SS

PORT_RETURN16 = 0xE3
FIRST_ATOM = 0xC000
FIRST_HWND = 0x0100
WM_NCCREATE = 0x0081
WM_CREATE = 0x0001


class Windows:
    """Mixin for Pass06. Needs the task loop's jump and _dispatch."""

    def _wintable(self):
        if not hasattr(self, "atoms"):
            self.atoms = {}
        if getattr(self, "windows", None) is None:
            self.windows = {}
            self.frames16 = []
            self.trap16 = self.arena.alloc_selector(0x10, 0x9A, bytes([0xE6, PORT_RETURN16, 0xF4]) + bytes(13))

    def _class_named(self, name):
        """The class RegisterClass kept. Main keys it by (name, instance)."""
        key = name.lower()
        for k, cls in getattr(self, "classes", {}).items():
            if (k[0] if isinstance(k, tuple) else k) == key:
                return cls
        return None

    def _atom(self, name):
        self._wintable()
        key = name.lower()
        if key not in self.atoms:
            self.atoms[key] = FIRST_ATOM + len(self.atoms)
        return self.atoms[key]

    def _far_string(self, far):
        """A far string pointer, or an atom in its low word (MAKEINTATOM)."""
        if far >> 16 == 0:
            return f"#{far & 0xFFFF}"
        return self._string(far >> 16, far & 0xFFFF)

    def _user(self, ordinal):
        # 118 and 57 stay on Pass04: one atom table, and a second register
        # of the same name for the same instance returns 0.
        if ordinal == 41:
            return self._create_window()
        if ordinal == 111:
            hwnd, msg, wparam = self._word(4), self._word(3), self._word(2)
            lparam = self._word(0) | (self._word(1) << 16)
            return self._send(hwnd, msg, wparam, lparam, self._dx_ax)
        return super()._user(ordinal)

    def _create_window(self):
        """CreateWindow. Sends WM_NCCREATE and WM_CREATE, as USER does."""
        self._wintable()
        name = self._far_string(self._word(13) | (self._word(14) << 16))
        cls = self._class_named(name)
        if cls is None:
            self._dx_ax(0)
            return True
        hwnd = FIRST_HWND + 2 * len(self.windows)
        inst = self._word(2) or cls["inst"]
        self.windows[hwnd] = {
            "class": cls, "proc": cls["proc"], "inst": cls["inst"] or inst,
            "task": self.task, "parent": self._word(4),
            "style": self._word(9) | (self._word(10) << 16),
        }
        who = self.task["name"] if self.task else "?"
        if self.task_log is not None:
            self.task_log.append(f"CreateWindow {name!r} hwnd {hwnd:#x} in {who}")
        # CREATESTRUCT for lParam, in the caller's stack segment below SP.
        words = [self._word(n) for n in range(15)]
        cs = struct.pack(
            "<IHHHHHHHIIII",
            words[0] | (words[1] << 16), words[2], words[3], words[4],
            words[5], words[6], words[7], words[8],
            words[9] | (words[10] << 16), words[11] | (words[12] << 16), words[13] | (words[14] << 16), 0,
        )
        create = self._scratch(cs)

        def created(result):
            ok = result & 0xFFFF != 0xFFFF
            self._dx_ax(hwnd if ok else 0)
            if not ok:
                self.windows.pop(hwnd, None)

        def after_nc(result):
            if not result & 0xFFFF:
                self.windows.pop(hwnd, None)
                self._dx_ax(0)
                return
            self._send(hwnd, WM_CREATE, 0, create, created, nested=True)

        return self._send(hwnd, WM_NCCREATE, 0, create, after_nc)

    def _scratch(self, data):
        """A far pointer to data in a selector the host keeps for messages."""
        if not getattr(self, "scratch16", 0):
            self.scratch16 = self.arena.alloc_selector(0x1000, 0x92, bytes(0x1000))
            self.scratch_at = 0
        if self.scratch_at + len(data) > 0x1000:
            self.scratch_at = 0
        at = self.scratch_at
        self.arena.write(self.scratch16, at, data)
        self.scratch_at = (at + len(data) + 15) & ~15
        return (self.scratch16 << 16) | at

    # -- sending --------------------------------------------------------

    def _send(self, hwnd, msg, wparam, lparam, done, nested=False):
        """Call hwnd's procedure; done(dx_ax) runs in the sender's context.

        With nested, the call is made from inside another send's done,
        after the sender's context was restored: the host is already
        between slices, so it is entered directly.
        """
        self._wintable()
        window = self.windows.get(hwnd)
        if window is None:
            done(0)
            return True
        words = [hwnd, msg, wparam, lparam >> 16, lparam & 0xFFFF]
        self.jump = lambda: self._enter16(window, words, done)
        if not nested:
            self.uc.emu_stop()
        return True

    def _enter16(self, window, words, done):
        uc = self.uc
        saved = uc.context_save()
        sender = self.task
        target = window["task"]
        if target is not sender:
            if target.get("ctx") is None:
                self.fault = f"send to {target['name']}, which has not run"
                return 0
            sender["ctx"] = saved
            uc.context_restore(target["ctx"])
            self.task = target
            self.exe_inst = target.get("exe_inst") or target["inst"]
        # Below the receiver's SP, with room for what the stop left there.
        sp = (uc.reg_read(UC_X86_REG_SP) - 2 * len(words) - 4 - 0x20) & 0xFFFF
        frame = struct.pack("<HH", 0, self.trap16) + b"".join(struct.pack("<H", w) for w in reversed(words))
        ss = uc.reg_read(UC_X86_REG_SS)
        self.arena.write(ss, sp, frame)
        uc.reg_write(UC_X86_REG_SP, sp)
        self.frames16.append((saved, done, sender, target))
        proc_seg, proc_off = window["proc"]
        return self._dispatch(proc_seg, proc_off, window["inst"])

    def _leave16(self):
        saved, done, sender, target = self.frames16.pop()
        result = self.uc.reg_read(UC_X86_REG_AX) | (self.uc.reg_read(UC_X86_REG_DX) << 16)
        self.uc.context_restore(saved)
        if target is not sender:
            # The receiver goes back to where it was blocked; its saved
            # context was never overwritten.
            self.task = sender
            self.exe_inst = sender.get("exe_inst") or sender["inst"]
        done(result)
        if self.jump is not None:
            # done started another send; it runs from here.
            go, self.jump = self.jump, None
            return go()
        return self.uc.reg_read(UC_X86_REG_EIP)

    def _on_out(self, uc, port, size, value, user):
        if port == PORT_RETURN16:
            self.jump = self._leave16
            uc.emu_stop()
            return
        super()._on_out(uc, port, size, value, user)
