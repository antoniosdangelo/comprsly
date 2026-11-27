"""Making a Tk window look right on macOS.

This is the one genuinely macOS-specific piece of the UI, and it is not
cosmetic. The badge is a circle drawn on a square window, and the square is
hidden on Windows with

    win.attributes("-transparentcolor", BRAND_DARK)

which colour keys that exact shade to true transparency, so the corners are
invisible AND click through. **That attribute does not exist outside Windows.**
Tk's own wm documentation lists it under "On Windows", and on other platforms
it raises "bad attribute". Ship it unchanged and the Mac badge is a dark
square with a circle painted on it.

macOS has "-transparent" plus a systemTransparent background instead. Community
reports on it disagree: some say it works and also removes the window shadow,
others report the window flashing at startup and then vanishing. That
disagreement is exactly why this is isolated here behind one function with a
fallback, rather than spread through the badge code.

UNVERIFIED. Of everything in the Mac port this is the most likely thing to
look wrong first, and it needs eyes on a real Mac, not a test.
"""

import sys

BADGE_ALPHA_FALLBACK = 0.92


def is_macos():
    return sys.platform == "darwin"


def make_badge_window_transparent(win, key_color):
    """Hide the square around the circular badge. Returns what it managed.

    "keyed"       the square is genuinely invisible and click through
    "alpha"       fell back to a whole window alpha; the square is faint but
                  present, and the badge is still usable
    "opaque"      neither worked; the badge will show its background
    """
    if not is_macos():
        try:
            win.attributes("-transparentcolor", key_color)
            return "keyed"
        except Exception:
            pass
    else:
        try:
            win.attributes("-transparent", True)
            win.configure(bg="systemTransparent")
            return "keyed"
        except Exception:
            pass
    try:
        win.attributes("-alpha", BADGE_ALPHA_FALLBACK)
        return "alpha"
    except Exception:
        return "opaque"


def keep_on_top(win):
    """Float above other applications' windows.

    -topmost behaves on both, but on macOS a window that is topmost AND
    overrideredirect can steal focus from the app being typed into, which for
    this product is fatal: the badge appearing must never interrupt typing.
    Marking it a non-activating utility panel is the documented way to float
    without taking key focus.
    """
    try:
        win.attributes("-topmost", True)
    except Exception:
        return False
    if is_macos():
        try:
            win.tk.call("::tk::unsupported::MacWindowStyle", "style",
                        win._w, "utility", "noActivates")
        except Exception:
            # Older Tk builds lack the call. The badge still floats; it may
            # take focus on click, which is worth knowing but not fatal.
            return True
    return True
