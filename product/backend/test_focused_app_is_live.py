"""Which application has focus has to be read now, not remembered.

Measured on a CI Mac, 2026-11-28, and it is the clearest bug this port has
produced so far.

A freshly launched `--check` printed "frontmost app: Finder" and the Finder
desktop's AXGroup at (0, 0, 1024, 768), which was correct at that instant.
The long lived script that then opened TextEdit polled for twenty seconds and
kept reading that same desktop AXGroup, while its own screenshot showed
TextEdit frontmost with a caret blinking in an open document.

Nothing was wrong with the Accessibility calls. They were pointed at a pid
that was twenty seconds out of date, because `NSWorkspace.frontmostApplication`
is a cached property kept current by notifications delivered on the run loop,
and neither that script nor anything else here runs one.

**The product is the long lived process**, so this was never only a test
problem: the badge would have followed whichever application was in front
when Comprsly started and never moved to another one.

These tests drive the module with a fake Accessibility layer, so they run on
any machine. They cannot prove the real API behaves; the macOS smoke run does
that, and it is the thing that caught this.
"""

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from platform_mac import accessibility

FOCUSED_APP = "the focused application element"
FOCUSED_CONTROL = "the control with the caret"


class FakeAS:
    """Only the four names accessibility.py reaches for."""
    kAXFocusedApplicationAttribute = "AXFocusedApplication"
    kAXFocusedUIElementAttribute = "AXFocusedUIElement"
    kAXRoleAttribute = "AXRole"
    kAXValueAttribute = "AXValue"


class FakeApp:
    def __init__(self, name, bundle):
        self._name, self._bundle = name, bundle

    def localizedName(self):
        return self._name

    def bundleIdentifier(self):
        return self._bundle


class FakeRunningApplication:
    """NSRunningApplication, looked up by pid rather than by "who is in
    front", which is the distinction this whole file is about."""

    by_pid = {}

    @classmethod
    def runningApplicationWithProcessIdentifier_(cls, pid):
        return cls.by_pid.get(pid)


def fake_ax(answers, pid=4242, systemwide_calls=None):
    """An _AX dict whose answers can change between calls, like a real screen.

    `answers` maps an attribute name to a list of values, popped one per call,
    the last repeating. That is how a stale read is told from a live one: ask
    twice, and a cached implementation cannot give two different answers.
    """
    def copy(element, attribute, _placeholder):
        queue = answers.get(attribute)
        if not queue:
            return (-25212, None)          # kAXErrorNoValue
        value = queue[0] if len(queue) == 1 else queue.pop(0)
        if value is None:
            return (-25212, None)
        return (0, value)

    def systemwide():
        if systemwide_calls is not None:
            systemwide_calls.append(1)
        return "the system wide element"

    return {
        "running_app": FakeRunningApplication,
        "AS": FakeAS,
        "systemwide": systemwide,
        "copy": copy,
        "set": lambda *a: 0,
        "pid_of": lambda element, _: (0, pid),
        "trusted": lambda: True,
    }


class contextual:
    """Install a fake _AX for the duration of a block."""

    def __init__(self, ax):
        self.ax = ax

    def __enter__(self):
        self.saved = accessibility._AX
        accessibility._AX = self.ax
        return self.ax

    def __exit__(self, *exc):
        accessibility._AX = self.saved


class TheFocusedApplicationComesFromAccessibility(unittest.TestCase):
    def test_it_asks_the_system_wide_element_every_time(self):
        """The fix, stated as plainly as it can be: a question, not a memory."""
        calls = []
        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP]},
                     systemwide_calls=calls)
        FakeRunningApplication.by_pid = {4242: FakeApp("TextEdit", "com.apple.TextEdit")}
        with contextual(ax):
            accessibility.frontmost()
            accessibility.frontmost()
            accessibility.focused_element()
        self.assertEqual(3, len(calls),
                         "something is caching the focused application")

    def test_a_second_call_sees_a_different_app(self):
        """The exact CI failure: Finder first, TextEdit a moment later. A
        cached answer gives Finder both times and the badge never moves."""
        ax = fake_ax({"AXFocusedApplication": ["finder element", "textedit element"]})
        FakeRunningApplication.by_pid = {4242: FakeApp("Finder", "com.apple.finder")}
        with contextual(ax):
            first = accessibility.frontmost()
            FakeRunningApplication.by_pid = {
                4242: FakeApp("TextEdit", "com.apple.TextEdit")}
            second = accessibility.frontmost()
        self.assertEqual("Finder", first[2])
        self.assertEqual("TextEdit", second[2])

    def test_it_reports_the_pid_bundle_and_name(self):
        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP]}, pid=991)
        FakeRunningApplication.by_pid = {991: FakeApp("TextEdit", "com.apple.TextEdit")}
        with contextual(ax):
            self.assertEqual((991, "com.apple.TextEdit", "TextEdit"),
                             accessibility.frontmost())

    def test_nothing_focused_is_none_and_not_a_stale_guess(self):
        """Failing closed here hides the badge. Falling back to the cached
        value would put it on the wrong window, which is worse."""
        ax = fake_ax({"AXFocusedApplication": [None]})
        with contextual(ax):
            self.assertIsNone(accessibility.frontmost())
            self.assertIsNone(accessibility.focused_element())

    def test_an_app_that_has_already_exited_still_gives_a_pid(self):
        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP]}, pid=7)
        FakeRunningApplication.by_pid = {}
        with contextual(ax):
            self.assertEqual((7, "", ""), accessibility.frontmost())


class TheFocusedControlComesFromThatApplication(unittest.TestCase):
    """Through the application element, never the system wide one, which does
    not answer kAXFocusedUIElement reliably."""

    def test_it_reads_the_control_from_the_app_element(self):
        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP],
                      "AXFocusedUIElement": [FOCUSED_CONTROL]})
        with contextual(ax):
            self.assertEqual(FOCUSED_CONTROL, accessibility.focused_element())

    def test_an_app_with_no_focused_control_is_none(self):
        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP],
                      "AXFocusedUIElement": [None]})
        with contextual(ax):
            self.assertIsNone(accessibility.focused_element())

    def test_it_does_not_go_through_a_pid_any_more(self):
        """Creating an application element from a pid is how the stale value
        got in. There is no pid in this path now, which is why the fake has
        no AXUIElementCreateApplication to offer."""
        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP],
                      "AXFocusedUIElement": [FOCUSED_CONTROL]})
        self.assertNotIn("create_app", ax)
        with contextual(ax):
            self.assertEqual(FOCUSED_CONTROL, accessibility.focused_element())


class ItStillNeverRaises(unittest.TestCase):
    """Same rule as the rest of the layer. A screen that answers strangely
    hides the badge; it does not take the app down."""

    def test_a_raising_accessibility_layer_is_swallowed(self):
        def boom(*args):
            raise RuntimeError("the window server went away")

        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP]})
        ax["copy"] = boom
        with contextual(ax):
            self.assertIsNone(accessibility.frontmost())
            self.assertIsNone(accessibility.focused_element())

    def test_a_pid_lookup_that_fails_is_swallowed(self):
        ax = fake_ax({"AXFocusedApplication": [FOCUSED_APP]})
        ax["pid_of"] = lambda element, _: (-25200, 0)
        with contextual(ax):
            self.assertIsNone(accessibility.frontmost())


class NoSourceMentionsTheCachedProperty(unittest.TestCase):
    """A check that will outlive the memory of why. frontmostApplication is
    the cache; reaching for it again brings the bug straight back."""

    def test_it_is_gone(self):
        """Parsed rather than grepped, because the docstring that explains the
        bug has to be free to name the thing it is warning about."""
        import ast
        path = os.path.join(HERE, "platform_mac", "accessibility.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        called = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
        self.assertNotIn("frontmostApplication", called)
        self.assertNotIn("sharedWorkspace", called)


if __name__ == "__main__":
    unittest.main(verbosity=2)
