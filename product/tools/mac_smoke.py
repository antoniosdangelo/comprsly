"""Run the Mac build on a machine nobody owns, and report what truly happened.

Antonio wants to see the Mac app behave before paying to rent a Mac. A GitHub
macos runner is the only Mac available, so this drives the built .app there and
writes down what worked, what was blocked by macOS privacy, and what actually
broke. Those three are different things and the whole point of this script is
that it never lets one read as another.

What it does, in order:

    1. writes down the machine: macOS version, SIP state, display, user
    2. reads the Accessibility grant state, without trying to forge one
    3. opens TextEdit with some typed text to be the app under observation
    4. runs the .app's own --check, and the source tree's --check too
    5. draws the badge window, so the circle and the transparency can be seen
    6. puts the caret in TextEdit's text area and runs --check again
    7. screenshots each of those moments
    8. writes smoke-report.txt with a verdict per capability

On granting Accessibility: there is no supported way to do it from code. Apple
provides no API, `tccutil` can only reset permissions and never grant them, and
the only method that works is writing rows into the system TCC database, which
Apple's developer support calls unsupported and which is exactly the hack we
were told not to do. The runner image itself pre-grants Accessibility to bash,
osascript and Terminal, so a process the job starts may inherit it through its
responsible parent. That is the only route tried here: ask, and report the
answer. A refusal is recorded as BLOCKED and never as a pass.

    python mac_smoke.py --app <path to Comprsly.app> --out <directory>

Exit code is 0 when the run completed, whatever the verdicts were, because a
blocked permission is a finding and not a failure of this script. It is 1 only
when the run could not be carried out, for example when the .app is not there.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))

TYPED_TEXT = (
    "Comprsly smoke test. This sentence is deliberately wordy and repetitive "
    "and says the same thing more than once so that there is something here "
    "worth compressing, which is the whole job of the product."
)

# A screenshot of a screen that the capture was not allowed to see comes back
# as a single flat colour, and PNG squeezes a flat image down to almost
# nothing. There is no image library in the Mac requirements and decoding a PNG
# by hand to measure its variance is far more code than this is worth.
# shortcut: size only, so a genuinely blank desktop could read as blocked,
# upgrade to a pixel check if Pillow ever joins requirements-mac.txt.
BLANK_SCREENSHOT_BYTES = 40_000

PASS, BLOCKED, FAILED, UNKNOWN = "PASS", "BLOCKED", "FAILED", "UNKNOWN"


def run(args, timeout=60, stdin_text=None):
    """A subprocess that can never hang the job. Returns (code, output)."""
    try:
        done = subprocess.run(
            args,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "%s is not on this machine" % args[0]
    except subprocess.TimeoutExpired:
        return 124, "timed out after %ss" % timeout
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def osascript(script, timeout=30):
    return run(["osascript", "-e", script], timeout=timeout)


# ---------------------------------------------------------------- verdicts
# These four are the only decisions this script makes, so they are pure
# functions of their inputs and they are unit tested. Everything else is
# plumbing that only a Mac can run.

def classify_check(code, text):
    """What the app's own --check actually told us.

    main_mac.py exits 0 when the Accessibility half works, 2 when macOS is
    withholding permission, 3 when pyobjc is missing, and 1 on anything
    unexpected. The text is consulted as well so a wrapper that loses the exit
    code cannot turn a block into a pass.
    """
    lowered = (text or "").lower()
    if "traceback (most recent call last)" in lowered:
        return FAILED, "the check crashed"
    if code == 3 or "pyobjc is not installed" in lowered:
        return FAILED, "pyobjc missing from the build, so nothing could run"
    if code == 2 or "accessibility permission: not granted" in lowered:
        return BLOCKED, "macOS withheld Accessibility; no text box is visible"
    if code == 124:
        return FAILED, "the check never finished"
    if code == 127:
        return FAILED, "the binary could not be executed"
    if code == 0 and "accessibility permission: granted" in lowered:
        return PASS, "Accessibility works and the check read the screen"
    return FAILED, "unexpected exit code %s" % code


def classify_screenshot(code, path):
    """Whether we really got a picture of the screen."""
    if code == 127:
        return FAILED, "screencapture is not on this machine"
    if code != 0 or not os.path.isfile(path):
        return BLOCKED, "screencapture refused; Screen Recording is not granted"
    size = os.path.getsize(path)
    if size == 0:
        return BLOCKED, "wrote an empty file"
    if size < BLANK_SCREENSHOT_BYTES:
        return BLOCKED, (
            "only %d bytes, which is a flat image, so the capture was almost "
            "certainly a black frame rather than the screen" % size
        )
    return PASS, "%d bytes" % size


def classify_badge(code, text):
    """Whether the badge window appeared, and how transparent it managed."""
    lowered = (text or "").lower()
    if "no display" in lowered or "couldn't connect to display" in lowered:
        return BLOCKED, "no window server session, so no window could be made"
    if "modulenotfounderror" in lowered and "tkinter" in lowered:
        return FAILED, "this Python has no tkinter, so the badge cannot draw"
    if "traceback (most recent call last)" in lowered:
        return FAILED, "drawing the badge raised"
    for mode, meaning in (
        ("transparency: keyed", "the square around the circle is invisible"),
        ("transparency: alpha", "fell back to window alpha; the square is faint"
                                " but present"),
        ("transparency: opaque", "neither worked; the badge shows a dark square"),
    ):
        if mode in lowered:
            return (PASS if "keyed" in mode else BLOCKED), meaning
    if code != 0:
        return FAILED, "exit code %s" % code
    return UNKNOWN, "the badge said nothing about its transparency"


def classify_automation(code, text):
    """Whether we were allowed to drive another app at all."""
    lowered = (text or "").lower()
    if "not authorized" in lowered or "-1743" in lowered or "1743" in lowered:
        return BLOCKED, "macOS withheld Automation, so TextEdit cannot be driven"
    if code == 124:
        return BLOCKED, "the script hung, which is what a silent prompt looks like"
    if code != 0:
        return FAILED, "osascript exit code %s: %s" % (code, (text or "").strip()[:200])
    return PASS, "TextEdit accepted the instruction"


# ---------------------------------------------------------------- the run

class Report:
    def __init__(self):
        self.lines = []
        self.verdicts = []

    def note(self, text=""):
        self.lines.append(text)
        print(text, flush=True)

    def section(self, title):
        self.note()
        self.note("=" * 70)
        self.note(title)
        self.note("=" * 70)

    def verdict(self, what, state, why):
        self.verdicts.append((what, state, why))
        self.note("  [%s] %s: %s" % (state, what, why))

    def command(self, title, args, timeout=60):
        code, text = run(args, timeout=timeout)
        self.note()
        self.note("$ %s" % " ".join(args))
        for line in (text or "").rstrip().splitlines():
            self.note("    %s" % line)
        return code, text

    def write(self, path):
        worst = FAILED if any(s == FAILED for _, s, _ in self.verdicts) else (
            BLOCKED if any(s == BLOCKED for _, s, _ in self.verdicts) else PASS)
        header = [
            "Comprsly macOS smoke run",
            "",
            "Read the verdicts, not the exit code. BLOCKED means macOS refused a",
            "permission that only a human sitting at the Mac can give, which is",
            "the expected answer on a CI runner and is NOT a defect in the app.",
            "FAILED means something is genuinely wrong with the build.",
            "",
            "Worst verdict in this run: %s" % worst,
            "",
        ]
        for what, state, why in self.verdicts:
            header.append("  %-8s %-34s %s" % (state, what, why))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(header + [""] + self.lines) + "\n")
        return worst


def badge_window(seconds):
    """Draw the badge and hold it, so a screenshot can catch it.

    Nothing on macOS draws the badge yet: main_mac.py prints where it would go
    and the real badge lives in main.py, which imports ctypes.wintypes and
    cannot be imported here at all. So this is not the product's badge. It is
    the product's badge geometry and the product's transparency helper, drawn
    on a real window, which is what makes the two open questions in
    MACOS_UI.md answerable from a screenshot: is it a circle or a square, and
    does it float without stealing focus.
    """
    sys.path.insert(0, BACKEND)
    import tkinter
    from platform_mac import window

    BRAND_DARK = "#0d0d0f"
    SIZE = 17            # the terminal line height the Windows badge matches

    root = tkinter.Tk()
    root.overrideredirect(True)
    root.geometry("%dx%d+%d+%d" % (SIZE, SIZE, 420, 360))
    mode = window.make_badge_window_transparent(root, BRAND_DARK)
    floated = window.keep_on_top(root)
    canvas = tkinter.Canvas(root, width=SIZE, height=SIZE,
                            highlightthickness=0, bg=BRAND_DARK)
    canvas.pack()
    canvas.create_oval(1, 1, SIZE - 1, SIZE - 1, fill="#7c5cff", outline="")

    print("transparency: %s" % mode, flush=True)
    print("kept on top: %s" % floated, flush=True)
    root.update()
    root.after(int(seconds * 1000), root.destroy)
    root.mainloop()
    print("badge window closed cleanly", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", help="path to the built Comprsly.app")
    parser.add_argument("--out", default="smoke-out", help="where to write results")
    parser.add_argument("--badge-window", type=float, default=None,
                        help="internal: draw the badge for N seconds and exit")
    args = parser.parse_args()

    if args.badge_window is not None:
        return badge_window(args.badge_window)

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    shots = 0
    r = Report()

    def shot(label):
        nonlocal shots
        shots += 1
        path = os.path.join(out, "%02d-%s.png" % (shots, label))
        code, text = run(["screencapture", "-x", "-t", "png", path], timeout=60)
        state, why = classify_screenshot(code, path)
        r.verdict("screenshot %s" % label, state, why)
        if text.strip():
            r.note("    screencapture said: %s" % text.strip())

    # ---- 1. the machine
    r.section("1. The machine this ran on")
    r.command("", ["sw_vers"])
    r.command("", ["uname", "-m"])
    r.command("", ["whoami"])
    # SIP decides whether the TCC database can be written at all, which is the
    # single fact that explains every permission result below.
    r.command("", ["csrutil", "status"])
    r.command("", ["system_profiler", "SPDisplaysDataType"], timeout=120)

    # ---- 2. the Accessibility grant, read and not forged
    r.section("2. Accessibility permission")
    r.note()
    r.note("  Not attempting to grant this. There is no API for it, tccutil can")
    r.note("  only reset permissions, and the only thing that works is writing")
    r.note("  rows into the system TCC database, which Apple calls unsupported.")
    r.note("  The runner image pre-grants bash and osascript, so a child of the")
    r.note("  job's shell may inherit the grant. Reading the state below.")
    code, text = run(
        ["sqlite3", "-cmd", ".timeout 5000",
         "/Library/Application Support/com.apple.TCC/TCC.db",
         "select client, auth_value from access where service="
         "'kTCCServiceAccessibility';"],
        timeout=30,
    )
    r.note()
    r.note("  system TCC rows for Accessibility (exit %s):" % code)
    for line in (text or "").rstrip().splitlines() or ["    (nothing returned)"]:
        r.note("    %s" % line)
    if code != 0:
        r.note("  Could not read the database. That is normal: it needs Full Disk")
        r.note("  Access. It does not tell us the grant is missing, only that we")
        r.note("  cannot see it from here. The --check runs below are what count.")

    # ---- 3. something to watch
    r.section("3. TextEdit, with text typed into it")
    code, text = osascript(
        'tell application "TextEdit"\n'
        '  activate\n'
        '  make new document\n'
        '  set text of document 1 to "%s"\n'
        'end tell' % TYPED_TEXT
    )
    state, why = classify_automation(code, text)
    r.verdict("drive TextEdit", state, why)
    if text.strip():
        r.note("    osascript said: %s" % text.strip())
    time.sleep(2)
    shot("app-started")

    # ---- 4. the app's own diagnosis
    r.section("4. Comprsly's own --check")
    if args.app:
        inner = os.path.join(args.app, "Contents", "MacOS", "Comprsly")
        if not os.path.isfile(inner):
            r.verdict("the .app exists", FAILED, "no executable at %s" % inner)
            r.write(os.path.join(out, "smoke-report.txt"))
            return 1
        r.verdict("the .app exists", PASS, inner)
        r.note()
        r.note("  Running the binary inside the bundle rather than `open`, because")
        r.note("  the bundle is LSUIElement with console=False and `open` throws")
        r.note("  its output away. One consequence worth knowing: launched this")
        r.note("  way the responsible process for permissions is the shell, not")
        r.note("  Comprsly.app, so this says whether the CODE works, not what a")
        r.note("  user sees before they grant anything.")
        code, text = r.command("", [inner, "--check"], timeout=120)
        state, why = classify_check(code, text)
        r.verdict("the built .app can see a text box", state, why)
    else:
        r.verdict("the built .app can see a text box", UNKNOWN, "no --app given")

    r.note()
    r.note("  The same check from the source tree, for comparison.")
    code, text = r.command("", [sys.executable, "main_mac.py", "--check"], timeout=120)
    # main_mac.py resolves its imports relative to itself, so it has to run
    # from its own directory.
    if code == 127 or "No such file" in (text or ""):
        code, text = run([sys.executable, os.path.join(BACKEND, "main_mac.py"),
                          "--check"], timeout=120)
        for line in (text or "").rstrip().splitlines():
            r.note("    %s" % line)
    state, why = classify_check(code, text)
    r.verdict("the source tree can see a text box", state, why)

    # ---- 5. the badge
    r.section("5. The badge window")
    r.note()
    r.note("  This is not the product's badge: nothing on macOS draws that yet.")
    r.note("  It is the real transparency helper and the real size, on a real")
    r.note("  window, which is what makes the screenshot worth looking at.")
    badge = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--badge-window", "6"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(3)
    shot("badge-drawn")
    try:
        said = badge.communicate(timeout=30)[0]
    except subprocess.TimeoutExpired:
        badge.kill()
        said = badge.communicate()[0]
    for line in (said or "").rstrip().splitlines():
        r.note("    %s" % line)
    state, why = classify_badge(badge.returncode, said)
    r.verdict("the badge draws as a circle", state, why)

    # ---- 6. the caret in a text box, which is the real question
    r.section("6. The caret inside TextEdit's text area")
    code, text = osascript(
        'tell application "TextEdit" to activate\n'
        'delay 1\n'
        'tell application "System Events" to tell process "TextEdit"\n'
        '  set frontmost to true\n'
        '  keystroke " and one more clause typed by the smoke test."\n'
        'end tell'
    )
    state, why = classify_automation(code, text)
    r.verdict("type into TextEdit", state, why)
    if text.strip():
        r.note("    osascript said: %s" % text.strip())
    time.sleep(1)
    shot("focus-in-textedit")

    r.note()
    r.note("  And the check once more, now that a text box genuinely has focus.")
    r.note("  If Accessibility is working at all, this is where it reports an")
    r.note("  AXTextArea and the rectangle the badge would sit in.")
    code, text = r.command("", [sys.executable, os.path.join(BACKEND, "main_mac.py"),
                                "--check"], timeout=120)
    state, why = classify_check(code, text)
    r.verdict("a focused text box is readable", state, why)

    # ---- done
    report_path = os.path.join(out, "smoke-report.txt")
    worst = r.write(report_path)
    print("\nwrote %s (worst verdict: %s)" % (report_path, worst), flush=True)
    print("screenshots in %s" % out, flush=True)
    if shutil.which("ls"):
        print(run(["ls", "-la", out])[1], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
