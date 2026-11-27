"""The dev tools still load.

Three of them, the two surface tools and the CLI tree measurement, do
`import main` to use the product's own decisions rather than a lookalike. That
only works while `product/backend` is on `sys.path`, and after the 2026-11-26
restructure none of them put it there: each inserted its own directory, which
had stopped holding `main.py`. All three raised ModuleNotFoundError from any
working directory, and nothing noticed, because nothing imported them.

This is that nothing. It is deliberately a smoke test and no more: if the
module body loads, the path is right. These tools drive real UI Automation
against whatever is on screen, so running one inside a test would be nonsense.

**Each import runs in its own interpreter, which is the whole point.** Imported
in-process, the first tool puts `product/backend` on `sys.path` and `main` into
`sys.modules`, and every tool after it then imports fine whether its own path
line is right or wrong. The first version of this test did exactly that and
passed against the broken code it was written to catch.
"""

import os
import subprocess
import sys
import unittest

# They import main.py, which calls into Windows as it loads. The windows-latest
# job in checks.yml is where this really runs; see test_workflows.py, which
# fails if that job ever disappears.
if sys.platform != "win32":
    raise unittest.SkipTest("the tools import main.py, the Windows layer")

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "tools"))

# Only the tools that import the app. The others import nothing of ours, and
# measure_vscode_pane.py deliberately does its sampling at module level, so
# importing it would block for twelve seconds.
TOOLS_THAT_IMPORT_THE_APP = (
    "tools_probe_surfaces",
    "tools_measure_cli_trees",
    "tools_scan_surfaces",
)


def import_in_a_fresh_interpreter(name):
    """Import one tool the way running it does: a clean interpreter with
    product/tools as the starting directory, so the only thing that can put
    product/backend on sys.path is the tool's own line."""
    return subprocess.run(
        [sys.executable, "-c", "import " + name],
        cwd=TOOLS, capture_output=True, text=True, timeout=120,
    )


class TheToolsThatImportTheAppStillImport(unittest.TestCase):
    def test_each_one_loads_on_its_own(self):
        for name in TOOLS_THAT_IMPORT_THE_APP:
            with self.subTest(tool=name):
                done = import_in_a_fresh_interpreter(name)
                self.assertEqual(
                    0, done.returncode,
                    "%s.py does not import. Its sys.path line probably points at "
                    "its own folder instead of ../backend:\n%s" % (name, done.stderr),
                )

    def test_they_really_do_import_main(self):
        """Otherwise this file would keep passing after someone removed the
        import it exists to protect, and the next restructure breaks them
        again in silence."""
        for name in TOOLS_THAT_IMPORT_THE_APP:
            with self.subTest(tool=name):
                with open(os.path.join(TOOLS, name + ".py"), encoding="utf-8") as handle:
                    self.assertIn("import main", handle.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
