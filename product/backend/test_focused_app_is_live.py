"""Finding out which application the user is actually in, on macOS.

Two CI Macs' worth of evidence sit behind this file, and both runs failed in
a way that looked like the Accessibility calls were wrong when they were not.

**Round one.** The focused application came from
`NSWorkspace.frontmostApplication()`, which is a cached property kept current
by notifications delivered on the run loop. Nothing here runs one, so the
first answer was also the last: a fresh `--check` printed "Finder" correctly,
then the long lived script that opened TextEdit sat for twenty seconds reading
the Finder desktop's AXGroup at (0, 0, 1024, 768) while its own screenshot
showed TextEdit frontmost with a caret blinking in a document.

**Round two.** Replacing it with `kAXFocusedApplication` on the system wide
element, which is Apple's documented answer, made it worse: that attribute
returned nothing on that runner on every call, including from a fresh
process, while Accessibility was granted and every other attribute worked.
It is a known pitfall (rdar://10969414) rather than a surprise.

So there is a chain now, every rung a different route to the same question,
and every rung but the last a live query. The point of these tests is that
the chain FALLS THROUGH and SAYS WHICH RUNG ANSWERED, because a third round
of guessing would cost more than the diagnostics do.

They drive the module with a fake Accessibility layer, so they run on any
machine. They cannot prove the real API behaves. The macOS smoke run does
that, and it is what caught both of these.
"""

import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from platform_mac import accessibility

APP_ELEMENT = "the focused application element"
CONTROL = "the control with the caret"


class FakeAS:
    kAXFocusedApplicationAttribute = "AXFocusedApplication"
    kAXFocusedUIElementAttribute = "AXFocusedUIElement"
    kAXRoleAttribute = "AXRole"
    kAXValueAttribute = "AXValue"


class FakeApp:
    def __init__(self, name, bundle, pid):
        self._name, self._bundle, self._pid = name, bundle, pid

    def localizedName(self):
        return self._name

    def bundleIdentifier(self):
        return self._bundle

    def processIdentifier(self):
        return self._pid


class FakeRunningApplication:
    by_pid = {}

    @classmethod
    def runningApplicationWithProcessIdentifier_(cls, pid):
        return cls.by_pid.get(pid)


class FakeWorkspace:
    frontmost_app = None

    @classmethod
    def sharedWorkspace(cls):
        return cls

    @classmethod
    def frontmostApplication(cls):
        return cls.frontmost_app


NO_VALUE = -25212
CANNOT_COMPLETE = -25204


def fake_ax(answers, pids=None, calls=None):
    """An _AX dict. `answers` maps an attribute name to a value or an error
    code; `pids` maps an element to the process that owns it."""
    pids = pids or {}

    def copy(element, attribute, _placeholder):
        if calls is not None:
            calls.append(attribute)
        value = answers.get(attribute, NO_VALUE)
        if isinstance(value, int):
            return (value, None)
        return (0, value)

    def pid_of(element, _placeholder):
        pid = pids.get(element)
        return (0, pid) if pid else (CANNOT_COMPLETE, 0)

    return {
        "running_app": FakeRunningApplication,
        "workspace": FakeWorkspace,
        "AS": FakeAS,
        "systemwide": lambda: "the system wide element",
        "create_app": lambda pid: "app element for %d" % pid,
        "copy": copy,
        "set": lambda *a: 0,
        "pid_of": pid_of,
        "trusted": lambda: True,
    }


class installed:
    def __init__(self, ax):
        self.ax = ax

    def __enter__(self):
        self.saved = accessibility._AX
        accessibility._AX = self.ax
        return self.ax

    def __exit__(self, *exc):
        accessibility._AX = self.saved


def setUpModule():
    FakeRunningApplication.by_pid = {
        77: FakeApp("TextEdit", "com.apple.TextEdit", 77),
        88: FakeApp("Finder", "com.apple.finder", 88),
    }


class TheFirstRungThatAnswersWins(unittest.TestCase):
    def test_the_documented_attribute_is_tried_first(self):
        ax = fake_ax({"AXFocusedApplication": APP_ELEMENT}, {APP_ELEMENT: 77})
        with installed(ax):
            trace = []
            pid, how = accessibility.focused_pid(trace)
        self.assertEqual(77, pid)
        self.assertEqual("system wide kAXFocusedApplication", how)
        self.assertEqual(1, len(trace), "it kept going after an answer")

    def test_it_falls_through_the_attribute_that_failed_on_the_runner(self):
        """The round two failure, exactly: the attribute is refused, and the
        focused control is reachable, so its owner is the answer."""
        ax = fake_ax({"AXFocusedApplication": CANNOT_COMPLETE,
                      "AXFocusedUIElement": CONTROL}, {CONTROL: 77})
        with installed(ax):
            trace = []
            pid, how = accessibility.focused_pid(trace)
        self.assertEqual(77, pid)
        self.assertEqual("system wide kAXFocusedUIElement", how)
        self.assertIn("cannot complete", trace[0][1])

    def test_the_last_rung_is_the_cached_one(self):
        """NSWorkspace is still here because it is right in a short lived
        process. It is LAST because it is the one that can be stale, which is
        the round one failure."""
        self.assertEqual("NSWorkspace frontmostApplication",
                         accessibility._RUNGS[-1][0])

    def test_the_cached_rung_still_answers_when_nothing_else_can(self):
        FakeWorkspace.frontmost_app = FakeApp("TextEdit", "com.apple.TextEdit", 77)
        ax = fake_ax({})
        with installed(ax):
            trace = []
            pid, how = accessibility.focused_pid(trace)
        FakeWorkspace.frontmost_app = None
        self.assertEqual(77, pid)
        self.assertEqual("NSWorkspace frontmostApplication", how)
        self.assertIn("stale", trace[-1][1], "it has to say so")

    def test_every_rung_is_recorded_even_the_ones_that_failed(self):
        """The whole reason this exists. Two CI rounds were spent guessing at
        which call was refusing; a trace is cheaper than a third."""
        ax = fake_ax({})
        with installed(ax):
            trace = []
            pid, how = accessibility.focused_pid(trace)
        self.assertIsNone(pid)
        self.assertIsNone(how)
        self.assertEqual([name for name, _ in accessibility._RUNGS],
                         [name for name, _ in trace])
        for name, note in trace:
            self.assertTrue(note, "%s said nothing about why" % name)

    def test_the_error_code_is_named_and_not_just_a_number(self):
        ax = fake_ax({"AXFocusedApplication": CANNOT_COMPLETE})
        with installed(ax):
            trace = []
            accessibility.focused_pid(trace)
        self.assertIn("-25204", trace[0][1])
        self.assertIn("cannot complete", trace[0][1])

    def test_a_rung_that_raises_is_noted_and_the_chain_continues(self):
        ax = fake_ax({"AXFocusedUIElement": CONTROL}, {CONTROL: 77})

        def boom(*args):
            raise RuntimeError("the window server went away")

        ax["systemwide"] = boom
        with installed(ax):
            trace = []
            pid, how = accessibility.focused_pid(trace)
        # Rungs one and two both need the system wide element, so both raise;
        # the window server rung is what should answer in a real run.
        self.assertIn("RuntimeError", trace[0][1])
        self.assertIsNotNone(trace[1][1])

    def test_nothing_at_all_is_none_rather_than_a_guess(self):
        ax = fake_ax({})
        with installed(ax):
            self.assertIsNone(accessibility.frontmost())
            self.assertIsNone(accessibility.focused_element())


class TheControlComesFromTheApplicationElement(unittest.TestCase):
    """The one part of this that a real Mac HAS verified: an application
    element built from a pid returned TextEdit's AXTextArea, with its
    rectangle and its text. Only the question of which pid has moved around."""

    def test_it_reads_the_control_through_the_app_element(self):
        ax = fake_ax({"AXFocusedApplication": APP_ELEMENT,
                      "AXFocusedUIElement": CONTROL}, {APP_ELEMENT: 77})
        with installed(ax):
            self.assertEqual(CONTROL, accessibility.focused_element())

    def test_it_asks_the_application_and_not_the_system_wide_element(self):
        asked = []
        ax = fake_ax({"AXFocusedApplication": APP_ELEMENT,
                      "AXFocusedUIElement": CONTROL}, {APP_ELEMENT: 77})
        original = ax["copy"]

        def copy(element, attribute, placeholder):
            asked.append((element, attribute))
            return original(element, attribute, placeholder)

        ax["copy"] = copy
        with installed(ax):
            accessibility.focused_element()
        self.assertIn(("app element for 77", "AXFocusedUIElement"), asked)


class FrontmostNamesTheApplication(unittest.TestCase):
    def test_pid_bundle_and_name(self):
        ax = fake_ax({"AXFocusedApplication": APP_ELEMENT}, {APP_ELEMENT: 77})
        with installed(ax):
            self.assertEqual((77, "com.apple.TextEdit", "TextEdit"),
                             accessibility.frontmost())

    def test_an_app_that_has_already_gone_still_gives_a_pid(self):
        ax = fake_ax({"AXFocusedApplication": APP_ELEMENT}, {APP_ELEMENT: 404})
        with installed(ax):
            self.assertEqual((404, "", ""), accessibility.frontmost())


class ItStillNeverRaises(unittest.TestCase):
    """A screen that answers strangely hides the badge. It does not take the
    app down."""

    def test_a_raising_layer_is_swallowed(self):
        def boom(*args):
            raise RuntimeError("nope")

        ax = fake_ax({})
        ax["copy"] = boom
        ax["workspace"] = type("W", (), {"sharedWorkspace": staticmethod(boom)})
        with installed(ax):
            self.assertIsNone(accessibility.frontmost())
            self.assertIsNone(accessibility.focused_element())

    def test_without_pyobjc_the_trace_says_so(self):
        saved = accessibility._AX
        accessibility._AX = False
        try:
            trace = []
            self.assertEqual((None, None), accessibility.focused_pid(trace))
            self.assertEqual([("pyobjc", "not installed")], trace)
        finally:
            accessibility._AX = saved


class TheDiagnosticsAreWiredUp(unittest.TestCase):
    """--check has to print the trace, or the next CI round is another guess.
    Read as source: main_mac imports tkinter lazily but this is cheaper."""

    def test_check_prints_which_rung_answered(self):
        path = os.path.join(HERE, "main_mac.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        diagnose = next(n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == "diagnose")
        src = ast.unparse(diagnose)
        self.assertIn("focused_pid", src)
        self.assertIn("trace", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
