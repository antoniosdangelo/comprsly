"""The macOS entry point.

It configures the shared engine with macOS paths, confirms Accessibility
permission, watches for the focused text box, and **draws the real badge on
it**. The badge is the product's own: the same PIL artwork Windows draws, at
the place the shared geometry puts it, through the transparency ladder in
platform_mac/window.py. See mac_badge.py.

    python main_mac.py                watch, and draw the badge
    python main_mac.py --seconds 20   the same, then stop (for CI)
    python main_mac.py --check        print a one shot diagnosis and exit
    python main_mac.py --fix-once     correct the focused text box and exit

What is still NOT here is the review card: the panel that lists what would be
changed and lets you accept it. That is SuggestionPopup in main.py, 1,450
lines wound through Win32 focus restore and per-site window measurement, and
porting it is its own piece of work. `--fix-once` is the half of it that does
not need a window: read the box, run the rules, write the result back. It is
what the card's Apply button will call when the card lands, and it is also the
only way to watch the end to end loop work on a Mac today.

The exit code of --check says which of three different things happened, so
that a machine reading it cannot mistake one for another:

    0   the Accessibility half works
    2   macOS is withholding permission, which only a human at the Mac can give
    3   pyobjc is not installed, so the build itself is wrong
    1   something unexpected

--fix-once uses 0 for "the text was corrected" and 4 for "there was nothing
to correct", plus the same 2 and 3 above.
"""

import argparse
import sys
import time

import engine.storage as storage
import platform_mac
import suggestion_engine
from platform_mac import accessibility, input, paths, processes

POLL_SECONDS = 0.7          # the same cadence the Windows watch loop uses
MIN_TEXT_LENGTH_TO_ANALYZE = 20   # main.py's value, same threshold

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


def suggestion_count(text):
    """How many fixes the rules found, and whether there was enough to judge.

    Below MIN_TEXT_LENGTH_TO_ANALYZE there is nothing to say yet, which is a
    different state from "checked, and it is clean" and draws a different
    badge. Same distinction main.py makes, same threshold.
    """
    if len(text.strip()) < MIN_TEXT_LENGTH_TO_ANALYZE:
        return 0, False
    return len(suggestion_engine.analyze(text)["suggestions"]), True


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

    # The trace, printed whether it worked or not. Two CI rounds were spent
    # guessing which call was refusing and why; this is cheaper than a third.
    trace = []
    _pid, how = accessibility.focused_pid(trace)
    print("  finding the focused application:")
    for rung, note in trace:
        print("    %-36s %s" % (rung, note))
    print("  answered by: %s" % (how or "nothing, every route refused"))
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
            import mac_badge
            badge = mac_badge.badge_rect(rect)
            print("  the badge would sit at: (%d, %d) to (%d, %d)"
                  % (badge.left, badge.top, badge.right, badge.bottom))
            count, checked = suggestion_count(text or "")
            print("  the rules found: %d suggestion(s)%s"
                  % (count, "" if checked else ", too little text to judge yet"))

    table = processes.process_table()
    print("  processes visible: %d" % len(table))
    if front:
        cli = processes.ai_cli_under(front[0], table)
        print("  AI CLI under the front app: %s" % (cli or "none"))

    print("\n  Storage: %s" % paths.support_dir())
    return 0


def apply_to_focused():
    """Read the focused text box, run the rules, write the result back.

    The apply half of the review card, without the card. Two routes, the same
    two the Windows layer uses and in the same order: set the Accessibility
    value directly, and when the application refuses that, put the text on the
    pasteboard and send Command+A, Command+V.

    The user's own clipboard goes back either way. The short wait before
    restoring is not politeness: CGEventPost returns before the target app has
    read the pasteboard, and restoring straight away pastes the old contents.
    """
    element = accessibility.focused_element()
    role = accessibility.element_role(element) if element else None
    if role not in TEXT_ROLES:
        print("No text box has the caret. Click into one and try again.")
        return 4
    text = accessibility.read_text(element)
    if not text:
        print("The focused %s has no readable text." % role)
        return 4

    found = suggestion_engine.analyze(text)["suggestions"]
    fixed = suggestion_engine.apply_suggestions(text, found) if found else text
    if fixed == text:
        print("Nothing to correct in %d characters." % len(text))
        return 4

    print("  before: %s" % text)
    print("  after:  %s" % fixed)
    print("  %d suggestion(s): %s"
          % (len(found), ", ".join(sorted({s["label"] for s in found}))))

    if accessibility.write_text(element, fixed):
        print("  written back through the Accessibility API")
        return 0

    print("  the app refused a direct write, pasting instead")
    snapshot = input.snapshot_clipboard()
    try:
        if not input.set_clipboard_text(fixed):
            print("  could not put the text on the pasteboard")
            return 1
        if not input.send_select_all_and_paste():
            print("  could not send Command+A, Command+V")
            return 1
        time.sleep(0.4)
    finally:
        input.restore_clipboard(snapshot)
    print("  pasted")
    return 0


def watch(seconds=None):
    """Watch the focused text box, and draw the badge on it.

    Tk drives the clock rather than a sleep loop, because the badge is a Tk
    window and it has to keep drawing while we wait. Same 0.7s cadence.
    """
    if not accessibility.permission_granted():
        print("Accessibility permission is off; run with --check for how to fix it.")
        return 2

    import tkinter as tk
    import mac_badge

    mac_badge.configure_art()
    root = tk.Tk()
    root.withdraw()                      # the app has no window of its own
    badge = mac_badge.MacBadge(root)
    last = [None]
    announced = [False]
    stopping = [False]

    def tick():
        if stopping[0]:
            return
        element = accessibility.focused_element()
        role = accessibility.element_role(element) if element else None
        rect = accessibility.element_rect(element) if role in TEXT_ROLES else None
        if rect:
            text = accessibility.read_text(element) or ""
            count, checked = suggestion_count(text)
            where = badge.show(rect, count, checked)
            if not announced[0]:
                # Printed the moment the window really exists, so a CI log
                # says what the ladder managed rather than what it tried.
                print("transparency: %s" % badge.transparency, flush=True)
                print("kept on top: %s" % badge.floated, flush=True)
                announced[0] = True
            now = (role, rect, len(text), count, checked)
            if now != last[0]:
                print("  %-14s rect=%s  %d characters  %d suggestion(s)  "
                      "badge at (%d, %d) %dx%d"
                      % (role, rect, len(text), count, where.left, where.top,
                         where.right - where.left, where.bottom - where.top),
                      flush=True)
                last[0] = now
        else:
            badge.hide()
            if last[0] is not None:
                print("  (left the text box)", flush=True)
                last[0] = None
        root.after(int(POLL_SECONDS * 1000), tick)

    def stop():
        """Stop ticking BEFORE tearing the window down. A poll that fires
        into a half destroyed Tk interpreter raises, and a traceback at the
        end of a CI run reads as a failure however clean the run was."""
        stopping[0] = True
        root.destroy()

    print("Watching. Ctrl+C to stop.\n", flush=True)
    root.after(0, tick)
    if seconds:
        root.after(int(seconds * 1000), stop)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Comprsly for macOS")
    parser.add_argument("--check", action="store_true",
                        help="print a one shot diagnosis and exit")
    parser.add_argument("--fix-once", action="store_true",
                        help="correct the focused text box and exit")
    parser.add_argument("--seconds", type=float, default=None,
                        help="watch for this long, then stop")
    args = parser.parse_args(argv)

    configure_storage()
    if args.check:
        return diagnose()
    if args.fix_once:
        if not platform_mac.available():
            print("pyobjc is not installed.")
            return 3
        if not accessibility.permission_granted():
            print("Accessibility permission is off; run with --check for how "
                  "to fix it.")
            return 2
        return apply_to_focused()
    return watch(args.seconds)


if __name__ == "__main__":
    sys.exit(main())
