"""
Tests for VS Code surface recognition.

The risk being guarded against is specific: recognising code.exe puts a badge
in a window that contains BOTH a terminal and a code editor. Getting the
discrimination wrong means a badge on top of somebody's source, which is worse
than not supporting VS Code at all.

So these lean on the negative cases. Every one of them must stay hidden.

Run:
    "C:/Users/anton/AppData/Local/Python/pythoncore-3.14-64/python.exe" test_vscode_surface.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uiautomation as auto

import main as app


class FakeControl:
    """Only Name matters to the gate; BoundingRectangle is for the pane walk."""

    def __init__(self, name, rect=None, parent=None):
        self.Name = name
        self._rect = rect
        self._parent = parent

    @property
    def BoundingRectangle(self):
        if self._rect is None:
            raise RuntimeError("no rect")
        return app._SimpleRect(*self._rect)

    def GetParentControl(self):
        return self._parent


class FocusGate(unittest.TestCase):
    """_vscode_focus_is_terminal decides whether the badge may appear at all."""

    def setUp(self):
        self._real = auto.GetFocusedControl
        self.addCleanup(lambda: setattr(auto, "GetFocusedControl", self._real))

    def focus(self, control):
        auto.GetFocusedControl = lambda: control

    def test_integrated_terminal_is_recognised(self):
        self.focus(FakeControl("Terminal 1, Orchestrator  Run the command: Toggle"))
        self.assertTrue(app._vscode_focus_is_terminal())

    def test_terminal_name_is_matched_case_insensitively(self):
        self.focus(FakeControl("TERMINAL 7, build"))
        self.assertTrue(app._vscode_focus_is_terminal())

    def test_code_editor_stays_hidden(self):
        self.focus(FakeControl("main.py, Editor Group"))
        self.assertFalse(app._vscode_focus_is_terminal())

    def test_settings_pane_stays_hidden(self):
        self.focus(FakeControl("Settings"))
        self.assertFalse(app._vscode_focus_is_terminal())

    def test_empty_name_stays_hidden(self):
        self.focus(FakeControl(""))
        self.assertFalse(app._vscode_focus_is_terminal())

    def test_name_merely_containing_terminal_stays_hidden(self):
        # Prefix, never substring. This file already carries a documented bug
        # from an "anywhere in the title" rule activating on the wrong pages.
        self.focus(FakeControl("terminal-ish but actually the editor"))
        self.assertFalse(app._vscode_focus_is_terminal())

    def test_no_focused_control_stays_hidden(self):
        self.focus(None)
        self.assertFalse(app._vscode_focus_is_terminal())

    def test_unreadable_control_fails_closed(self):
        def boom():
            raise RuntimeError("UIA busy")

        auto.GetFocusedControl = boom
        self.assertFalse(app._vscode_focus_is_terminal())


class PaneWalk(unittest.TestCase):
    """The focused control is the caret; the badge needs the pane around it."""

    # Real measurements, 2026-11-22.
    CARET = (422, -467, 429, -450)        # 7x17
    SHARES_CARET_RECT = (422, -467, 429, -450)
    PANE = (408, -1011, 1409, -399)       # 1001x612

    def test_walks_past_the_parent_that_shares_the_caret_rect(self):
        pane = FakeControl("", self.PANE)
        shadow = FakeControl("", self.SHARES_CARET_RECT, parent=pane)
        caret = FakeControl("Terminal 1,", self.CARET, parent=shadow)

        got = app._vscode_terminal_pane_rect(caret)
        self.assertIsNotNone(got, "should have found the pane two levels up")
        self.assertEqual((got.left, got.top, got.right, got.bottom), self.PANE)

    def test_returns_none_when_no_ancestor_is_big_enough(self):
        tiny = FakeControl("", self.SHARES_CARET_RECT)
        caret = FakeControl("Terminal 1,", self.CARET, parent=tiny)
        self.assertIsNone(app._vscode_terminal_pane_rect(caret))

    def test_returns_none_at_the_top_of_the_chain(self):
        caret = FakeControl("Terminal 1,", self.CARET, parent=None)
        self.assertIsNone(app._vscode_terminal_pane_rect(caret))

    def test_unreadable_caret_returns_none(self):
        self.assertIsNone(app._vscode_terminal_pane_rect(FakeControl("x", None)))


class Registration(unittest.TestCase):
    def test_vscode_family_goes_through_the_terminal_path(self):
        for process in ("code.exe", "cursor.exe", "windsurf.exe"):
            self.assertIn(process, app.TERMINAL_HOST_PROCESSES)
            self.assertIn(process, app.VSCODE_PROCESSES)

    def test_other_terminals_are_not_treated_as_vscode(self):
        # Only the VS Code family pays the extra focus check.
        for process in ("windowsterminal.exe", "powershell.exe", "wsl.exe"):
            self.assertNotIn(process, app.VSCODE_PROCESSES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
