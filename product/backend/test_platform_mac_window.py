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
import contextlib
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
SCREEN_HEIGHT = 768


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


RECT = Rect(686, 434, 724, 472)


class FakeFrame:
    def __init__(self, x, y, w, h):
        self.origin = type("P", (), {"x": x, "y": y})
        self.size = type("S", (), {"width": w, "height": h})


class FakeNS:
    """An NSWindow whose frame is given in Tk coordinates and converted the
    way AppKit really reports it, from the bottom of the screen."""

    def __init__(self, rect):
        self._frame = FakeFrame(rect.left, SCREEN_HEIGHT - rect.bottom,
                                rect.right - rect.left, rect.bottom - rect.top)

    def isVisible(self):
        return True

    def frame(self):
        return self._frame


@contextlib.contextmanager
def fake_appkit(windows):
    """An AppKit whose application shows exactly these windows."""
    screen = type("Screen", (), {
        "frame": staticmethod(lambda: FakeFrame(0, 0, 1024, SCREEN_HEIGHT))})
    fake = type("AppKit", (), {
        "NSApplication": type("NSApplication", (), {
            "sharedApplication": staticmethod(
                lambda: type("App", (), {
                    "windows": staticmethod(lambda: windows)}))}),
        "NSScreen": type("NSScreen", (), {
            "screens": staticmethod(lambda: [screen])}),
    })
    with mock.patch.dict("sys.modules", {"AppKit": fake}):
        yield windows


def as_platform(macos):
    """Pretend we are, or are not, on a Mac. The whole point of these tests."""
    return mock.patch.object(window, "is_macos", lambda: macos)


def appkit_clear(works):
    """Whether AppKit gives us a per pixel transparent window. That needs a
    real NSWindow, so it is an input here rather than a fact."""
    return mock.patch.object(window, "upgrade_to_clear",
                             lambda win, rect: works)


class TransparencyFallsBackRatherThanFails(unittest.TestCase):
    def test_windows_uses_the_colour_key(self):
        w = FakeWin()
        with as_platform(macos=False):
            self.assertEqual(window.make_badge_window_transparent(w, KEY), "keyed")
        self.assertIn(("-transparentcolor", KEY), w.calls)

    def test_macos_builds_on_a_rung_that_definitely_draws(self):
        """-transparentcolor does not exist outside Windows, and neither does
        anything in Tk that worked. `wm attributes -transparent 1` plus a
        systemTransparent background was measured on macOS 26.7.2 drawing
        NOTHING AT ALL, while Tk reported the window mapped and viewable at
        exactly the right rectangle. The same run forced the alpha and opaque
        rungs and both drew the real badge in the right place.

        So macOS has no top rung HERE. The window is built on alpha, which
        draws, and upgrade_to_clear improves it once there is an NSWindow to
        improve. A window that is mapped and ugly beats one that is perfect
        and invisible."""
        w = FakeWin()
        with as_platform(macos=True):
            self.assertEqual(window.make_badge_window_transparent(w, KEY), "alpha")
        self.assertNotIn(("-transparentcolor", KEY), w.calls)
        self.assertNotIn(("-transparent", True), w.calls)

    def test_it_falls_back_to_alpha_when_the_window_cannot_be_cleared(self):
        """A dark square around the badge is worse than a slightly faint one.
        Both platforms have to fall the same way."""
        w = FakeWin(refuse={"-transparentcolor"})
        with as_platform(macos=False):
            self.assertEqual(window.make_badge_window_transparent(w, KEY), "alpha")
        self.assertIn(("-alpha", window.BADGE_ALPHA_FALLBACK), w.calls)

        w = FakeWin()
        with as_platform(macos=True):
            self.assertEqual(window.make_badge_window_transparent(w, KEY), "alpha")
        self.assertIn(("-alpha", window.BADGE_ALPHA_FALLBACK), w.calls)

    def test_it_reports_opaque_rather_than_pretending(self):
        for macos in (False, True):
            with self.subTest(macos=macos):
                w = FakeWin(refuse={"-transparentcolor", "-alpha"})
                with as_platform(macos=macos):
                    self.assertEqual(
                        window.make_badge_window_transparent(w, KEY), "opaque")

    def test_it_never_raises_whatever_the_toolkit_does(self):
        for macos in (False, True):
            with self.subTest(macos=macos):
                w = FakeWin(refuse={"-transparentcolor", "-alpha"})
                with as_platform(macos=macos):
                    window.make_badge_window_transparent(w, KEY)   # must return


class TheLadderHasToReachTheWidgetsInside(unittest.TestCase):
    """The first real CI run reported `transparency: keyed` over a screenshot
    of a dark rectangle, and both were true. `-transparent` was accepted on
    the toplevel, and the Canvas inside it had a solid -background and was
    drawn straight over it. A transparent window with an opaque child is an
    opaque badge."""

    def test_a_cleared_mac_window_makes_its_children_transparent_too(self):
        with as_platform(macos=True):
            self.assertEqual("systemTransparent",
                             window.badge_background("clear", KEY))

    def test_the_dead_macos_keying_is_not_coming_back(self):
        """keyed is the Windows colour key now and nothing else. On Aqua it
        was measured drawing nothing at all."""
        with as_platform(macos=True):
            self.assertEqual(KEY, window.badge_background("keyed", KEY))

    def test_windows_children_keep_the_key_colour(self):
        """That shade is what -transparentcolor deletes, so on Windows the
        children painting it IS the transparency."""
        with as_platform(macos=False):
            self.assertEqual(KEY, window.badge_background("keyed", KEY))

    def test_the_lower_rungs_keep_the_key_colour_on_both(self):
        """alpha and opaque both mean the square is visible, faintly or not,
        which is what the ladder already promises you get."""
        for macos in (False, True):
            for mode in ("alpha", "opaque"):
                with self.subTest(macos=macos, mode=mode):
                    with as_platform(macos=macos):
                        self.assertEqual(KEY, window.badge_background(mode, KEY))

    def test_an_unknown_mode_is_treated_as_not_transparent(self):
        """Fail towards the visible square rather than towards a background
        the toolkit may not understand at all."""
        with as_platform(macos=True):
            self.assertEqual(KEY, window.badge_background(None, KEY))


class TheLadderCanBeForcedToOneRung(unittest.TestCase):
    """Nothing in the product forces a rung. The smoke run does, so a real Mac
    can measure all three in one go instead of us picking one and finding out
    a CI round later which was visible."""

    def test_forcing_alpha_skips_the_colour_key_entirely(self):
        for macos in (False, True):
            with self.subTest(macos=macos):
                w = FakeWin()
                with as_platform(macos=macos):
                    self.assertEqual(
                        "alpha",
                        window.make_badge_window_transparent(w, KEY, prefer="alpha"))
                self.assertNotIn(("-transparentcolor", KEY), w.calls)

    def test_forcing_opaque_asks_for_nothing_at_all(self):
        w = FakeWin()
        with as_platform(macos=True):
            self.assertEqual(
                "opaque",
                window.make_badge_window_transparent(w, KEY, prefer="opaque"))
        self.assertEqual([], w.calls)

    def test_no_preference_takes_the_top_rung(self):
        w = FakeWin()
        with as_platform(macos=False):
            self.assertEqual("keyed",
                             window.make_badge_window_transparent(w, KEY))

    def test_a_forced_rung_that_the_toolkit_refuses_still_degrades(self):
        w = FakeWin(refuse={"-alpha"})
        with as_platform(macos=True):
            self.assertEqual(
                "opaque",
                window.make_badge_window_transparent(w, KEY, prefer="alpha"))


class TheAppMustNotBeARegularApplication(unittest.TestCase):
    """LSUIElement is true in the built Info.plist, which was confirmed by
    reading the bundle, and it is NOT enough: Tk sets the activation policy
    back to regular when it starts. The CI screenshot shows Tk's own default
    Aqua menu bar, File / Edit / Window / Help, under the name Comprsly, with
    a Dock icon beside the Finder's.

    A regular app activates when it shows a window, so the badge appearing
    took the caret from TextEdit, and the watch loop then read Comprsly's own
    focused element instead of the text box it was meant to badge."""

    def test_it_does_nothing_on_windows(self):
        with as_platform(macos=False):
            self.assertFalse(window.become_accessory_app())

    def test_it_asks_for_the_accessory_policy_on_a_mac(self):
        asked = []

        class FakeNSApp:
            @staticmethod
            def setActivationPolicy_(policy):
                asked.append(policy)
                return True

        class FakeAppKit:
            NSApplicationActivationPolicyAccessory = 1

            @staticmethod
            def NSApplication():
                raise AssertionError("must go through sharedApplication")

        FakeAppKit.NSApplication = type(
            "NSApplication", (), {"sharedApplication": staticmethod(lambda: FakeNSApp)})
        with as_platform(macos=True), mock.patch.dict(
                "sys.modules", {"AppKit": FakeAppKit}):
            self.assertTrue(window.become_accessory_app())
        self.assertEqual([1], asked)

    def test_a_toolkit_that_refuses_is_reported_and_not_raised(self):
        class Broken:
            @staticmethod
            def sharedApplication():
                raise RuntimeError("no NSApplication here")

        with as_platform(macos=True), mock.patch.dict(
                "sys.modules", {"AppKit": type("AppKit", (), {
                    "NSApplication": Broken,
                    "NSApplicationActivationPolicyAccessory": 1})}):
            self.assertFalse(window.become_accessory_app())


class WhatAppKitIsAskedForDirectly(unittest.TestCase):
    """Tk hands out no pointer to the NSWindow, and `wm attributes` covers a
    fraction of what one can be told. The fraction it covers turned out not
    to include anything that worked, so these three go through AppKit.

    None of them can be exercised for real here: they need a window server
    and a running NSApplication. What is pinned is that they fail closed off
    a Mac, never raise, and are actually wired into the badge."""

    def test_they_do_nothing_at_all_on_windows(self):
        with as_platform(macos=False):
            self.assertIsNone(window.native_window(FakeWin()))
            self.assertFalse(window.upgrade_to_clear(FakeWin(), RECT))
            self.assertFalse(window.float_without_activating(FakeWin()))

    def test_describing_a_window_that_is_not_there_says_so(self):
        with as_platform(macos=False):
            self.assertIn("not found", window.describe_native(FakeWin()))

    def test_a_broken_appkit_is_swallowed_rather_than_raised(self):
        """A badge is decoration. It may fail to float; it may not take the
        product down while someone is typing."""
        class Broken:
            @staticmethod
            def sharedApplication():
                raise RuntimeError("no NSApplication here")

        fake = type("AppKit", (), {"NSApplication": Broken})
        with as_platform(macos=True), mock.patch.dict(
                "sys.modules", {"AppKit": fake}):
            self.assertIsNone(window.native_window(FakeWin()))
            self.assertFalse(window.upgrade_to_clear(FakeWin(), RECT))
            self.assertFalse(window.float_without_activating(FakeWin()))
            self.assertIn("not found", window.describe_native(FakeWin()))

    def test_the_only_window_on_screen_is_the_badge(self):
        """The Tk root is permanently withdrawn and the badge is the only
        window this application shows, so one visible window needs no
        matching at all."""
        with as_platform(macos=True), fake_appkit([FakeNS(RECT)]) as shown:
            self.assertIs(shown[0], window.native_window(FakeWin(), RECT))

    def test_a_title_lookup_would_never_have_matched(self):
        """This is how the first four CI rounds failed: an overrideredirect
        window on Aqua is a borderless NSWindow and `wm title` does not reach
        it, so every AppKit call reported success doing nothing."""
        with open(os.path.join(HERE, "platform_mac", "window.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        called = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertNotIn("title", called)

    def test_several_windows_are_told_apart_by_their_frame(self):
        """Tk measures from the top of the screen and AppKit from the bottom,
        so a badge near the bottom of a text box is near the top of a frame.
        Getting that backwards picks the wrong window silently."""
        wrong = FakeNS(Rect(0, 0, 38, 38))
        right = FakeNS(RECT)
        with as_platform(macos=True), fake_appkit([wrong, right]):
            self.assertIs(right, window.native_window(FakeWin(), RECT))

    def test_several_windows_and_none_of_them_fit_is_none(self):
        with as_platform(macos=True), fake_appkit([FakeNS(Rect(1, 1, 9, 9))]):
            # one visible window is taken on trust; two that do not fit is not
            with as_platform(macos=True), fake_appkit(
                    [FakeNS(Rect(1, 1, 9, 9)), FakeNS(Rect(2, 2, 9, 9))]):
                self.assertIsNone(window.native_window(FakeWin(), RECT))


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
