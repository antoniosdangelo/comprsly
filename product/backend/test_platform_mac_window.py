"""What can be tested about the Mac window handling without a Mac.

Not much, honestly, and that is the point of these: they pin the decisions and
the fallback order, so a later change cannot quietly drop the fallback and
leave Mac users with a dark square around the badge.
"""

import os
import sys
import unittest

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


class TransparencyFallsBackRatherThanFails(unittest.TestCase):
    def test_windows_uses_the_colour_key(self):
        w = FakeWin()
        self.assertEqual(window.make_badge_window_transparent(w, "#0B0B0D"), "keyed")
        self.assertIn(("-transparentcolor", "#0B0B0D"), w.calls)

    def test_it_falls_back_to_alpha_when_the_key_is_refused(self):
        """A dark square around the badge is worse than a slightly faint one."""
        w = FakeWin(refuse={"-transparentcolor"})
        self.assertEqual(window.make_badge_window_transparent(w, "#0B0B0D"), "alpha")
        self.assertIn(("-alpha", window.BADGE_ALPHA_FALLBACK), w.calls)

    def test_it_reports_opaque_rather_than_pretending(self):
        w = FakeWin(refuse={"-transparentcolor", "-alpha"})
        self.assertEqual(window.make_badge_window_transparent(w, "#0B0B0D"), "opaque")

    def test_it_never_raises_whatever_the_toolkit_does(self):
        w = FakeWin(refuse={"-transparentcolor", "-transparent", "-alpha"})
        window.make_badge_window_transparent(w, "#0B0B0D")   # must simply return


class StayingOnTopWithoutStealingFocus(unittest.TestCase):
    def test_it_asks_for_topmost(self):
        w = FakeWin()
        self.assertTrue(window.keep_on_top(w))
        self.assertIn(("-topmost", True), w.calls)

    def test_it_survives_a_toolkit_that_refuses(self):
        w = FakeWin(refuse={"-topmost"})
        self.assertFalse(window.keep_on_top(w))


class TheWindowsPathIsUntouched(unittest.TestCase):
    def test_main_still_uses_transparentcolor_directly(self):
        """Windows has a Store submission pending, so its badge code was not
        rerouted through this module. If that ever changes, this test should be
        changed deliberately, not discovered."""
        import inspect
        import main
        src = inspect.getsource(main.PersistentBadge._ensure_window)
        self.assertIn("-transparentcolor", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
