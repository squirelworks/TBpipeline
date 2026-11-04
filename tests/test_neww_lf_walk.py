"""Roadmap #201 T4: Logic Families walked by clicks in neww, with the page label after each click.

The label is the last page id the book draws in its `Page#` field (GDI.351 ExtTextOut 'P...')
between one WM_LBUTTONDOWN and the next. The expected pages are the ones opentoolbook8
SETTLED "Menu" sections and tests/test_menu.py settle by clicking, and that GUIDELINES
§opentoolbook8.4 holds: Menu Selection 1 is TTL (P1001), Selection 2 is Other ICs (P2001);
Back on P1050-P1080 is P1040, P1090 is P1082 and P1150 is P1140; Back on P2050-P2070 is P2040,
P2080 is P2070 and P2150 is P2130.

Screen points: the book window's client starts at (200, 172), and a page unit is 1/15 pixel,
so a button's centre is (200 + x/15, 172 + y/15) of its bounds in twips. Next (8907..9342,
6210..6630) is (808, 600), Back (-3..432) is (215, 600), Menu on P450 (8152..9352) is
(783, 600), selection1 and selection2 on P900 are (513, 257) and (513, 311), and selection1
on P1001 and P2001 is (511, 272). Each step waits 500 ms, as the long run does.

Needs TBK_BIN and TBK_BOOK2 (Logic Families with nida81.tbk beside it). About a minute each.
"""

import os
import re
import unittest
from pathlib import Path

WAIT = "wait 500; "
NEXT, BACK = WAIT + "click 808,600; ", WAIT + "click 215,600; "
TO_MENU = "click 512,420; " + NEXT * 8 + WAIT + "click 783,600; "
OPENING = ["P10", "P100", "P300", "P400", "P410", "P420", "P430", "P440", "P450", "P900"]
LABEL = re.compile(r"^GDI\.351 ExtTextOut '(P\d+)'$")


def walk(script):
    from tests.binpath import bin_or_skip
    root = bin_or_skip("TB80RTM.EXE", "TB80BAS.DLL", "TB80F32L.dll", "TB80RMT.DLL")
    book = os.environ.get("TBK_BOOK2")
    if not book or not (Path(book).parent / "nida81.tbk").exists():
        raise unittest.SkipTest("TBK_BOOK2 is not set, or has no nida81.tbk beside it")
    from tbpipeline_neww.machine import Machine
    host = Machine(str(root), book, input_script=script.rstrip("; "))
    host.call_limit = 1_000_000
    host.timeout_us = 1_000_000_000
    host.run(limit=1_000_000 * 1000)
    trace = host.box.wine.trace
    downs = [i for i, t in enumerate(trace) if t.startswith("  input WM_LBUTTONDOWN")]
    pages = []
    for k, i in enumerate(downs):
        labels = [m.group(1) for m in map(LABEL.match, trace[i:downs[k + 1] if k + 1 < len(downs) else None]) if m]
        pages.append(labels[-1] if labels else None)
    return host, pages


class LogicFamiliesWalk(unittest.TestCase):
    def check(self, host, pages, expected):
        self.assertEqual(host.box.wine.input.raw, [])
        self.assertTrue(host.stop.startswith("idle: input script done"), host.stop)
        self.assertEqual([t for t in host.box.wine.trace if t.startswith("USER.1 MessageBox")], [])
        self.assertEqual(pages, OPENING + expected)

    def test_ttl_discussion_back_returns_to_the_section_starts(self):
        host, pages = walk(TO_MENU + WAIT + "click 513,257; " + WAIT + "click 511,272; "
                           + NEXT * 3 + BACK + NEXT * 5 + BACK + NEXT * 7 + BACK)
        self.check(host, pages, [
            "P1001", "P1040", "P1050", "P1060", "P1070", "P1040",
            "P1050", "P1060", "P1070", "P1080", "P1090", "P1082",
            "P1090", "P1100", "P1110", "P1120", "P1130", "P1140", "P1150", "P1140"])

    def test_other_ics_discussion_back_returns_to_the_section_starts(self):
        host, pages = walk(TO_MENU + WAIT + "click 513,311; " + WAIT + "click 511,272; "
                           + NEXT + BACK + NEXT * 4 + BACK + NEXT * 8 + BACK)
        self.check(host, pages, [
            "P2001", "P2040", "P2050", "P2040",
            "P2050", "P2060", "P2070", "P2080", "P2070",
            "P2080", "P2090", "P2100", "P2110", "P2120", "P2130", "P2140", "P2150", "P2130"])


if __name__ == "__main__":
    unittest.main()
