"""Tests for the audit fixes of 2026-11-26.

Each one pins a specific failure that was found by reading the code, so these
are written to fail against the version before the fix, not merely to pass
against the version after it.
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import local_model
import main as app


class ModelDownloadFilenames(unittest.TestCase):
    """The file list comes from a remote API, and the name off it was joined
    straight onto a local path. A compromised or renamed repo could write
    anywhere the user can write."""

    def test_a_plain_model_filename_is_allowed(self):
        for name in ("model.onnx", "genai_config.json", "tokenizer.model",
                     "model.onnx.data", "added_tokens.json"):
            self.assertTrue(local_model._is_plain_filename(name), name)

    def test_traversal_is_refused(self):
        for name in ("../evil.exe", "../../../Startup/x.exe", "a/b.onnx",
                     "..", ".", "", "sub" + chr(92) + "evil.exe"):
            self.assertFalse(local_model._is_plain_filename(name), repr(name))

    def test_absolute_paths_are_refused(self):
        for name in ("C:/Windows/System32/x.dll", "C:" + chr(92) + "Windows" + chr(92) + "x.dll", "/etc/passwd"):
            self.assertFalse(local_model._is_plain_filename(name), name)

    def test_dotfiles_are_refused(self):
        self.assertFalse(local_model._is_plain_filename(".gitattributes"))

    def test_the_model_revision_is_pinned_not_a_branch(self):
        """"main" means whatever the repo owner is serving today."""
        rev = local_model._DOWNLOAD_REVISION
        self.assertEqual(len(rev), 40, "expected a full commit sha")
        self.assertTrue(all(c in "0123456789abcdef" for c in rev))
        self.assertNotIn(rev, ("main", "master"))


class AtomicJsonWrites(unittest.TestCase):
    """open(path, "w") empties the real file before writing a byte. A crash in
    that gap left settings or the whole savings history empty, and every
    loader swallows the error and returns a default, so it was silent."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._old = app.LOG_DIR
        app.LOG_DIR = self.dir

    def tearDown(self):
        app.LOG_DIR = self._old

    def test_it_writes_and_reads_back(self):
        p = os.path.join(self.dir, "x.json")
        self.assertTrue(app._write_json_atomically(p, {"a": 1}))
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": 1})

    def test_the_existing_file_survives_a_failed_write(self):
        p = os.path.join(self.dir, "x.json")
        app._write_json_atomically(p, {"good": True})

        class Unserialisable:
            pass

        self.assertFalse(app._write_json_atomically(p, {"bad": Unserialisable()}))
        with open(p, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"good": True},
                             "a failed write must not damage what was already there")

    def test_no_temp_file_is_left_behind(self):
        p = os.path.join(self.dir, "x.json")
        app._write_json_atomically(p, {"a": 1})

        class Unserialisable:
            pass

        app._write_json_atomically(p, {"bad": Unserialisable()})
        leftovers = [n for n in os.listdir(self.dir) if ".tmp" in n]
        self.assertEqual(leftovers, [])

    def test_the_real_savers_go_through_it(self):
        """Guards the fix itself: a future edit that reaches for open(..., "w")
        again would pass every test above and still reintroduce the bug."""
        import inspect
        for fn in (app.save_settings, app.append_history, app.save_badge_position):
            source = inspect.getsource(fn)
            self.assertIn("_write_json_atomically", source, fn.__name__)
            self.assertNotIn('"w"', source, fn.__name__)


class ClipboardIsAlwaysRestored(unittest.TestCase):
    def test_the_restore_sits_in_a_finally(self):
        """The user's clipboard is replaced with Comprsly's text mid apply. If
        anything raises before it is put back, their copied screenshot or files
        are gone with no message. Source level because the real path needs a
        live foreground window and synthetic keystrokes."""
        import inspect
        source = inspect.getsource(app.apply_new_text)
        after_finally = source.split("finally:")[1:]
        self.assertTrue(after_finally, "expected a finally block in apply_new_text")
        self.assertTrue(
            any("_restore_clipboard(original)" in block.split("\n\n")[0]
                for block in after_finally),
            "_restore_clipboard must run from a finally, not only on the happy path",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
