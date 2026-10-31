"""Stage 2b and stage 2c name the count they report.

The book is built here: one page, four curves. No binary, no CPU.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from tbpipeline_bf.runtime.debug import run
from tbpipeline_bf.runtime.tbk import BOOK_MAGIC, MARK, STUB


def curve(x0, y0, pairs=20):
    return b"".join(struct.pack("<HH", x0 + 15 * i, y0 + 10 * i) for i in range(pairs))


def book_with_four_curves() -> bytes:
    stub = bytearray(STUB)
    stub[0x40:0x40 + 13] = b"ZZZTBKBOOKLOC"
    page = bytearray(MARK + b"\x00" * 4 + b"P1\x00")
    for n in range(4):
        page += curve(4000 + 1000 * n, 4000)
        page += b"\x00" * 4
    return bytes(stub) + struct.pack("<I", BOOK_MAGIC) + b"\x00" * 12 + bytes(page)


class RenderCounts(unittest.TestCase):
    def test_2b_and_2c_say_which_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            book = tmp / "four.tbk"
            book.write_bytes(book_with_four_curves())
            out = tmp / "db"
            lines, _ = run(str(book), out, dbgrender=True)

            pngs = sorted((out / "render").glob("*.png"))
            self.assertEqual(len(pngs), 4)
            self.assertEqual({p.stem.split("_")[0] for p in pngs}, {"P1"})

            stage_2b = (out / "02b_render.txt").read_text().splitlines()
            stage_2c = (out / "02c.txt").read_text().splitlines()
            pages = [line.strip() for line in stage_2b if line.strip().startswith("render/")]
            files = [line.strip() for line in stage_2c if line.strip().startswith("render/")]
            self.assertEqual(pages, ["render/ 1 pages with a drawing"])
            self.assertEqual(files, ["render/ 4 PNG files, drawn and not placed"])
            self.assertNotEqual(pages, files)


if __name__ == "__main__":
    unittest.main()
