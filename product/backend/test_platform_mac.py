"""Tests for the macOS layer, run with fakes so they work on any machine.

What these CAN prove: the matching rules, the process tree walk, the path
layout, and that every entry point fails closed when the OS is not there.

What they CANNOT prove: that Apple's Accessibility API returns what we expect
from real applications. That needs a human on a Mac who has granted
Accessibility permission, because the API returns nothing at all until someone
ticks a box in System Settings and no CI runner can do that.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import platform_mac
from platform_mac import accessibility, autostart, input as mac_input, paths, processes


class FailsClosedWithoutMacOS(unittest.TestCase):
    """On Windows pyobjc is absent. Nothing may raise, and nothing may claim
    success, because a badge drawn on a wrong guess is worse than no badge."""

    def test_the_package_knows_it_is_unavailable(self):
        self.assertFalse(platform_mac.available())

    def test_accessibility_returns_nothing_rather_than_raising(self):
        self.assertFalse(accessibility.permission_granted())
        self.assertIsNone(accessibility.frontmost())
        self.assertIsNone(accessibility.focused_element())
        self.assertIsNone(accessibility.element_rect(None))
        self.assertIsNone(accessibility.read_text(None))
        self.assertFalse(accessibility.write_text(None, "x"))

    def test_input_returns_nothing_rather_than_raising(self):
        self.assertIsNone(mac_input.snapshot_clipboard())
        self.assertFalse(mac_input.restore_clipboard(None))
        self.assertFalse(mac_input.set_clipboard_text("x"))
        self.assertIsNone(mac_input.peek_clipboard_text())
        self.assertFalse(mac_input.send_select_all_and_paste())
        self.assertIsNone(mac_input.install_key_tap(lambda k: None))


class ProcessMatching(unittest.TestCase):
    """The rules that decide whether an AI CLI is running under a terminal.
    Driven with a fake table, so this is the real logic on any OS."""

    def table(self, rows):
        return {pid: (ppid, comm, args) for pid, ppid, comm, args in rows}

    def test_finds_a_cli_by_its_own_binary(self):
        t = self.table([(100, 1, "iTerm2", "iTerm"),
                        (200, 100, "zsh", "-zsh"),
                        (300, 200, "claude", "claude")])
        self.assertEqual(processes.ai_cli_under(100, t), "Claude Code")

    def test_finds_gemini_which_ships_no_binary(self):
        t = self.table([(100, 1, "Terminal", "Terminal"),
                        (200, 100, "zsh", "-zsh"),
                        (300, 200, "node", "node /opt/n/@google/gemini-cli/dist/index.js")])
        self.assertEqual(processes.ai_cli_under(100, t), "Gemini CLI")

    def test_bare_node_is_never_a_match(self):
        """The rule that keeps the badge off every dev server and build. The
        Windows layer has the same test for the same reason."""
        t = self.table([(100, 1, "Terminal", "Terminal"),
                        (200, 100, "zsh", "-zsh"),
                        (300, 200, "node", "node server.js")])
        self.assertIsNone(processes.ai_cli_under(100, t))

    def test_an_unrelated_tree_does_not_match(self):
        t = self.table([(100, 1, "Terminal", "Terminal"),
                        (200, 100, "zsh", "-zsh"),
                        (300, 200, "vim", "vim notes.md")])
        self.assertIsNone(processes.ai_cli_under(100, t))

    def test_it_reaches_a_grandchild(self):
        t = self.table([(100, 1, "Terminal", "Terminal"),
                        (200, 100, "zsh", "-zsh"),
                        (300, 200, "npm", "npm exec"),
                        (400, 300, "codex", "codex")])
        self.assertEqual(processes.ai_cli_under(100, t), "Codex CLI")

    def test_a_cli_in_another_terminal_is_not_borrowed(self):
        t = self.table([(100, 1, "Terminal", "Terminal"),
                        (500, 1, "iTerm2", "iTerm"),
                        (600, 500, "claude", "claude")])
        self.assertIsNone(processes.ai_cli_under(100, t))

    def test_a_cycle_cannot_hang_the_walk(self):
        t = self.table([(100, 1, "Terminal", "Terminal"),
                        (200, 100, "a", "a"), (300, 200, "b", "b"), (200, 300, "a", "a")])
        processes.ai_cli_under(100, t)   # must simply return

    def test_an_empty_table_fails_closed(self):
        self.assertIsNone(processes.ai_cli_under(100, {}))

    def test_vscode_bundles_are_a_subset_of_the_terminal_hosts(self):
        self.assertTrue(processes.VSCODE_BUNDLES <= processes.TERMINAL_HOST_BUNDLES)


class PathsMatchTheMacConvention(unittest.TestCase):
    def test_support_dir_is_under_application_support(self):
        d = paths.support_dir()
        self.assertIn("Application Support", d)
        self.assertTrue(d.endswith("Comprsly"))

    def test_storage_paths_cover_what_the_engine_configures(self):
        got = set(paths.storage_paths())
        self.assertEqual(got, {"log_dir", "settings_path", "history_path", "badge_position_path"})

    def test_no_windows_path_leaked_in(self):
        for value in paths.storage_paths().values():
            self.assertNotIn("AppData", value)


class AutostartIsALaunchAgent(unittest.TestCase):
    def test_the_label_is_reverse_dns(self):
        self.assertTrue(autostart.LABEL.startswith("com."))

    def test_it_does_not_keep_the_app_alive(self):
        """KeepAlive would relaunch Comprsly the moment the user quit it, which
        reads as an app refusing to close."""
        import inspect
        self.assertIn('"KeepAlive": False', inspect.getsource(autostart.enable))


class SharedWithWindowsOnPurpose(unittest.TestCase):
    def test_the_cli_names_match_the_windows_layer(self):
        import main
        win = set(v for v in main.AI_CLI_DESCENDANT_PROCESSES.values())
        mac = set(processes.AI_CLI_PROCESSES.values())
        self.assertEqual(win, mac, "the two layers disagree about which CLIs exist")

    def test_node_is_the_only_interpreter_inspected_on_both(self):
        import main
        self.assertEqual({p.replace(".exe", "") for p in main.CMDLINE_CHECK_PROCESSES},
                         processes.CMDLINE_CHECK_PROCESSES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
