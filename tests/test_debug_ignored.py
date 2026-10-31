"""Debug run folders are not committed.

Each run writes tbpipeline_bf/_debug/db-YYYYMMDD-HHMMSS/. git must
ignore that path, and no file under a db- folder may be tracked.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = "tbpipeline_bf/_debug/db-20261031-043900"


def git(*argv):
    return subprocess.run(["git", "-C", str(ROOT), *argv], capture_output=True, text=True)


class DebugIgnored(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None or git("rev-parse", "--git-dir").returncode != 0:
            self.skipTest("this is not a git checkout, so there is no ignore rule to read.")

    def test_run_folder_is_ignored(self):
        for name in ("RUN.txt", "02_launch.txt", "render.html", "render/P430_0.png"):
            done = git("check-ignore", "--no-index", "-q", f"{RUN}/{name}")
            self.assertEqual(done.returncode, 0, f"{RUN}/{name} is not ignored")

    def test_no_run_folder_is_tracked(self):
        tracked = [p for p in git("ls-files").stdout.splitlines() if "/_debug/db-" in p or p.startswith("_debug/db-")]
        self.assertEqual(tracked, [])


if __name__ == "__main__":
    unittest.main()
