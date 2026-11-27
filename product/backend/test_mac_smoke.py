"""The smoke run's verdicts, which are the only part of it a Mac is not needed for.

The whole value of mac_smoke.py is that a permission macOS refused reads as
BLOCKED and never as a pass. That promise lives in four pure functions, so they
are tested here, on Windows, in the same suite as everything else. The rest of
that script is subprocess plumbing only a Mac can run.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "tools")))

import mac_smoke
from mac_smoke import BLOCKED, FAILED, PASS, UNKNOWN

GRANTED = "  pyobjc: installed\n  Accessibility permission: granted\n"
REFUSED = "  pyobjc: installed\n  Accessibility permission: NOT granted\n"


def state(pair):
    return pair[0]


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


class AScreenshotWeDidNotGetIsNeverAPass(unittest.TestCase):
    def test_no_file_means_blocked(self):
        self.assertEqual(
            BLOCKED,
            state(mac_smoke.classify_screenshot(1, os.path.join(HERE, "nope.png"))),
        )

    def test_screencapture_missing_means_failed(self):
        self.assertEqual(FAILED, state(mac_smoke.classify_screenshot(127, "x.png")))

    def test_a_flat_image_means_blocked(self):
        """Screen Recording refused gives a black frame, and PNG squeezes a flat
        image to almost nothing. Small file, therefore no real screenshot."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "shot.png")
            with open(path, "wb") as handle:
                handle.write(b"\x00" * 900)
            self.assertEqual(BLOCKED, state(mac_smoke.classify_screenshot(0, path)))

    def test_an_empty_file_means_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "shot.png")
            open(path, "wb").close()
            self.assertEqual(BLOCKED, state(mac_smoke.classify_screenshot(0, path)))

    def test_a_real_sized_image_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "shot.png")
            with open(path, "wb") as handle:
                handle.write(b"\x00" * (mac_smoke.BLANK_SCREENSHOT_BYTES + 1))
            self.assertEqual(PASS, state(mac_smoke.classify_screenshot(0, path)))


class OnlyAKeyedBadgeIsAPass(unittest.TestCase):
    def test_keyed_is_the_only_pass(self):
        self.assertEqual(PASS, state(mac_smoke.classify_badge(0, "transparency: keyed")))

    def test_the_fallbacks_are_blocked_because_the_badge_looks_wrong(self):
        """alpha and opaque both mean the square around the circle is visible.
        The app runs, so it is not FAILED, but it is not what ships either."""
        self.assertEqual(BLOCKED, state(mac_smoke.classify_badge(0, "transparency: alpha")))
        self.assertEqual(BLOCKED, state(mac_smoke.classify_badge(0, "transparency: opaque")))

    def test_no_tkinter_is_our_problem(self):
        self.assertEqual(
            FAILED,
            state(mac_smoke.classify_badge(
                1, "ModuleNotFoundError: No module named 'tkinter'")),
        )

    def test_no_window_server_is_the_runners_problem(self):
        self.assertEqual(
            BLOCKED,
            state(mac_smoke.classify_badge(1, "couldn't connect to display")),
        )

    def test_silence_is_unknown_rather_than_a_pass(self):
        self.assertEqual(UNKNOWN, state(mac_smoke.classify_badge(0, "")))


class AutomationRefusalsAreBlocked(unittest.TestCase):
    def test_the_apple_events_refusal_code(self):
        self.assertEqual(
            BLOCKED,
            state(mac_smoke.classify_automation(
                1, "execution error: Not authorized to send Apple events (-1743)")),
        )

    def test_a_hang_is_a_silent_permission_prompt(self):
        self.assertEqual(BLOCKED, state(mac_smoke.classify_automation(124, "")))

    def test_success(self):
        self.assertEqual(PASS, state(mac_smoke.classify_automation(0, "")))


class TheScriptItselfIsSound(unittest.TestCase):
    def test_it_imports_on_windows_so_this_suite_can_run_anywhere(self):
        """Nothing at module level may touch pyobjc, tkinter or a Mac binary."""
        self.assertTrue(hasattr(mac_smoke, "main"))

    def test_every_verdict_name_is_distinct(self):
        self.assertEqual(4, len({PASS, BLOCKED, FAILED, UNKNOWN}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
