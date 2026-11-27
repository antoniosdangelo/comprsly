"""Clipboard and keystrokes on macOS.

Windows uses the Win32 clipboard and SetWindowsHookExW(WH_KEYBOARD_LL). The
macOS equivalents are NSPasteboard and a CGEventTap.

Two differences from Windows that are not cosmetic:

A CGEventTap needs the same Accessibility permission as everything else, and it
needs a CFRunLoop to deliver events. The Windows hook can be installed from any
thread with a message pump; here the tap must be added to a run loop that keeps
running, which is why install_key_tap takes a callback and hands back a stop
function rather than blocking.

macOS pastes with Command+V, not Control+V. The apply path is otherwise the
same shape as the Windows one: put the new text on the pasteboard, select all,
paste, then put the user's own clipboard back whatever happened.

UNVERIFIED on real hardware.
"""

from . import available

CMD_KEY = 0x37        # kVK_Command
A_KEY = 0x00          # kVK_ANSI_A
V_KEY = 0x09          # kVK_ANSI_V


def _appkit():
    if not available():
        return None
    import AppKit
    return AppKit


def snapshot_clipboard():
    """Everything on the pasteboard, so it can be put back untouched.

    Returns a list of (type, data) or None. Like the Windows version this keeps
    every representation, not just text: a copied image or a set of files must
    survive an Apply, and the Windows code lost exactly that once.
    """
    AppKit = _appkit()
    if AppKit is None:
        return None
    try:
        pb = AppKit.NSPasteboard.generalPasteboard()
        out = []
        for t in list(pb.types() or []):
            data = pb.dataForType_(t)
            if data is not None:
                out.append((t, data))
        return out
    except Exception:
        return None


def restore_clipboard(snapshot):
    """Put back what snapshot_clipboard took. Never raises."""
    AppKit = _appkit()
    if AppKit is None or snapshot is None:
        return False
    try:
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        for t, data in snapshot:
            pb.setData_forType_(data, t)
        return True
    except Exception:
        return False


def set_clipboard_text(text):
    AppKit = _appkit()
    if AppKit is None:
        return False
    try:
        pb = AppKit.NSPasteboard.generalPasteboard()
        pb.clearContents()
        return bool(pb.setString_forType_(text, AppKit.NSPasteboardTypeString))
    except Exception:
        return False


def peek_clipboard_text():
    AppKit = _appkit()
    if AppKit is None:
        return None
    try:
        pb = AppKit.NSPasteboard.generalPasteboard()
        value = pb.stringForType_(AppKit.NSPasteboardTypeString)
        return str(value) if value is not None else None
    except Exception:
        return None


def send_select_all_and_paste():
    """Command+A then Command+V, as synthetic events.

    Returns False rather than half sending if anything goes wrong, so the
    caller can abort before it has selected the user's text. That ordering is
    not fussiness: on Windows a half completed version of this once left a
    prompt fully selected and one keystroke from deletion.
    """
    if not available():
        return False
    try:
        import Quartz
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)

        def tap(keycode, down):
            e = Quartz.CGEventCreateKeyboardEvent(src, keycode, down)
            Quartz.CGEventSetFlags(e, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)

        for key in (A_KEY, V_KEY):
            tap(key, True)
            tap(key, False)
        return True
    except Exception:
        return False


def install_key_tap(on_key, on_flags_changed=None):
    """Watch keystrokes. Returns a stop() callable, or None if it cannot start.

    The tap only sees events once Accessibility permission is granted, and it
    is silently disabled by the system if the callback is too slow, which is a
    real failure mode with no Windows equivalent and is why the callback here
    must do nothing but record.
    """
    if not available():
        return None
    try:
        import Quartz
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        if on_flags_changed is not None:
            mask |= Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)

        def handler(proxy, type_, event, refcon):
            try:
                if type_ == Quartz.kCGEventFlagsChanged:
                    if on_flags_changed:
                        on_flags_changed(Quartz.CGEventGetFlags(event))
                else:
                    on_key(Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode))
            except Exception:
                pass          # a raising tap gets torn down by the system
            return event

        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly, mask, handler, None)
        if not tap:
            return None
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)

        def stop():
            try:
                Quartz.CGEventTapEnable(tap, False)
                Quartz.CFRunLoopRemoveSource(loop, source, Quartz.kCFRunLoopCommonModes)
            except Exception:
                pass

        return stop
    except Exception:
        return None
