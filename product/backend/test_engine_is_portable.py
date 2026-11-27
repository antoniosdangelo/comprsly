"""The engine must stay portable, enforced rather than trusted.

engine/ is the half of Comprsly that a macOS build reuses unchanged. The only
thing keeping it portable is that nobody imports an OS API into it, and that is
exactly the kind of rule that decays the first time someone needs a window
handle "just here". So it is a test.

These import engine/ WITHOUT importing main, which also proves the engine does
not secretly depend on the Windows layer.
"""

import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ENGINE = os.path.join(HERE, "engine")

# Anything here means the file stopped being portable.
BANNED = {
    "ctypes", "winreg", "uiautomation", "comtypes", "win32api", "win32gui",
    "win32con", "win32clipboard", "pywintypes", "pystray", "tkinter",
    "winspell", "main", "webui",
}


def engine_files():
    for name in sorted(os.listdir(ENGINE)):
        if name.endswith(".py"):
            yield name, os.path.join(ENGINE, name)


class EngineStaysPortable(unittest.TestCase):
    def test_there_is_an_engine(self):
        names = [n for n, _ in engine_files()]
        self.assertIn("__init__.py", names)
        self.assertGreater(len(names), 1, "engine/ should hold more than its __init__")

    def test_no_os_specific_imports(self):
        for name, path in engine_files():
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module.split(".")[0]]
                for m in mods:
                    self.assertNotIn(
                        m, BANNED,
                        "engine/%s imports %r, which ties the shared engine to one OS" % (name, m),
                    )

    def test_it_imports_without_the_windows_layer(self):
        """If this needs main.py, it is not a shared engine."""
        from engine import geometry, storage
        self.assertTrue(callable(geometry._pane_bottom_row))
        self.assertTrue(callable(storage._write_json_atomically))

    def test_no_windows_paths_or_apis_in_the_text(self):
        for name, path in engine_files():
            src = open(path, encoding="utf-8").read()
            for needle in ("windll", "LOCALAPPDATA", "C:\\", "HKEY_", ".exe"):
                self.assertNotIn(
                    needle, src,
                    "engine/%s mentions %r, which belongs in the platform layer" % (name, needle),
                )


class TheGeometryStillBehaves(unittest.TestCase):
    """The moved functions must do exactly what they did inside main.py."""

    def test_pane_bottom_row_is_the_panes_last_row(self):
        from engine.geometry import _pane_bottom_row
        r = _pane_bottom_row(100, 1900, 1080, 18)
        self.assertEqual((r.left, r.top, r.right, r.bottom), (100, 1062, 1900, 1080))

    def test_pane_bottom_row_ignores_everything_above_it(self):
        from engine.geometry import _pane_bottom_row
        a = _pane_bottom_row(100, 1900, 1080, 18)
        b = _pane_bottom_row(100, 1900, 1080, 18)
        self.assertEqual((a.top, a.bottom), (b.top, b.bottom))

    def test_badge_inset_adds_the_override(self):
        from engine.geometry import _badge_inset_for
        self.assertEqual(_badge_inset_for("ChatGPT", 16, {"ChatGPT": 56}), 72)
        self.assertEqual(_badge_inset_for("Claude Code", 16, {"ChatGPT": 56}), 16)

    def test_heat_runs_green_to_red(self):
        from engine.geometry import _heat_color
        green, red = _heat_color(0, 6), _heat_color(6, 6)
        self.assertGreater(green[1], green[0], "no suggestions should read green")
        self.assertGreater(red[0], red[1], "a lot of suggestions should read red")

    def test_heat_never_divides_by_zero(self):
        from engine.geometry import _heat_color
        self.assertEqual(len(_heat_color(3, 0)), 4)

    @unittest.skipUnless(sys.platform == "win32",
                         "main.py calls ctypes.windll at import; Windows only")
    def test_the_windows_layer_still_calls_them_the_old_way(self):
        """main.py keeps the original one argument signatures, so no call site
        in those 11,700 lines had to change."""
        import main
        self.assertEqual(main._badge_inset_for("ChatGPT"),
                         main.BADGE_INSIDE_INSET + main.BADGE_INSIDE_INSET_OVERRIDES["ChatGPT"])
        self.assertEqual(len(main._heat_color(2)), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
