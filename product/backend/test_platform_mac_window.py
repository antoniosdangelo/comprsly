"""What can be tested about the Mac window handling without a Mac.

These pin the decisions and the fallback order, so a later change cannot
quietly drop the fallback and leave Mac users with a dark square around the
badge.

They used to read whichever branch the host OS happened to take, which meant
the macOS branch was never exercised at all on Windows and the Windows branch
was never exercised on a Mac. The first real macos-latest run failed three of
them for that reason alone: the code did the right thing and the tests, which
had quietly assumed they were not on a Mac, called it wrong. The platform is
an argument now, and every case runs on every machine.
"""

import ast
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from platform_mac import window


class FakeWin:
    """A Tk window that refuses whichever attributes we tell it to."""

    def __init__(self, refuse=()):
        self.refuse = set(refuse)
        self.calls = []
        self._w = ".fake"
        self.tk = self
        self.bg = None

    def attributes(self, name, value):
        self.calls.append((name, value))
        if name in self.refuse:
            raise RuntimeError("bad attribute %s" % name)

    def configure(self, **kw):
        self.bg = kw.get("bg")

    def call(self, *args):
        self.calls.append(args)


KEY = "#0B0B0D"


def as_platform(macos):
    """Pretend we are, or are not, on a Mac. The whole point of these tests."""
    return mock.patch.object(window, "is_macos", lambda: macos)


class TransparencyFallsBackRatherThanFails(unittest.TestCase):
    def test_windows_uses_the_colour_key(self):
        w = FakeWin()
        with as_platform(macos=False):
            self.assertEqual(window.make_badge_window_transparent(w, KEY), "keyed")
        self.assertIn(("-transparentcolor", KEY), w.calls)

    def test_macos_uses_transparent_and_a_system_background(self):
        """-transparentcolor does not exist outside Windows, so the Mac has to
        take the other road. This case never ran until the suite reached a
        Mac, and then it ran as a failure."""
        w = FakeWin()
        with as_platform(macos=True):
            self.assertEqual(window.make_badge_window_transparent(w, KEY), "keyed")
        self.assertIn(("-transparent", True), w.calls)
        self.assertEqual("systemTransparent", w.bg)
        self.assertNotIn(("-transparentcolor", KEY), w.calls)

    def test_it_falls_back_to_alpha_when_the_key_is_refused(self):
        """A dark square around the badge is worse than a slightly faint one.
        Both platforms have to fall the same way."""
        for macos, refused in ((False, "-transparentcolor"), (True, "-transparent")):
            with self.subTest(macos=macos):
                w = FakeWin(refuse={refused})
                with as_platform(macos=macos):
                    self.assertEqual(
                        window.make_badge_window_transparent(w, KEY), "alpha")
                self.assertIn(("-alpha", window.BADGE_ALPHA_FALLBACK), w.calls)

    def test_it_reports_opaque_rather_than_pretending(self):
        for macos in (False, True):
            with self.subTest(macos=macos):
                w = FakeWin(refuse={"-transparentcolor", "-transparent", "-alpha"})
                with as_platform(macos=macos):
                    self.assertEqual(
                        window.make_badge_window_transparent(w, KEY), "opaque")

    def test_it_never_raises_whatever_the_toolkit_does(self):
        for macos in (False, True):
            with self.subTest(macos=macos):
                w = FakeWin(refuse={"-transparentcolor", "-transparent", "-alpha"})
                with as_platform(macos=macos):
                    window.make_badge_window_transparent(w, KEY)   # must return


class TheMacBadgeMustNotStealFocus(unittest.TestCase):
    """The one thing that would make the badge unusable: appearing mid sentence
    and taking the caret. Also never exercised before the suite saw a Mac."""

    def test_it_marks_itself_a_non_activating_panel_on_macos(self):
        w = FakeWin()
        with as_platform(macos=True):
            self.assertTrue(window.keep_on_top(w))
        self.assertIn(
            ("::tk::unsupported::MacWindowStyle", "style", ".fake",
             "utility", "noActivates"),
            w.calls,
        )

    def test_windows_does_not_get_the_mac_call(self):
        w = FakeWin()
        with as_platform(macos=False):
            self.assertTrue(window.keep_on_top(w))
        self.assertEqual([("-topmost", True)], w.calls)

    def test_a_toolkit_that_refuses_topmost_reports_failure(self):
        """Was in the class this replaced. Kept, because a badge that cannot
        float is a badge hidden behind the window it belongs to."""
        for macos in (False, True):
            with self.subTest(macos=macos):
                w = FakeWin(refuse={"-topmost"})
                with as_platform(macos=macos):
                    self.assertFalse(window.keep_on_top(w))

    def test_an_older_tk_without_the_call_still_floats(self):
        """Losing noActivates costs focus on click, which is worth knowing and
        not worth refusing to float over."""
        class NoSuchCall(FakeWin):
            def call(self, *args):
                raise RuntimeError("bad window style")

        w = NoSuchCall()
        with as_platform(macos=True):
            self.assertTrue(window.keep_on_top(w))


class TheWindowsPathIsUntouched(unittest.TestCase):
    def test_main_still_uses_transparentcolor_directly(self):
        """Windows has a Store submission pending, so its badge code was not
        rerouted through this module. If that ever changes, this test should be
        changed deliberately, not discovered.

        Reads main.py as text rather than importing it, because importing it
        runs ctypes.windll and that does not exist on a Mac. The assertion is
        the same one; only the way of reaching the source changed.
        """
        path = os.path.join(HERE, "main.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        found = [
            node
            for cls in tree.body
            if isinstance(cls, ast.ClassDef) and cls.name == "PersistentBadge"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "_ensure_window"
        ]
        self.assertEqual(1, len(found), "PersistentBadge._ensure_window moved")
        src = ast.unparse(found[0])
        self.assertIn("-transparentcolor", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
