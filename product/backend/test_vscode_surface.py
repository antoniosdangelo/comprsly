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

# main.py calls ctypes.windll at import and the suite now runs on macos-latest
# too, where that attribute does not exist. These tests are about the Windows
# layer and there is nothing for them to assert on a Mac, so the whole module
# steps aside rather than erroring. The windows-latest job in checks.yml runs
# them on every pull request, and test_workflows.py pins that job so this skip
# cannot quietly become permanent.
if sys.platform != "win32":
    raise unittest.SkipTest("the Windows layer; see the windows-latest job")

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


class AiCliDetection(unittest.TestCase):
    """Which CLIs the terminal path will actually recognise.

    Verified on a real machine 2026-11-22 rather than taken from the website,
    which had claimed four CLIs for months while only one was detected.
    """

    def test_claude_code_is_detected(self):
        self.assertEqual(app.AI_CLI_DESCENDANT_PROCESSES.get("claude.exe"), "Claude Code")

    def test_copilot_cli_is_detected(self):
        # GitHubCopilotCLI ships a real copilot.exe, so a process name match is
        # safe and specific.
        self.assertEqual(app.AI_CLI_DESCENDANT_PROCESSES.get("copilot.exe"), "Copilot CLI")

    def test_codex_is_detected_by_name(self):
        # Measured 2026-11-23: Codex spawns a native vendored codex.exe
        # alongside its node shim, so no command line read is needed.
        self.assertEqual(app.AI_CLI_DESCENDANT_PROCESSES.get("codex.exe"), "Codex CLI")

    def test_gemini_is_detected_by_cmdline(self):
        # Measured 2026-11-23: Gemini's whole tree is node, conhost, cmd and
        # powershell, with no distinctly named binary, so the package entry
        # path in the command line is the only thing that identifies it.
        labels = {label for _markers, label in app.AI_CLI_CMDLINE_MARKERS}
        self.assertIn("Gemini CLI", labels)

    def test_cmdline_markers_are_package_paths_not_bare_words(self):
        # A marker like "gemini" would match any file or folder with that in
        # its path. Every marker must be scoped to a package.
        for markers, label in app.AI_CLI_CMDLINE_MARKERS:
            for marker in markers:
                self.assertTrue(marker.startswith("@"), f"{label}: {marker!r} is not a package path")
                self.assertGreater(len(marker), 8, f"{label}: {marker!r} is too loose")

    def test_only_node_ever_triggers_a_cmdline_read(self):
        # Keeps the expensive path rare and the blast radius small.
        self.assertEqual(app.CMDLINE_CHECK_PROCESSES, {"node.exe"})

    def test_unreadable_cmdline_fails_closed(self):
        # pid 0 is the System Idle Process: OpenProcess always refuses it, so
        # it is a real unreadable case rather than a mocked one.
        self.assertIsNone(app._process_command_line(0))
        self.assertIsNone(app._ai_cli_label_from_cmdline(0))

    def test_a_plain_node_cmdline_matches_nothing(self):
        # The exact shapes that must never trigger: a dev server, a build, a
        # test runner. Checked against the real matcher logic.
        import os as _os
        own = app._process_command_line(_os.getpid())
        self.assertIsNotNone(own, "should be able to read our own command line")
        self.assertIsNone(app._ai_cli_label_from_cmdline(_os.getpid()))

    def test_cmdline_cache_is_keyed_by_process_instance_not_pid(self):
        """The guard against PID reuse handing one process another's answer.

        Windows recycles PIDs. A Gemini node.exe cached under pid 4242 can
        exit and a dev server's node.exe can be given 4242 minutes later. A
        pid-only cache would answer "Gemini CLI" for the dev server, which is
        a false POSITIVE and so breaks fail closed, not merely staleness.
        """
        import os as _os
        app._cmdline_cache.clear()
        own = app._process_command_line(_os.getpid())
        self.assertIsNotNone(own)

        keys = list(app._cmdline_cache)
        self.assertEqual(len(keys), 1)
        key = keys[0]
        self.assertIsInstance(key, tuple, "cache key must be a tuple, not a bare pid")
        self.assertEqual(len(key), 2, "cache key must be (pid, creation time)")
        self.assertEqual(key[0], _os.getpid())
        self.assertIsInstance(key[1], int)
        self.assertGreater(key[1], 0, "creation time must be a real value")

    def test_a_recycled_pid_does_not_inherit_a_cached_cmdline(self):
        # Simulate the reuse directly: poison the cache with this pid under a
        # DIFFERENT creation time, as a dead process would have left it. The
        # live process must not pick that answer up.
        import os as _os
        pid = _os.getpid()
        app._cmdline_cache.clear()
        app._cmdline_cache[(pid, 1)] = "node.exe C:/some/dead/@google/gemini-cli/x.js"

        self.assertIsNone(
            app._ai_cli_label_from_cmdline(pid),
            "a stale entry under a recycled pid was trusted; fail closed is broken",
        )
        app._cmdline_cache.clear()

    def test_node_is_never_matched(self):
        # The guard that matters. Codex CLI runs as `node.exe codex.js`, so
        # adding node.exe would light the badge under ANY node process:
        # a dev server, a build, this project's own test runner.
        self.assertNotIn("node.exe", app.AI_CLI_DESCENDANT_PROCESSES)

    def test_no_invented_executables_are_claimed(self):
        # Updated 2026-11-23. codex.exe was on this list while Codex was
        # unverified; it has since been measured and is real, so it moved into
        # the map. These never existed and must not be invented: Gemini ships
        # no binary of its own, which is exactly why it needs a command line
        # match rather than a name.
        for never in ("gemini.exe", "gemini-cli.exe", "openai.exe", "google.exe"):
            self.assertNotIn(never, app.AI_CLI_DESCENDANT_PROCESSES)


class TerminalBadgeInLine(unittest.TestCase):
    """2026-11-25: the badge sits at the right end of the input line, never on typed text."""

    def _vscode(self, caret):
        pane = FakeControl("Terminal 1", (100, 200, 1900, 1000))
        wrap = FakeControl("", caret, parent=pane)
        return FakeControl("Terminal 1, input", caret, parent=wrap)

    def test_spans_the_pane_so_the_badge_docks_at_its_right_edge(self):
        caret = (400, 960, 411, 978)
        r = app._terminal_badge_rect(self._vscode(caret), "code.exe", 0, app._SimpleRect(*caret), "Claude Code")
        self.assertEqual((r.left, r.right), (100, 1900))
        self.assertEqual(r.bottom - r.top, 18)

    def test_sits_on_the_panes_last_row_below_every_line(self):
        """Below the input, not beside it. The pane here is 100..1900 by
        0..1080, so the badge sits on 1062..1080 whatever the caret does."""
        caret = (400, 960, 411, 978)
        r = app._terminal_badge_rect(self._vscode(caret), "code.exe", 0, app._SimpleRect(*caret), "Claude Code")
        self.assertEqual((r.top, r.bottom), (982, 1000))

    def test_it_does_not_move_when_the_caret_does(self):
        """The whole complaint, as a test. Four very different caret positions,
        including different lines and different columns, must all produce the
        same badge rect."""
        rects = set()
        for caret in [(400, 960, 411, 978), (1800, 300, 1811, 318),
                      (120, 1040, 131, 1058), (950, 500, 961, 518)]:
            r = app._terminal_badge_rect(self._vscode(caret), "code.exe", 0,
                                         app._SimpleRect(*caret), "Claude Code")
            rects.add((r.left, r.top, r.right, r.bottom))
        self.assertEqual(len(rects), 1, "the badge moved with the caret: %r" % (rects,))

    def test_it_never_renders_outside_the_pane(self):
        caret = (400, 960, 411, 978)
        r = app._terminal_badge_rect(self._vscode(caret), "code.exe", 0, app._SimpleRect(*caret), "Claude Code")
        self.assertLessEqual(r.bottom, 1000)
        self.assertGreaterEqual(r.top, 200)

    def test_carries_the_line_height_so_the_badge_can_fit_the_row(self):
        caret = (400, 960, 411, 978)
        r = app._terminal_badge_rect(self._vscode(caret), "code.exe", 0, app._SimpleRect(*caret), "Claude Code")
        self.assertEqual(r.line_h, 18)

    def test_badge_is_drawn_no_taller_than_the_row(self):
        """The whole point: a 38 px badge on a 17 px row covers the lines
        around it. Guards the size, not just the position."""
        badge = app.PersistentBadge.__new__(app.PersistentBadge)
        badge.MIN_SIZE = app.PersistentBadge.MIN_SIZE
        row = app._SimpleRect(100, 978, 1900, 996)
        row.line_h = 18
        self.assertLessEqual(badge._size_for_rect(row), 18)

    def test_a_normal_box_keeps_the_full_size_badge(self):
        """Browser chats have no line_h and must be untouched by any of this."""
        badge = app.PersistentBadge.__new__(app.PersistentBadge)
        badge.MIN_SIZE = app.PersistentBadge.MIN_SIZE
        self.assertEqual(badge._size_for_rect(app._SimpleRect(100, 500, 900, 560)),
                         app.BADGE_ICON_SIZE)

    def test_never_shrinks_below_the_clickable_floor(self):
        badge = app.PersistentBadge.__new__(app.PersistentBadge)
        badge.MIN_SIZE = app.PersistentBadge.MIN_SIZE
        tiny = app._SimpleRect(100, 978, 1900, 982)
        tiny.line_h = 4
        self.assertEqual(badge._size_for_rect(tiny), app.PersistentBadge.MIN_SIZE)

    def test_all_four_clis_dock_at_the_same_inset(self):
        """He asked for the badge to be the same on all of them. It was not:
        Claude Code carried a 64 px override the others never had."""
        insets = {app._badge_inset_for(c) for c in
                  ("Claude Code", "Codex CLI", "Gemini CLI", "Copilot CLI")}
        self.assertEqual(len(insets), 1)

    def test_no_pane_found_keeps_the_old_fallback(self):
        caret = (400, 960, 411, 978)
        lone = FakeControl("Terminal 1, input", caret, parent=None)
        self.assertIsNone(app._terminal_badge_rect(lone, "code.exe", 0, app._SimpleRect(*caret), "Claude Code"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
