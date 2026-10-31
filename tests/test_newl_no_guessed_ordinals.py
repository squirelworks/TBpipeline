"""newl does not carry LocalInit, GlobalReAlloc or MakeProcInstance until a real Gap names one.

Ordinals are Wine's krnl386.exe16.spec: 4 LocalInit, 16 GlobalReAlloc, 51 MakeProcInstance.
When a real run stops on one, the PR that adds it quotes that stop and removes it from here.
"""

import unittest

from tbpipeline_newl.layer import EQUATES, KERNEL, TABLES, Gap, Layer

NOT_YET = {4: "LocalInit", 16: "GlobalReAlloc", 51: "MakeProcInstance"}


class NoGuessedOrdinals(unittest.TestCase):
    def test_not_in_the_table(self):
        for ordinal, name in NOT_YET.items():
            self.assertNotIn(ordinal, KERNEL, name)
            self.assertNotIn(ordinal, EQUATES["KERNEL"], name)
            names = {row[0].upper() for table in TABLES.values() for row in table.values()}
            self.assertNotIn(name.upper(), names)

    def test_a_call_is_a_gap(self):
        for ordinal in NOT_YET:
            with self.assertRaises(Gap) as got:
                Layer().call("KERNEL", ordinal)
            self.assertEqual(str(got.exception), f"gap KERNEL.{ordinal}")


if __name__ == "__main__":
    unittest.main()
