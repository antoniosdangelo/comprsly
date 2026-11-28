"""Drive the Mac build on a machine nobody owns, and measure what happened.

Antonio wants to see the Mac app behave before paying to rent a Mac. A GitHub
macos runner is the only Mac available, so this drives the built .app there,
puts a sentence with mistakes into a real TextEdit window, and watches the
product do its job.

    python mac_smoke.py --app <path to Comprsly.app> --out <directory>

What it does, in order:

    1. writes down the machine: macOS version, SIP state, display, user
    2. runs the .app's own --check, which is also the Accessibility answer
    3. opens TextEdit on an empty file and waits for the caret to land
    4. types a sentence with three mistakes in it, through the product's own
       pasteboard and Command+V path, and reads it back to prove it arrived
    5. asks the real rules engine what it makes of that sentence
    6. launches the built .app, which draws the REAL badge on the text box,
       and MEASURES the badge in a screenshot
    7. runs the .app's --fix-once, which corrects the sentence in place, and
       reads the box back to prove the correction really landed
    8. writes smoke-report.txt with a verdict per capability

## Three things this version does differently, each for a reason the last run
## gave us

**No Apple Events.** The previous version drove TextEdit with
`tell application "TextEdit"`, which needs Automation permission. The first
real run hung for thirty seconds on the permission prompt and then left a
"Don't Allow" dialog sitting on top of the screen, in every later screenshot.
Everything here is either a shell command (`open`) or a synthetic event posted
through Quartz, which needs Accessibility, and Accessibility the runner image
already grants.

**It does not trust what the window says about itself.** The first run
reported `transparency: keyed` and the screenshot showed a dark rectangle.
Both were true: the attribute was accepted, and the widget inside the window
was still opaque and drawn straight over it. So the badge is measured now, by
screenshotting its exact rectangle before and after it appears. Corners
unchanged means the square really is invisible; a window that claims "keyed"
while its corners change is a FAILED, not a pass.

**A BLOCKED verdict fails the run.** It used to exit 0, because the
expectation was a page of refused permissions. The runner turned out to grant
both Accessibility and Screen Recording, so every verdict here can genuinely
pass, and anything less is worth stopping for. Pass --allow-blocked on a real
Mac where the human has not ticked the Accessibility box.

## What is NOT covered

**The review card.** macOS does not have one yet: it is SuggestionPopup in
main.py, 1,450 lines wound through Win32 focus restore and per-site window
measurement. `--fix-once` exercises the half of it that does not need a
window, which is why there is a corrected-text screenshot and no card
screenshot. The report says so rather than photographing something that stands
in for it.
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND)

try:
    from PIL import Image, ImageChops, ImageStat
except Exception:          # pragma: no cover - checked below, not assumed
    Image = ImageChops = ImageStat = None

# Three mistakes the rules engine definitely catches: a lowercase "i", a
# repeated word, and a misspelling. Deliberately not a filler phrase, because
# which fillers are worth removing is a judgement that changes, and this
# sentence is here to prove the loop runs rather than to pin the rules.
TYPED_TEXT = ("i think we should basically just go ahead and and update teh "
              "readme file, if that makes sense.")

PASS, BLOCKED, FAILED, UNKNOWN = "PASS", "BLOCKED", "FAILED", "UNKNOWN"

# How different two crops of the same rectangle have to be before the
# difference is the badge rather than the screen's own noise. Mean absolute
# channel difference, 0..255. Antialiasing and PNG rounding sit near zero; a
# badge drawn over the area moves it by tens.
PIXEL_NOISE = 6


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


# ---------------------------------------------------------------- verdicts
# These are the only decisions this script makes, so they are pure functions
# of their inputs and they are unit tested on Windows. Everything else is
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
    """Whether we really got a picture of the screen.

    Screen Recording refused gives a black frame. That used to be judged by
    file size, because the Mac dependencies had no image library; Pillow is in
    them now, since the badge is a PIL image, so the pixels are counted and
    the guess is gone.
    """
    if code == 127:
        return FAILED, "screencapture is not on this machine"
    if code != 0 or not os.path.isfile(path):
        return BLOCKED, "screencapture refused; Screen Recording is not granted"
    if os.path.getsize(path) == 0:
        return BLOCKED, "wrote an empty file"
    if Image is None:
        return UNKNOWN, "%d bytes, and no Pillow here to look inside it" % (
            os.path.getsize(path))
    try:
        with Image.open(path) as img:
            colors = img.convert("RGB").getcolors(maxcolors=64)
    except Exception as exc:
        return FAILED, "the file is not a readable image: %s" % exc
    if colors is not None and len(colors) < 4:
        return BLOCKED, (
            "only %d distinct colours, so this is a flat frame rather than "
            "the screen" % len(colors))
    return PASS, "a real picture of the screen"


def classify_typed(expected, actual):
    """Whether the sentence we sent is the sentence that arrived."""
    if actual is None:
        return FAILED, "the text box could not be read back"
    if actual == expected:
        return PASS, "all %d characters arrived" % len(expected)
    if expected in actual:
        return PASS, "arrived, alongside %d characters already in the box" % (
            len(actual) - len(expected))
    return FAILED, "the box holds %d characters and not the sentence: %r" % (
        len(actual), actual[:80])


def classify_badge(mode, corner_delta, centre_delta, noise=PIXEL_NOISE):
    """Did the badge draw, and are the corners of its square really gone.

    `mode` is what platform_mac/window.py's ladder reported it achieved. It is
    used to tell two different wrongs apart, which is the whole point: falling
    back to `alpha` is a known, documented rung of that ladder and shows a
    faint square, while claiming `keyed` and still painting the corners is the
    bug that shipped the first time and must never read as a pass again.
    """
    if centre_delta <= noise:
        return FAILED, "nothing was drawn there: the badge never appeared"
    if corner_delta <= noise:
        return PASS, ("drawn, and the square around the circle is invisible "
                      "(corners moved %.1f, the mark moved %.1f)"
                      % (corner_delta, centre_delta))
    if mode == "keyed":
        return FAILED, ("the window reported 'keyed' and its corners still "
                        "changed by %.1f, so the square is being drawn"
                        % corner_delta)
    return BLOCKED, ("the transparency ladder fell back to '%s', so the square "
                     "around the badge is visible (corners moved %.1f)"
                     % (mode, corner_delta))


def classify_focus(frontmost_before, frontmost_after):
    """The badge must never take the caret from what you are typing in."""
    if frontmost_after is None:
        return FAILED, "could not read which app is in front"
    if frontmost_after == frontmost_before:
        return PASS, "%s still has focus with the badge on screen" % frontmost_after
    return FAILED, "focus moved from %s to %s when the badge appeared" % (
        frontmost_before, frontmost_after)


def classify_correction(before, after, expected):
    """Whether the corrected sentence is really in the box now."""
    if after is None:
        return FAILED, "the text box could not be read back"
    if after == before:
        return FAILED, "the text is unchanged, so nothing was written back"
    if after == expected:
        return PASS, "the box holds exactly what the rules produced"
    return FAILED, "the box changed but not into the corrected sentence: %r" % (
        after[:80],)


# ---------------------------------------------------------------- measuring

def mean_delta(a, b, box):
    """Mean absolute channel difference between the same patch of two images."""
    pa = a.crop(box).convert("RGB")
    pb = b.crop(box).convert("RGB")
    diff = ImageChops.difference(pa, pb)
    if not diff.width or not diff.height:
        return 0.0
    bands = ImageStat.Stat(diff).mean
    return sum(bands) / float(len(bands))


def badge_deltas(before_png, after_png, rect, scale):
    """How much the badge's corners and its middle changed. (corner, centre).

    The badge is a circle drawn inside a square window. Everything outside the
    circle is meant to be invisible, so the four corners should look exactly
    as the screen did a moment earlier, and the middle should not.
    """
    with Image.open(before_png) as before_img, Image.open(after_png) as after_img:
        before = before_img.convert("RGB")
        after = after_img.convert("RGB")
        left, top = int(rect.left * scale), int(rect.top * scale)
        size = int((rect.right - rect.left) * scale)
        patch = max(2, size // 6)
        corners = [
            (left, top, left + patch, top + patch),
            (left + size - patch, top, left + size, top + patch),
            (left, top + size - patch, left + patch, top + size),
            (left + size - patch, top + size - patch, left + size, top + size),
        ]
        corner = max(mean_delta(before, after, box) for box in corners)
        inset = size // 4
        centre = mean_delta(before, after,
                            (left + inset, top + inset,
                             left + size - inset, top + size - inset))
        return corner, centre


def crop_badge(png, rect, scale, out_path, margin=3):
    """A zoomed cut of the badge for human eyes, saved beside the report."""
    with Image.open(png) as shot:
        cut = shot.crop((int((rect.left - margin) * scale),
                         int((rect.top - margin) * scale),
                         int((rect.right + margin) * scale),
                         int((rect.bottom + margin) * scale)))
        cut = cut.resize((cut.width * 4, cut.height * 4), Image.NEAREST)
        cut.save(out_path)


# ---------------------------------------------------------------- the run

class Report:
    def __init__(self):
        self.lines = []
        self.verdicts = []
        self.missing = []

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

    def not_covered(self, what, why):
        self.missing.append((what, why))
        self.note("  [NOT COVERED] %s: %s" % (what, why))

    def command(self, title, args, timeout=60):
        code, text = run(args, timeout=timeout)
        self.note()
        self.note("$ %s" % " ".join(args))
        for line in (text or "").rstrip().splitlines():
            self.note("    %s" % line)
        return code, text

    def worst(self):
        states = [s for _, s, _ in self.verdicts]
        for bad in (FAILED, BLOCKED, UNKNOWN):
            if bad in states:
                return bad
        return PASS if states else UNKNOWN

    def write(self, path):
        worst = self.worst()
        header = [
            "Comprsly macOS smoke run",
            "",
            "Every verdict below is measured, not taken from the thing being",
            "measured. FAILED means something is wrong with the build. BLOCKED",
            "means macOS refused a permission, which on this runner should not",
            "happen and is worth stopping for.",
            "",
            "Worst verdict in this run: %s" % worst,
            "",
        ]
        for what, state, why in self.verdicts:
            header.append("  %-8s %-36s %s" % (state, what, why))
        if self.missing:
            header.append("")
            header.append("Not covered by this run:")
            for what, why in self.missing:
                header.append("  %-36s %s" % (what, why))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(header + [""] + self.lines) + "\n")
        return worst


def display_width_points():
    """How wide the main display is, in points.

    The Accessibility API reports points and screencapture writes pixels, so
    one has to be converted before a rectangle from the first can be cropped
    out of the second. Dividing the screenshot's own width by this gives the
    scale, which is 2 on a Retina display and 1 everywhere else, without
    hardcoding either.
    """
    try:
        import Quartz
        return float(Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size.width)
    except Exception:
        return None


def wait_for_text_box(accessibility, roles, seconds=20):
    """Poll until the caret is in a text box.

    Returns (element, role, rect, trace). The trace is from the LAST attempt
    and says which route to the focused application answered, or what each
    one said when none did. Without it a failure here is unreadable: the
    screenshot shows TextEdit in front with a caret in it and the script
    says it found nothing, and the gap between those two is the whole bug.
    """
    deadline = time.time() + seconds
    last_role = None
    trace = []
    while time.time() < deadline:
        trace = []
        element = accessibility.focused_element(trace)
        role = accessibility.element_role(element) if element else None
        last_role = role or last_role
        if role in roles:
            rect = accessibility.element_rect(element)
            if rect:
                return element, role, rect, trace
        time.sleep(0.5)
    return None, last_role, None, trace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, help="path to the built Comprsly.app")
    parser.add_argument("--out", default="smoke-out", help="where to write results")
    parser.add_argument("--allow-blocked", action="store_true",
                        help="exit 0 even when macOS refused a permission, for "
                             "a real Mac where it has not been granted")
    args = parser.parse_args()

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    r = Report()
    shots = [0]

    def shot(label):
        """A full screen capture. Returns its path, or None if it was refused."""
        shots[0] += 1
        path = os.path.join(out, "%02d-%s.png" % (shots[0], label))
        code, text = run(["screencapture", "-x", "-t", "png", path], timeout=60)
        state, why = classify_screenshot(code, path)
        r.verdict("screenshot %s" % label, state, why)
        if text.strip():
            r.note("    screencapture said: %s" % text.strip())
        return path if state == PASS else None

    def finish(code):
        path = os.path.join(out, "smoke-report.txt")
        worst = r.write(path)
        print("\nwrote %s (worst verdict: %s)" % (path, worst), flush=True)
        print(run(["ls", "-la", out])[1], flush=True)
        if code is not None:
            return code
        if worst == PASS:
            return 0
        if worst == BLOCKED and args.allow_blocked:
            print("exiting 0: --allow-blocked was passed", flush=True)
            return 0
        return 1

    inner = os.path.join(args.app, "Contents", "MacOS", "Comprsly")

    # ---- 1. the machine
    r.section("1. The machine this ran on")
    r.command("", ["sw_vers"])
    r.command("", ["uname", "-m"])
    r.command("", ["whoami"])
    # SIP decides whether the TCC database can be written at all, which is the
    # single fact that explains every permission result below.
    r.command("", ["csrutil", "status"])
    r.command("", ["system_profiler", "SPDisplaysDataType"], timeout=120)

    if Image is None:
        r.verdict("Pillow is installed", FAILED,
                  "no image library, so nothing below could be measured")
        return finish(1)
    r.verdict("Pillow is installed", PASS, "the badge can be measured")

    if not os.path.isfile(inner):
        r.verdict("the .app exists", FAILED, "no executable at %s" % inner)
        return finish(1)
    r.verdict("the .app exists", PASS, inner)

    # ---- 2. what the app says about this machine
    r.section("2. Comprsly's own --check, from the built bundle")
    r.note()
    r.note("  Running the binary inside the bundle rather than `open`, because")
    r.note("  the bundle is LSUIElement with console=False and `open` throws")
    r.note("  its output away. One consequence worth knowing: launched this")
    r.note("  way the responsible process for permissions is the shell, not")
    r.note("  Comprsly.app, so this says whether the CODE works, not what a")
    r.note("  user sees before they grant anything.")
    code, text = r.command("", [inner, "--check"], timeout=120)
    r.verdict("the built .app can see a text box", *classify_check(code, text))

    import platform_mac
    from platform_mac import accessibility, input as mac_input
    import mac_badge
    import suggestion_engine
    from main_mac import TEXT_ROLES

    if not platform_mac.available():
        r.verdict("pyobjc for this script", FAILED,
                  "the smoke run's own Python cannot reach the Mac APIs")
        return finish(1)

    # ---- 3. a real text box
    r.section("3. A TextEdit window with the caret in it")
    r.note()
    r.note("  `open` goes through Launch Services, not Apple Events, so it")
    r.note("  cannot raise the Automation prompt that hung the last run. An")
    r.note("  empty file is passed so TextEdit opens a document rather than")
    r.note("  its file chooser.")
    scratch = os.path.join(out, "comprsly-smoke.txt")
    with open(scratch, "w", encoding="utf-8") as handle:
        handle.write("")
    code, text = r.command("", ["open", "-a", "TextEdit", scratch], timeout=60)
    r.verdict("TextEdit opens",
              PASS if code == 0 else FAILED,
              "opened %s" % os.path.basename(scratch) if code == 0
              else (text or "").strip()[:200])
    element, role, text_rect, trace = wait_for_text_box(accessibility, TEXT_ROLES)
    r.note()
    r.note("  finding the focused application, on the last attempt:")
    for rung, note in trace:
        r.note("    %-36s %s" % (rung, note))
    if text_rect is None:
        r.verdict("the caret lands in a text box", FAILED,
                  "after 20s the focused control was %s" % role)
        shot("no-text-box")
        return finish(1)
    r.verdict("the caret lands in a text box", PASS,
              "%s at %s" % (role, (text_rect,)))
    shot("textedit-open")

    front = accessibility.frontmost()
    front_before = front[2] if front else None

    # ---- 4. typing, through the product's own input path
    r.section("4. A sentence with three mistakes, typed in")
    r.note()
    r.note("  Sent with platform_mac/input.py: the text goes on the pasteboard")
    r.note("  and Command+A, Command+V are posted as real CGEvents. That is the")
    r.note("  product's own apply path, and it needs Accessibility rather than")
    r.note("  Automation, so nothing here can raise a permission prompt.")
    r.note()
    r.note("  typing: %s" % TYPED_TEXT)
    snapshot = mac_input.snapshot_clipboard()
    try:
        mac_input.set_clipboard_text(TYPED_TEXT)
        sent = mac_input.send_select_all_and_paste()
        time.sleep(1.5)
        arrived = accessibility.read_text(element)
    finally:
        mac_input.restore_clipboard(snapshot)
    if not sent:
        r.verdict("the sentence is typed in", FAILED,
                  "Quartz would not post the keystrokes")
    else:
        r.verdict("the sentence is typed in", *classify_typed(TYPED_TEXT, arrived))
    shot("typed")

    # ---- 5. what the rules make of it
    r.section("5. What the rules engine finds in it")
    found = suggestion_engine.analyze(TYPED_TEXT)["suggestions"]
    corrected = suggestion_engine.apply_suggestions(TYPED_TEXT, found)
    r.note()
    for s in found:
        r.note("    %-28s %r -> %r" % (s["label"], s["original"], s["replacement"]))
    r.note()
    r.note("  corrected: %s" % corrected)
    r.verdict("the rules find the mistakes",
              PASS if found and corrected != TYPED_TEXT else FAILED,
              "%d suggestion(s), and they change the text" % len(found)
              if found and corrected != TYPED_TEXT
              else "%d suggestion(s), text unchanged" % len(found))

    # ---- 6. the real badge
    r.section("6. The real badge, drawn by the built app and then measured")
    # Re-read the box rather than reusing the rectangle from before the text
    # went in: the app computes its own from live Accessibility data when it
    # draws, and measuring a different rectangle than the one it drew into
    # would report a working badge as missing.
    text_rect = accessibility.element_rect(element) or text_rect
    where = mac_badge.badge_rect(text_rect)
    r.note()
    r.note("  The badge belongs at (%d, %d) to (%d, %d): the shared geometry's"
           % (where.left, where.top, where.right, where.bottom))
    r.note("  answer for this text box, the bottom row docked right. That")
    r.note("  rectangle is screenshotted before and after the app draws, so")
    r.note("  what follows is a measurement rather than the window's own")
    r.note("  opinion of itself.")
    points = display_width_points()
    before_png = shot("badge-before")
    watcher = subprocess.Popen(
        [inner, "--seconds", "20"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    mode = None
    said = []
    deadline = time.time() + 30
    while time.time() < deadline:
        line = watcher.stdout.readline()
        if not line:
            break
        said.append(line.rstrip())
        if line.startswith("transparency:"):
            mode = line.split(":", 1)[1].strip()
            break
    time.sleep(2)              # let it paint before the shutter
    after_png = shot("badge-drawn")
    front = accessibility.frontmost()
    r.verdict("the badge did not steal focus",
              *classify_focus(front_before, front[2] if front else None))
    try:
        watcher.wait(timeout=40)
    except subprocess.TimeoutExpired:
        watcher.kill()
    said += [line.rstrip() for line in (watcher.stdout.read() or "").splitlines()]
    r.note()
    r.note("  what the app printed while it ran:")
    for line in said:
        r.note("    %s" % line)

    if before_png is None or after_png is None:
        r.verdict("the real badge draws as a circle", BLOCKED,
                  "no screenshot to measure")
    elif points is None:
        r.verdict("the real badge draws as a circle", UNKNOWN,
                  "could not read the display size, so the crop would be a guess")
    else:
        with Image.open(after_png) as img:
            scale = img.width / points
        r.note()
        r.note("  display is %d points wide and the screenshot is %.0fx that"
               % (points, scale))
        corner, centre = badge_deltas(before_png, after_png, where, scale)
        r.note("  corners moved %.1f, the mark itself moved %.1f (0-255)"
               % (corner, centre))
        r.verdict("the real badge draws as a circle",
                  *classify_badge(mode, corner, centre))
        zoom = os.path.join(out, "badge-zoom.png")
        try:
            crop_badge(after_png, where, scale, zoom)
            r.note("  a 4x cut of it is in %s" % os.path.basename(zoom))
        except Exception as exc:
            r.note("  could not cut the zoom: %s" % exc)

    # ---- 7. the corrected text, written back into the box
    r.section("7. The correction, applied in place")
    r.note()
    r.note("  --fix-once is the review card's Apply button without the card:")
    r.note("  read the focused box, run the rules, write the result back")
    r.note("  through the Accessibility API, falling back to a paste.")
    before_text = accessibility.read_text(element)
    code, text = r.command("", [inner, "--fix-once"], timeout=120)
    time.sleep(1.0)
    after_text = accessibility.read_text(element)
    if code not in (0, 4):
        r.verdict("the correction is applied", FAILED,
                  "--fix-once exited %s" % code)
    else:
        r.verdict("the correction is applied",
                  *classify_correction(before_text, after_text, corrected))
    shot("corrected")

    # ---- what nobody measured
    r.section("8. What this run does not cover")
    r.not_covered("the review card",
                  "macOS has no review card yet; it is SuggestionPopup in "
                  "main.py and porting it is its own piece of work")
    r.not_covered("a second display",
                  "the runner has one, and a display above or left of the "
                  "primary is where the shared geometry is most likely wrong")
    return finish(None)


if __name__ == "__main__":
    sys.exit(main())
