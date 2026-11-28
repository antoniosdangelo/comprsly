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


BADGE_WINDOW_TITLE = "Comprsly badge"


def native_window(win):
    """The NSWindow behind a Tk toplevel, found by its title.

    Tk hands out no pointer to it, so the window is given a title nobody ever
    sees (it is borderless, and an accessory app has no Window menu) and
    matched by that. Matching is what makes everything below possible: Tk's
    `wm attributes` covers a fraction of what an NSWindow can be told, and
    the fraction it covers turned out not to include anything that worked.
    """
    if not is_macos():
        return None
    try:
        import AppKit
        for ns in AppKit.NSApplication.sharedApplication().windows():
            if str(ns.title() or "") == BADGE_WINDOW_TITLE:
                return ns
    except Exception:
        pass
    return None


def make_badge_window_clear(win):
    """Per pixel transparency, asked of AppKit rather than of Tk.

    Replaces `wm attributes -transparent 1` plus a systemTransparent
    background, which is what the first three CI rounds used and what
    MACOS_UI.md warned about from the day it was written. Measured on
    macOS 26.7.2: Tk reported the window mapped and viewable at exactly the
    right 38x38 rectangle, and the screen was byte identical before and
    after. Nothing was drawn at all. Forcing the alpha and opaque rungs in
    the same run drew the real badge in exactly the right place, which is
    what rules out position, artwork and geometry and leaves the keying.

    setOpaque_(False) with a clear background colour is the documented way
    to get a window whose transparency comes from what is drawn into it,
    which is what the badge wants: the mark keeps its own alpha and the
    square around it has none. The shadow goes because a shadow around an
    invisible square is a visible square.
    """
    ns = native_window(win)
    if ns is None:
        return False
    try:
        import AppKit
        ns.setOpaque_(False)
        ns.setBackgroundColor_(AppKit.NSColor.clearColor())
        ns.setHasShadow_(False)
        win.configure(bg="systemTransparent")
        return True
    except Exception:
        return False


def float_without_activating(win):
    """Float above other applications WITHOUT becoming the key window.

    `wm attributes -topmost` and the non-activating panel style both report
    success and both leave the badge taking key status: measured on a CI Mac,
    where the app was correctly an accessory (the menu bar still said
    TextEdit) and TextEdit's own title bar went grey the moment the badge
    appeared. A window that is not key still owns the keyboard focus question
    as far as the Accessibility API is concerned, so the watch loop then read
    Comprsly's focused element instead of the text box it was badging.

    orderOut_ then orderFrontRegardless is the pair that fixes it. Ordering
    out makes AppKit hand key status to the next window in line, which for an
    accessory app with no other windows is whatever the user was actually in;
    ordering front regardless shows it again without asking to be key and
    without activating the application.
    """
    ns = native_window(win)
    if ns is None:
        return False
    try:
        import AppKit
        ns.setLevel_(AppKit.NSStatusWindowLevel)
        ns.orderOut_(None)
        ns.orderFrontRegardless()
        return True
    except Exception:
        return False


def describe_native(win):
    """What AppKit says about the badge window. For the report, so that the
    next thing we are wrong about is visible rather than inferred."""
    ns = native_window(win)
    if ns is None:
        return "no NSWindow with that title"
    try:
        frame = ns.frame()
        return ("key=%s visible=%s opaque=%s alpha=%.2f level=%s "
                "frame=%.0fx%.0f+%.0f+%.0f"
                % (bool(ns.isKeyWindow()), bool(ns.isVisible()),
                   bool(ns.isOpaque()), float(ns.alphaValue()), int(ns.level()),
                   frame.size.width, frame.size.height,
                   frame.origin.x, frame.origin.y))
    except Exception as exc:
        return "could not be read: %s" % exc


def become_accessory_app():
    """Take the Dock icon and the menu bar away, and stop activating.

    LSUIElement is already true in the built Info.plist. It is not enough:
    **Tk sets the activation policy back to regular when it starts.** The
    first CI screenshot of the real badge shows the proof, which is Tk's own
    default Aqua menu bar, File / Edit / Window / Help, sitting under the name
    Comprsly, with a Dock icon beside the Finder's.

    A regular application activates when it shows a window, so the badge
    appearing took the caret away from TextEdit. For this product that is
    fatal twice over: it interrupts typing, and the watch loop then reads
    Comprsly's own focused element instead of the text box it is meant to
    badge, so the badge can never appear again either.

    Must be called AFTER the Tk root exists, since that is when Tk sets the
    policy it is undoing.
    """
    if not is_macos():
        return False
    try:
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        return bool(app.setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory))
    except Exception:
        return False


def make_badge_window_transparent(win, key_color, prefer=None):
    """Hide the square around the circular badge. Returns what it managed.

    "keyed"       the square is genuinely invisible and click through
    "alpha"       fell back to a whole window alpha; the square is faint but
                  present, and the badge is still usable
    "opaque"      neither worked; the badge will show its background

    `prefer` forces a rung instead of taking the first that works. Nothing in
    the product passes it: it exists so the smoke run can measure all three on
    a real Mac and settle which one is actually visible there, rather than us
    picking one and finding out a CI round later. See MACOS_UI.md, which has
    warned since it was written that the macOS keying is disputed and that
    some report the window vanishing outright.
    """
    if prefer != "alpha" and prefer != "opaque":
        if not is_macos():
            try:
                win.attributes("-transparentcolor", key_color)
                return "keyed"
            except Exception:
                pass
        elif make_badge_window_clear(win):
            return "clear"
    if prefer != "opaque":
        try:
            win.attributes("-alpha", BADGE_ALPHA_FALLBACK)
            return "alpha"
        except Exception:
            pass
    return "opaque"


def badge_background(mode, key_color):
    """What to paint behind the badge's own widgets, given what the window
    managed. **Every widget inside the badge window has to use this.**

    Making the TOPLEVEL transparent is not enough on macOS, and finding that
    out cost the first real CI screenshot. The run reported `transparency:
    keyed` and the picture showed a dark rectangle with a sliver of purple in
    it. Both were true: `-transparent` was accepted, and the Canvas inside it
    had a solid `-background` and was drawn solid straight over the top. The
    window was transparent; nothing you could see was.

    So "keyed" on a Mac means the children go to `systemTransparent` as well.
    Anywhere else, including the alpha and opaque rungs of the ladder, the
    children keep the key colour: on Windows that is the shade the window
    deletes, and on a Mac that is the faint-or-solid square the ladder already
    says you get when the keying did not work.
    """
    if mode == "clear" and is_macos():
        return "systemTransparent"
    return key_color


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
