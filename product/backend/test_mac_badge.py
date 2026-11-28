"""Where the Mac badge goes, and that it is the real badge.

Everything here runs without a Mac and without a display, because it is
arithmetic plus one reading of the source. The window itself needs a window
server and is covered by the smoke run, which measures it in a screenshot.
"""

import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.geometry import _SimpleRect, _pane_bottom_row, dock_right


def box(left, top, right, bottom):
    return (left, top, right, bottom)


class ABadgeDockedAtTheRightEndOfTheBottomRow(unittest.TestCase):
    """The rule Antonio asked for by name on 2026-11-25, after the badge was
    reported three times for moving around while he typed. The bottom row of
    the pane does not move; the caret's line does."""

    def test_it_sits_inside_the_box_at_the_bottom_right(self):
        row = _pane_bottom_row(100, 500, 400, 38)
        rect = dock_right(row, 38, 11)
        self.assertEqual((451, 362, 489, 400),
                          (rect.left, rect.top, rect.right, rect.bottom))

    def test_it_is_square(self):
        rect = dock_right(_pane_bottom_row(0, 300, 200, 38), 38, 11)
        self.assertEqual(rect.right - rect.left, rect.bottom - rect.top)

    def test_the_inset_is_measured_from_the_right_edge(self):
        row = _SimpleRect(0, 0, 500, 40)
        self.assertEqual(500, dock_right(row, 40, 0).right)
        self.assertEqual(490, dock_right(row, 40, 10).right)

    def test_a_box_narrower_than_the_badge_still_gets_an_answer(self):
        """A one line search field is narrower than the badge is wide. It must
        produce a rectangle rather than raise; placing it well is a question
        for a Mac, placing it at all is this function's job."""
        rect = dock_right(_pane_bottom_row(0, 20, 30, 38), 38, 11)
        self.assertEqual(38, rect.right - rect.left)


class TheMacBadgeAsksTheSharedGeometry(unittest.TestCase):
    """mac_badge imports tkinter, which exists on both machines this suite
    runs on, but it never opens a window at import."""

    def test_badge_rect_matches_the_engine(self):
        import mac_badge
        text_box = box(79, 156, 665, 538)
        rect = mac_badge.badge_rect(text_box)
        expected = dock_right(
            _pane_bottom_row(79, 665, 538, mac_badge.BADGE_SIZE),
            mac_badge.BADGE_SIZE, mac_badge.BADGE_INSET)
        self.assertEqual((expected.left, expected.top, expected.right, expected.bottom),
                          (rect.left, rect.top, rect.right, rect.bottom))

    def test_the_badge_is_inside_the_text_box(self):
        import mac_badge
        rect = mac_badge.badge_rect((79, 156, 665, 538))
        self.assertLess(rect.right, 665)
        self.assertLessEqual(rect.bottom, 538)
        self.assertGreater(rect.left, 79)

    def test_the_heat_colour_runs_green_to_red(self):
        import mac_badge
        clean = mac_badge.heat_color(0)
        busy = mac_badge.heat_color(mac_badge.BADGE_HEAT_MAX)
        self.assertGreater(clean[1], clean[0], "clean should be greener than red")
        self.assertGreater(busy[0], busy[1], "busy should be redder than green")


class ItDrawsTheProductsBadgeAndNotAStandIn(unittest.TestCase):
    """The reason this file exists. The smoke run used to draw a purple circle
    on a Tk canvas, which shared no code with the product, so a screenshot of
    it could not tell you anything about the badge users would see.

    Read as source rather than run, because the drawing needs a window server.
    """

    def tree(self):
        path = os.path.join(HERE, "mac_badge.py")
        with open(path, encoding="utf-8") as handle:
            return ast.parse(handle.read(), filename=path)

    def test_the_picture_comes_from_the_shared_artwork(self):
        src = ast.unparse(self.tree())
        self.assertIn("badge_art.make_heat_badge_image", src)

    def test_it_never_asks_for_the_windows_colour_key(self):
        """Flattening onto the key colour is what turns the Mac badge into a
        dark square. badge_art only does it when asked, so the Mac must never
        ask."""
        src = ast.unparse(self.tree())
        self.assertNotIn("key_color=", src)

    def test_every_widget_takes_its_background_from_the_ladder(self):
        """The toplevel being transparent is not enough: the first CI
        screenshot was an opaque Canvas drawn over a transparent window. Any
        literal background colour here is that bug coming back."""
        src = ast.unparse(self.tree())
        self.assertIn("window.badge_background", src)
        tree = self.tree()
        literals = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.keyword) and node.arg == "bg"
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual([], literals,
                          "a widget is given a hardcoded background")

    def test_the_app_turns_itself_into_an_accessory(self):
        """Tk makes this a regular application with a Dock icon and a menu
        bar, whatever Info.plist says, and a regular application activates
        when it shows a window. The badge taking the caret is fatal."""
        path = os.path.join(HERE, "main_mac.py")
        with open(path, encoding="utf-8") as handle:
            src = ast.unparse(ast.parse(handle.read(), filename=path))
        self.assertIn("become_accessory_app", src)

    def test_it_is_positioned_before_it_is_ever_mapped(self):
        """withdraw() then deiconify() on an overrideredirect Aqua window is
        one more candidate for a badge that never appeared. Built in place
        instead, so the only flash possible is one frame in the right spot."""
        build = next(
            node for cls in ast.walk(self.tree())
            if isinstance(cls, ast.ClassDef) and cls.name == "MacBadge"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "_build")
        src = ast.unparse(build)
        self.assertNotIn("withdraw", src)
        self.assertIn("geometry", src, "it is mapped without a position")

    def test_it_floats_without_taking_focus(self):
        src = ast.unparse(self.tree())
        self.assertIn("window.keep_on_top", src)
        self.assertIn("overrideredirect", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
