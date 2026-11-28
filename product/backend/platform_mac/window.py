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


def native_window(win, rect=None):
    """The NSWindow behind a Tk toplevel, or None.

    **Not by title.** That was the first attempt and it never matched once:
    an overrideredirect window on Aqua is a borderless NSWindow and `wm title`
    does not reach it, so every CI run reported "no NSWindow with that title"
    and every AppKit call below it silently did nothing.

    By what is on screen instead. The Tk root is permanently withdrawn and the
    badge is the only window this application shows, so a single visible
    window is the badge. When there is more than one, the frame decides, and
    that conversion is the part worth reading: Tk and the Accessibility API
    both measure from the TOP left of the screen, AppKit measures from the
    BOTTOM left, so a badge near the bottom of a text box is near the top of
    an NSWindow frame.
    """
    if not is_macos():
        return None
    try:
        import AppKit
        showing = [w for w in AppKit.NSApplication.sharedApplication().windows()
                   if w.isVisible()]
    except Exception:
        return None
    if not showing:
        return None
    if len(showing) == 1:
        return showing[0]
    if rect is None:
        return None
    try:
        import AppKit
        height = AppKit.NSScreen.screens()[0].frame().size.height
        want_x, want_y = rect.left, height - rect.bottom
        want_w, want_h = rect.right - rect.left, rect.bottom - rect.top
        for ns in showing:
            frame = ns.frame()
            if (abs(frame.origin.x - want_x) <= 2
                    and abs(frame.origin.y - want_y) <= 2
                    and abs(frame.size.width - want_w) <= 2
                    and abs(frame.size.height - want_h) <= 2):
                return ns
    except Exception:
        pass
    return None


def upgrade_to_clear(win, rect):
    """Per pixel transparency, asked of AppKit AFTER Tk has mapped the window.

    It cannot be asked for before. Tk creates the NSWindow when it maps, so
    the first version of this ran during construction, found nothing, and the
    ladder reported 'alpha' on a run where there was nothing wrong with the
    clearing itself. That is also why this is an upgrade rather than a rung:
    the window is built on a rung that definitely draws, and then improved if
    AppKit is reachable.

    What it replaces is `wm attributes -transparent 1` plus a systemTransparent
    background, which on macOS 26.7.2 drew nothing at all while Tk reported
    the window mapped and viewable at exactly the right rectangle. Forcing the
    alpha and opaque rungs in the same run drew the real badge in exactly the
    right place, which rules out position, geometry and artwork.

    setOpaque_(False) with a clear background is the documented way to get a
    window whose transparency comes from what is drawn into it, which is what
    the badge wants: the mark keeps its own alpha and the square around it has
    none. The shadow goes because a shadow around an invisible square is a
    visible square.
    """
    ns = native_window(win, rect)
    if ns is None:
        return False
    try:
        import AppKit
        ns.setOpaque_(False)
        ns.setBackgroundColor_(AppKit.NSColor.clearColor())
        ns.setHasShadow_(False)
        # Undo the rung it was built on, or the whole badge stays at 0.92.
        win.attributes("-alpha", 1.0)
        return True
    except Exception:
        return False


def attach_badge_image(win, rect, png_bytes):
    """Draw the badge with AppKit, because Tk will not draw it on a clear window.

    Measured on macOS 26.7.2, and this is the end of a chain of four:

        the window is there        appkit says visible=True
        the frame is right         38x38 at exactly the computed point
        it is genuinely clear      opaque=False, alpha=1.00
        it is not stealing focus   key=False
        and the screen is byte identical before and after

    Everything about the window is correct and nothing is drawn into it. A Tk
    Label on a `systemTransparent` background renders nothing on Aqua, which
    is also what killed the older `-transparent` route: both times the window
    was blamed and both times it was the content.

    So Tk stops painting the mark here. An NSImageView holding the real PNG,
    with its own alpha, goes in as a subview of the content view Tk already
    owns, which leaves Tk owning geometry, mapping and teardown. The image is
    the same one Windows draws, unflattened, so its edges stay soft instead
    of being keyed to one shade.

    shortcut: the image view swallows mouse events, which costs nothing today
    because there is no review card on macOS for the badge to open. Give it a
    hitTest_ that returns None, or forward the click, when there is one.
    """
    ns = native_window(win, rect)
    if ns is None:
        return None
    try:
        import AppKit
        import Foundation
        data = Foundation.NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
        image = AppKit.NSImage.alloc().initWithData_(data)
        if image is None:
            return None
        content = ns.contentView()
        view = AppKit.NSImageView.alloc().initWithFrame_(content.bounds())
        view.setImage_(image)
        view.setImageScaling_(AppKit.NSImageScaleAxesIndependently)
        view.setAutoresizingMask_(
            AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        content.addSubview_(view)
        return view
    except Exception:
        return None


def set_badge_image(view, png_bytes):
    """Swap the picture when the heat ring changes. True when it took."""
    if view is None:
        return False
    try:
        import AppKit
        import Foundation
        data = Foundation.NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
        image = AppKit.NSImage.alloc().initWithData_(data)
        if image is None:
            return False
        view.setImage_(image)
        return True
    except Exception:
        return False


def float_without_activating(win, rect=None):
    """Float above other applications WITHOUT becoming the key window.

    Tk's own map is makeKeyAndOrderFront:, so the badge takes key status as
    it appears. Ordering out hands that back to whatever the user was really
    in, which for an accessory application with no other windows is the app
    they are typing in; ordering front regardless puts the badge back on
    screen without asking to be key and without activating us.

    Worth saying plainly: this has never run. Every CI round so far found no
    NSWindow, because the lookup was by title. Focus came right anyway when
    the macOS colour key was abandoned, which means the `-transparent` window
    was the thing taking focus, not the mapping. This stays because the
    clearing below may bring the problem back, and the run will say.
    """
    ns = native_window(win, rect)
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


def describe_native(win, rect=None):
    """What AppKit says about the badge window. For the report, so that the
    next thing we are wrong about is visible rather than inferred."""
    ns = native_window(win, rect)
    if ns is None:
        showing = "unknown"
        try:
            import AppKit
            showing = str(len([
                w for w in AppKit.NSApplication.sharedApplication().windows()
                if w.isVisible()]))
        except Exception:
            pass
        return "not found, %s visible window(s) in this app" % showing
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

    On macOS the top rung is NOT here. "clear" is applied by upgrade_to_clear
    after the window is mapped, because the NSWindow it needs does not exist
    until then. So this builds the window on a rung that definitely draws, and
    the upgrade improves it if AppKit is reachable.

    `prefer` forces a rung instead of taking the first that works. Nothing in
    the product passes it: it exists so the smoke run can measure every rung on
    a real Mac and settle which is actually visible there, rather than us
    picking one and finding out a CI round later.
    """
    if prefer != "alpha" and prefer != "opaque" and not is_macos():
        try:
            win.attributes("-transparentcolor", key_color)
            return "keyed"
        except Exception:
            pass
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
