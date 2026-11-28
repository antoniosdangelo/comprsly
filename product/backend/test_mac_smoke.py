"""The smoke run's verdicts, which are the only part of it a Mac is not needed for.

The value of mac_smoke.py is that it reports what it measured, and that a
permission macOS refused reads as BLOCKED and never as a pass. That promise
lives in a handful of pure functions, so they are tested here, on Windows, in
the same suite as everything else. The rest of that script is subprocess
plumbing only a Mac can run.

The badge verdict is the one worth reading twice. The first real CI run said
`transparency: keyed` and the screenshot showed a dark rectangle: the window
accepted the attribute and the widget inside it was still opaque. The verdict
is a measurement now, and the case where a window claims "keyed" while its
corners keep changing is pinned as FAILED here so it cannot come back quietly.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "tools")))

import mac_smoke
from mac_smoke import BLOCKED, FAILED, PASS, UNKNOWN

try:
    from PIL import Image
except Exception:          # pragma: no cover
    Image = None

GRANTED = "  pyobjc: installed\n  Accessibility permission: granted\n"
REFUSED = "  pyobjc: installed\n  Accessibility permission: NOT granted\n"

SENTENCE = "i think we should go ahead and and update teh readme."
CORRECTED = "I think we should go ahead and update the readme."


def state(pair):
    return pair[0]


def write_png(folder, name, color, size=(40, 40)):
    path = os.path.join(folder, name)
    Image.new("RGB", size, color).save(path)
    return path


class ACheckThatWasRefusedIsNeverAPass(unittest.TestCase):
    def test_the_normal_refusal(self):
        self.assertEqual(BLOCKED, state(mac_smoke.classify_check(2, REFUSED)))

    def test_a_refusal_still_reads_as_blocked_when_the_exit_code_is_lost(self):
        """A shell pipeline, a CI wrapper or a `| tee` can hand back 0. The text
        has to be enough on its own, or this script would report a pass on a
        machine where the product cannot work at all."""
        self.assertEqual(BLOCKED, state(mac_smoke.classify_check(0, REFUSED)))

    def test_a_pass_needs_both_the_code_and_the_words(self):
        self.assertEqual(PASS, state(mac_smoke.classify_check(0, GRANTED)))
        # Exit 0 with nothing to show for it is not a pass.
        self.assertEqual(FAILED, state(mac_smoke.classify_check(0, "")))

    def test_a_broken_build_is_failed_and_not_blocked(self):
        """pyobjc missing is our bug. A withheld permission is not. Reporting
        them the same way would hide the one we have to fix."""
        self.assertEqual(
            FAILED,
            state(mac_smoke.classify_check(3, "  pyobjc is not installed, so...")),
        )

    def test_a_crash_is_failed(self):
        self.assertEqual(
            FAILED,
            state(mac_smoke.classify_check(1, "Traceback (most recent call last):")),
        )

    def test_a_hang_and_an_unrunnable_binary_are_failed(self):
        self.assertEqual(FAILED, state(mac_smoke.classify_check(124, "")))
        self.assertEqual(FAILED, state(mac_smoke.classify_check(127, "")))


@unittest.skipIf(Image is None, "Pillow is not installed on this machine")
class AScreenshotWeDidNotGetIsNeverAPass(unittest.TestCase):
    """This used to judge a black frame by file size, because the Mac
    dependencies had no image library. Pillow is in them now, so the pixels
    are counted and the guess is gone."""

    def test_no_file_means_blocked(self):
        self.assertEqual(
            BLOCKED,
            state(mac_smoke.classify_screenshot(1, os.path.join(HERE, "nope.png"))),
        )

    def test_screencapture_missing_means_failed(self):
        self.assertEqual(FAILED, state(mac_smoke.classify_screenshot(127, "x.png")))

    def test_a_flat_image_means_blocked(self):
        """Screen Recording refused gives a frame of one colour, however many
        bytes the encoder happens to spend on it."""
        with tempfile.TemporaryDirectory() as folder:
            path = write_png(folder, "black.png", (0, 0, 0))
            self.assertEqual(BLOCKED, state(mac_smoke.classify_screenshot(0, path)))

    def test_an_empty_file_means_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "shot.png")
            open(path, "wb").close()
            self.assertEqual(BLOCKED, state(mac_smoke.classify_screenshot(0, path)))

    def test_a_picture_with_something_in_it_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "shot.png")
            img = Image.new("RGB", (40, 40), (10, 20, 30))
            for x in range(40):
                img.putpixel((x, x), (200, 100, 50 + x))
            img.save(path)
            self.assertEqual(PASS, state(mac_smoke.classify_screenshot(0, path)))

    def test_a_file_that_is_not_an_image_is_our_problem(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "shot.png")
            with open(path, "wb") as handle:
                handle.write(b"not a png at all")
            self.assertEqual(FAILED, state(mac_smoke.classify_screenshot(0, path)))


class TheBadgeVerdictIsAMeasurement(unittest.TestCase):
    """A window that says it is transparent is not evidence that it is."""

    def test_untouched_corners_are_the_only_pass(self):
        self.assertEqual(PASS, state(mac_smoke.classify_badge("keyed", 0.4, 90.0)))

    def test_a_window_that_claims_keyed_and_paints_its_corners_is_a_bug(self):
        """This is exactly what shipped the first time: `-transparent` was
        accepted, the Canvas inside it was opaque, and the report said keyed
        over a screenshot of a dark rectangle. It must never be a pass."""
        self.assertEqual(FAILED, state(mac_smoke.classify_badge("keyed", 70.0, 90.0)))

    def test_a_declared_fallback_is_blocked_rather_than_failed(self):
        """alpha and opaque are documented rungs of the ladder. The square is
        visible, which is not what ships, but the app is behaving as written."""
        for mode in ("alpha", "opaque"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    BLOCKED, state(mac_smoke.classify_badge(mode, 70.0, 90.0)))

    def test_a_badge_that_never_appeared_beats_every_other_complaint(self):
        """Corners that did not move only mean transparency if something was
        drawn at all. Checked first, or an app that failed to start would
        report a perfectly transparent badge."""
        self.assertEqual(FAILED, state(mac_smoke.classify_badge("keyed", 0.0, 0.0)))
        self.assertEqual(FAILED, state(mac_smoke.classify_badge(None, 0.0, 0.0)))

    def test_a_window_that_said_nothing_still_gets_judged_on_its_pixels(self):
        """The app may die before printing its mode. The screenshot does not
        care, and a visible square is still reportable."""
        self.assertEqual(PASS, state(mac_smoke.classify_badge(None, 0.2, 80.0)))
        self.assertEqual(BLOCKED, state(mac_smoke.classify_badge(None, 80.0, 90.0)))

    def test_screen_noise_does_not_count_as_a_square(self):
        just_under = mac_smoke.PIXEL_NOISE - 0.1
        self.assertEqual(PASS, state(mac_smoke.classify_badge("keyed", just_under, 90.0)))


@unittest.skipIf(Image is None, "Pillow is not installed on this machine")
class TheMeasurementItself(unittest.TestCase):
    """badge_deltas is arithmetic over two PNGs, so it runs anywhere."""

    class Rect:
        def __init__(self, left, top, right, bottom):
            self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def test_a_circle_on_a_background_moves_the_middle_and_not_the_corners(self):
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as folder:
            before = Image.new("RGB", (100, 100), (240, 240, 240))
            before.save(os.path.join(folder, "before.png"))
            after = before.copy()
            # The badge: a circle inscribed in the 40x40 square at (20, 20).
            ImageDraw.Draw(after).ellipse((20, 20, 59, 59), fill=(20, 20, 24))
            after.save(os.path.join(folder, "after.png"))
            corner, centre = mac_smoke.badge_deltas(
                os.path.join(folder, "before.png"),
                os.path.join(folder, "after.png"),
                self.Rect(20, 20, 60, 60), scale=1.0)
        self.assertLess(corner, mac_smoke.PIXEL_NOISE)
        self.assertGreater(centre, 100)

    def test_a_filled_square_moves_the_corners_too(self):
        """The failure this whole measurement exists to catch."""
        with tempfile.TemporaryDirectory() as folder:
            before = Image.new("RGB", (100, 100), (240, 240, 240))
            before.save(os.path.join(folder, "before.png"))
            after = before.copy()
            for x in range(20, 60):
                for y in range(20, 60):
                    after.putpixel((x, y), (20, 20, 24))
            after.save(os.path.join(folder, "after.png"))
            corner, centre = mac_smoke.badge_deltas(
                os.path.join(folder, "before.png"),
                os.path.join(folder, "after.png"),
                self.Rect(20, 20, 60, 60), scale=1.0)
        self.assertGreater(corner, 100)
        self.assertGreater(centre, 100)

    def test_a_retina_screenshot_is_cropped_at_the_right_place(self):
        """The Accessibility API answers in points and screencapture writes
        pixels. Getting this backwards would measure empty desktop and call
        the badge missing."""
        from PIL import ImageDraw
        with tempfile.TemporaryDirectory() as folder:
            before = Image.new("RGB", (200, 200), (240, 240, 240))
            before.save(os.path.join(folder, "before.png"))
            after = before.copy()
            ImageDraw.Draw(after).ellipse((40, 40, 119, 119), fill=(20, 20, 24))
            after.save(os.path.join(folder, "after.png"))
            corner, centre = mac_smoke.badge_deltas(
                os.path.join(folder, "before.png"),
                os.path.join(folder, "after.png"),
                self.Rect(20, 20, 60, 60), scale=2.0)
        self.assertLess(corner, mac_smoke.PIXEL_NOISE)
        self.assertGreater(centre, 100)


@unittest.skipIf(Image is None, "Pillow is not installed on this machine")
class WhereDidAnythingChangeAtAll(unittest.TestCase):
    """The question that comes after "the badge is not where it belongs".

    The first CI run of the real badge reported corners 0.0 AND centre 0.0:
    the rectangle was byte identical. From one cropped measurement that reads
    the same whether the badge drew somewhere else or never drew at all, and
    those need completely different fixes."""

    def shots(self, folder, paint=None):
        from PIL import ImageDraw
        before = Image.new("RGB", (200, 150), (240, 240, 240))
        # A menu bar with a clock in it, and a Dock, both of which move on
        # their own and would swamp a 38 point badge if they counted.
        ImageDraw.Draw(before).rectangle((0, 0, 199, 12), fill=(200, 200, 200))
        ImageDraw.Draw(before).rectangle((0, 135, 199, 149), fill=(180, 180, 180))
        after = before.copy()
        draw = ImageDraw.Draw(after)
        draw.rectangle((170, 2, 190, 10), fill=(90, 90, 90))      # the clock
        draw.rectangle((10, 138, 30, 147), fill=(20, 20, 20))     # the Dock
        if paint:
            draw.ellipse(paint, fill=(20, 20, 24))
        before.save(os.path.join(folder, "before.png"))
        after.save(os.path.join(folder, "after.png"))
        return (os.path.join(folder, "before.png"),
                os.path.join(folder, "after.png"))

    def test_a_badge_somewhere_else_is_found(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = self.shots(folder, paint=(60, 60, 97, 97))
            box = mac_smoke.changed_box(before, after, ignore_top=13,
                                        ignore_bottom=15)
        self.assertIsNotNone(box, "a badge on screen was reported as nowhere")
        left, top, right, bottom = box
        self.assertTrue(55 <= left <= 65 and 55 <= top <= 65, box)

    def test_a_badge_that_never_drew_is_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            before, after = self.shots(folder)
            box = mac_smoke.changed_box(before, after, ignore_top=13,
                                        ignore_bottom=15)
        self.assertIsNone(box, "the clock or the Dock was counted as the badge")

    def test_the_box_is_reported_in_points_not_pixels(self):
        """Everything else in the report talks in display points, so a Retina
        screenshot's pixel coordinates would be silently double."""
        self.assertEqual("(10, 20) to (30, 40), 20x20 points",
                         mac_smoke.describe_box((20, 40, 60, 80), scale=2.0))

    def test_nothing_says_so_in_words(self):
        self.assertEqual("nothing changed anywhere",
                         mac_smoke.describe_box(None, scale=1.0))


class TheTypedSentenceHasToArrive(unittest.TestCase):
    def test_exactly_what_was_sent(self):
        self.assertEqual(PASS, state(mac_smoke.classify_typed(SENTENCE, SENTENCE)))

    def test_landing_in_a_box_that_was_not_empty_is_still_a_pass(self):
        self.assertEqual(
            PASS, state(mac_smoke.classify_typed(SENTENCE, "old. " + SENTENCE)))

    def test_an_unreadable_box_is_failed(self):
        self.assertEqual(FAILED, state(mac_smoke.classify_typed(SENTENCE, None)))

    def test_something_else_entirely_is_failed(self):
        """A paste that went to the wrong window is the realistic way this
        breaks, and it looks like success from the sending end."""
        self.assertEqual(FAILED, state(mac_smoke.classify_typed(SENTENCE, "")))
        self.assertEqual(
            FAILED, state(mac_smoke.classify_typed(SENTENCE, "something else")))


class TheBadgeMustNotTakeTheCaret(unittest.TestCase):
    """The one thing that would make the badge unusable: appearing mid
    sentence and stealing focus from what you are typing in."""

    def test_focus_staying_put_is_the_pass(self):
        self.assertEqual(PASS, state(mac_smoke.classify_focus("TextEdit", "TextEdit")))

    def test_focus_moving_is_failed(self):
        self.assertEqual(
            FAILED, state(mac_smoke.classify_focus("TextEdit", "Comprsly")))

    def test_not_being_able_to_tell_is_failed_rather_than_assumed_fine(self):
        self.assertEqual(FAILED, state(mac_smoke.classify_focus("TextEdit", None)))


class TheCorrectionHasToLand(unittest.TestCase):
    def test_the_corrected_sentence_is_the_pass(self):
        self.assertEqual(
            PASS,
            state(mac_smoke.classify_correction(SENTENCE, CORRECTED, CORRECTED)))

    def test_unchanged_text_is_failed(self):
        """--fix-once can exit 0 having written nothing if the write was
        refused silently, so the box is read rather than the exit code."""
        self.assertEqual(
            FAILED,
            state(mac_smoke.classify_correction(SENTENCE, SENTENCE, CORRECTED)))

    def test_changed_into_something_else_is_failed(self):
        self.assertEqual(
            FAILED,
            state(mac_smoke.classify_correction(SENTENCE, "", CORRECTED)))

    def test_an_unreadable_box_is_failed(self):
        self.assertEqual(
            FAILED, state(mac_smoke.classify_correction(SENTENCE, None, CORRECTED)))


class TheRealSentenceReallyDoesGetCorrected(unittest.TestCase):
    """The smoke run compares the text box against what the rules produced, so
    if the rules found nothing the comparison would be vacuous. This runs the
    real engine on the real sentence, here, where a Mac is not needed."""

    def test_the_three_mistakes_are_all_fixed(self):
        import suggestion_engine
        sys.path.insert(0, HERE)
        found = suggestion_engine.analyze(mac_smoke.TYPED_TEXT)["suggestions"]
        fixed = suggestion_engine.apply_suggestions(mac_smoke.TYPED_TEXT, found)
        self.assertNotEqual(mac_smoke.TYPED_TEXT, fixed)
        self.assertTrue(fixed.startswith("I think"), fixed)
        self.assertNotIn("and and", fixed)
        self.assertNotIn("teh", fixed)


class TheScriptItselfIsSound(unittest.TestCase):
    def test_it_imports_on_windows_so_this_suite_can_run_anywhere(self):
        """Nothing at module level may touch pyobjc, tkinter or a Mac binary."""
        self.assertTrue(hasattr(mac_smoke, "main"))

    def test_it_never_sends_an_apple_event(self):
        """The Automation prompt hung the first real run for thirty seconds and
        left a dialog over every screenshot after it. `open` and CGEvents only.
        osascript is not inherently wrong, but reaching for it is how the
        prompt comes back, so it is pinned out."""
        with open(os.path.join(HERE, "..", "tools", "mac_smoke.py"),
                  encoding="utf-8") as handle:
            body = handle.read().split('"""', 2)[2]
        self.assertNotIn("osascript", body)
        self.assertNotIn("tell application", body)

    def test_every_verdict_name_is_distinct(self):
        self.assertEqual(4, len({PASS, BLOCKED, FAILED, UNKNOWN}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
