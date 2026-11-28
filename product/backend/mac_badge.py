"""The floating badge, on macOS. The real one.

Until now nothing on a Mac drew a badge at all. `main_mac.py` printed where
one would go, and the CI smoke run drew a purple circle on a Tk window to
answer the two questions in MACOS_UI.md from a screenshot. That circle was
honest about being a stand in, and it was still the wrong thing to be looking
at: it shared no code with the product, so a screenshot of it could not tell
you anything about the badge users would actually see.

This draws the product's badge. The same PIL artwork Windows draws
(badge_art.py), at the same place the shared geometry puts it
(engine/geometry.py), through the same transparency ladder that was written
for this (platform_mac/window.py). What is new here is only the window: a Tk
toplevel, floated without taking focus.

## Sizes

macOS works in points and Windows in physical pixels, so the numbers cannot
simply be copied. Antonio approved the badge at 58 px on a 144 DPI laptop
panel, which is 58/1.5 = 38.7 points of the same physical size, so the badge
is 38 points here. BADGE_INSIDE_INSET is S(16) on that screen, so 11.

Both are a conversion of a number he approved on a screen he was looking at,
not a number anyone has seen on a Mac. They are the first thing to adjust
when he does.

## What this deliberately does not do

No per-site insets, no terminal pane detection, no review card anchoring.
Those live in main.py's _position_for, which is two hundred lines of special
cases for named websites on Windows, and none of them can be verified here.
The plain rule, bottom right of whatever text box has the caret, is the one
the Accessibility API can actually support today.

shortcut: no click handling beyond a callback, because there is no review
card on macOS to open. Wire on_click when there is one.
"""

import os
import tkinter as tk

import badge_art
from engine.geometry import _pane_bottom_row, dock_right
from platform_mac import window

try:
    from PIL import ImageTk
except Exception:          # pragma: no cover - a build without Pillow
    ImageTk = None

BRAND_DARK = "#0b0b0d"     # the key colour, same shade as main.py's
BRAND_PRIMARY = "#6471db"
BADGE_SIZE = 38            # points, see the module docstring
BADGE_INSET = 11           # points, from the right edge of the text box
BADGE_MIN_SIZE = 13        # below this the mark stops reading as the logo
BADGE_HEAT_MAX = 6         # count at which the heat ring is fully red


def badge_rect(text_box, size=BADGE_SIZE, inset=BADGE_INSET):
    """Where the badge goes for a text box at (left, top, right, bottom).

    The bottom row of the box, docked right, which is the rule Antonio asked
    for by name on 2026-11-25 after the badge was reported three times for
    moving around while he typed. Both halves are the shared engine's, so
    this is the same answer Windows gives for the same rectangle.
    """
    left, _top, right, bottom = text_box
    row = _pane_bottom_row(left, right, bottom, size)
    return dock_right(row, size, inset)


def heat_color(count):
    from engine.geometry import _heat_color
    return _heat_color(count, BADGE_HEAT_MAX)


class MacBadge:
    """The badge window. Built on first show, kept, moved, hidden.

    Rebuilt rather than resized when the size changes, for the same reason
    the Windows one is: the image is baked at one size and the label keeps
    the old one otherwise.
    """

    def __init__(self, root, on_click=None, transparency=None):
        self.root = root
        self.on_click = on_click
        # Forced only by the smoke run, through COMPRSLY_BADGE_TRANSPARENCY,
        # so a real Mac can measure all three rungs of the ladder in one go.
        # None means the ladder picks, which is what the product does.
        self.prefer = transparency or os.environ.get(
            "COMPRSLY_BADGE_TRANSPARENCY") or None
        self.transparency = None   # what the ladder actually managed
        self.floated = None
        self.window = None
        self.placed = None         # where Tk says it ended up, after mapping
        self._photo = None         # must stay referenced, Tk drops GC'd images
        self._label = None
        self._size = None
        self._heat = None

    # ---------------------------------------------------------------- window

    def _build(self, size, rect):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        # Positioned before it is ever mapped, rather than built hidden and
        # revealed. withdraw() followed by deiconify() on an overrideredirect
        # Aqua window is one more thing that could explain a badge that never
        # appeared, and the flash it was there to avoid is one frame in the
        # right place now instead of the wrong one.
        win.geometry("%dx%d+%d+%d" % (size, size, rect.left, rect.top))
        self.transparency = window.make_badge_window_transparent(
            win, BRAND_DARK, prefer=self.prefer)
        bg = window.badge_background(self.transparency, BRAND_DARK)
        win.configure(bg=bg)
        self.floated = window.keep_on_top(win)

        image = badge_art.make_heat_badge_image(size, 0, checked=False)
        if image is not None and ImageTk is not None:
            self._photo = ImageTk.PhotoImage(image)
            label = tk.Label(win, image=self._photo, bg=bg, borderwidth=0,
                             highlightthickness=0, cursor="hand2")
        else:
            # Same fallback as Windows: a text glyph rather than no badge, if
            # Pillow or the asset is ever missing from the bundle.
            label = tk.Label(win, text="C", font=("Helvetica", int(size * 0.5), "bold"),
                             fg=BRAND_PRIMARY, bg=bg, borderwidth=0,
                             highlightthickness=0, cursor="hand2")
        label.pack()
        if self.on_click is not None:
            for widget in (win, label):
                widget.bind("<ButtonRelease-1>", lambda _e: self.on_click())

        # A Toplevel's title is the literal "tk" until something sets it, and
        # it is what the window list shows. Same fix as the Windows badge.
        try:
            win.title("Comprsly")
        except Exception:
            pass

        self.window = win
        self._label = label
        self._size = size
        self._heat = None

    def _destroy(self):
        if self.window is None:
            return
        try:
            self.window.destroy()
        except Exception:
            pass
        self.window = None
        self._label = self._photo = self._size = self._heat = None

    # ------------------------------------------------------------------ use

    def show(self, text_box, count, checked=True, line_h=None):
        """Put the badge on this text box. Builds the window the first time.

        `line_h`, when the platform can measure one, makes the badge the
        height of a terminal row so it fits that row exactly, which is the
        2026-11-26 rule. Nothing on macOS measures one yet, so it is only
        ever passed by a caller that has one.
        """
        size = BADGE_SIZE if line_h is None else max(BADGE_MIN_SIZE,
                                                     min(int(line_h), BADGE_SIZE))
        rect = badge_rect(text_box, size=size)
        if self.window is None or size != self._size:
            self._destroy()
            self._build(size, rect)
        self._update_heat(count, checked)
        self.window.geometry("%dx%d+%d+%d" % (size, size, rect.left, rect.top))
        self.window.deiconify()
        # What Tk believes, as opposed to what is on screen. When the two
        # disagree, which one is wrong is the whole question, so both are
        # reported rather than only the one we can see from in here.
        try:
            self.window.update_idletasks()
            self.placed = "%s mapped=%s viewable=%s" % (
                self.window.winfo_geometry(),
                self.window.winfo_ismapped(),
                self.window.winfo_viewable())
        except Exception as exc:
            self.placed = "could not be read: %s" % exc
        return rect

    def hide(self):
        if self.window is not None:
            self.window.withdraw()

    def _update_heat(self, count, checked):
        """Only regenerate the image when the count or `checked` moved.
        Redrawing a PIL image every poll otherwise would be waste."""
        key = (count, checked)
        if key == self._heat or self._label is None:
            return
        image = badge_art.make_heat_badge_image(self._size, count, checked=checked)
        if image is not None and ImageTk is not None:
            self._photo = ImageTk.PhotoImage(image)
            self._label.config(image=self._photo)
        self._heat = key


def configure_art():
    """Point badge_art at this platform's assets and heat scale. Once, at
    startup, the same call main.py makes with its own two answers."""
    from platform_mac import paths
    badge_art.configure(asset_path=paths.asset_path, heat_color=heat_color)
