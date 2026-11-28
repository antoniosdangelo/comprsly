"""The curated spelling table has to work without a spell checker.

Found on a real Mac, 2026-11-28. `_find_spelling_suggestions` opened with

    if winspell is None or not winspell.is_available():
        return []

and winspell is Windows COM, so on macOS it returned immediately. That also
threw away the override table further down, which is 75 hand-written
misspelling pairs, needs no dictionary whatsoever, and whose own comment says
it is scanned "INDEPENDENTLY of winspell's own flagging". "teh" went
uncorrected on a Mac for that reason alone.

It was never a macOS bug as such. The same thing happened on Windows any time
the COM object failed to create, which is a case main.py has a whole fallback
path for, and there it would have been far harder to notice: the product would
simply have stopped fixing a word it had always fixed.

These run on every machine, with the checker forced absent, so neither
platform can regress it.
"""

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import suggestion_engine

# One of each: a capitalization fix, a repeated word, and a misspelling from
# the override table. None of the three needs a dictionary. This is the
# sentence the macOS smoke run types, which is how the bug surfaced.
SENTENCE = ("i think we should basically just go ahead and and update teh "
            "readme file, if that makes sense.")


def no_spell_checker():
    """What every non-Windows machine looks like, and what a Windows machine
    looks like when the COM checker will not create."""
    return mock.patch.object(suggestion_engine, "winspell", None)


def fixed(text):
    found = suggestion_engine.analyze(text)["suggestions"]
    return suggestion_engine.apply_suggestions(text, found), found


class TheCuratedTableNeedsNoDictionary(unittest.TestCase):
    def test_a_known_misspelling_is_still_corrected(self):
        with no_spell_checker():
            out, found = fixed(SENTENCE)
        self.assertNotIn("teh", out)
        self.assertIn("update the readme", out)
        self.assertIn("spelling", [s["kind"] for s in found])

    def test_the_other_rules_still_run_alongside_it(self):
        """The early return was inside the spelling rule, so the rest always
        worked. Pinned so a later fix cannot trade one for the other."""
        with no_spell_checker():
            out, _ = fixed(SENTENCE)
        self.assertTrue(out.startswith("I think"), out)
        self.assertNotIn("and and", out)

    def test_a_sample_of_the_table_all_the_way_through(self):
        for wrong, right in (("alot", "a lot"), ("seperate", "separate"),
                             ("definately", "definitely"), ("recieve", "receive")):
            with self.subTest(wrong=wrong):
                with no_spell_checker():
                    out, _ = fixed("please %s the files before you continue" % wrong)
                self.assertIn(right, out)
                self.assertNotIn(wrong, out)

    def test_capitalisation_is_carried_over(self):
        with no_spell_checker():
            out, _ = fixed("Teh readme needs updating before anyone reads it.")
        self.assertTrue(out.startswith("The readme"), out)


class OnlyTheDictionaryHalfDegrades(unittest.TestCase):
    """The fix must not start guessing. Without a checker there is nothing to
    guess against, and inventing corrections would be far worse than missing
    them."""

    def test_a_typo_that_is_not_in_the_table_is_left_alone(self):
        with no_spell_checker():
            out, found = fixed("the outptu file needs regenerating before release")
        self.assertIn("outptu", out)
        self.assertEqual([], [s for s in found if s["kind"] == "spelling"])

    def test_the_rules_that_genuinely_need_a_dictionary_still_find_nothing(self):
        """Splitting and joining words asks "is this half a real word", which
        has no answer without one. Those keep their early return."""
        with no_spell_checker():
            self.assertEqual(
                [], suggestion_engine._find_orphan_letter_join_suggestions(
                    "lets tak eto them about it", []))
            self.assertEqual(
                [], suggestion_engine._find_misplaced_space_suggestions(
                    "lets tak eto them about it", []))


@unittest.skipUnless(sys.platform == "win32", "needs the Windows spell checker")
class WindowsIsUnchanged(unittest.TestCase):
    """The checker is still consulted where there is one. If this stops being
    true, Windows has quietly lost every correction outside the 75."""

    def test_the_checker_is_still_asked(self):
        import winspell
        if not winspell.is_available():
            self.skipTest("the COM checker would not create on this machine")
        out, _ = fixed("the outptu file needs regenerating before release")
        self.assertNotIn("outptu", out)

    def test_the_curated_words_come_out_the_same_either_way(self):
        with_checker, _ = fixed(SENTENCE)
        with no_spell_checker():
            without, _ = fixed(SENTENCE)
        self.assertEqual(with_checker, without)


if __name__ == "__main__":
    unittest.main(verbosity=2)
