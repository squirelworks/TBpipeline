"""MMSYSTEM.350 auxGetNumDevs is 0, Wine's count with no auxiliary audio driver.

Roadmap #201 T3. Spec (mmsystem.dll16.spec:60): `350 pascal auxGetNumDevs() auxGetNumDevs16`,
pop 0, a long. At Wine 2528aff2, mmsystem.dll16/mmsystem.c:602-605 auxGetNumDevs16 returns
winmm auxGetNumDevs, and winmm/winmm.c:195-198 returns MMDRV_GetNum(MMDRV_AUX).
winmm/lolvldrv.c:75-81 MMDRV_GetNum is llTypes[MMDRV_AUX].wMaxId. MMDRV_Init
(lolvldrv.c:482-487) installs mmdevapi and the two mappers. mmdevapi's auxMessage
(mmdevapi/main.c:451-465) asks the unix audio driver. A count of 0 adds nothing
(lolvldrv.c:358-361), and only a driver's device count adds to wMaxId (lolvldrv.c:363).
neww has no audio driver, so the count is 0. Before this row, the call was answered by a
loaded spec row with no handler. No binary needed.
"""

import tempfile
import unittest

from tests import neww_ne
from unicorn.x86_const import UC_X86_REG_DS


class AuxGetNumDevs(unittest.TestCase):
    def test_row_is_the_spec(self):
        from tbpipeline_neww.wine import MMSYSTEM
        row = MMSYSTEM[350]
        self.assertIsNotNone(row)
        self.assertEqual((row.name, row.args, row.pop, row.ret), ("auxGetNumDevs", (), 0, "long"))

    def test_no_devices_and_no_spec_row_default(self):
        from tbpipeline_neww.machine import Machine
        # mov ax, 0x5555 ; mov dx, 0x5555 ; call ; mov [0x40], ax ; mov [0x42], dx
        code = neww_ne.mov_ax(0x5555) + bytes([0xBA, 0x55, 0x55])
        at = len(code) + 1
        code += neww_ne.call_far() + bytes([0xA3, 0x40, 0x00, 0x89, 0x16, 0x42, 0x00])
        with tempfile.TemporaryDirectory() as d:
            neww_ne.exit_program_with(d, code, [(3, 1, at, 1, 350)], modules=("MMSYSTEM", "KERNEL"))
            host = Machine(d).run(limit=5000)
        ds = host.uc.reg_read(UC_X86_REG_DS)
        self.assertEqual(host.stop, "dos exit 0x0")
        self.assertEqual((host.word(ds, 0x40), host.word(ds, 0x42)), (0, 0))
        self.assertEqual([d for d in host.box.wine.defaults if d[1] == 350], [])


if __name__ == "__main__":
    unittest.main()
