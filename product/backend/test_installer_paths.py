"""Every file the Inno Setup script points at has to actually be there.

The restructure of 2026-11-26 moved the UI assets from product/build/assets to
product/frontend/assets. installer.iss had its SetupIconFile updated and its
two wizard image lines missed, so the Windows installer build failed on main
with "Could not read ... wizard_large_164x314.bmp". Fifteen bitmaps were sitting
in the repo one directory away.

Nothing caught it locally, because installer.iss is only ever read by Inno
Setup, which only runs on a push to main. This test reads it instead.
"""

import os
import re
import unittest

B = chr(92)  # a literal backslash, spelled out so no escape can be mangled

BUILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build")
ISS = os.path.join(BUILD, "installer.iss")

# Keys whose value is one or more paths to files that must exist at compile
# time, relative to the directory holding installer.iss.
PATH_KEYS = (
    "SetupIconFile",
    "WizardImageFile",
    "WizardSmallImageFile",
    "InfoBeforeFile",
    "InfoAfterFile",
    "LicenseFile",
)


def referenced_paths():
    """Static source paths out of installer.iss, as (key, path) pairs.

    Skips anything with a brace in it: {app} is resolved on the user's machine
    and {#Define} by the preprocessor, so neither can be checked from here.
        Also skips the dist directory, which is PyInstaller output and does
    the build step before this one has run.
    """
    found = []
    with open(ISS, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith(";"):
                continue
            key = line.split("=", 1)[0].strip()
            if "=" in line and key in PATH_KEYS:
                for piece in line.split("=", 1)[1].split(","):
                    found.append((key, piece.strip()))
                continue
            match = re.match(r'Source:\s*"([^"]+)"', line)
            if match:
                found.append(("Source", match.group(1)))
    return [
        (key, value)
        for key, value in found
        if value and "{" not in value and not value.lower().startswith("dist" + os.sep)
        and not value.lower().startswith("dist" + B)
    ]


class TheInstallerScriptPointsAtRealFiles(unittest.TestCase):
    def test_the_script_is_there_and_references_something(self):
        self.assertTrue(os.path.isfile(ISS), ISS)
        self.assertTrue(referenced_paths(), "parsed installer.iss but found no paths")

    def test_every_referenced_file_exists(self):
        missing = []
        for key, value in referenced_paths():
            full = os.path.normpath(os.path.join(BUILD, value.replace("\\", os.sep)))
            if not os.path.isfile(full):
                missing.append("%s=%s -> %s" % (key, value, full))
        self.assertEqual(
            [],
            missing,
            "installer.iss points at files that are not there:\n  "
            + "\n  ".join(missing),
        )

    def test_the_wizard_images_are_the_ones_that_moved(self):
        """Pins the specific regression, not just the general rule."""
        wizards = [v for k, v in referenced_paths() if k.startswith("Wizard")]
        self.assertEqual(15, len(wizards), wizards)
        for value in wizards:
            self.assertTrue(
                value.replace(B, "/").startswith("../frontend/assets/"),
                "%s still points inside product/build" % value,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
