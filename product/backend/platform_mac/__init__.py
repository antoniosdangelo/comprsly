"""The macOS half of the platform seam described in PLATFORM.md.

Status, stated plainly because it matters: **this code has never run on a Mac.**
It was written on Windows against Apple's documented Accessibility API. What is
proven is the logic, by the tests beside it, which use fakes and run anywhere,
and that it imports cleanly on macos-latest in CI. What is NOT proven is that
the Accessibility calls return what we expect from real applications. That
needs a human in front of a Mac, because the API refuses to work at all until
someone grants Accessibility permission in System Settings, and no CI runner
can click that.

Everything here is import safe on Windows: pyobjc is optional, and when it is
missing the module still imports and `available()` returns False. That is what
lets the logic be tested on this machine at all.
"""

AVAILABLE = None


def available():
    """True when pyobjc is importable, so the rest of this package can be used."""
    global AVAILABLE
    if AVAILABLE is None:
        try:
            import AppKit  # noqa: F401
            import ApplicationServices  # noqa: F401
            AVAILABLE = True
        except Exception:
            AVAILABLE = False
    return AVAILABLE
