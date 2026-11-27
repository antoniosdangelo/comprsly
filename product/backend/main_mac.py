"""The macOS entry point.

What this is today: the wiring, and a real check that the platform layer works
on the machine it is running on. It configures the shared engine with macOS
paths, confirms Accessibility permission, and runs the detection loop that
decides whether a badge should appear and where.

What it is NOT yet: the badge and the review card. Those are Tkinter windows
that need one genuine macOS change, which is on the frontend branch, see
PLATFORM.md. Running this today prints what it detects rather than drawing it,
which is deliberately the most useful thing it can do before the UI lands: it
is how you find out whether the Accessibility half works at all on a real Mac,
which nobody has been able to answer yet.

    python main_mac.py           watch and print what would be badged
    python main_mac.py --check   print a one shot diagnosis and exit

The exit code of --check says which of three different things happened, so
that a machine reading it cannot mistake one for another:

    0   the Accessibility half works
    2   macOS is withholding permission, which only a human at the Mac can give
    3   pyobjc is not installed, so the build itself is wrong
    1   something unexpected
"""

import sys
import time

import engine.storage as storage
from engine.geometry import _pane_bottom_row
import platform_mac
from platform_mac import accessibility, paths, processes

POLL_SECONDS = 0.7          # the same cadence the Windows watch loop uses

# Roles that hold typed text. The Windows layer asks UI Automation for an
# editable control; macOS names the roles directly.
TEXT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}


def configure_storage():
    """Point the shared engine at the macOS locations."""
    paths.ensure_support_dir()      # the one place that may create it
    p = paths.storage_paths()
    storage.configure(
        log_dir=p["log_dir"],
        settings_path=p["settings_path"],
        history_path=p["history_path"],
        badge_position_path=p["badge_position_path"],
        default_settings={"cat_ai_chat": True, "ai_enabled": True, "theme": "light"},
        history_max_entries=500,
    )
    return p


def diagnose():
    """One shot: say exactly what works and what does not, in plain words."""
    print("Comprsly macOS check\n")

    if not platform_mac.available():
        print("  pyobjc is not installed, so nothing below can work.")
        print("  Fix: pip install -r ../build/requirements-mac.txt")
        return 3
    print("  pyobjc: installed")

    if not accessibility.permission_granted():
        print("  Accessibility permission: NOT granted")
        print("  Comprsly cannot see any text box until this is on. Nothing")
        print("  here is broken; macOS simply returns nothing until you allow")
        print("  it, and there is no way to grant it from code.")
        print("  Fix: System Settings, Privacy and Security, Accessibility,")
        print("  then add whatever is running this (Terminal, or Comprsly.app).")
        return 2
    print("  Accessibility permission: granted")

    front = accessibility.frontmost()
    print("  frontmost app: %s" % (front[2] if front else "could not read it"))

    element = accessibility.focused_element()
    if element is None:
        print("  focused control: none, click into a text box and try again")
    else:
        role = accessibility.element_role(element)
        rect = accessibility.element_rect(element)
        text = accessibility.read_text(element)
        print("  focused control: %s" % role)
        print("  its rectangle: %s" % (rect,))
        print("  text length: %s" % (len(text) if text is not None else "unreadable"))
        if rect and role in TEXT_ROLES:
            badge = _pane_bottom_row(rect[0], rect[2], rect[3], 18)
            print("  the badge would sit at: (%d, %d) to (%d, %d)"
                  % (badge.left, badge.top, badge.right, badge.bottom))

    table = processes.process_table()
    print("  processes visible: %d" % len(table))
    if front:
        cli = processes.ai_cli_under(front[0], table)
        print("  AI CLI under the front app: %s" % (cli or "none"))

    print("\n  Storage: %s" % paths.support_dir())
    return 0


def watch():
    """Print what would be badged, every tick. The loop, without the drawing."""
    configure_storage()
    if not accessibility.permission_granted():
        print("Accessibility permission is off; run with --check for how to fix it.")
        return 2
    print("Watching. Ctrl+C to stop.\n")
    last = None
    try:
        while True:
            element = accessibility.focused_element()
            role = accessibility.element_role(element) if element else None
            if role in TEXT_ROLES:
                rect = accessibility.element_rect(element)
                text = accessibility.read_text(element) or ""
                now = (role, rect, len(text))
                if now != last:
                    print("  %-14s rect=%s  %d characters" % (role, rect, len(text)))
                    last = now
            elif last is not None:
                print("  (left the text box)")
                last = None
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    configure_storage()
    sys.exit(diagnose() if "--check" in sys.argv else watch())
