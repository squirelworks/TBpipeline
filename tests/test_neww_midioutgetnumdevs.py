"""MMSYSTEM.201 midiOutGetNumDevs is 0, Wine's count with no audio driver.

Spec: `201 pascal midiOutGetNumDevs() midiOutGetNumDevs16`, pop 0, a
long. winmm.c midiOutGetNumDevs is lolvldrv.c MMDRV_GetNum(MMDRV_MIDIOUT),
the devices of the installed drivers. The midimapper is a mapper and adds
none. With no audio driver there is no MIDI driver, mmdevapi's DriverProc
answers DRV_LOAD with 0, and MMDRV_Install installs no mmdevapi. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


class WaveOutGetNumDevs(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import MMSYSTEM
        row = MMSYSTEM[201]
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("midiOutGetNumDevs", (), 0, "long"))

    def test_no_devices(self):
        from tbpipeline_neww.machine import Machine
        # mov ax, 0x5555 ; mov dx, 0x5555 ; call ; mov [0x40], ax ; mov [0x42], dx
        code = neww_ne.mov_ax(0x5555) + bytes([0xBA, 0x55, 0x55])
        at = len(code) + 1
        code += neww_ne.call_far() + bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00])
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, code, [(3, 1, at, 1, 201)], modules=("MMSYSTEM", "KERNEL"))
            host = Machine(d).run(limit=5000)
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((host.word(ds, 0x40), host.word(ds, 0x42)), (0, 0))


if __name__ == "__main__":
    unittest.main()
