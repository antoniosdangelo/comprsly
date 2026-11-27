"""Finding the focused text box on macOS, and reading and writing it.

This is the Windows UI Automation half of PLATFORM.md, rewritten against
Apple's Accessibility API. The call shape is the one Apple's own
accessibility-dev list gives: take the frontmost application's pid from
NSWorkspace, build an AXUIElement for it, then ask that element for its
focused UI element. The system wide element does NOT reliably answer
kAXFocusedUIElement, which is a documented gotcha and the reason this goes
through the application element.

UNVERIFIED on real hardware. Every function fails closed: anything unexpected
returns None and the badge stays hidden, which is the same rule the Windows
layer follows, because showing a badge in the wrong place is worse than not
showing one.
"""

from . import available

# pyobjc constants, imported lazily so this module loads on Windows for tests.
_AX = None


def _ax():
    """The handful of symbols we need, or None when pyobjc is missing."""
    global _AX
    if _AX is None:
        if not available():
            _AX = False
            return None
        import AppKit
        import ApplicationServices as AS
        _AX = {
            "workspace": AppKit.NSWorkspace,
            "AS": AS,
            "create_app": AS.AXUIElementCreateApplication,
            "copy": AS.AXUIElementCopyAttributeValue,
            "set": AS.AXUIElementSetAttributeValue,
            "trusted": AS.AXIsProcessTrusted,
        }
    return _AX or None


def permission_granted():
    """Accessibility permission, which the user grants in System Settings.

    Nothing else here works without it, and there is no way to request it from
    code beyond prompting once: the user has to tick the box themselves. This
    is the single biggest difference from Windows, where UI Automation needs no
    permission at all.
    """
    ax = _ax()
    if ax is None:
        return False
    try:
        return bool(ax["trusted"]())
    except Exception:
        return False


def frontmost():
    """(pid, bundle_id, localised_name) of the app in front, or None."""
    ax = _ax()
    if ax is None:
        return None
    try:
        app = ax["workspace"].sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        return (int(app.processIdentifier()),
                str(app.bundleIdentifier() or ""),
                str(app.localizedName() or ""))
    except Exception:
        return None


def _attr(element, name):
    """One accessibility attribute, or None.

    PyObjC returns (error_code, value); 0 is kAXErrorSuccess. Anything else,
    including the kAXErrorCannotComplete that unresponsive apps return, is
    treated as "no answer" rather than raised.
    """
    ax = _ax()
    if ax is None or element is None:
        return None
    try:
        err, value = ax["copy"](element, name, None)
        return value if err == 0 else None
    except Exception:
        return None


def focused_element():
    """The AXUIElement the caret is in, or None.

    Via the application element, not the system wide one. See the module
    docstring.
    """
    ax = _ax()
    if ax is None:
        return None
    front = frontmost()
    if front is None:
        return None
    try:
        app_element = ax["create_app"](front[0])
    except Exception:
        return None
    return _attr(app_element, ax["AS"].kAXFocusedUIElementAttribute)


def element_role(element):
    """"AXTextField", "AXTextArea" and so on, or None."""
    ax = _ax()
    if ax is None:
        return None
    role = _attr(element, ax["AS"].kAXRoleAttribute)
    return str(role) if role is not None else None


def element_rect(element):
    """Screen rectangle as (left, top, right, bottom), or None.

    macOS gives position and size as two separate AXValue structs, and its
    origin is the TOP left of the primary display for AX (unlike NSWindow
    coordinates, which start bottom left). The engine's geometry expects top
    left, so no flip is applied here. Worth re-checking on a multi display Mac,
    which is exactly the kind of thing this code cannot be sure of yet.
    """
    ax = _ax()
    if ax is None:
        return None
    AS = ax["AS"]
    pos = _attr(element, AS.kAXPositionAttribute)
    size = _attr(element, AS.kAXSizeAttribute)
    if pos is None or size is None:
        return None
    try:
        import CoreFoundation  # noqa: F401
        ok_p, p = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
        ok_s, s = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
        if not ok_p or not ok_s:
            return None
        left, top = int(p.x), int(p.y)
        return (left, top, left + int(s.width), top + int(s.height))
    except Exception:
        return None


def read_text(element):
    """What is typed in the focused control, or None if it cannot be read."""
    ax = _ax()
    if ax is None:
        return None
    value = _attr(element, ax["AS"].kAXValueAttribute)
    return str(value) if isinstance(value, str) else None


def write_text(element, new_text):
    """Replace the control's text. True when the API accepted it.

    The direct set is tried first, exactly like SetValue on Windows. When it
    fails, the Windows layer falls back to the clipboard and a paste keystroke;
    the same fallback belongs here and lives in input.py, so that a failure
    returns False rather than silently doing nothing.
    """
    ax = _ax()
    if ax is None or element is None:
        return False
    try:
        err = ax["set"](element, ax["AS"].kAXValueAttribute, new_text)
        return err == 0
    except Exception:
        return False
