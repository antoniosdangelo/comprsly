"""Finding the focused text box on macOS, and reading and writing it.

This is the Windows UI Automation half of PLATFORM.md, rewritten against
Apple's Accessibility API. The call shape is the one Apple's own
accessibility-dev list gives: ask the system wide element which application
has focus, then ask THAT element for its focused UI element. The system wide
element does NOT reliably answer kAXFocusedUIElement itself, which is a
documented gotcha and the reason this goes through the application element.

It used to take the pid from NSWorkspace.frontmostApplication() instead, and
that is a cache fed by run loop notifications. A process that does not run
one, which includes both the watch loop and anything driving this from a
script, reads the app that was in front when it first asked and never finds
out that it changed. See _focused_app_element, which has the measurement.

Every function fails closed: anything unexpected returns None and the badge
stays hidden, which is the same rule the Windows layer follows, because
showing a badge in the wrong place is worse than not showing one.
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
            "running_app": AppKit.NSRunningApplication,
            "workspace": AppKit.NSWorkspace,
            "AS": AS,
            "systemwide": AS.AXUIElementCreateSystemWide,
            "create_app": AS.AXUIElementCreateApplication,
            "copy": AS.AXUIElementCopyAttributeValue,
            "set": AS.AXUIElementSetAttributeValue,
            "pid_of": AS.AXUIElementGetPid,
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


def _error(err):
    """An AX error code with its name, because the number alone means nothing
    to anyone reading a CI log at speed."""
    return "%s (%s)" % (err, _AX_ERRORS.get(err, "unknown"))


# The handful that actually come back from these calls. From AXError.h.
_AX_ERRORS = {
    0: "success",
    -25200: "failure",
    -25201: "illegal argument",
    -25202: "invalid UIElement",
    -25204: "cannot complete",
    -25205: "attribute unsupported",
    -25212: "no value",
    -25211: "not implemented",
    -25214: "API disabled, Accessibility is off",
}


def _pid_from_element(element):
    """The process an AXUIElement belongs to, or None."""
    ax = _ax()
    err, pid = ax["pid_of"](element, None)
    if err != 0 or not pid:
        return None
    return int(pid)


def _rung_focused_application():
    """kAXFocusedApplication on the system wide element.

    Apple's documented answer to this exact question, and the first thing to
    try. It is also known to fail: rdar://10969414 reports the system wide
    element refusing this attribute, and a CI Mac on macOS 26.7.2 returned
    nothing for it on every call while Accessibility was granted and every
    other attribute worked. Hence the rungs below rather than a second guess.
    """
    ax = _ax()
    name = getattr(ax["AS"], "kAXFocusedApplicationAttribute",
                   "AXFocusedApplication")
    err, app = ax["copy"](ax["systemwide"](), name, None)
    if err != 0 or app is None:
        return None, "attribute %r -> %s" % (str(name), _error(err))
    pid = _pid_from_element(app)
    return pid, ("no pid for the element" if pid is None else "pid %d" % pid)


def _rung_focused_ui_element():
    """kAXFocusedUIElement on the system wide element, for its owner only.

    The module docstring is right that this is not a reliable way to get the
    focused CONTROL. It is a perfectly good way to find out which process
    owns it, which is all this rung is asked for; the control is then read
    back through that application's own element like every other rung.
    """
    ax = _ax()
    err, element = ax["copy"](ax["systemwide"](),
                              ax["AS"].kAXFocusedUIElementAttribute, None)
    if err != 0 or element is None:
        return None, _error(err)
    pid = _pid_from_element(element)
    return pid, ("no pid for the element" if pid is None else "pid %d" % pid)


def _rung_front_window_owner():
    """Who owns the frontmost on screen window, asked of the window server.

    No cache and no run loop: CGWindowListCopyWindowInfo is a live query. The
    list comes back front to back, so the first window at layer 0 is the one
    the user is looking at. Higher layers are the menu bar, the Dock, and
    floating panels, which includes our own badge, so layer 0 alone would
    nearly always be enough; our pid is skipped as well, because a badge that
    found itself would pin the badge to the badge.

    Window TITLES need Screen Recording permission. Owner pid, layer and
    bounds do not, and those are all this reads.
    """
    import os
    import Quartz
    options = (Quartz.kCGWindowListOptionOnScreenOnly
               | Quartz.kCGWindowListExcludeDesktopElements)
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    if not windows:
        return None, "the window server listed no windows"
    mine = os.getpid()
    for window in windows:
        if int(window.get("kCGWindowLayer", 0)) != 0:
            continue
        pid = window.get("kCGWindowOwnerPID")
        if pid is None or int(pid) == mine:
            continue
        return int(pid), "pid %d, %r" % (int(pid),
                                         str(window.get("kCGWindowOwnerName", "")))
    return None, "%d windows on screen, none at layer 0" % len(windows)


def _rung_workspace():
    """NSWorkspace.frontmostApplication(), last because it may be stale.

    It is a cached property kept current by notifications delivered on the
    run loop. A process that never runs one reads whatever was in front the
    first time it asked and never learns otherwise, which is how a CI run sat
    for twenty seconds reading the Finder desktop while TextEdit had the
    caret. For a short lived process it is correct, which is why it is still
    here rather than deleted.

    Deliberately NOT pumping the run loop to refresh it. The watch loop is a
    Tk application sharing the same main run loop, and running it re-entrantly
    from inside a Tk callback can re-enter Tk's own callbacks. If this ever
    turns out to be the rung that answers, that is the moment to deal with it,
    and the trace below will say so.
    """
    ax = _ax()
    app = ax["workspace"].sharedWorkspace().frontmostApplication()
    if app is None:
        return None, "nothing reported as frontmost"
    return int(app.processIdentifier()), "pid %d, possibly stale" % int(
        app.processIdentifier())


# In order. Each one answers the same question, "which process has the user's
# attention", by a different route, and every one of them is a live query
# except the last.
_RUNGS = (
    ("system wide kAXFocusedApplication", _rung_focused_application),
    ("system wide kAXFocusedUIElement", _rung_focused_ui_element),
    ("frontmost window's owner", _rung_front_window_owner),
    ("NSWorkspace frontmostApplication", _rung_workspace),
)


def focused_pid(trace=None):
    """(pid, which rung answered), or (None, None).

    Pass a list as `trace` to collect (rung name, what it said) for every rung
    tried. --check prints that, which is the difference between knowing why
    this failed and guessing at it for another CI round.
    """
    if _ax() is None:
        if trace is not None:
            trace.append(("pyobjc", "not installed"))
        return None, None
    for name, rung in _RUNGS:
        try:
            pid, note = rung()
        except Exception as exc:
            pid, note = None, "raised %s: %s" % (type(exc).__name__, exc)
        if trace is not None:
            trace.append((name, note))
        if pid:
            return pid, name
    return None, None


def frontmost(trace=None):
    """(pid, bundle_id, localised_name) of the app in front, or None."""
    ax = _ax()
    pid, _how = focused_pid(trace)
    if ax is None or pid is None:
        return None
    try:
        # Looked up BY pid, so this is a direct lookup and not the cached
        # "who is in front" value. A running app's name and bundle id do not
        # change while it runs.
        app = ax["running_app"].runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return (pid, "", "")
        return (pid,
                str(app.bundleIdentifier() or ""),
                str(app.localizedName() or ""))
    except Exception:
        return None


def focused_element(trace=None):
    """The AXUIElement the caret is in, or None.

    Via the application element, not the system wide one: that is the one
    thing about this that has been verified on a real Mac, where it returned
    TextEdit's AXTextArea with its rectangle and its text. Only the question
    of WHICH application has moved around, which is what focused_pid answers.
    """
    ax = _ax()
    pid, _how = focused_pid(trace)
    if ax is None or pid is None:
        return None
    try:
        app_element = ax["create_app"](pid)
    except Exception:
        return None
    return _attr(app_element, ax["AS"].kAXFocusedUIElementAttribute)

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
