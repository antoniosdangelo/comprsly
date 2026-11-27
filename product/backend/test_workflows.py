"""One rule about the GitHub workflow files, pinned here because CI cannot
pin it itself.

A step `if:` can read the env context but NOT the secrets context. Writing
`if: ${{ secrets.FOO != '' }}` is a workflow validation error, and GitHub
reports it in the worst possible way: the run fails in 0 seconds with no
jobs, no log and no annotation, and `gh run view` says only "likely failed
because of a workflow file issue". macos.yml shipped with it on two lines
and failed on every push for a day without anyone noticing.

The fix is always the same: lift the secret into a job level `env:` and test
that instead. This test fails on the broken form so the next person finds out
in one second instead of reading an empty run page.
"""

import os
import re
import unittest

WORKFLOWS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", ".github", "workflows"
)

# An `if:` key, at any indent, whose value mentions the secrets context.
SECRETS_IN_IF = re.compile(r"^\s*if\s*:.*\bsecrets\s*\.", re.IGNORECASE)


def workflow_files():
    if not os.path.isdir(WORKFLOWS):
        return []
    return [
        os.path.join(WORKFLOWS, n)
        for n in sorted(os.listdir(WORKFLOWS))
        if n.endswith((".yml", ".yaml"))
    ]


class TheWindowsJobMustKeepExisting(unittest.TestCase):
    """Several tests skip themselves off Windows, because main.py calls
    ctypes.windll at import and the suite now runs on macos-latest too. Those
    skips are only safe while something still runs the suite on Windows. If
    that job is ever removed or renamed away, the Windows layer would stop
    being tested anywhere and every sign of it would be a quiet "s" in the
    output. This is the tripwire for that.
    """

    def test_checks_yml_runs_the_suite_on_windows(self):
        path = os.path.join(WORKFLOWS, "checks.yml")
        self.assertTrue(os.path.isfile(path), path)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("windows-latest", text,
                      "nothing runs the Windows only tests any more")
        self.assertIn('unittest discover -s product/backend', text,
                      "the Windows job no longer runs the test suite")


class SecretsAreNotReadableInAnIf(unittest.TestCase):
    def test_the_workflow_files_are_actually_there(self):
        """A passing test over an empty list proves nothing."""
        self.assertTrue(workflow_files(), "no workflow files found at %s" % WORKFLOWS)

    def test_no_if_condition_reads_the_secrets_context(self):
        offences = []
        for path in workflow_files():
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if line.lstrip().startswith("#"):
                        continue
                    if SECRETS_IN_IF.match(line):
                        offences.append(
                            "%s:%d %s" % (os.path.basename(path), number, line.strip())
                        )
        self.assertEqual(
            [],
            offences,
            "an `if:` cannot read secrets; put the value in a job level `env:` "
            "and test env instead:\n  " + "\n  ".join(offences),
        )

    def test_the_rule_is_detected_when_it_is_broken(self):
        """The regex, not just the current files, is what is being trusted."""
        self.assertTrue(SECRETS_IN_IF.match("        if: ${{ secrets.APPLE_ID != '' }}"))
        self.assertTrue(SECRETS_IN_IF.match("    if: secrets.FOO == ''"))
        self.assertIsNone(SECRETS_IN_IF.match("        if: env.DEVELOPER_ID != ''"))
        self.assertIsNone(SECRETS_IN_IF.match("          DEVELOPER_ID: ${{ secrets.X }}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
