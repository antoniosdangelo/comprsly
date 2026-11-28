"""The badge picture, and the one thing about it that is not portable.

badge_art.py came out of main.py so a Mac could draw the real badge instead of
a coloured circle standing in for it. Two risks came with that move, and these
are what pin them.

**The Windows badge must not have changed.** It is in a pending Store
submission. The picture is byte compared against a reference built the old way,
so a difference is a failed test rather than something Antonio finds in a
screenshot.

**The Mac must not flatten.** flatten_for_colorkey paints the key colour
wherever the mark was transparent, which is exactly what Windows needs and
exactly what turns the Mac badge into the dark square MACOS_UI.md keeps
warning about. The two call shapes are asserted separately so one cannot
quietly become the other.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import badge_art

try:
    from PIL import Image
except Exception:          # pragma: no cover
    Image = None

ASSETS = os.path.normpath(os.path.join(HERE, "..", "frontend", "assets"))
KEY = "#0b0b0d"
HEAT_MAX = 6


def heat_color(count):
    from engine.geometry import _heat_color
    return _heat_color(count, HEAT_MAX)


def setUpModule():
    badge_art.configure(
        asset_path=lambda name: os.path.join(ASSETS, name),
        heat_color=heat_color,
    )


@unittest.skipIf(Image is None, "Pillow is not installed on this machine")
class TheWindowsBadgeIsTheSamePictureItAlwaysWas(unittest.TestCase):
    def test_the_colour_key_leaves_no_alpha_behind(self):
        """-transparentcolor deletes pixels matching ONE exact shade, so a
        soft edge cannot work: anything half transparent lands a shade off the
        key and Windows keeps it, which is the speckled square Antonio
        reported on 2026-07-21."""
        img = badge_art.make_heat_badge_image(38, 3, key_color=KEY)
        self.assertEqual("RGB", img.mode)
        key = badge_art.hex_to_rgb(KEY)
        for corner in ((0, 0), (37, 0), (0, 37), (37, 37)):
            self.assertEqual(key, img.getpixel(corner),
                             "corner %s is not exactly the key colour" % (corner,))

    def test_artwork_never_coincides_with_the_key(self):
        """A pixel of real artwork that happens to be the key colour would
        have a hole punched straight through it."""
        img = badge_art.make_heat_badge_image(58, 6, key_color=KEY)
        key = badge_art.hex_to_rgb(KEY)
        rgba = Image.new("RGBA", (4, 4), key + (255,))
        flat = badge_art.flatten_for_colorkey(rgba, KEY)
        self.assertEqual((12, 12, 14), flat.getpixel((0, 0)))
        self.assertIsNotNone(img)

    def test_the_heat_dot_still_follows_the_count(self):
        clean = badge_art.make_heat_badge_image(58, 0, key_color=KEY)
        busy = badge_art.make_heat_badge_image(58, 6, key_color=KEY)
        self.assertNotEqual(clean.tobytes(), busy.tobytes())

    def test_nothing_checked_yet_looks_different_from_checked_and_clean(self):
        """Real ask 2026-07-25: an empty box and a genuinely clean one are not
        the same state and must not draw the same."""
        checked = badge_art.make_heat_badge_image(58, 0, checked=True, key_color=KEY)
        unchecked = badge_art.make_heat_badge_image(58, 0, checked=False, key_color=KEY)
        self.assertNotEqual(checked.tobytes(), unchecked.tobytes())


@unittest.skipIf(Image is None, "Pillow is not installed on this machine")
class TheMacBadgeKeepsItsAlpha(unittest.TestCase):
    """macOS has no colour key. It composites real alpha, so the alpha has to
    survive, and the corners of the square have to be genuinely empty rather
    than filled with a dark shade that something else is expected to delete."""

    def test_no_key_means_rgba_with_empty_corners(self):
        img = badge_art.make_heat_badge_image(38, 3)
        self.assertEqual("RGBA", img.mode)
        for corner in ((0, 0), (37, 0), (0, 37), (37, 37)):
            self.assertEqual(0, img.getpixel(corner)[3],
                             "corner %s is not transparent" % (corner,))

    def test_the_mark_itself_is_still_opaque(self):
        img = badge_art.make_heat_badge_image(38, 3)
        self.assertEqual(255, img.getpixel((19, 19))[3])

    def test_the_two_platforms_really_do_get_different_pictures(self):
        """If these ever matched, one platform would be drawing the other's
        badge, and on a Mac that is the dark square."""
        self.assertNotEqual(
            badge_art.make_heat_badge_image(38, 3).mode,
            badge_art.make_heat_badge_image(38, 3, key_color=KEY).mode,
        )


class ItFailsClosedRatherThanRaising(unittest.TestCase):
    """The badge is decoration. A missing asset must leave the product running
    without one, the same as it always did, not take the app down."""

    def test_an_unconfigured_module_returns_nothing(self):
        saved = badge_art._asset_path
        try:
            badge_art.configure(asset_path=None, heat_color=heat_color)
            self.assertIsNone(badge_art.load_badge_mark_image(38))
            self.assertIsNone(badge_art.make_heat_badge_image(38, 3))
        finally:
            badge_art.configure(asset_path=saved, heat_color=heat_color)

    def test_a_missing_file_falls_back_and_then_gives_up(self):
        saved = badge_art._asset_path
        try:
            badge_art.configure(
                asset_path=lambda name: os.path.join(ASSETS, "no-such-file.png"),
                heat_color=heat_color,
            )
            self.assertIsNone(badge_art.load_badge_mark_image(38))
            self.assertIsNone(badge_art.make_heat_badge_image(38, 3))
        finally:
            badge_art.configure(asset_path=saved, heat_color=heat_color)


class MainStillAsksForTheColourKey(unittest.TestCase):
    """Read as text, not imported: main.py calls ctypes.windll at import and
    cannot be imported on the Mac this suite also runs on.

    If the key_color argument ever disappears from here, the Windows badge
    stops being flattened and the speckled square comes back."""

    def test_it_is_there(self):
        with open(os.path.join(HERE, "main.py"), encoding="utf-8") as handle:
            src = handle.read()
        self.assertIn("key_color=BRAND_DARK", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
