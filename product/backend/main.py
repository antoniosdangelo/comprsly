"""Comprsly -- native Windows desktop watcher (v1 proof of concept).

Uses Windows UI Automation (via the `uiautomation` package) to watch the
currently focused text field system-wide, native apps and browsers alike,
and shows the same suggestion card design as the browser extension, just
rendered as a native popup instead of injected HTML.

Real product pivot 2026-07-20: rules-first, AI-second. The local LLM
(local_model.py) was the whole rewrite mechanism until this pivot; it's now
only a fallback for text the fast, local, zero-network suggestion_engine.py
rules can't confidently improve on their own, since running a multi-second,
multi-GB local model for every single click was never actually necessary
for the common case (a rule-findable filler phrase or redundant sentence),
and doing that by default is what caused the memory-pressure lag earlier
this session. Token efficiency stays the first-order goal; grammar/clarity
improvement rides along as a secondary benefit of whichever mechanism runs.

This is a real, running proof of concept, not a mockup, but it's a v1:
- Polling-based (checks the focused control every 700ms), not a true
  event-driven hook yet. Event-driven focus/text-change handlers are a real
  next step (uiautomation supports AddAutomationEventHandler) once this
  polling version is confirmed to reliably catch the fields that matter.
- Tkinter for the popup UI (built into Python, zero extra install), a
  packaged version would likely move to a lighter native toolkit, this is
  about proving the detection + suggestion loop works end to end first.
"""

import colorsys
import json
import math
import os
import re
import sys
import subprocess
import time
import threading
import traceback
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import font as tkfont

# uiautomation loads a native DLL (UIAutomationClient_VC140_*.dll) that needs
# the Visual C++ 2015+ Redistributable. On this dev machine that's always
# present; on a friend's fresh Windows PC it may not be, and then this import
# throws AT STARTUP. Because the app is built --noconsole, an unhandled import
# crash here is completely silent: no window, no error, the app just never
# appears (real report 2026-07-22: "the UI doesn't pop up on their end").
# Catching it lets main() show a real message and log the reason instead of
# vanishing. auto/PatternId are only ever used at call time inside functions,
# so setting them to None here doesn't break module load; main() bails early
# with a clear message when the import failed.
try:
    import uiautomation as auto
    from uiautomation import PatternId
    _UIA_IMPORT_ERROR = None
except Exception as _uia_e:  # pragma: no cover - only trips on a broken host
    auto = None
    PatternId = None
    _UIA_IMPORT_ERROR = str(_uia_e)

import local_model
import suggestion_engine
from suggestion_engine import estimate_tokens

URL_LIKE_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

# Real bug found from Antonio's debug.log 2026-07-21: an EMPTY chat box still
# reports text through UI Automation, because the placeholder is part of the
# accessible tree. Comprsly read Claude's "Type / for commands", analysed it
# (no grammar issues, correctly), and then handed it to the AI, which
# faithfully compressed a placeholder from 4 tokens to 5. From the outside
# that looks exactly like "the grammar found nothing and the AI did nothing."
#
# There is no reliable accessibility flag for "this is placeholder text", so
# this is a known-strings list. Exact match only, after stripping, so it can
# never eat something a user actually typed beyond these literal phrases.
PLACEHOLDER_TEXTS = {
    "type / for commands",
    "how can i help you today?",
    "how can i help you today",
    "message chatgpt",
    "message claude",
    "ask anything",
    "ask gemini",
    "reply to claude...",
    "reply to claude…",
    "send a message",
    "write or paste text here",
    "start typing...",
    "start typing…",
    "enter a prompt here",
}


def is_placeholder_text(text):
    return (text or "").strip().lower() in PLACEHOLDER_TEXTS

try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None
    ImageTk = None

# Real ask 2026-07-20: rebrand from Token Saver to Comprsly, real logo
# supplied directly (cropped from the source PNG into assets/icon.png). The
# installed-app folder path below deliberately stays "Token Saver", not
# "Comprsly", real tradeoff: renaming it would mean moving the already-
# downloaded 2.7GB model directory and updating the installer, for zero
# user-visible benefit since nobody sees this path day to day, only what's
# on screen. Every user-visible string (tray tooltip, MessageBox, popup
# text, badge) is Comprsly branded below.
BRAND_NAME = "Comprsly"
BRAND_PRIMARY = "#6471db"  # sampled directly from the supplied logo's gradient
BRAND_DARK = "#0b0b0d"     # matches the logo's own icon-card background
# Real ask 2026-07-20: bigger badge, and a green->red "heat ring" around
# the logo instead of a number, the more the prompt could be compacted /
# grammar-fixed, the redder the ring, starting green when it's clean.
# --- Universal sizing -------------------------------------------------
# Real ask 2026-07-21: "make sure it works for any screen size, keeping it
# the size it is now on my screen, make that size universal, don't let it get
# bigger than what it is."
#
# Every dimension in this file is in PHYSICAL pixels, and the process is
# per-monitor DPI aware, so nothing scaled at all. On Antonio's 144 DPI
# laptop the card is 560px, about 3.9 inches wide. Run the same build on an
# ordinary 96 DPI 1080p screen and those same 560 pixels are 5.8 inches: the
# UI would appear roughly 50% larger, which is exactly what he doesn't want.
#
# So sizes scale by the monitor's DPI relative to HIS, which makes 144 the
# reference and means the app looks identical on his machine before and
# after this change, and the same physical size everywhere else.
REFERENCE_DPI = 144.0

# MUST run before _monitor_dpi() below, and before any window exists.
#
# Two separate reasons, and the second one cost a real bug:
#  1. Without it Windows DPI-virtualizes the whole process. uiautomation's
#     BoundingRectangle reports real physical pixels while an unmanifested
#     Tk window positions itself in a virtualized coordinate space, so the
#     badge was created successfully and placed off-screen every time
#     (2026-07-20, this is why nothing ever appeared).
#  2. GetDpiForMonitor reports 96 to a DPI-UNAWARE process, whatever the
#     monitor really is. This call used to sit ~400 lines below UI_SCALE, so
#     the scale was computed while still unaware and collapsed to 96/144 =
#     0.67, shrinking the whole UI by a third. Worse, it was
#     non-deterministic: the same binary logged "UI scale 1.00 (monitor 144
#     dpi)" on one launch and "UI scale 0.67 (monitor 96 dpi)" on the next,
#     which is exactly the kind of bug that wastes an afternoon. Antonio
#     reported it as "the UI is too small now, earlier was good."
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _monitor_dpi():
    try:
        MONITOR_DEFAULTTOPRIMARY = 1
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, ctypes.c_ulong]
        hmon = user32.MonitorFromPoint(wintypes.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
        # MDT_EFFECTIVE_DPI = 0
        ctypes.windll.shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return float(dpi_x.value) or REFERENCE_DPI
    except Exception:
        return REFERENCE_DPI


# Design sizes, as approved on the 144 DPI laptop panel.
DESIGN_POPUP_WIDTH = 560
DESIGN_BADGE_SIZE = 58

# Floor for _clamp_popup_width_to_host below -- never shrink the card
# narrower than this even in a tiny host window, past this point text
# wrapping degrades badly. Real bug caught by reading the actual debug.log
# after deploying, not by re-deriving the math on paper: an earlier value
# of 320 here was ABOVE the confirmed real target (~283px, for the exact
# 912px ChatGPT window Antonio measured against), so the floor silently
# won and the card never actually reached the size he'd confirmed -- the
# log showed "560px -> 320px" where "-> ~283px" was expected. Set below
# that confirmed target so it only bites for windows narrower than this
# session actually tested. Not related to the per-DPI card sizing this
# file's history warns against (see scale_for_dpi's "ship one size" essay
# just below): that essay is about NEVER varying card width by monitor/DPI,
# which still holds -- DESIGN_POPUP_WIDTH itself never changes. This is a
# separate axis: capping width against a specific host WINDOW that's
# narrower than the design width, regardless of which monitor/DPI it's on.
MIN_POPUP_WIDTH = 260

# A STEP FUNCTION, not a curve. Two outcomes only:
#
#     dpi >= 120  ->  1.00   laptop panel and any high-DPI screen
#                            card 560px, text 15px. Antonio: "the laptop
#                            sizing and font sizing is perfect."
#     dpi <  120  ->  0.61   the 1920x1080 96 DPI monitor
#                            card 343px, text 9px, the value he picked
#                            himself after two rounds of tuning.
#
# Why a step and not the interpolated curve this used to be: the laptop must
# be UNTOUCHABLE. With a curve, every adjustment to the monitor end changed
# the slope, and any slightly-off DPI reading moved the laptop too. That is
# what went wrong, repeatedly. A step function cannot do that: the laptop
# sits far from the 120 boundary, so nothing short of changing its Windows
# scaling can give it anything but 1.00.
#
# One fixed size for both screens was tried in between and was also wrong, in
# the opposite direction. Identical PIXELS are not identical SIZE: the
# monitor's pixels are physically much larger, so 560px there rendered
# noticeably bigger than the same 560px on the laptop. "It completely
# enlarges on the monitor." Matching how it LOOKS means different pixel
# counts per screen; there is no single number that satisfies both.
# REVERTED 2026-07-21. Per-screen sizing is off again, on Antonio's call.
# The UI is ONE size everywhere: the laptop's, card 560px, text 15px.
#
# Every attempt at making this screen-dependent has been rejected, and the
# list is worth keeping because each one looked reasonable going in:
#   1. dpi / 144            constant physical size   -> monitor too small
#   2. max(1.0, ...)        design size as a floor   -> monitor too large
#   3. curve through two measured screens            -> kept dragging the
#                                                       laptop off 1.00
#   4. retuning that curve twice (0.80, 0.72, 0.61)  -> same problem
#   5. step function at 120 dpi                      -> rejected on sight
#
# Do not try a sixth. Ship one size.
def scale_for_dpi(dpi):
    return 1.0


UI_SCALE = 1.0


def S(px):
    """Scale a design pixel value for this monitor. Design values are
    written as they appear on the 144 DPI reference screen."""
    return max(1, int(round(px * UI_SCALE)))


# Real ask 2026-07-25 (Antonio, direct, reopening the settled question
# above -- but scoped narrower this time): "the sizing for the laptop is
# amazing already, don't touch it... the badges are huge on any monitor
# that isn't a laptop, make them smaller." Everything scale_for_dpi's own
# history warns against (a curve, retuning, DPI misreads dragging the
# laptop off 1.00) was about moving the FULL UI together -- card width AND
# font size. This is scoped to the badge alone: UI_SCALE, POPUP_WIDTH, and
# every font stay exactly 1.00/560px/ship-one-size, completely untouched.
# Reuses the same dpi>=120 boundary scale_for_dpi's own comment already
# vouches for as laptop-safe ("sits far from the boundary, nothing short
# of changing Windows scaling moves it") -- Windows doesn't expose a
# monitor's true physical size reliably, DPI is the same signal this file
# already trusts for exactly this laptop/monitor distinction, just applied
# to one element instead of the whole UI. 0.65 approximates matching the
# badge's PHYSICAL size across screens (this laptop panel measures 144
# DPI, so 144/96 of a typical external 1080p monitor's 96 DPI is ~1.5x;
# 1/1.5 = ~0.65) -- a starting point, not yet tuned live the way the old
# card ratio (0.61) went through two rounds of Antonio's own adjustment.
BADGE_MONITOR_SCALE = 0.65


def badge_scale_for_dpi(dpi):
    return 1.0 if dpi >= 120 else BADGE_MONITOR_SCALE


# Fonts are specified in POINTS. Tk's default conversion follows the native
# Windows convention, where 9pt Segoe UI is the standard UI size and lands at
# 12px. That is correct for a native app and visibly WRONG here, because this
# card floats on top of Claude and ChatGPT, whose web UIs set body text
# around 16px. Antonio put the two side by side: "look at the Claude text and
# see ours, notice how ours is smaller, make it relative size."
#
# So type is scaled up to sit in the same range as the app underneath rather
# than the Windows shell. Applied through `tk scaling` in main(), which moves
# every font in the app at once and keeps their relative hierarchy intact.
#
# TWO INDEPENDENT profiles, not one shared constant (real ask 2026-07-26,
# Antonio, direct: "changing one size affects the other... we never want to
# have that intertwined... one at a time"). Before this, there was exactly
# one FONT_SCALE used everywhere, so tuning it for either screen necessarily
# moved the other -- there was nothing else it COULD do. Same fix shape as
# BADGE_MONITOR_SCALE above (one value per category, selected by the same
# dpi>=120 boundary that already reliably tells this laptop panel from the
# external monitor on this exact hardware): Windows' own physical-size
# reporting (EDID via GetDeviceCaps/WMI) is notoriously unreliable across
# arbitrary monitors, so DPI is the practical proxy for "is this a large
# external monitor (Antonio's own >18in cutoff) or a laptop panel (<=17in)",
# not a literal inch measurement. Both start at the identical current value
# so today's look is completely unchanged; each can now be retuned on its
# own without the other ever moving as a side effect.
FONT_SCALE_LAPTOP = 1.28
FONT_SCALE_MONITOR = 1.28


def font_scale_for_dpi(dpi):
    return FONT_SCALE_LAPTOP if dpi >= 120 else FONT_SCALE_MONITOR

# Initial value uses the PRIMARY monitor's DPI directly (no window exists
# yet at module load to ask apply_scale_for_window's usual way) -- correct
# for a single-monitor start, and re-derived properly for whichever real
# monitor the app ends up on once apply_scale_for_window starts running
# per foreground-window tick (see watch_loop).
BADGE_ICON_SIZE = max(1, int(round(DESIGN_BADGE_SIZE * badge_scale_for_dpi(_monitor_dpi()))))
_active_dpi = [None]
_scale_listeners = []


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", ctypes.c_ulong)]


def _monitor_from_point(x, y):
    MONITOR_DEFAULTTONEAREST = 2
    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, ctypes.c_ulong]
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    return user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                   MONITOR_DEFAULTTONEAREST)


def _dpi_of_monitor(hmon):
    try:
        dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(
            ctypes.c_void_p(hmon), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        return float(dpi_x.value) or REFERENCE_DPI
    except Exception:
        return REFERENCE_DPI


def monitor_work_area(x, y):
    """Usable rectangle (excludes the taskbar) of the monitor at this point."""
    try:
        hmon = _monitor_from_point(x, y)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                                         ctypes.POINTER(_MONITORINFO)]
        if not ctypes.windll.user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(info)):
            return None
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def _rects_overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def place_card(x, y, width, height, badge_rect):
    """Final position for the review card: on one monitor, on screen, and
    never on top of the badge.

    Real bug Antonio screenshotted 2026-07-21: with the badge low on the
    screen the card is anchored below it, runs past the bottom edge, and
    fit_on_one_monitor drags it back up THROUGH the badge. The clamp was
    right, the anchor was wrong for that case. When there isn't room below,
    the card flips above the badge, the way any well-behaved menu does.
    """
    area = monitor_work_area(x + width // 2, y + height // 2)
    if area is not None and badge_rect is not None:
        left, top, right, bottom = area
        bx, by, bw, bh = badge_rect
        if y + height > bottom:
            above = by - height - 10
            if above >= top:
                y = above

    x, y = fit_on_one_monitor(x, y, width, height)

    # Last resort: if it still lands on the badge (a very tall card on a
    # short screen, where neither above nor below fits), move it beside.
    if badge_rect is not None and _rects_overlap((x, y, width, height), badge_rect):
        bx, by, bw, bh = badge_rect
        if area is not None:
            left, top, right, bottom = area
            beside = bx + bw + 10
            if beside + width <= right:
                x = beside
            else:
                x = max(left, bx - width - 10)
            x, y = fit_on_one_monitor(x, y, width, height)
    return x, y


def _host_window_rect(x, y):
    """The on-screen rect of the TOP-LEVEL window at this point, or None.

    Real bug found live 2026-07-25 (screenshot: the card floating dead
    center, straddling two snapped windows side by side): the badge and
    card only ever clamped to the MONITOR's full work area, never to the
    actual bounds of the app window they're meant to sit inside. In a
    half-and-half snapped layout the monitor is much wider than either
    window, so a card anchored near the badge in a half-width browser
    window still had "room" by the monitor's math and spilled straight
    across the seam into a completely different app's window."""
    try:
        user32 = ctypes.windll.user32
        GA_ROOT = 2
        hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not hwnd:
            return None
        root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        rect = wintypes.RECT()
        if not user32.GetWindowRect(root, ctypes.byref(rect)):
            return None
        return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        return None


def fit_within_window_and_monitor(x, y, width, height, anchor_x, anchor_y):
    """Like fit_on_one_monitor, but ALSO never lets the rect extend past the
    actual application window hosting (anchor_x, anchor_y) -- see
    _host_window_rect above for why the monitor alone isn't enough in a
    snapped/split-screen layout. Falls back to the monitor-only clamp if the
    window rect can't be determined, same fallback discipline as everywhere
    else in this file."""
    mx, my = fit_on_one_monitor(x, y, width, height)
    win = _host_window_rect(anchor_x, anchor_y)
    if win is None:
        return mx, my
    wleft, wtop, wright, wbottom = win
    if width <= wright - wleft:
        mx = max(wleft, min(mx, wright - width))
    else:
        mx = wleft
    if height <= wbottom - wtop:
        my = max(wtop, min(my, wbottom - height))
    else:
        my = wtop
    return mx, my


def fit_on_one_monitor(x, y, width, height):
    """Nudges a window rect so it sits entirely on ONE screen.

    Real bug Antonio screenshotted 2026-07-21: the review card opened across
    the seam between his two monitors, half on each. Besides looking broken,
    it makes "which screen is this on" genuinely undefined, which is what
    made the per-screen sizing look like it was picking sizes at random.
    Keeping the card wholly on one monitor removes both problems at once.
    """
    area = monitor_work_area(x + width // 2, y + height // 2)
    if area is None:
        return x, y
    left, top, right, bottom = area
    if width <= right - left:
        x = max(left, min(x, right - width))
    else:
        x = left
    if height <= bottom - top:
        y = max(top, min(y, bottom - height))
    else:
        y = top
    return x, y


def _card_corner(bx, by, anchor_x, anchor_y):
    """Which corner of the review card the badge should nest at: "left"
    (the default -- the card's body extends RIGHT from the badge, so the
    badge sits at the card's own left corner) unless there isn't room for
    the card's width on that side within the box's own host window/
    monitor, in which case "right" (mirrored: the card's body extends
    LEFT from the badge instead).

    Real bug found live 2026-07-25 (Antonio, screenshot: the card covering
    real message text): this used to default the OTHER way (grow left,
    badge at the card's right corner), copied from the OLD outside-left
    badge design without re-deriving it for the NEW one. With the badge
    now docked INSIDE the box at its own right edge (see
    PersistentBadge._position_for), the box's own content -- the text
    actually being read -- sits to the badge's LEFT, filling the box
    from its left edge up to the badge. Growing the card further left
    from there covers exactly that content, every time, not just on an
    edge case. Growing right instead moves into whatever's to the right
    of the box, almost always empty margin or unrelated chrome, not the
    conversation. The narrow-sidebar case this function was originally
    built for (a box near the screen's LEFT edge, e.g. Claude's Design
    mode) still falls back to "right" correctly below -- growing right
    was already the right answer there too, so flipping the DEFAULT here
    doesn't reopen that case, it was never the one this default served.

    `anchor_x`/`anchor_y` must be a point guaranteed to land on the real
    host app window, never the badge's own topmost window (see
    _host_window_rect's docstring on why) -- callers already have this
    from the real box rect, same discipline as everywhere else this file
    anchors a window lookup.

    Real bug found while re-deriving this math (2026-07-25, following a
    live report of the card looking "too large" / misaligned with the
    badge on a second, larger monitor): _finalize positions the card from
    the badge's CENTRE (bx + bw/2), not bx or bx+bw, for BOTH corners --
    but this used bx+BADGE_ICON_SIZE for one side and bare bx for the
    other. Both branches OVER-estimated available room by half a badge
    width, so a card could get selected to grow into a direction it
    doesn't quite fit, right at the margin -- exactly where
    fit_within_window_and_monitor then has to clamp it away from the
    badge, visually detaching the corner notch (see _punch_gap) from the
    badge it's supposed to nest around. Using the same centre point
    _finalize actually positions from removes that margin entirely rather
    than narrowing it."""
    win = _host_window_rect(anchor_x, anchor_y) or monitor_work_area(anchor_x, anchor_y)
    if win is None:
        return "left"
    wleft, _, wright, _ = win
    center = bx + BADGE_ICON_SIZE / 2
    room_for_left_growth = center - wleft
    room_for_right_growth = wright - center
    if room_for_right_growth >= POPUP_WIDTH:
        return "left"
    if room_for_left_growth >= POPUP_WIDTH:
        return "right"
    return "left" if room_for_right_growth >= room_for_left_growth else "right"


def apply_scale_for_window(hwnd_or_point):
    """Re-scale for the monitor holding this window (or point).

    Driven by the WINDOW rather than an arbitrary coordinate: Windows picks
    the monitor with the largest overlap, which is well-defined even while a
    window straddles a seam. An arbitrary point is not, and that ambiguity is
    what previously let the laptop pick up the monitor's scale.
    """
    global UI_SCALE, POPUP_WIDTH, BADGE_ICON_SIZE
    try:
        if isinstance(hwnd_or_point, tuple):
            hmon = _monitor_from_point(*hwnd_or_point)
        else:
            MONITOR_DEFAULTTONEAREST = 2
            user32 = ctypes.windll.user32
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, ctypes.c_ulong]
            user32.MonitorFromWindow.restype = ctypes.c_void_p
            hmon = user32.MonitorFromWindow(hwnd_or_point, MONITOR_DEFAULTTONEAREST)
        dpi = _dpi_of_monitor(hmon)
    except Exception:
        return False
    if _active_dpi[0] == dpi:
        return False
    _active_dpi[0] = dpi
    UI_SCALE = scale_for_dpi(dpi)
    POPUP_WIDTH = S(DESIGN_POPUP_WIDTH)
    # Badge size uses its OWN scale (badge_scale_for_dpi), deliberately NOT
    # S()/UI_SCALE -- see badge_scale_for_dpi's docstring. The card/font
    # sizing above is untouched, exactly the ship-one-size decision.
    BADGE_ICON_SIZE = max(1, int(round(DESIGN_BADGE_SIZE * badge_scale_for_dpi(dpi))))
    log(f"screen changed: {dpi:.0f} dpi -> scale {UI_SCALE:.2f}, "
        f"card {POPUP_WIDTH}px, badge {BADGE_ICON_SIZE}px, "
        f"text {9 * (96.0/72.0) * UI_SCALE * font_scale_for_dpi(dpi):.0f}px "
        f"(font profile: {'laptop' if dpi >= 120 else 'monitor'})")
    for fn in _scale_listeners:
        try:
            fn()
        except Exception:
            log_exception("scale listener")
    return True


def clamp_popup_width_to_host(hwnd):
    """Shrink POPUP_WIDTH when the host app window is small (real report
    2026-07-26: the card looked oversized in a ~910px, non-maximized
    ChatGPT window). Runs every watch_loop tick like apply_scale_for_window
    above, deliberately NOT gated behind that function's DPI-unchanged
    cache -- a window can be resized without ever changing monitor or DPI,
    and this has to track that live.

    A pure overflow guard (only shrink once 560px genuinely doesn't fit)
    turned out not to be enough: verified live against the real reported
    case, a 912px-wide ChatGPT window, and 560px fits inside it with ~350px
    to spare -- no overflow, yet it still reads as the card dominating the
    window. So this caps at a FRACTION of the host width too, not just
    "does it fit," matching the actual complaint (proportion, not clipping).

    This is NOT the per-screen/DPI card scaling scale_for_dpi's docstring
    says to never try again -- that essay is about the design width itself
    varying by MONITOR, which stays exactly 560px here. This only ever
    shrinks the EFFECTIVE width below that fixed design value, and only
    when the specific host window is small -- a roomy or maximized window
    (the common case) always gets the untouched 560px card, on every
    monitor, exactly as before."""
    global POPUP_WIDTH
    design_width = S(DESIGN_POPUP_WIDTH)
    try:
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            POPUP_WIDTH = design_width
            return
        host_width = rect.right - rect.left
    except Exception:
        POPUP_WIDTH = design_width
        return
    # Antonio's explicit target (2026-07-26, confirmed live against the
    # real ~912px ChatGPT window): "roughly half" of the 560px design width
    # in a window that size, i.e. ~280px. 0.31 gives 912*0.31=283px there.
    # 560px against a maximized ~1920px window stays at 30% of that width,
    # nowhere near this cap, so the common/roomy case is still untouched.
    HOST_FRACTION = 0.31
    new_width = max(S(MIN_POPUP_WIDTH), min(design_width, int(host_width * HOST_FRACTION)))
    if new_width != POPUP_WIDTH:
        log(f"card width adjusted for host window ({host_width}px wide): {POPUP_WIDTH}px -> {new_width}px")
    POPUP_WIDTH = new_width


BADGE_HEAT_MAX = 6  # suggestion count at which the ring is fully red
# Displayed in the settings status bar and About. MUST be bumped together
# with version_info.txt and installer.iss (it drifted to a stale 0.9.4 while
# those advanced, so the UI lied about the version -- 2026-07-22).
APP_VERSION = "1.1.1"


def _heat_color(count):
    """Green (clean) -> red (lots to fix), through yellow/orange. Uses HSV
    hue 120deg->0deg so it passes through natural yellow/orange rather than
    the muddy brown a straight green->red RGB blend would give."""
    t = min(count / BADGE_HEAT_MAX, 1.0) if BADGE_HEAT_MAX > 0 else 0.0
    hue = (120.0 - 120.0 * t) / 360.0  # 120=green, 0=red
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.88)
    return (int(r * 255), int(g * 255), int(b * 255), 255)


def _load_logo_image(size):
    """The bare teardrop mark, transparent background. Used for the panel
    header and, since 2026-07-21, for the floating badge itself, the two
    places that must not look like a chrome-framed app window."""
    if Image is None:
        return None
    try:
        img = Image.open(resource_path(os.path.join("assets", "logo.png"))).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _load_mark_dark_image(size):
    """The bare dark 'C/' glyph, no circle/fill behind it -- the same
    mark_dark.png the web Settings/Onboarding header already uses (see
    webui.py's __MARK_DARK_URI__). Real ask 2026-07-26: the native review
    card's header was using the filled-circle badge mark instead, which
    doesn't match Settings' actual look despite both looking like "a dark
    icon" at a glance -- Antonio: "making it replicable to the logo on the
    settings page is the goal." Use this here too so the two surfaces
    genuinely match, not just resemble each other."""
    if Image is None:
        return None
    try:
        img = Image.open(resource_path(os.path.join("assets", "mark_dark.png"))).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _load_badge_mark_image(size):
    """The floating badge's mark: the teardrop with its OWN silhouette
    filled dark, no square tile behind it.

    Real correction 2026-07-21 (Antonio, direct): the badge briefly used the
    tiled app icon, which put a visible black box around the indicator and
    made it look like a little app window sitting on top of the text field.
    The bare transparent mark fixes that but is close to invisible on a
    white page, its interior "C/" is white on white. Filling inside the
    teardrop instead of behind it gives both: legible on any background,
    and the only shape on screen is the mark itself.

    Generated by tools_make_badge_asset.py, rerun that if logo.png changes."""
    if Image is None:
        return None
    try:
        img = Image.open(resource_path(os.path.join("assets", "badge.png"))).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        # Falls back to the bare mark rather than the tile: worse contrast
        # on light backgrounds, but never a box.
        return _load_logo_image(size)


def _load_app_icon_image(size):
    """The app icon: the mark on a dark rounded tile.

    Real problem found 2026-07-21 by rendering the icon at 16/24/32/48px
    over both light and dark backdrops: the bare transparent mark all but
    disappeared on light ones, and its white "C/" vanished completely.
    Anywhere Windows itself draws us AS AN APPLICATION (taskbar, Explorer,
    notification area, settings window, installer) needs the tile baked in
    so the mark is always legible.

    Explicitly NOT the floating badge, corrected 2026-07-21: the tile there
    put a black box around the indicator and made it look like a little app
    window parked on top of the text field. The badge uses the bare mark,
    see _make_heat_badge_image."""
    if Image is None:
        return None
    try:
        img = Image.open(resource_path(os.path.join("assets", "icon.png"))).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _make_heat_badge_image(size, count, checked=True, ring_width=None):
    """The badge image: the circular logo with a colored heat dot in the
    corner, color driven by `count`. Returns a PIL Image, or None if
    PIL/asset unavailable (caller falls back to a text glyph).

    `checked` (real ask 2026-07-25, new plain-circle mark): whether
    there's been an actual analysis to report on at all. There's a real
    difference between "checked, and it's clean" (count=0, show a GREEN
    dot, same status-indicator convention as the amber/red states) and
    "nothing to check yet" (empty/near-empty box, no dot at all, same
    MIN_TEXT_LENGTH_TO_ANALYZE threshold used everywhere else this
    distinction matters). Previously count==0 covered BOTH cases and drew
    no dot for either, which is why the dot didn't need a `checked` flag
    before this asset changed no dot could pass for "clean" well enough.
    A plain black circle with nothing on it doesn't read as "checked
    clean" the way the old mark's outline did, so the two cases need to
    look different now.
    """
    if Image is None:
        return None
    try:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        logo = _load_badge_mark_image(size)
        if logo is None:
            return None
        canvas.alpha_composite(logo, (0, 0))
        if checked:
            d = max(9, round(size / 4.2))
            draw = ImageDraw.Draw(canvas)
            # Inset by the ring's own width, not 1px. Real bug Antonio
            # spotted 2026-07-21: at 1px the ring ran to x=size+1 and y=-1,
            # so its top-right was sliced off by the image bounds and the
            # dot read as a cut-out semicircle. The ring extends RING_PAD
            # beyond the dot on every side, so the dot has to start at least
            # that far in.
            ring = 2
            inset = ring + 1
            # Bottom-right (real ask 2026-07-25, matching the new circle
            # mark's reference design -- a standard presence-dot position,
            # unlike the old top-right placement the teardrop mark used).
            x1, y1 = size - d - inset, size - d - inset
            # Thin light ring only, not a filled disc behind the dot. A
            # filled backing was fine against the tile but would read as a
            # second little black box now that there's nothing behind it.
            draw.ellipse(
                (x1 - ring, y1 - ring, x1 + d + ring, y1 + d + ring),
                outline=(255, 255, 255, 210), width=ring,
            )
            draw.ellipse((x1, y1, x1 + d, y1 + d), fill=_heat_color(count))
        return _flatten_for_colorkey(canvas)
    except Exception:
        return None


# Anything at least this opaque becomes solid artwork; anything below becomes
# exactly the key colour and therefore truly invisible. No middle ground.
_BADGE_ALPHA_CUTOFF = 130


def _flatten_for_colorkey(rgba):
    """Collapses soft alpha to a hard edge against the exact key colour.

    Real bug Antonio reported 2026-07-21, with a screenshot: "the edges of
    the square are still visible on the UI, it looks bad." Confirmed by
    driving the real Tk widget and screenshotting it, rather than simulating
    the colour-key in PIL, which is why earlier checks looked clean and the
    live badge did not.

    Cause: `-transparentcolor` removes pixels matching BRAND_DARK EXACTLY.
    Downscaling the mark with LANCZOS leaves a rim of semi-transparent
    pixels (plus a little resampling ringing further out). Tk composites
    those against the label's dark background, landing them a shade or two
    off the key, so Windows keeps them. The result is a scatter of dark
    speckles tracing the old square bounds.

    Exact-match keying cannot be made to work with soft alpha, so the alpha
    is made binary here instead. Slightly crisper edge, zero halo.
    """
    key = _hex_to_rgb(BRAND_DARK)
    w, h = rgba.size
    out = Image.new("RGB", (w, h), key)
    src, dst = rgba.load(), out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a < _BADGE_ALPHA_CUTOFF:
                continue  # left exactly on the key colour = invisible
            if (r, g, b) == key:
                # Real artwork must never coincide with the key colour or
                # Windows would punch a hole straight through the mark.
                r, g, b = 12, 12, 14
            dst[x, y] = (r, g, b)
    return out


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


# product/ , the folder holding backend/, frontend/ and the shipped docs. Only
# meaningful when running from source; a frozen build uses _MEIPASS and the
# executable's own directory instead.
PRODUCT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path):
    """Bundled data files (the logo) live next to this script when running
    from source, but PyInstaller's --onefile bootloader extracts them into
    a temp _MEIPASS dir at runtime, this is the standard way to find either."""
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path is None:
        # Running from source. assets/ and webui/ live in the sibling
        # product/frontend folder since the 2026-11-26 layout change, so the
        # base is one level up and across, NOT this file's own directory. The
        # frozen build still finds them at the _MEIPASS root, because
        # Comprsly.spec maps them back to plain "assets" and "webui" there.
        # That is deliberate: every resource_path("assets/...") call site
        # keeps working untouched in both modes.
        base_path = os.path.join(PRODUCT_ROOT, "frontend")
    return os.path.join(base_path, relative_path)


def install_dir_path(relative_path):
    """Files that ship in the INSTALL directory alongside Comprsly.exe via
    Inno Setup's [Files] section (installer.iss), not inside the PyInstaller
    onefile bundle. ACKNOWLEDGEMENTS.txt is one of these: it is NOT in
    Comprsly.spec's datas, so resource_path (which resolves into the
    PyInstaller temp extraction dir, _MEIPASS) would never find it in the
    frozen build, only in a dev run. sys.executable's OWN directory is the
    real install dir when frozen (installer.iss's DefaultDirName places
    Comprsly.exe and ACKNOWLEDGEMENTS.txt side by side); running from
    source, that file sits at the product/ root, one level above this file."""
    base = (os.path.dirname(os.path.abspath(sys.executable))
            if getattr(sys, "frozen", False)
            else PRODUCT_ROOT)
    return os.path.join(base, relative_path)


def _load_badge_icon_image(size, circular=False):
    """Returns a resized PIL Image of the real logo, or None if PIL isn't
    available or the asset is missing, callers fall back to a plain text
    glyph in that case rather than crashing. circular=True crops it into a
    circle with a thin outline ring, the Grammarly-style presentation
    Antonio asked for, used for the badge specifically; other callers
    (tray/settings icons) keep the logo's own square card as-is."""
    if Image is None:
        return None
    try:
        img = Image.open(resource_path(os.path.join("assets", "icon.png"))).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        if circular:
            img = _apply_circular_mask(img)
        return img
    except Exception:
        return None


def _apply_circular_mask(img):
    size = img.size
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
    circular = Image.new("RGBA", size, (0, 0, 0, 0))
    circular.paste(img, (0, 0), mask)
    ImageDraw.Draw(circular).ellipse(
        (0, 0, size[0] - 1, size[1] - 1), outline=(255, 255, 255, 90), width=1
    )
    return circular


# --windowed builds have no console, so any unhandled exception (main thread
# or a daemon thread) normally just vanishes and the app looks "frozen but
# invisible" with zero clue why. This writes every crash to a real log file
# so failures are actually diagnosable instead of silent.
# Data folder renamed "Token Saver" -> "Compresly" -> "Comprsly" (real ask
# 2026-07-25, second rebrand). Same reasoning as the first rename: the
# installer migrates the ~1GB model cleanly (see installer.iss's
# MyLegacyFolder, now pointed at the old "Compresly" folder), and
# _migrate_legacy_data_dir below covers the small app-side files. Only the
# IMMEDIATELY PREVIOUS folder is tracked -- anyone still on the original
# "Token Saver" folder from the first rebrand would need one extra
# in-between upgrade, an acceptable, unlikely-in-practice gap rather than
# an ever-growing migration chain. The MUTEX_NAME stays TokenSaver* on
# purpose, it's invisible and changing it mid-transition could let two
# instances run.
_LEGACY_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Compresly")
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Comprsly")


def _migrate_legacy_data_dir():
    """One-time, best-effort move of the small user-data files from the old
    'Token Saver' folder to the new 'Comprsly' one, for anyone upgrading
    in place. Runs at import, before anything writes, and is a pure no-op
    on a fresh install (no legacy folder) or once migration has happened.

    Only the small JSON/log files are copied here, never the ~1GB model:
    the installer bundles the model straight into the new folder and then
    deletes the whole legacy folder, so copying the model app-side would
    just duplicate a gigabyte. If the running exe still lives in the legacy
    folder (a dev run), the model is found there by local_model's own path
    only when that hasn't been repointed, so this stays limited to data."""
    try:
        if not os.path.isdir(_LEGACY_DATA_DIR):
            return
        os.makedirs(LOG_DIR, exist_ok=True)
        import shutil
        for name in ("settings.json", "history.json", "badge_position.json"):
            old = os.path.join(_LEGACY_DATA_DIR, name)
            new = os.path.join(LOG_DIR, name)
            if os.path.isfile(old) and not os.path.exists(new):
                shutil.copy2(old, new)
    except Exception:
        # Never let a migration hiccup stop the app from starting; worst
        # case the user re-picks a couple of settings.
        pass


_migrate_legacy_data_dir()

LOG_PATH = os.path.join(LOG_DIR, "debug.log")
BADGE_POSITION_PATH = os.path.join(LOG_DIR, "badge_position.json")
SETTINGS_PATH = os.path.join(LOG_DIR, "settings.json")
HISTORY_PATH = os.path.join(LOG_DIR, "history.json")
HISTORY_MAX_ENTRIES = 500  # a real cap so this can't grow forever on disk, not a meaningful prompt limit


def point_is_on_a_monitor(x, y):
    """Is this screen coordinate on a monitor that currently exists?"""
    try:
        MONITOR_DEFAULTTONULL = 0
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, ctypes.c_ulong]
        return bool(user32.MonitorFromPoint(
            wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONULL))
    except Exception:
        return True  # can't tell, don't throw away a position over it


def load_saved_badge_position():
    """The remembered badge position, but only if it's still somewhere you
    can actually see.

    Real bug Antonio hit 2026-07-21: "where is it, it's not showing up now."
    He had dragged the badge onto a left-hand monitor (saved as x=-1327,
    entirely legitimate at the time, his virtual desktop started at -4176),
    then later worked on the laptop alone, where the desktop is 0..2256. The
    badge dutifully restored itself to a coordinate on a monitor that no
    longer existed and rendered off-screen, so the app looked dead while
    running perfectly.

    Any persisted window position has to be re-validated against the CURRENT
    monitor layout on load, because that layout changes every time a laptop
    is docked, undocked, or plugged into a TV."""
    try:
        with open(BADGE_POSITION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        x, y = int(data["x"]), int(data["y"])
    except Exception:
        return None
    # Check the badge's middle, not its corner: a position a few pixels off
    # the edge of a real monitor should still count as on it.
    if not point_is_on_a_monitor(x + BADGE_ICON_SIZE // 2, y + BADGE_ICON_SIZE // 2):
        log(f"saved badge position ({x},{y}) is not on any current monitor, "
            f"ignoring it and re-anchoring to the text field")
        try:
            os.remove(BADGE_POSITION_PATH)
        except Exception:
            pass
        return None
    return x, y


def save_badge_position(x, y):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(BADGE_POSITION_PATH, "w", encoding="utf-8") as f:
            json.dump({"x": x, "y": y}, f)
    except Exception:
        pass


# Real ask 2026-07-20: a real settings window (Handy's own settings UI was
# the explicit visual reference). DEFAULT_SETTINGS doubles as the schema,
# load_settings() only keeps keys it recognizes so a corrupted or
# older-version file can't inject something unexpected.
DEFAULT_SETTINGS = {
    "launch_on_login": False,
    # Real direction 2026-07-20: rules and the AI always work TOGETHER, not
    # one gating out the other, and there is deliberately no confidence/
    # threshold variable, everyone gets the same pipeline and the same kind
    # of output. This is the only AI-related switch: a plain on/off for the
    # AI compression stage (a capability toggle for slow machines), not a
    # quality dial. Default on.
    "ai_enabled": True,
    # Real direction 2026-07-25 (Antonio, reversing the 2026-07-21
    # "Grammarly-style, use it anywhere" pivot): Comprsly should ONLY ever
    # activate inside a recognized LLM app or LLM website tab -- Claude,
    # ChatGPT, Gemini, and the rest of KNOWN_LLM_PROCESSES/LLM_TITLE_HINTS.
    # Everywhere else (Facebook, a generic search box, Word, Teams, Slack,
    # any other app) it must not even detect a text field, let alone show
    # the badge. This USED to be a set of five per-app-category toggles
    # (ai_chat/browsers/comm/email_docs/other, see git history for the old
    # DOCUMENT_APP_PROCESSES/SAFE_WRITE_ONLY_PROCESSES/COMM_PROCESSES special-
    # casing that supported those other categories) -- all of that is gone
    # now that ai_chat is the only surface, replaced by a single on/off
    # switch for the one category that still exists. is_llm (app_label is
    # not None, see app_label_for) is the actual recognizer: it already knew
    # "what text box this lives in" by process name or browser tab title,
    # this change just makes EVERYTHING gate on it, not only compression.
    "cat_ai_chat": True,
    # Real ask 2026-07-22: with the model no longer bundled, offer the AI
    # download in a first-run prompt. Shown once (this flag), only when the
    # model isn't already present. See show_ai_onboarding().
    "ai_onboarding_shown": False,
    # Real ask 2026-07-30 (Antonio, direct: notify on next login that an
    # update landed). The last APP_VERSION this install actually showed the
    # Settings sidebar for -- see consume_version_update_flag(). Blank means
    # either a fresh install or an existing install from before this flag
    # existed; either way that's not a real update to announce.
    "last_seen_version": "",
}

# --- Where Comprsly works (2026-07-25: LLM-only, reversing the earlier
# per-app-category system) -------------------------------------------------
# Used to be five togglable categories (ai_chat/browsers/comm/email_docs/
# other, each with its own process-name set: COMM_PROCESSES,
# DOCUMENT_APP_PROCESSES, SAFE_WRITE_ONLY_PROCESSES -- see git history for
# that era). Antonio's direct call: Comprsly should only ever recognize a
# text box that lives inside a known LLM app or LLM website tab, nothing
# else -- not a generic browser field, not Teams/Slack/Discord, not
# PowerPoint, not "other." The recognizer for "what app/site does this box
# live in" already existed (app_label_for, KNOWN_LLM_PROCESSES,
# LLM_TITLE_HINTS) and was already used to gate compression; this just makes
# EVERYTHING (badge, grammar, all of it) gate on that same signal, not only
# compression. What's left of the category system is a single remaining
# category/flag so the Settings UI (both the web one and the Tk fallback,
# both iterate this list generically) needs no other code changes.
APP_CATEGORIES = ("ai_chat",)
CATEGORY_SETTING = {"ai_chat": "cat_ai_chat"}
CATEGORY_LABEL = {"ai_chat": "AI chat apps"}
CATEGORY_BLURB = {
    "ai_chat": "Claude, ChatGPT, Gemini, Perplexity, Copilot, and other AI "
               "chat -- the only surface Comprsly works on. Turn this off "
               "to disable Comprsly everywhere without uninstalling.",
}


def load_settings():
    merged = dict(DEFAULT_SETTINGS)
    data = {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    except Exception:
        data = {}
    return merged


def save_settings(settings):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f)
    except Exception:
        pass


def consume_version_update_flag():
    """One-time 'Updated to vX.X.X' signal for the Settings sidebar (real ask
    2026-07-30, Antonio, direct: notify on next login that an update landed;
    placement is the same sidebar slot as the existing 'Update available'
    box, see settings.html's .sidebottom). Works for any install path
    (Store auto-update, a re-run installer, or a manual exe swap) since it
    only ever compares APP_VERSION to what was last recorded, no Store API
    involved.

    Consumed, not just read: the stored version is updated to APP_VERSION
    the moment this is called, so the notice fires exactly once per real
    version bump and never again for that version, even across many Settings
    opens. A blank stored value (fresh install, or an existing install from
    before this flag existed) is recorded silently -- there's no prior
    version to have "updated" from, so nothing is announced."""
    s = load_settings()
    seen = s.get("last_seen_version") or ""
    if seen != APP_VERSION:
        s["last_seen_version"] = APP_VERSION
        save_settings(s)
        if seen:
            return {"updated": True, "from": seen, "to": APP_VERSION}
    return {"updated": False}


def load_history():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_history(entry):
    history = load_history()
    history.append(entry)
    history = history[-HISTORY_MAX_ENTRIES:]
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f)
    except Exception:
        pass


# Real ask 2026-07-20: launch-on-login via the standard per-user Registry
# Run key, independent of the installer's own optional start-on-login task
# (installer.iss), a direct toggle here shouldn't depend on which install
# path was used to get the app onto the machine.
#
# 2026-07-26 (MSIX/Store prep): a Run-key write is not a reliable way to
# autostart once the app runs under a packaged identity (MSIX/Desktop
# Bridge) -- packaged registry writes are virtualized per-package, so this
# key would either not persist the way a real system Run key does, or would
# quietly stop working depending on the package's virtualization settings.
# Microsoft's own documented replacement for packaged apps is a
# windows.startupTask manifest extension paired with the runtime
# Windows.ApplicationModel.StartupTask API, so every function below now
# branches on package identity: unpackaged (today's Inno Setup install)
# keeps the exact registry behavior that's already shipped and verified;
# packaged (future MSIX/Store build) uses StartupTask instead. The
# windows.startupTask <Extension> itself still has to be declared in the
# AppxManifest.xml the MSIX Packaging Tool generates -- this only handles
# the runtime side.
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Comprsly"

# Must match the TaskId given to the <desktop:StartupTask> element in the
# packaged app's manifest exactly, or StartupTask.get_async() below can't
# find it.
MSIX_STARTUP_TASK_ID = "ComprslyStartupTask"


def _is_packaged():
    """True only under a real package identity (MSIX/Desktop Bridge).

    GetCurrentPackageFullName returns APPMODEL_ERROR_NO_PACKAGE (15700) for
    every unpackaged process, including today's Inno Setup install and any
    dev run -- this is the standard, dependency-free way to tell the two
    apart (no winrt import needed just to check)."""
    try:
        length = wintypes.UINT(0)
        ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None)
        return length.value > 0
    except Exception:
        return False


def _set_launch_on_login_packaged(enabled):
    """StartupTask side of the toggle, only reachable when _is_packaged().

    Lazy-imported so an unpackaged build never needs the winrt dependency
    installed at all -- it's only exercised inside a real MSIX package."""
    from winrt.windows.applicationmodel import startup as wsa
    task = wsa.StartupTask.get_async(MSIX_STARTUP_TASK_ID).get()
    if enabled:
        task.request_enable_async().get()
    else:
        task.disable()
    return True


_STORE_UPDATE_CHECK_MIN_INTERVAL = 1800  # matches the Store API's own documented rate limit
_last_store_update_check = [0.0, {"available": False}]


def check_for_update():
    """Real ask 2026-07-28 (Antonio, direct: 'what is the best route the
    MSIX can be updated'): packaged builds ask the Microsoft Store's own
    update service -- Windows.Services.Store.StoreContext -- rather than
    a custom version-check, since it's the officially supported mechanism
    for exactly this, needs no hosting of our own, and hands off to the
    Store's own trusted download/install pipeline instead of a self-signed
    one. Unpackaged (today's Inno Setup .exe) has no equivalent yet -- a
    separate, still-open piece of work.

    Rate-limited to the Store API's own documented cap (max one real check
    per 30 minutes, max ten per 24h) -- a repeat call inside that window
    returns the cached result instead of re-querying, so the Settings
    window can safely call this every time it opens without ever tripping
    that limit itself."""
    if not _is_packaged():
        return {"available": False}
    now = time.time()
    if now - _last_store_update_check[0] < _STORE_UPDATE_CHECK_MIN_INTERVAL:
        return _last_store_update_check[1]
    try:
        from winrt.windows.services.store import StoreContext
        context = StoreContext.get_default()
        updates = context.get_app_and_optional_store_package_updates_async().get()
        result = {"available": len(updates) > 0}
    except Exception:
        log_exception("check_for_update")
        result = {"available": False}
    _last_store_update_check[0] = now
    _last_store_update_check[1] = result
    return result


def start_store_update():
    """Hands off to the Store's own download+install pipeline -- Windows
    shows its own permission and progress dialogs for the actual transfer,
    this only kicks it off. Runs on a background thread since the
    underlying WinRT calls block on .get(), so the Settings window doesn't
    freeze while the user works through the OS's own prompts.

    Real gap, not yet verified live (2026-07-28): Microsoft's own docs say
    a Win32 desktop-bridge app must associate the StoreContext with an
    owner HWND (via IInitializeWithWindow) before calling a method that
    shows a modal dialog, or it can fail with ERROR_INVALID_WINDOW_HANDLE
    (0x80070578) -- see the Q&A thread linked in that doc for exactly this
    symptom. There's no documented Python/pywinrt example of that
    association step anywhere found, only C#/C++. This call is left
    without it for now; if it throws that specific error once this is
    actually tested in a real packaged install, that's the concrete next
    thing to solve, not something to guess at further here. The check
    above (get_app_and_optional_store_package_updates_async) shows no UI
    at all per its own docs, so it isn't affected by this gap."""
    if not _is_packaged():
        return {"ok": False, "error": "not a packaged install"}

    def _run():
        try:
            from winrt.windows.services.store import StoreContext
            context = StoreContext.get_default()
            updates = context.get_app_and_optional_store_package_updates_async().get()
            if updates:
                context.request_download_and_install_store_package_updates_async(updates).get()
        except Exception:
            log_exception("start_store_update")

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True}


def set_launch_on_login(enabled):
    if _is_packaged():
        try:
            return _set_launch_on_login_packaged(enabled)
        except Exception:
            log_exception("set_launch_on_login (packaged)")
            return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            if enabled:
                exe_path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        log_exception("set_launch_on_login")
        return False


def launch_on_login_is_active():
    """Reads the ACTUAL autostart state rather than trusting settings.json.

    Real ask 2026-07-22 (UI-backend audit): the Settings toggle initialised
    its checked/unchecked state from APP_SETTINGS["launch_on_login"], which is
    just what was persisted -- if that ever diverged from the real registry
    (a build before heal_launch_on_login existed, a key removed by another
    tool, a settings file carried across machines) the toggle would show ON
    with no key behind it. A toggle that can visibly lie undermines trust in
    every toggle, so the UI now derives its state from reality via this.
    Packaged builds ask StartupTask the same question instead of the Run key."""
    if _is_packaged():
        try:
            from winrt.windows.applicationmodel import startup as wsa
            task = wsa.StartupTask.get_async(MSIX_STARTUP_TASK_ID).get()
            return task.state == wsa.StartupTaskState.ENABLED
        except Exception:
            log_exception("launch_on_login_is_active (packaged)")
            return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ)
        try:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
        finally:
            winreg.CloseKey(key)
        return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        log_exception("launch_on_login_is_active")
        return False


def heal_launch_on_login():
    """Re-point the autostart entry at the CURRENT exe if it's enabled but
    stale (real ask 2026-07-22, folder rename). The registry Run value is
    an absolute path; after the data/app folder moved from 'Token Saver' to
    'Comprsly' the old value pointed at a binary that no longer exists, so
    autostart silently did nothing until the user next toggled it. Called
    once at startup: if login-launch is on and the recorded path isn't the
    exe we're actually running from, rewrite it. Never turns autostart ON,
    only corrects a path the user already opted into.

    No-op under a packaged (MSIX) build: StartupTask is keyed to the
    package identity, not an absolute exe path, so there's nothing here
    that can go stale the way the Run key value can."""
    if _is_packaged():
        return
    if not getattr(sys, "frozen", False):
        return  # dev run: __file__ isn't what the installer registers
    try:
        if not APP_SETTINGS.get("launch_on_login"):
            return
        import winreg
        current = f'"{sys.executable}"'
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ)
            try:
                existing, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            finally:
                winreg.CloseKey(key)
        except FileNotFoundError:
            existing = None
        if existing != current:
            set_launch_on_login(True)
            log(f"heal_launch_on_login: autostart path corrected to {sys.executable}")
    except Exception:
        log_exception("heal_launch_on_login")


# The value name the app used before the Compresly -> Comprsly rebrand.
# heal_launch_on_login above only ever manages RUN_VALUE_NAME ("Comprsly"),
# so an install that had login-launch enabled under the OLD name kept a
# second, orphaned Run entry pointing at the no-longer-updated Compresly
# folder -- both launching on every login. Nothing else would ever create a
# Run value literally named "Compresly", so it's always safe to remove.
STALE_RUN_VALUE_NAME = "Compresly"


def remove_stale_compresly_startup_entry():
    """One-time cleanup of the pre-rebrand duplicate startup entry (real bug
    found live 2026-07-26: two Run-key entries launching what's basically the
    same app). No-op if it's already gone."""
    if _is_packaged():
        return
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, STALE_RUN_VALUE_NAME)
            log(f"removed stale '{STALE_RUN_VALUE_NAME}' startup entry from the old rebrand")
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)
    except Exception:
        log_exception("remove_stale_compresly_startup_entry")


# Loaded once at import time, mutated in place by SettingsWindow and read
# live by watch_loop, a plain dict works fine here since Tk callbacks and
# watch_loop's polling both run cooperatively (no real concurrent-write
# race, watch_loop only ever reads these values).
APP_SETTINGS = load_settings()


# Document editors, communication apps, and the general "other" catch-all
# (DOCUMENT_APP_PROCESSES, SAFE_WRITE_ONLY_PROCESSES, COMM_PROCESSES, and the
# categorize_process()/category_enabled() functions that dispatched between
# them) are gone as of 2026-07-25 -- Comprsly is LLM-only now (see the
# DEFAULT_SETTINGS note above), so there's no other category left to
# categorize a process INTO. Activation is a direct check in watch_loop:
# `app_label is not None and APP_SETTINGS.get("cat_ai_chat")`.

# Cap the log so it can't grow without bound on disk (real ask 2026-07-22).
# At ~1 MB we roll to a single .old backup, so at most ~2 MB is ever kept.
_LOG_MAX_BYTES = 1_000_000


def log(message):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        try:
            if os.path.getsize(LOG_PATH) > _LOG_MAX_BYTES:
                old = LOG_PATH + ".old"
                if os.path.exists(old):
                    os.remove(old)
                os.replace(LOG_PATH, old)
        except OSError:
            pass  # first write, or a transient error; just append below
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {message}\n")
    except Exception:
        pass


def log_exception(context):
    log(f"EXCEPTION in {context}:\n{traceback.format_exc()}")


def _thread_excepthook(args):
    log_exception(f"thread '{args.thread.name}'")


threading.excepthook = _thread_excepthook

# Explicit taskbar identity. Windows groups taskbar buttons and picks the
# icon by AppUserModelID; a Python/Tk process that never sets one inherits a
# host-derived default, which is part of why the taskbar kept showing a
# stale icon after the rebrand. Must run before any window exists, same as
# the DPI call above.
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Comprsly.Desktop")
except Exception:
    pass

# Real bug found 2026-07-20: capping onnxruntime's thread count (see
# local_model.py) wasn't enough on its own, Antonio still reported the whole
# system, mouse included, going "extremely laggy" during a rewrite. Even a
# handful of CPU-bound threads at NORMAL priority contend directly with
# every other app's NORMAL-priority threads for the same cores, including
# whatever handles cursor/input processing. Dropping this WHOLE process to
# BELOW_NORMAL means Windows favors every other app over us whenever there's
# contention, this is the standard mechanism background/batch tools (backup
# software, indexers) use specifically so they don't feel like they're
# stealing the machine. Set once at startup, not toggled per-inference, both
# simpler and safer (nothing to leave in the wrong state if a rewrite errors
# mid-call).
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
try:
    # Real bug found 2026-07-20: GetCurrentProcess() returns a 64-bit pseudo-
    # handle (0xFFFFFFFFFFFFFFFF); without explicit restype/argtypes, ctypes
    # marshals it through a default 32-bit int and SetPriorityClass fails
    # with ERROR_INVALID_HANDLE (error 6), silently swallowed by the bare
    # except below, so this looked like it worked but never actually took
    # effect. Confirmed both the failure and the fix directly by hand before
    # shipping this, same class of bug this file already works around for
    # GetKeyState/SetWindowsHookExW elsewhere.
    ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ctypes.windll.kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    ctypes.windll.kernel32.SetPriorityClass.restype = wintypes.BOOL
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS
    )
except Exception:
    pass

# A named mutex so double-clicking the exe again doesn't spawn a duplicate
# background watcher, real bug found 2026-07-20: every double-click launched
# a brand new invisible instance, 8 ended up running at once with zero
# feedback that anything had happened.
MUTEX_NAME = "TokenSaverSingleInstanceMutex"
ERROR_ALREADY_EXISTS = 183

POLL_INTERVAL_SECONDS = 0.7
MIN_TEXT_LENGTH_TO_ANALYZE = 20

# Real ask 2026-07-22: moving the badge to a newly-clicked box felt laggy
# because the watcher only noticed on its next scheduled poll, up to
# POLL_INTERVAL_SECONDS (0.7s) later. Rather than poll faster and burn CPU
# continuously, the low-level mouse hook now SETS this event on every real
# left-click, and watch_loop waits on it instead of sleeping, so a click
# wakes the loop within milliseconds while the idle cadence stays at 0.7s.
_focus_recheck_event = threading.Event()

# After a click wakes the loop, give the OS a beat to actually move
# keyboard focus into the clicked control before reading it. Chromium in
# particular transfers focus slightly after the mouse-up. 60ms is
# imperceptible next to the 700ms it replaces, and if it's still a hair
# early the normal poll a moment later corrects it.
FOCUS_SETTLE_AFTER_CLICK_SECONDS = 0.06

# Real direction correction 2026-07-20: the whole "gate" idea (rules OR AI,
# chosen by a confidence threshold) was the wrong model. Antonio was
# explicit: rules and the AI must WORK TOGETHER, not hijack each other, and
# there should be no confidence variable, one pipeline, same output for
# everyone. So there is no gate constant here anymore. The real pipeline
# (in the Apply handler) is: rules always do the safe deterministic cleanup
# first, then the AI always compresses that cleaned prompt holistically, the
# two stages feeding each other, see on_apply in watch_loop.

# The real product scope, corrected 2026-07-20: this is not a "works in any
# text field" tool, it's a tool that recognizes when you're talking to an
# LLM specifically (a known native app here, or a known site through the
# browser extension) and only activates there. Everywhere else, it stays
# fully invisible on purpose.
KNOWN_LLM_PROCESSES = {
    "claude.exe": "Claude",
    "chatgpt.exe": "ChatGPT",
    # Real gap found 2026-07-21: Antonio's actual installed app runs as
    # "chatgpt classic.exe", not "chatgpt.exe". Missing this meant it never
    # got app_label, so it fell through to the generic (non-LLM) badge
    # heuristic instead of the always-relative-to-the-box positioning built
    # for known LLM apps, see PersistentBadge._position_for. It happened to
    # look right in one screenshot purely because a leftover dragged
    # position coincided with that window's layout, not because the
    # mechanism was actually running.
    "chatgpt classic.exe": "ChatGPT",
}

# Real ask 2026-07-21: Gemini and Grok, and any other LLM that isn't its
# own installed desktop app the way Claude/ChatGPT Classic are. Both are
# just browser tabs, so process name alone is always "chrome.exe" or
# "msedge.exe" no matter which site is actually open, KNOWN_LLM_PROCESSES
# can never catch them by exe name. The window TITLE is the one signal a
# browser tab gives up that actually says which site it is.
BROWSER_PROCESS_NAMES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

# Matched case-insensitively against the browser tab's PAGE title, only
# when the process itself is a browser (see BROWSER_PROCESS_NAMES above).
# The original bare-substring match called the tab-merely-ABOUT-an-LLM
# false positive (a blog post titled "How Gemini Works") a harmless,
# accepted tradeoff. That judgment didn't survive the 2026-07-25 audit:
# "stay active on this tab" is the FULL pipeline, keystroke buffering and
# Apply's write machinery included, armed on a Reddit thread titled "Grok
# vs Claude benchmarks". A hint now has to BE the page title's leading or
# trailing dash-segment, not merely appear somewhere in the title, see
# _llm_title_match below.
LLM_TITLE_HINTS = {
    "gemini": "Gemini",
    "grok": "Grok",
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    # Real ask 2026-07-22: Perplexity and Copilot added the same way, but
    # UNVERIFIED, unlike the four above, which either came from a real
    # KNOWN_LLM_PROCESSES entry or Antonio's own debug.log. Neither
    # Perplexity nor Copilot has ever shown up in debug.log on this
    # machine, so these are a best-effort guess at their real tab titles,
    # not a confirmed match. If the badge doesn't show up correctly in
    # either, that's why, tell me and I'll check what their titles
    # actually are instead of guessing again.
    "perplexity": "Perplexity",
    "copilot": "Copilot",
    # Deliberately NOT adding a bare "meta" hint: unlike the others, it's
    # an ordinary word that shows up constantly outside any AI context
    # (Meta/Facebook's own properties, ads, unrelated pages), so it would
    # false-positive far more often than it would ever help. "meta ai" is
    # specific enough to be safe the same way the others are, but I don't
    # know if that's really what Meta AI's tab title looks like, same
    # caveat as Perplexity/Copilot above.
    "meta ai": "Meta AI",
    # More LLM web UIs (real ask 2026-07-22: "every single LLM"). Each hint is
    # a distinctive-enough substring of the tab title that it won't match
    # unrelated pages. Still best-effort until seen in a real debug.log.
    "deepseek": "DeepSeek",
    "le chat": "Le Chat",      # Mistral's chat
    "mistral": "Mistral",
    "poe.com": "Poe",
    "huggingchat": "HuggingChat",
    "hugging face": "Hugging Face",
    "you.com": "You.com",
    "phind": "Phind",
    "pi.ai": "Pi",
    "character.ai": "Character.AI",
}

# Real ask 2026-07-26 (Antonio, direct): recognize an AI CLI (Claude Code,
# etc.) running INSIDE a terminal, not just the desktop app / browser tab
# cases above. Explicitly scoped narrower than "any terminal typing" --
# Antonio's own call: a bare shell prompt (a git command, a plain `ls`)
# must NOT activate this, only an actual AI CLI running in the foreground.
#
# A terminal host process (PowerShell, Windows Terminal, cmd, git bash...)
# has no structured "compose box" UIA can point at -- it's one scrolling
# character buffer, not a real control -- so this can't reuse
# KNOWN_LLM_PROCESSES/app-name matching the way the desktop app case does.
#
# FIRST ATTEMPT (window title matching, same idea as LLM_TITLE_HINTS
# above) was flat wrong: Antonio confirmed the terminal's title is just
# his own custom session name ("Venture Assistant"), never anything
# containing "claude" -- a terminal's title is arbitrary and user-chosen,
# so it can never be a reliable signal here. Removed rather than kept
# disabled, since it was built on a wrong assumption.
#
# What actually works: checked the real process tree live
# (Get-CimInstance Win32_Process) while a genuine Claude Code CLI session
# was running, and confirmed it launches as a literal child process named
# "claude.exe" (`C:\Users\anton\.local\bin\claude.exe --resume`), a few
# levels below the terminal's own process (terminal -> powershell.exe ->
# claude.exe). Walking the process tree for a known AI CLI descendant is
# what this uses instead of the title.
TERMINAL_HOST_PROCESSES = {
    "windowsterminal.exe", "powershell.exe", "pwsh.exe", "cmd.exe",
    "conhost.exe", "wt.exe", "git.exe", "bash.exe", "wsl.exe",
    # VS Code and its forks host a real terminal too, so they go through the
    # same AI-CLI-descendant gate as every other terminal above. See
    # VSCODE_PROCESSES for the extra check that keeps the badge out of the
    # code editor.
    "code.exe", "cursor.exe", "windsurf.exe",
}

# VS Code, Cursor and Windsurf are Electron, so the integrated terminal is not
# a TermControl the way Windows Terminal's is. Measured live 2026-11-22 with
# tools_probe_surfaces.py, not inferred:
#
#   EditControl  7x17  rect=(422,-467,429,-450)
#   name='Terminal 1, [kbd] Orchestrator  Run the command: Toggle Screen...'
#
# Two things follow. First, the accessible name begins "Terminal <n>," while
# focus is in the integrated terminal and does not while focus is in the
# editor, which is the only reliable way to tell the two apart. Without that
# check, recognising code.exe would put a badge on screen while you are
# writing code, which is worse than not supporting it at all.
#
# Second, that 7x17 rect is the CARET, not the box: successive readings came
# back at x=1244, 1409, 1541, 1629, 1684, 1772 at a fixed height as text was
# typed. Anchoring to it would make the badge chase the cursor, the same
# mistake already learned and documented for dictation further down this file.
# _vscode_terminal_pane_rect walks up to the real pane instead.
VSCODE_PROCESSES = {"code.exe", "cursor.exe", "windsurf.exe"}
VSCODE_TERMINAL_NAME_PREFIX = "terminal "
# The caret is a handful of pixels wide. A real pane is orders of magnitude
# bigger, so this tells the two apart without hardcoding either size.
VSCODE_MIN_PANE_AREA_RATIO = 20
# Which AI CLIs count as "a chat is happening in this terminal".
#
# Process name only, which means a CLI has to ship a real, distinctly named
# executable to be detectable here. Verified on this machine 2026-11-22:
#
#   claude.exe   real PE executable            -> detectable
#   copilot.exe  real PE executable            -> detectable
#   codex        npm shim, runs as node.exe    -> NOT detectable
#
# Codex CLI is deliberately absent. Its launcher is a .cmd that execs
# `node.exe codex.js`, so the only process name in the tree is node.exe, and
# matching that would activate the badge under ANY node process. Supporting it
# needs command line inspection, not a name. Gemini CLI is unverified: it was
# not installed here, and being npm distributed it is likely the same shape.
#
# The website claimed all four for months. Three of them were never detected.
AI_CLI_DESCENDANT_PROCESSES = {
    "claude.exe": "Claude Code",
    "copilot.exe": "Copilot CLI",
    # Measured 2026-11-23 with tools_measure_cli_trees.py: Codex spawns a real
    # native binary alongside its node shim, vendored at
    # @openai/codex-win32-x64/vendor/.../bin/codex.exe, so a plain name match
    # works and no command line reading is needed for it.
    "codex.exe": "Codex CLI",
}

# CLIs that run as node and nothing else, so a process NAME can never identify
# them. Measured 2026-11-23: Gemini's whole tree is node.exe, node.exe,
# conhost, cmd and powershell, with no distinctly named binary anywhere.
#
# Matching bare node.exe is not an option: it would light the badge under any
# node process at all, a dev server, a build, this repo's own test runner. So
# these are matched on the PACKAGE ENTRY PATH inside the command line, which a
# dev server never has. Both separators are listed because the command line
# carries whichever the launcher used.
#
# Kept deliberately narrow. A marker here must be a package path, never a bare
# word like "gemini" that a filename or a cwd could contain by accident.
AI_CLI_CMDLINE_MARKERS = (
    (("@google/gemini-cli", r"@google\gemini-cli"), "Gemini CLI"),
    # Codex is already caught by codex.exe above. This is a fallback for a
    # future build that drops the native binary, and costs nothing.
    (("@openai/codex", r"@openai\codex"), "Codex CLI"),
)

# Only these process names are ever worth reading a command line for. Anything
# else is matched by name or not at all, so the expensive path stays rare.
CMDLINE_CHECK_PROCESSES = {"node.exe"}

TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _process_tree_snapshot():
    """{pid: (parent_pid, lower-case exe name)} for every running process,
    via the classic Toolhelp32 snapshot API. Returns {} on any failure --
    same fallback discipline as everywhere else in this file: a failed
    lookup here should just mean "no AI CLI found", never a crash."""
    snapshot = {}
    h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not h or h == -1:
        return snapshot
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = ctypes.windll.kernel32.Process32FirstW(h, ctypes.byref(entry))
        while ok:
            snapshot[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.lower())
            ok = ctypes.windll.kernel32.Process32NextW(h, ctypes.byref(entry))
    except Exception:
        pass
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    return snapshot


# Needed to read another process's PEB. VM_READ is the one that matters and
# is only granted for processes the current user owns, which is exactly the
# scope wanted: a CLI the user launched in their own terminal.
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

# Prototypes matter here. ctypes defaults a return type to c_int, which is 32
# bits, so a 64-bit HANDLE would be silently truncated and every later call on
# it would fail or, worse, act on a different object. Same reason the file
# already pins GetKeyState's restype further down.
_k32 = ctypes.windll.kernel32
_ntdll = ctypes.windll.ntdll
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.ReadProcessMemory.restype = wintypes.BOOL
_k32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
_k32.GetProcessTimes.restype = wintypes.BOOL
_k32.GetProcessTimes.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
]
_ntdll.NtQueryInformationProcess.restype = ctypes.c_long
_ntdll.NtQueryInformationProcess.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_ulong),
]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ushort),
                ("MaximumLength", ctypes.c_ushort),
                ("Buffer", ctypes.c_void_p)]


class _PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("Reserved1", ctypes.c_void_p),
                ("PebBaseAddress", ctypes.c_void_p),
                ("Reserved2", ctypes.c_void_p * 2),
                ("UniqueProcessId", ctypes.c_void_p),
                ("Reserved3", ctypes.c_void_p)]


# Offsets into the 64-bit PEB and RTL_USER_PROCESS_PARAMETERS. Stable across
# every supported Windows version; the app is x64 only (the Store package is
# x64, min 10.0.17763.0), so there is no WOW64 case to handle.
_PEB_PROCESS_PARAMETERS_OFFSET = 0x20
_PARAMS_COMMANDLINE_OFFSET = 0x70

# Keyed by (pid, creation time), NEVER by pid alone.
#
# Windows recycles PIDs aggressively. A Gemini node.exe cached as "Gemini CLI"
# can exit and a dev server's node.exe can be handed the same pid minutes
# later, at which point a pid-only cache would answer "Gemini CLI" for it and
# put a badge over an unrelated terminal. That is a false POSITIVE, so it
# breaks the fail-closed guarantee rather than merely being stale.
#
# A process's creation time is unique for the life of that process, so the
# pair identifies one specific process instance and a recycled pid simply
# misses the cache and is read fresh.
_cmdline_cache = {}
_CMDLINE_CACHE_MAX = 64


def _process_creation_time(handle):
    """The process's creation time as an int, or None if unreadable.

    Used only to make the cache key identify a process INSTANCE rather than a
    pid. None means no caching for that process, which is correct: better to
    re-read than to risk answering for a recycled pid.
    """
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not _k32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                ctypes.byref(kernel), ctypes.byref(user)):
        return None
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


def _process_command_line(pid):
    """A process's command line, or None if it cannot be read.

    Reads the PEB directly rather than taking a psutil or WMI dependency: the
    app ships with a fixed, audited requirements list and this is the only
    place that needs a command line. A WMI query would also cost about a
    second, which is unusable on a 0.7s loop.

    FAILS CLOSED in every failure mode. A process that has exited, one owned
    by another user, an elevated one, a partial read: all return None, and a
    None means the caller does not match, so the badge stays hidden.

    Only called for the handful of names in CMDLINE_CHECK_PROCESSES, and only
    for processes already found inside a terminal's own descendant tree.
    """
    handle = _k32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return None
    try:
        # Identify the process INSTANCE before trusting any cached answer, so
        # a recycled pid can never inherit the previous process's command
        # line. See the _cmdline_cache comment.
        created = _process_creation_time(handle)
        key = (pid, created) if created is not None else None
        if key is not None:
            cached = _cmdline_cache.get(key)
            if cached is not None:
                return cached
        pbi = _PROCESS_BASIC_INFORMATION()
        written = ctypes.c_ulong()
        status = _ntdll.NtQueryInformationProcess(
            handle, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(written))
        if status != 0 or not pbi.PebBaseAddress:
            return None

        def _read(address, size):
            buf = (ctypes.c_char * size)()
            got = ctypes.c_size_t()
            ok = _k32.ReadProcessMemory(
                handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got))
            if not ok or got.value != size:
                return None
            return bytes(buf)

        peb = ctypes.cast(pbi.PebBaseAddress, ctypes.c_void_p).value
        raw_ptr = _read(peb + _PEB_PROCESS_PARAMETERS_OFFSET, 8)
        if not raw_ptr:
            return None
        params = int.from_bytes(raw_ptr, "little")

        raw_us = _read(params + _PARAMS_COMMANDLINE_OFFSET,
                       ctypes.sizeof(_UNICODE_STRING))
        if not raw_us:
            return None
        length = int.from_bytes(raw_us[0:2], "little")
        buffer_ptr = int.from_bytes(raw_us[8:16], "little")
        # A command line longer than 32KB is not a real one; refuse rather
        # than allocate on a number read out of another process's memory.
        if not length or not buffer_ptr or length > 32768:
            return None

        raw = _read(buffer_ptr, length)
        if not raw:
            return None
        value = raw.decode("utf-16-le", "replace")
    except Exception:
        return None
    finally:
        _k32.CloseHandle(handle)

    if key is not None:
        if len(_cmdline_cache) >= _CMDLINE_CACHE_MAX:
            _cmdline_cache.clear()
        _cmdline_cache[key] = value
    return value


def _ai_cli_label_from_cmdline(pid):
    """Match a node process against the known package entry paths."""
    cmdline = _process_command_line(pid)
    if not cmdline:
        return None
    lowered = cmdline.lower()
    for markers, label in AI_CLI_CMDLINE_MARKERS:
        for marker in markers:
            if marker.lower() in lowered:
                return label
    return None


def _find_ai_cli_descendant(root_pid):
    """Breadth-first search down the process tree from root_pid (the
    foreground terminal's own PID) for any process matching
    AI_CLI_DESCENDANT_PROCESSES. Returns the matched label, or None."""
    snapshot = _process_tree_snapshot()
    if not snapshot:
        return None
    children_by_parent = {}
    for pid, (parent_pid, _name) in snapshot.items():
        children_by_parent.setdefault(parent_pid, []).append(pid)
    queue = list(children_by_parent.get(root_pid, []))
    seen = set(queue)
    while queue:
        pid = queue.pop(0)
        _parent, name = snapshot.get(pid, (None, ""))
        label = AI_CLI_DESCENDANT_PROCESSES.get(name)
        if label is not None:
            return label
        # Name told us nothing. For the few names that can only ever be
        # identified by what they are RUNNING (node), fall back to the command
        # line. Everything else is left alone, so the expensive read stays
        # rare and bare node.exe is never matched on its own.
        if name in CMDLINE_CHECK_PROCESSES:
            label = _ai_cli_label_from_cmdline(pid)
            if label is not None:
                return label
        for child in children_by_parent.get(pid, []):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return None


# Real ask 2026-07-27, pre-market audit (Antonio, direct: paste appears
# instantly, typing visibly doesn't, "is there any way at all"): researched
# and verified live in isolated disposable terminal windows, never touching
# a real session. WriteConsoleInputW writes a whole batch of key events
# into a target console's input buffer in one atomic call, instead of
# SendKeys' throttled one-keystroke-at-a-time loop with a sleep between
# each. Confirmed live: still reads as real keystrokes (doesn't trip Claude
# Code CLI's bracketed-paste "large paste" dialog / [Pasted text #N]
# placeholder the way an actual OS clipboard paste does), lands correctly,
# and a properly-built Ctrl+U-equivalent clears a line with zero residue.
#
# The one real gap: this needs a specific process ID to attach its console
# to (AttachConsole), unlike SendKeys, which just goes wherever OS keyboard
# focus currently is. A Windows Terminal window's OWN process is never the
# right PID (it's the pseudoconsole HOST, not the shell reading input) --
# the actual shell (powershell.exe, cmd.exe, etc.) is a direct CHILD
# process of it, one per tab/pane. With more than one tab open, there's no
# supported, reliable way from outside to tell which child belongs to the
# currently active pane specifically, so _find_unique_terminal_shell_pid
# below deliberately refuses to guess whenever there's more than one
# candidate -- same fail-closed-only-when-certain rule as everywhere else
# in this file.
TERMINAL_SHELL_PROCESS_NAMES = {
    "powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe", "wsl.exe", "git.exe",
}

_KEY_EVENT = 0x0001
_VK_CONTROL = 0x11
_VK_U = 0x55
_LEFT_CTRL_PRESSED = 0x0008
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_OPEN_EXISTING = 3


class _ConsoleKeyEventRecord(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("UnicodeChar", wintypes.WCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class _ConsoleInputRecord(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("KeyEvent", _ConsoleKeyEventRecord)]


# use_last_error=True and explicit argtypes/restype throughout: handles are
# 64-bit pointers, and ctypes silently truncating them to a 32-bit int is a
# known, previously-hit bug class in this exact file (main.py's
# GWLP_HWNDPARENT fix). Cheap insurance against a wrong handle value here.
_console_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_console_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_console_kernel32.CreateFileW.restype = wintypes.HANDLE
_console_kernel32.WriteConsoleInputW.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
_console_kernel32.WriteConsoleInputW.restype = wintypes.BOOL
_console_kernel32.AttachConsole.argtypes = [wintypes.DWORD]
_console_kernel32.AttachConsole.restype = wintypes.BOOL
_console_kernel32.FreeConsole.restype = wintypes.BOOL


def _find_unique_terminal_shell_pid(hwnd):
    """The direct child shell process of this terminal window's own
    process, if there is EXACTLY ONE. Returns None (never a guess) when
    there's zero or more than one candidate -- see the block comment above
    for why multiple tabs/panes make this genuinely ambiguous from
    outside, not just inconvenient to determine."""
    try:
        wt_pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wt_pid))
        if not wt_pid.value:
            return None
        snapshot = _process_tree_snapshot()
        if not snapshot:
            return None
        candidates = [
            pid for pid, (parent_pid, name) in snapshot.items()
            if parent_pid == wt_pid.value and name in TERMINAL_SHELL_PROCESS_NAMES
        ]
        # Real gap found 2026-07-27 (pre-market audit): this used to return
        # silently on ambiguity, with no way to tell from the log whether
        # "multiple terminal sessions open" was actually why the fast path
        # never engages, versus something else going wrong. Windows
        # Terminal runs as ONE process for every window it owns, not one
        # process per window, so this candidate count reflects shell
        # processes across ALL open terminal windows/tabs system-wide, not
        # just this one -- expected to be >1 whenever more than a single
        # terminal session is open anywhere, which logging makes visible
        # instead of silent.
        if len(candidates) != 1:
            log(f"_find_unique_terminal_shell_pid: {len(candidates)} candidate(s), declining (need exactly 1)")
            return None
        return candidates[0]
    except Exception:
        log_exception("_find_unique_terminal_shell_pid")
        return None


def _console_key_record(vk, ch, down, ctrl_state=0):
    rec = _ConsoleInputRecord()
    rec.EventType = _KEY_EVENT
    rec.KeyEvent.bKeyDown = down
    rec.KeyEvent.wRepeatCount = 1
    rec.KeyEvent.wVirtualKeyCode = vk
    rec.KeyEvent.wVirtualScanCode = 0
    rec.KeyEvent.UnicodeChar = ch
    rec.KeyEvent.dwControlKeyState = ctrl_state
    return rec


def _console_text_records(text):
    """Plain character key events, VK=0 -- verified live 2026-07-27: real
    console input processing still accepts and inserts these as literal
    text even without a matching virtual-key code."""
    records = []
    for ch in text:
        records.append(_console_key_record(0, ch, True))
        records.append(_console_key_record(0, ch, False))
    return records


def _console_ctrl_u_records():
    """A correctly-built Ctrl+U: VK_CONTROL down, then 'U' down carrying
    both the LEFT_CTRL_PRESSED state flag AND the real ASCII control code
    (0x15) as UnicodeChar, then both up in reverse -- mirrors what a real
    keyboard produces for this combo. Verified live 2026-07-27 in an
    isolated disposable Claude Code CLI window: fully cleared a real typed
    line with zero residue, same as SendKeys' Ctrl+U does today."""
    return [
        _console_key_record(_VK_CONTROL, "\x00", True, _LEFT_CTRL_PRESSED),
        _console_key_record(_VK_U, "\x15", True, _LEFT_CTRL_PRESSED),
        _console_key_record(_VK_U, "\x15", False, _LEFT_CTRL_PRESSED),
        _console_key_record(_VK_CONTROL, "\x00", False, 0),
    ]


def _write_console_records(pid, records):
    """Attaches to pid's console, writes a whole batch of key events in
    one atomic call (no artificial per-key delay, unlike SendKeys),
    detaches cleanly afterward either way. Returns True only if the
    console was reached AND every record was accepted -- any failure means
    the caller should treat this as if nothing happened and fall back to
    the proven SendKeys mechanism, not retry this path.

    Real bug found live 2026-07-27 (isolated testing): this process may
    already be attached to a console inherited from whatever launched it;
    AttachConsole fails with ERROR_ACCESS_DENIED unless FreeConsole runs
    first, since a process can only be attached to one console at a time."""
    try:
        _console_kernel32.FreeConsole()
        if not _console_kernel32.AttachConsole(pid):
            return False
        try:
            h_in = _console_kernel32.CreateFileW(
                "CONIN$", _GENERIC_READ | _GENERIC_WRITE,
                _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_EXISTING, 0, None,
            )
            if not h_in or h_in == wintypes.HANDLE(-1).value:
                return False
            arr = (_ConsoleInputRecord * len(records))(*records)
            written = wintypes.DWORD(0)
            ok = _console_kernel32.WriteConsoleInputW(h_in, arr, len(records), ctypes.byref(written))
            return bool(ok) and written.value == len(records)
        finally:
            _console_kernel32.FreeConsole()
    except Exception:
        log_exception("_write_console_records")
        return False


# Real gap found 2026-07-25, from Antonio's own debug.log: right after
# "browser tab mentions 'Claude' but it isn't the page itself, staying
# inactive" the very next lines show the focused control's own name as
# "Describe an app idea" / "Describe what you want to create..." -- that's
# Claude's own app-building mode, on claude.ai, not a page merely ABOUT
# Claude. Its tab title just never puts "Claude" in its own leading/
# trailing dash segment (Comprsly can't log the literal title to confirm
# the exact format, see the privacy note on _window_title, so the real
# fix isn't "guess a new title shape" -- it's stop trusting the title
# alone. KNOWN_LLM_DOMAINS below is read from the browser's own address
# bar (see _read_omnibox_url), which says what SITE this actually is
# regardless of whatever an SPA does with document.title.
KNOWN_LLM_DOMAINS = {
    "claude.ai": "Claude",
    "chatgpt.com": "ChatGPT",
    "chat.openai.com": "ChatGPT",
    "gemini.google.com": "Gemini",
    "perplexity.ai": "Perplexity",
    "grok.com": "Grok",
    "x.ai": "Grok",
    "chat.deepseek.com": "DeepSeek",
    "chat.mistral.ai": "Le Chat",
    "poe.com": "Poe",
    "huggingface.co": "Hugging Face",
    "you.com": "You.com",
    "pi.ai": "Pi",
    "character.ai": "Character.AI",
    "copilot.microsoft.com": "Copilot",
}


def _llm_domain_match(url):
    """Real hostname match against KNOWN_LLM_DOMAINS. `url` is whatever the
    omnibox's ValuePattern reports, which for Chrome/Edge is normally the
    display form with the "https://" scheme already elided, so this has to
    accept a bare host too, not just a real URL."""
    if not url:
        return None
    host = url.strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0].split(":")[0]
    for domain, name in KNOWN_LLM_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def _read_omnibox_url(hwnd):
    """The browser's real address-bar VALUE, read via UI Automation without
    needing it to be focused -- Chrome/Edge/Brave/Opera all expose it as an
    EditControl named 'Address and search bar' (confirmed live in
    debug.log 2026-07-25: 'focused control: EditControl/"OmniboxViewViews"
    name=\"Address and search bar\"'), findable anywhere in the window's own
    tree. searchDepth is bounded on purpose -- the omnibox lives in
    Chrome's native toolbar, a few levels deep, well short of the page
    content's own (potentially huge) accessibility tree, so an unbounded
    search would risk walking the whole page for nothing."""
    try:
        win = auto.ControlFromHandle(hwnd)
        if win is None:
            return None
        omnibox = win.EditControl(searchDepth=8, Name="Address and search bar")
        if not omnibox.Exists(0, 0):
            return None
        value_pattern = _safe_pattern(omnibox, PatternId.ValuePattern)
        if value_pattern is None:
            return None
        return value_pattern.Value or None
    except Exception:
        return None


# Keyed by (hwnd, title): avoids re-walking the UI tree every 0.7s poll
# while the same tab stays in the foreground -- only a real navigation or
# an SPA title change produces a new key. Unbounded growth isn't a real
# risk (every browser tab/title pair the user visits in one run, capped
# below anyway), but it's cleared past a small size regardless since this
# is a hot-loop cache, not a real store.
_domain_match_cache = {}


def _domain_label_for(hwnd, title):
    key = (hwnd, title)
    cached = _domain_match_cache.get(key, False)
    if cached is not False:
        return cached
    if len(_domain_match_cache) > 64:
        _domain_match_cache.clear()
    label = _llm_domain_match(_read_omnibox_url(hwnd))
    _domain_match_cache[key] = label
    return label


# Chrome/Edge side panels (2026-07-30) -- a side panel is a docked WebUI
# pane that never repaints the outer tab's title or address bar, so
# neither _llm_title_match nor _domain_label_for can ever catch it, no
# matter how the hint/domain lists are tuned (both read signals a side
# panel structurally doesn't touch). Confirmed live in a real debug.log:
# the Gemini side panel's own focused control reported
# Name='Gemini Chrome :: New Conversation' on two separate occasions, a
# few minutes apart, while the underlying tab's title stayed 'New Tab'
# the whole time -- exactly the gap the "unrecognized browser tab" +
# ancestor-walk diagnostic (see its 2026-07-25 comment) was logging in
# wait of. A control's accessible NAME is a different kind of signal
# than a window title or a URL, so this is its own check, not folded
# into either existing one.
KNOWN_SIDE_PANEL_NAME_PREFIXES = {
    "Gemini Chrome ::": "Gemini",
}


def _side_panel_label_for(hwnd):
    """Whichever known side panel is currently focused, by its content's
    own accessible Name, or None. Only ever consulted after both the title
    and domain checks already came up empty (see app_label_for) -- a side
    panel's docked pane sits alongside a real tab, so this must not run
    first and shadow an actual full-tab match.

    Real bug found live 2026-08-03 (Antonio, screenshot + a live UIA
    diagnostic run while he had the real composer focused): this only
    checked the immediately-focused control's OWN Name, which is
    'Gemini Chrome :: <conversation title>' while the message thread/
    document area has focus, but becomes something else entirely (e.g.
    'Enter a prompt for Gemini') the instant focus moves into the actual
    textarea -- exactly the moment someone is about to type. The prefixed
    Name is still there, just one or more ancestors up, so this now walks
    up looking for it instead of only ever checking the single deepest
    element, the same ancestor-walk pattern every other detector in this
    file already uses for exactly this reason.

    CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Ok lock it it works
    that was amazing"). Do not retune the ancestor-walk depth or the
    prefix matching without a new real ask."""
    try:
        node = auto.GetFocusedControl()
    except Exception:
        return None
    for _ in range(15):
        if node is None:
            return None
        try:
            name = node.Name
        except Exception:
            name = None
        if name:
            for prefix, label in KNOWN_SIDE_PANEL_NAME_PREFIXES.items():
                if name.startswith(prefix):
                    return label
        try:
            node = node.GetParentControl()
        except Exception:
            return None
    return None


# A same-day search-engine right-anchor feature (SEARCH_ENGINE_TITLE_HINTS /
# is_search_engine_page) briefly lived here, then was removed: Comprsly's
# scope changed to LLM-only (see the DEFAULT_SETTINGS note on cat_ai_chat)
# before it ever shipped, which makes a search-engine box unreachable -- it's
# never `active` (app_label is None there), so the badge never shows on one
# at all, and the positioning fix would have been dead code from the start.


# Title shapes _llm_title_match assumes, from real titles seen in debug.log
# plus how the browsers themselves compose them:
#   - A tab title is "<page title>", optionally with a trailing
#     " - <Browser>" suffix (Firefox joins with an em dash: "<page title>
#     — Mozilla Firefox"), and the browser part may carry decorations
#     ("Google Chrome (Incognito)", "Mozilla Firefox Private Browsing"),
#     hence the startswith test rather than equality.
#   - An unread-count prefix "(2) " may precede everything.
#   - LLM sites put their product name FIRST ("Gemini", "ChatGPT") or LAST
#     ("<conversation name> - Claude") in the page title, as its own
#     dash-separated segment, never buried mid-sentence. A mid-title
#     mention ("Grok vs Claude benchmarks : r/LocalLLaMA", "Why ChatGPT is
#     overhyped - YouTube") is a page ABOUT an LLM, not an LLM.
#   - Directionality/zero-width marks carry no meaning and are stripped
#     before comparing (Edge's own suffix ships a U+200B).
# NOT handled, deliberately: an extra profile segment between the site name
# and the browser suffix ("<conversation> - Claude - Personal - Microsoft
# Edge") goes inactive. Precision over recall on purpose: this gate arms
# Apply's write machinery, so a missed tab costs a badge, a false positive
# costs someone's text box.
_TITLE_UNREAD_PREFIX_RE = re.compile(r"^\(\d+\)\s+")
# ZERO WIDTH SPACE, LEFT-TO-RIGHT/RIGHT-TO-LEFT MARK, BOM. Escapes, not
# literals: these are invisible in an editor by definition.
_TITLE_INVISIBLE_MARKS = dict.fromkeys(map(ord, "​‎‏﻿"))
_BROWSER_TITLE_SUFFIX_NAMES = (
    "google chrome", "microsoft edge", "mozilla firefox", "brave", "opera",
    "vivaldi",
)


# Real company names only, never a connecting word like "vs"/"why"/"is" --
# see the comment inside _llm_title_match for why this set has to stay small
# and genuinely corporate.
_LLM_TITLE_COMPANY_QUALIFIERS = {"google", "microsoft", "meta", "amazon", "x"}


def _llm_title_match(title):
    """Strict replacement (2026-07-25 audit) for the old `hint in title`
    check: returns the LLM_TITLE_HINTS label only when the hint IS the page
    title's leading or trailing segment, None otherwise. Pure text-in/
    label-out on purpose so it can be probed without a real window."""
    t = title.translate(_TITLE_INVISIBLE_MARKS).lower()
    t = _TITLE_UNREAD_PREFIX_RE.sub("", t).strip()
    t = t.replace(" — ", " - ").replace(" – ", " - ")  # em/en dash
    segments = [s.strip() for s in t.split(" - ") if s.strip()]
    if len(segments) > 1 and any(
        segments[-1] == b or segments[-1].startswith(b + " ")
        for b in _BROWSER_TITLE_SUFFIX_NAMES
    ):
        segments = segments[:-1]
    if not segments:
        return None
    for hint, name in LLM_TITLE_HINTS.items():
        if segments[0] == hint or segments[-1] == hint:
            return name
    # Company-qualified product name (real regression 2026-07-25, found live
    # on stream): Google's actual page title is "Google Gemini", not bare
    # "Gemini" -- the exact-segment rule above never matches it, so the
    # audit's own stricter matcher silently broke a hint that had worked for
    # months. A generic word-boundary loosening would undo the fix it just
    # replaces (the rejected Reddit example, "grok vs claude benchmarks",
    # ALSO starts with the word "grok"). This is narrower on purpose: only a
    # segment of EXACTLY two words, whose first word is a small closed set
    # of real company names, not "vs"/"why"/"is"/etc. A sentence about a
    # product is never a bare two-word "Company Product" phrase.
    for seg in (segments[0], segments[-1]):
        words = seg.split(" ")
        if len(words) == 2 and words[0] in _LLM_TITLE_COMPANY_QUALIFIERS:
            name = LLM_TITLE_HINTS.get(words[1])
            if name is not None:
                return name
    return None


# Rate-limits the old-rule/new-rule disagreement line in app_label_for: the
# check re-runs on every 0.7s poll of the same foreground tab. Holds the
# last hint label logged.
_title_reject_logged = [None]
# Same rate-limit idea, for the terminal/AI-CLI check below.
_terminal_no_match_logged = [False]


def _vscode_focus_is_terminal():
    """True when focus is in VS Code's integrated terminal, not the editor.

    Gated on the focused control's accessible name, which begins
    "Terminal <n>," in the terminal pane and does not in the editor. See
    VSCODE_PROCESSES for the measurements behind this.

    Deliberately fails CLOSED: anything unreadable returns False, so an
    unexpected UIA state leaves the badge hidden rather than putting it on
    top of somebody's code.
    """
    try:
        node = auto.GetFocusedControl()
        if node is None:
            return False
        name = (node.Name or "").strip().lower()
    except Exception:
        return False
    return name.startswith(VSCODE_TERMINAL_NAME_PREFIX)


def _vscode_terminal_pane_rect(control):
    """Walk up from the caret to the terminal pane it sits in.

    The focused control in VS Code's terminal is the caret itself, a few
    pixels wide, and it moves as you type. The pane is several ancestors up,
    and the parent DIRECTLY above the caret shares the caret's own rect, so
    the walk has to keep going rather than stopping at the first parent.

    Returns a _SimpleRect for the first ancestor whose area is at least
    VSCODE_MIN_PANE_AREA_RATIO times the caret's, or None if the chain runs
    out, in which case the caller keeps its existing behaviour.
    """
    try:
        r = control.BoundingRectangle
        caret_area = max(1, (r.right - r.left) * (r.bottom - r.top))
    except Exception:
        return None

    node = control
    for _ in range(8):
        try:
            node = node.GetParentControl()
        except Exception:
            return None
        if node is None:
            return None
        try:
            pr = node.BoundingRectangle
        except Exception:
            return None
        area = (pr.right - pr.left) * (pr.bottom - pr.top)
        if area >= caret_area * VSCODE_MIN_PANE_AREA_RATIO:
            return _SimpleRect(pr.left, pr.top, pr.right, pr.bottom)
    return None


# Terminal badge rule (2026-11-25, Antonio, by name): on every terminal the
# badge sits at the RIGHT END OF THE INPUT LINE, inside the pane, and never on
# top of typed text. Measured from the live log first: in VS Code the focused
# control is the 11 px wide caret, and _position_for treats anything under
# 100 px wide as "dock just LEFT of it", so the badge rode on top of the text
# the user had just typed. _vscode_terminal_pane_rect existed for exactly this
# and was never called.
#
# The rect returned spans the pane's full width (so _position_for docks at the
# right edge) and the input line's height (so it is centred on that line).
# When the caret itself has reached the badge's column, the line is about to be
# typed under the badge, so the rect drops one line to the row below, which is
# empty or the input box's own bottom border.
TERMINAL_BADGE_CLEARANCE = S(8)


def _terminal_badge_rect(control, process_name, hwnd, caret_rect):
    try:
        if process_name in VSCODE_PROCESSES:
            pane = _vscode_terminal_pane_rect(control)
            if pane is None:
                return None
            top, bottom = caret_rect.top, caret_rect.bottom
            line_h = max(1, bottom - top)
            badge_left = pane.right - BADGE_ICON_SIZE - BADGE_INSIDE_INSET - TERMINAL_BADGE_CLEARANCE
            if caret_rect.right >= badge_left:
                top, bottom = top + line_h, bottom + line_h
            return _SimpleRect(pane.left, top, pane.right, bottom)
        # Windows Terminal and the classic consoles: the control is the whole
        # pane, so find the live input line from the CLI's own text.
        get_tp = getattr(control, "GetTextPattern", None)
        text_pattern = get_tp() if get_tp else None
        if text_pattern is None:
            return None
        line = _find_terminal_input_line_rect(text_pattern, hwnd)
        if line is None:
            return None
        return _SimpleRect(caret_rect.left, line.top, caret_rect.right, line.bottom)
    except Exception as e:
        log_exception(f"_terminal_badge_rect: {e!r}")
        return None


def app_label_for(process_name, hwnd):
    """Known-LLM label for whatever's in the foreground right now: by
    process name first (a real installed desktop app), then by browser tab
    title (anything that's only ever a website, never its own exe)."""
    label = KNOWN_LLM_PROCESSES.get(process_name)
    if label is not None:
        return label
    if process_name in TERMINAL_HOST_PROCESSES:
        # VS Code and its forks are the one terminal host where the window
        # also contains a code editor, so a running AI CLI is not on its own
        # enough: focus has to actually be in the terminal pane. Checked
        # before the process-tree walk because it is much cheaper.
        if process_name in VSCODE_PROCESSES and not _vscode_focus_is_terminal():
            return None
        # Process-tree check, not the title (see AI_CLI_DESCENDANT_PROCESSES
        # above for why the title never worked). Nothing content-derived is
        # logged here either way, just whether a known AI CLI process was
        # found running underneath this terminal.
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        label = _find_ai_cli_descendant(pid.value)
        if label is not None:
            _terminal_no_match_logged[0] = False
            return label
        if not _terminal_no_match_logged[0]:
            _terminal_no_match_logged[0] = True
            log(f"terminal foreground ({process_name}), no AI CLI descendant process found, staying inactive")
        return None
    if process_name in BROWSER_PROCESS_NAMES:
        title = _raw_window_title(hwnd)
        label = _llm_title_match(title)
        if label is not None:
            return label
        # Real fix 2026-07-25: the title alone can't see Claude's own
        # app-building mode (see the KNOWN_LLM_DOMAINS comment above), so
        # before giving up, check what site the address bar actually says
        # this is -- a signal an SPA's document.title can't hide.
        label = _domain_label_for(hwnd, title)
        if label is not None:
            return label
        # Neither the title nor the URL can see INTO a docked side panel
        # (see KNOWN_SIDE_PANEL_NAME_PREFIXES) -- last resort before giving
        # up on this browser tab entirely.
        label = _side_panel_label_for(hwnd)
        if label is not None:
            return label
        # Migration breadcrumb for the stricter matcher: name WHICH hint
        # the old anywhere-in-the-title rule would have activated on, so a
        # "badge stopped showing on <site>" report is checkable against
        # debug.log. Hint label only, NEVER the title -- titles are
        # conversation-derived, same privacy rule as _window_title.
        lowered = title.lower()
        for hint, name in LLM_TITLE_HINTS.items():
            if hint in lowered:
                if _title_reject_logged[0] != name:
                    _title_reject_logged[0] = name
                    log(
                        f"browser tab mentions '{name}' but it isn't the "
                        f"page itself (old substring rule would have "
                        f"activated), staying inactive"
                    )
                break
    return None


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _process_name_for_hwnd(hwnd):
    """Lower-case exe name (e.g. 'claude.exe') owning this window, or None
    if it can't be determined. Factored out of get_foreground_window_and_
    process below (2026-07-26) so apply_new_text can ask the same question
    about a specific already-captured target_hwnd, not just whatever's
    foreground right now."""
    try:
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        hproc = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
        )
        if not hproc:
            return None
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.c_uint(260)
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                hproc, 0, buf, ctypes.byref(size)
            )
            if not ok:
                return None
            return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(hproc)
    except Exception:
        return None


def get_foreground_window_and_process():
    """Returns (hwnd, lower-case exe name e.g. 'claude.exe') of whatever
    window currently has focus, process name is None if it can't be
    determined. Real bug found 2026-07-20: clicking the popup's own Apply
    button (a Tk Button, which grabs OS focus on click even through this
    window's WS_EX_NOACTIVATE style, a known Tk-on-Windows quirk) shifts the
    real foreground window to OUR OWN popup, not Claude. Returning the hwnd
    here lets the caller remember which window was really Claude's right
    before that happens, so apply_new_text can force it back before pasting,
    see SetForegroundWindow call there."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return hwnd, _process_name_for_hwnd(hwnd)


class _SimpleRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def get_caret_screen_rect():
    """For apps like Claude with no accessible control to anchor the badge
    to, this asks Windows directly for the real blinking text caret's
    screen position, real bug found 2026-07-20: without this, the badge
    fell back to the whole window's bottom-right corner instead of next to
    where you're actually typing, so it never looked broken, it was just
    rendering somewhere you'd never think to look. Returns None if the app
    doesn't expose a caret this way (common for GPU-composited apps that
    draw their own cursor instead of using the classic Win32 caret API)."""
    try:
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        if not ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return None
        if not info.hwndCaret:
            return None
        top_left = wintypes.POINT(info.rcCaret.left, info.rcCaret.top)
        bottom_right = wintypes.POINT(info.rcCaret.right, info.rcCaret.bottom)
        ctypes.windll.user32.ClientToScreen(info.hwndCaret, ctypes.byref(top_left))
        ctypes.windll.user32.ClientToScreen(info.hwndCaret, ctypes.byref(bottom_right))
        return _SimpleRect(top_left.x, top_left.y, bottom_right.x, bottom_right.y)
    except Exception:
        return None


# Win32 extended window style flags, used to make the popup behave like
# Grammarly's: visible and clickable, but it NEVER steals keyboard focus
# away from whatever text field you're actively typing in. Without this,
# Tkinter's default Toplevel window grabs focus the instant it appears,
# which would interrupt your typing every single time a suggestion shows up,
# exactly the thing Grammarly is careful never to do.
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
# SetWindowPos flags, used below only to force Windows to re-evaluate the
# taskbar/frame after an EXSTYLE change on an already-created window --
# MSDN documents this as required (SetWindowLongPtr alone doesn't trigger
# it): "If you have changed certain window data using SetWindowLong, you
# must call SetWindowPos... with the SWP_FRAMECHANGED flag." No position/
# size/z-order/activation change is wanted, just the frame refresh.
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
# GetWindowLongPtrW/SetWindowLongPtrW index for a window's real Win32 owner.
# Distinct from Tk's own .transient() -- see make_window_non_activating below.
GWLP_HWNDPARENT = -8


def make_window_non_activating(tk_window, owner=None):
    """Marks a Tk window WS_EX_NOACTIVATE so clicking it never steals
    keyboard focus from the app underneath (Claude's input box), and
    WS_EX_TOOLWINDOW so it doesn't get its own taskbar button.

    Real ask 2026-07-27: WS_EX_TOOLWINDOW alone still shows a taskbar button
    on some configs (see the 2026-07-26 note further down) -- Windows only
    fully suppresses the button when the window ALSO has a real Win32 owner.
    Only pass `owner` for windows that must NEVER show in the taskbar (the
    badge and the suggestion popup). Never pass it for a real app window like
    Settings, which should keep its normal taskbar icon when opened -- this
    function's other caller-less behavior is unaffected either way since
    `owner` defaults to None.

    A prior attempt to supply that owner via Tk's own .transient() was
    reverted (see PersistentBadge._ensure_window and SuggestionPopup's window
    build): Tk's transient() does more than set the raw owner, it also
    auto-withdraws the child whenever the owner is withdrawn, and the owner
    here (the app's hidden Tk root) is PERMANENTLY withdrawn, so the popup
    never showed at all. Setting GWLP_HWNDPARENT directly via
    SetWindowLongPtrW bypasses that Tk-level bookkeeping entirely -- it's a
    raw Win32 attribute Tk's Python wrapper has no hooks into, so the owner
    can stay withdrawn without the child being forced to follow it.

    Real root-cause bug found 2026-07-20: this MUST run after the window is
    realized. Before realization GetParent() returns 0, and
    SetWindowLongPtrW(0, ...) fails silently, leaving the window fully
    activatable. The suggestion popup hit exactly this (it called this right
    after Toplevel() with no update_idletasks first), so clicking "Fix
    spelling & grammar" activated our own window and pulled focus out of
    Claude's text box, which is why Ctrl+A/Ctrl+V then landed nowhere and
    Apply appeared to do nothing. Verified directly: pre-realize the target
    HWND is 0 and the flag never sticks; post-realize it applies. Now this
    realizes the window itself, falls back to the window's own HWND if it
    has no parent, and logs if the flag still didn't take.

    Real ask 2026-07-26 (Antonio: "I would rather have it not pop up at all"
    -- WS_EX_TOOLWINDOW alone was showing up in the taskbar anyway on some
    configs): added the SetWindowPos/SWP_FRAMECHANGED call below, which
    MSDN documents as required for an EXSTYLE change to actually take
    effect on a window that already exists (SetWindowLongPtr changes the
    stored style bits, but doesn't by itself make Windows re-decide
    anything about the window's frame/taskbar presence). The real owner
    (2026-07-27, see `owner` param above) is the other of the two actual
    documented conditions for a tool window to never get a taskbar button,
    not just look different once it has one."""
    tk_window.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()
    style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
    if owner is not None:
        try:
            # Explicit argtypes/restype -- same reasoning as the SetWindowPos
            # call below: GWLP_HWNDPARENT's value is a full HWND, exactly the
            # kind of pointer-sized value ctypes' default int guessing has
            # silently truncated in this project before.
            user32 = ctypes.windll.user32
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            owner.update_idletasks()
            owner_hwnd = ctypes.windll.user32.GetParent(owner.winfo_id()) or owner.winfo_id()
            user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, owner_hwnd)
        except Exception:
            log_exception("make_window_non_activating: SetWindowLongPtrW GWLP_HWNDPARENT")
    try:
        # Explicit argtypes/restype, not left to ctypes' default guessing --
        # a different SetWindowPos call elsewhere in this app's history was
        # a real, hard-to-catch crash from exactly that (a 64-bit HWND
        # silently truncated/misread with no argtypes declared). Cheap
        # insurance against repeating the same class of bug here.
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        log_exception("make_window_non_activating: SetWindowPos frame refresh")
    applied = bool(
        ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_NOACTIVATE
    )
    if not applied:
        log(f"make_window_non_activating: WS_EX_NOACTIVATE did NOT apply (hwnd={hwnd})")
    return applied


def _raw_window_title(hwnd):
    """The window's actual title text, unformatted. Real ask 2026-07-21:
    used for real logic now (see app_label_for), not just logging, so it's
    split out from _window_title below, whose f-string/repr formatting is
    for debug.log and was never meant to be matched against."""
    if not hwnd:
        return ""
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


def _window_title(hwnd):
    """Human-readable diagnostic only, for debug.log, not used for logic.

    Privacy (audit 2026-07-25): this used to log the actual title text, but
    LLM app titles ARE the conversation title -- derived from what the user
    typed -- and the foreground-window logs captured any app/tab title the
    user happened to focus. Same standard as the no-URLs/no-text-previews
    rules elsewhere in this file: identity comes from the hwnd and the
    window CLASS (app-identifying, never content-bearing), plus the title
    LENGTH so same-window-different-title transitions stay diagnosable."""
    if not hwnd:
        return "<none>"
    try:
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        cls = buf.value or "?"
    except Exception:
        cls = "?"
    return f"{hwnd}:{cls}:titlelen={len(_raw_window_title(hwnd))}"


def force_foreground(hwnd):
    """Real bug found 2026-07-20, continued: a plain SetForegroundWindow
    call only reliably succeeds within Windows' "recent input" grace
    window, fine for the fast rules-only Apply path, but the AI fallback
    can now take 15-30+ seconds (cold model load + generation), and by the
    time apply_new_text actually runs, that grace window has long expired,
    so the earlier fix silently stopped working for exactly the slow path
    Antonio was hitting: "applied suggestion" logged clean, but the paste
    landed nowhere. AttachThreadInput is the standard, Microsoft-documented
    workaround: temporarily merge our thread's input state with the target
    window's thread, which makes SetForegroundWindow succeed unconditionally
    regardless of how long it's been since real user input, then detach
    right after so we don't leave the two threads' input state entangled.

    Real call 2026-07-20, continued: three rounds of theory-based fixes for
    "Apply does nothing" haven't actually been confirmed working, each
    "applied suggestion" log line only proves the function ran without
    raising, not that the paste actually landed anywhere real. Logging the
    actual before/after foreground window here so the NEXT failure gives
    real evidence (did this even change the foreground window at all)
    instead of another guess."""
    if not hwnd:
        log("force_foreground: no target hwnd, skipping")
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    before = user32.GetForegroundWindow()
    is_valid = bool(user32.IsWindow(hwnd))
    log(
        f"force_foreground: target={_window_title(hwnd)} valid={is_valid} "
        f"before={_window_title(before)}"
    )
    target_thread_id = user32.GetWindowThreadProcessId(hwnd, None)
    current_thread_id = kernel32.GetCurrentThreadId()
    attached = False
    try:
        if target_thread_id and target_thread_id != current_thread_id:
            attached = bool(user32.AttachThreadInput(current_thread_id, target_thread_id, True))
        set_ok = bool(user32.SetForegroundWindow(hwnd))
        user32.BringWindowToTop(hwnd)
    except Exception:
        log_exception("force_foreground")
        set_ok = False
    finally:
        if attached:
            user32.AttachThreadInput(current_thread_id, target_thread_id, False)
    after = user32.GetForegroundWindow()
    log(
        f"force_foreground: attached={attached} SetForegroundWindow_returned={set_ok} "
        f"after={_window_title(after)} landed_on_target={after == hwnd}"
    )
    return after == hwnd


# Real bug found 2026-07-20: the original design read Claude's box by
# simulating Ctrl+A/Ctrl+C, which visibly select-all-flashes the box every
# time it runs. You said no highlighting at all, ever, full stop, same as
# Grammarly. Since Claude's editor exposes zero readable content through
# any accessibility API (confirmed by a full UI-tree probe: the input
# renders as an empty, childless control with no Name/Value/TextPattern),
# the only way to have both "know what you typed" and "never touch or
# select the box" is to stop reading the box entirely and instead
# reconstruct what you typed from the raw keystroke stream itself, via the
# same low-level keyboard hook already used for idle tracking. Real,
# accepted tradeoff: this can't see text that was already in the box
# before tracking started, and it can drift out of sync on heavy arrow-key
# editing, since there's no cursor-position tracking, just append/backspace
# from the end. For a chat prompt box (type forward, occasionally
# backspace) that covers the real-world case well.
IDLE_THRESHOLD_SECONDS = 1.5  # only gates the suggestion popup now, not reading
TYPED_BUFFER_MAX_CHARS = 8000  # defensive cap, not a real prompt length

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
LLKHF_INJECTED = 0x00000010  # set on any key event we generated ourselves via SendKeys

VK_BACK = 0x08
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_CAPITAL = 0x14
VK_DELETE = 0x2E
VK_SPACE = 0x20
VK_A = 0x41
VK_V = 0x56

# Standard US-QWERTY shift map. Deliberately NOT using Windows' ToUnicode/
# ToUnicodeEx for this: those calls are documented to interfere with the
# OS's own dead-key/diacritic composition state when called from a global
# low-level hook, which could actually corrupt your real typing in other
# apps, exactly the kind of side effect that caused today's earlier bugs.
# A plain lookup table can never touch that state. Real, accepted
# limitation: non-US keyboard layouts won't map symbol keys correctly.
US_SHIFT_MAP = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
    "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|",
    ";": ":", "'": "\"", ",": "<", ".": ">", "/": "?", "`": "~",
}
VK_OEM_MAP = {
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_last_keystroke_time = [0.0]
_keyboard_hook_handle = [None]

_typed_buffer_lock = threading.Lock()
_typed_buffer = [""]
_typed_buffer_active = [False]  # set by watch_loop: are we in a known LLM app right now
_select_all_pending = [False]

# Real data-loss bug found 2026-07-21. Claude exposes no readable text
# control at all (verified by walking its live UIA tree: only URL/file-path
# documents), so the typed buffer is our ONLY picture of the prompt. But the
# keyboard hook deliberately ignores LLKHF_INJECTED (synthetic) keystrokes,
# which is correct for not re-reading our own paste, and also means text
# entered by DICTATION or any other tool that injects input never lands in
# the buffer. Antonio dictates his prompts, so the buffer held a stale
# fragment while the real box held the full dictated text, and Apply
# (Ctrl+A over the REAL text, then paste the fragment) would replace the
# whole prompt with that fragment.
#
# _self_injecting marks the windows where WE are the ones injecting, so our
# own paste isn't mistaken for external input. Any injected keystroke seen
# outside those windows means the buffer can no longer be trusted.
_self_injecting = [False]
_buffer_untrusted = [False]

# Real bug found live 2026-07-24 (Antonio: click away from a finished Step-2
# result, come back, and it re-runs the ~1.5B model from scratch on the EXACT
# same text): SuggestionPopup.dismiss() wipes ALL card state on every close
# (see watch_loop's popup.dismiss() calls when the focused control drops out
# of view, even momentarily), and nothing else remembered the result -- every
# reopen called rewrite_prompt_via_subprocess unconditionally. One-slot
# cache, not a dict: only the MOST RECENT compression needs remembering here,
# and a single slot can't grow unbounded over a long session.
_last_compression = {"source": None, "rewritten": None}

_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


def reset_typed_buffer():
    with _typed_buffer_lock:
        _typed_buffer[0] = ""
        _select_all_pending[0] = False
        _buffer_untrusted[0] = False


def get_typed_buffer():
    with _typed_buffer_lock:
        return _typed_buffer[0]


def set_typed_buffer(text):
    with _typed_buffer_lock:
        _typed_buffer[0] = text
        _select_all_pending[0] = False


CF_UNICODETEXT = 13


def _peek_clipboard_text():
    """Read-only clipboard peek, used only to see what a real Ctrl+V paste
    is about to insert, never writes to the clipboard. Raw ctypes rather
    than Tkinter's clipboard_get, since this runs on the hook's own thread,
    not Tkinter's main thread."""
    if not ctypes.windll.user32.OpenClipboard(None):
        return None
    try:
        handle = ctypes.windll.user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        locked = ctypes.windll.kernel32.GlobalLock(handle)
        if not locked:
            return None
        try:
            return ctypes.wstring_at(locked)
        finally:
            ctypes.windll.kernel32.GlobalUnlock(handle)
    except Exception:
        return None
    finally:
        ctypes.windll.user32.CloseClipboard()


GMEM_MOVEABLE = 0x0002

# Explicit signatures: these return/take 64-bit handles and pointers, and
# ctypes' default 32-bit int would silently truncate them, the same class of
# bug that made SetPriorityClass fail earlier this session.
ctypes.windll.kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
ctypes.windll.kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
ctypes.windll.kernel32.GlobalLock.restype = wintypes.LPVOID
ctypes.windll.kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
ctypes.windll.kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
ctypes.windll.kernel32.GlobalFree.restype = wintypes.HGLOBAL
ctypes.windll.kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
ctypes.windll.user32.SetClipboardData.restype = wintypes.HANDLE
ctypes.windll.user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]


def _set_clipboard_text(text):
    """Writes text to the clipboard via the real Win32 API instead of
    Tkinter's clipboard_append.

    Real root-cause fix 2026-07-20 for "Apply highlights everything but
    doesn't change anything": Tk's clipboard uses DELAYED RENDERING, Tk
    doesn't put the data on the clipboard, it claims ownership and only
    hands the text over when another app asks for it, which requires Tk's
    event loop to be running to answer that request. But apply_new_text
    runs on the Tk main thread and sleeps between keystrokes, so the event
    loop is blocked exactly when Claude asks for the clipboard contents
    after Ctrl+V. Result: the Ctrl+A highlight lands (Claude handles that
    itself) but the paste comes back empty, precisely the symptom Antonio
    reported. SetClipboardData puts the actual bytes on the clipboard, so
    any app can read it with no message loop of ours involved."""
    if not text:
        text = ""
    if not _open_clipboard_with_retry():
        return False
    try:
        ctypes.windll.user32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        handle = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        locked = ctypes.windll.kernel32.GlobalLock(handle)
        if not locked:
            ctypes.windll.kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(locked, ctypes.byref(buf), size)
        finally:
            ctypes.windll.kernel32.GlobalUnlock(handle)
        if not ctypes.windll.user32.SetClipboardData(CF_UNICODETEXT, handle):
            # Only free on failure; on success the SYSTEM owns this memory
            # and freeing it would corrupt the clipboard.
            ctypes.windll.kernel32.GlobalFree(handle)
            return False
        return True
    except Exception:
        log_exception("_set_clipboard_text")
        return False
    finally:
        ctypes.windll.user32.CloseClipboard()


# --- Clipboard save/restore for Apply (real bug 2026-07-22, market audit) --
# The save/restore around Apply's paste only handled CF_UNICODETEXT, so a
# user with a SCREENSHOT or copied FILES on the clipboard who clicked Apply
# on the clipboard-paste path (Claude/Electron) had that content silently
# destroyed and replaced with the suggestion text. Screenshot-plus-prompt is
# a core Claude workflow, so this is exactly the user it bit.
#
# The formats below are all plain HGLOBAL memory blocks, safe to snapshot
# byte-for-byte and hand back. Deliberately NOT handled: CF_BITMAP and other
# GDI/metafile handles (not byte-copyable; CF_DIB/CF_DIBV5 cover images in
# practice because Windows synthesizes between DIB forms), and OLE data
# objects (a paste of cells from Excel restores as its DIB/text renderings).
CF_DIB = 8
CF_HDROP = 15
CF_DIBV5 = 17
# Skip anything pathological rather than duplicating it in RAM.
_CLIPBOARD_SNAPSHOT_MAX_BYTES = 128 * 1024 * 1024


def _open_clipboard_with_retry(attempts=5, delay=0.02):
    """OpenClipboard can transiently fail right after another clipboard
    update, because the Windows clipboard-history service (Win+V) briefly
    opens the clipboard itself on every change (observed while testing the
    snapshot/restore sequence: an immediate reopen lost the race about once
    per several tries). A few short retries make that window a non-event.
    NOT used by _peek_clipboard_text: that runs on the low-level hook
    thread, where sleeping is forbidden (a slow hook gets silently
    unhooked by Windows)."""
    for _ in range(attempts):
        if ctypes.windll.user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False

ctypes.windll.kernel32.GlobalSize.restype = ctypes.c_size_t
ctypes.windll.kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
ctypes.windll.user32.RegisterClipboardFormatW.restype = wintypes.UINT
ctypes.windll.user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
ctypes.windll.user32.GetClipboardData.restype = wintypes.HANDLE
ctypes.windll.user32.GetClipboardData.argtypes = [wintypes.UINT]


def _snapshot_clipboard():
    """Snapshots the clipboard's restorable contents as [(format, bytes)].
    Empty list means nothing snapshotable (which includes an empty
    clipboard); callers just skip the restore then, same net behavior the
    old text-only code had for non-text content, minus the data loss for
    the formats we now cover."""
    snapshot = []
    if not _open_clipboard_with_retry():
        return snapshot
    try:
        png_id = ctypes.windll.user32.RegisterClipboardFormatW("PNG")
        # CF_HTML / CF_RTF (2026-07-25 audit): a formatted copy (rich text
        # from Word, a table from a web page) used to come back from Apply
        # as its plain-text rendering only, because CF_UNICODETEXT was the
        # sole text-ish format snapshotted. Both are registered formats and
        # plain HGLOBAL blocks, exactly like PNG above, so the same
        # byte-for-byte snapshot/restore is safe. The deliberate exclusions
        # documented at CF_DIB above (GDI handles, OLE data objects) stand.
        html_id = ctypes.windll.user32.RegisterClipboardFormatW("HTML Format")
        rtf_id = ctypes.windll.user32.RegisterClipboardFormatW("Rich Text Format")
        for fmt in (CF_UNICODETEXT, CF_HDROP, CF_DIBV5, CF_DIB, png_id,
                    html_id, rtf_id):
            try:
                handle = ctypes.windll.user32.GetClipboardData(fmt)
                if not handle:
                    continue
                size = ctypes.windll.kernel32.GlobalSize(handle)
                if not size or size > _CLIPBOARD_SNAPSHOT_MAX_BYTES:
                    continue
                locked = ctypes.windll.kernel32.GlobalLock(handle)
                if not locked:
                    continue
                try:
                    snapshot.append((fmt, ctypes.string_at(locked, size)))
                finally:
                    ctypes.windll.kernel32.GlobalUnlock(handle)
            except Exception:
                continue
    except Exception:
        log_exception("_snapshot_clipboard")
    finally:
        ctypes.windll.user32.CloseClipboard()
    return snapshot


def _restore_clipboard(snapshot):
    """Puts a _snapshot_clipboard() result back. No-op on an empty snapshot
    (deliberate: restoring nothing over the paste text would be pointless,
    and the old code kept the same behavior for a previously-empty
    clipboard)."""
    if not snapshot:
        return False
    if not _open_clipboard_with_retry():
        return False
    try:
        ctypes.windll.user32.EmptyClipboard()
        restored_any = False
        for fmt, data in snapshot:
            handle = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                continue
            locked = ctypes.windll.kernel32.GlobalLock(handle)
            if not locked:
                ctypes.windll.kernel32.GlobalFree(handle)
                continue
            try:
                ctypes.memmove(locked, data, len(data))
            finally:
                ctypes.windll.kernel32.GlobalUnlock(handle)
            if ctypes.windll.user32.SetClipboardData(fmt, handle):
                restored_any = True
            else:
                # Only free on failure; on success the system owns it.
                ctypes.windll.kernel32.GlobalFree(handle)
        return restored_any
    except Exception:
        log_exception("_restore_clipboard")
        return False
    finally:
        ctypes.windll.user32.CloseClipboard()


def _vk_to_us_char(vk, shift_down, caps_on):
    if vk == VK_SPACE:
        return " "
    if 0x30 <= vk <= 0x39:  # digits
        ch = chr(vk)
        return US_SHIFT_MAP[ch] if shift_down else ch
    if 0x41 <= vk <= 0x5A:  # letters
        upper = shift_down != caps_on  # XOR: shift or capslock, not both
        return chr(vk) if upper else chr(vk).lower()
    if vk in VK_OEM_MAP:
        base = VK_OEM_MAP[vk]
        return US_SHIFT_MAP.get(base, base) if shift_down else base
    return None


def _handle_typed_key(vk):
    """Rebuilds what you've typed from raw keystrokes, character by
    character, without ever touching or selecting the actual text field.
    Runs on the keyboard hook's own thread."""
    shift_down = bool(ctypes.windll.user32.GetKeyState(VK_SHIFT) & 0x8000)
    ctrl_down = bool(ctypes.windll.user32.GetKeyState(VK_CONTROL) & 0x8000)
    caps_on = bool(ctypes.windll.user32.GetKeyState(VK_CAPITAL) & 0x0001)

    with _typed_buffer_lock:
        if ctrl_down and vk == VK_A:
            _select_all_pending[0] = True
            return

        if ctrl_down and vk == VK_V:
            # The one case we CAN read accurately: a real paste inserts
            # exactly what's on the clipboard right now.
            pasted = _peek_clipboard_text()
            if pasted:
                _typed_buffer[0] = pasted if _select_all_pending[0] else _typed_buffer[0] + pasted
            _select_all_pending[0] = False
            return

        if ctrl_down and vk == VK_RETURN:
            # Ctrl+Enter is a stock send binding in the LLM apps (and the
            # ONLY one in ChatGPT's "Enter inserts newline" mode), so the
            # box empties exactly like plain Enter below. The generic
            # ctrl-combo return right after this used to eat it, leaving
            # the buffer holding the whole already-sent message
            # (2026-07-25 audit).
            _typed_buffer[0] = ""
            _select_all_pending[0] = False
            return

        if ctrl_down:
            return  # other ctrl-combos (bold, undo, etc), not text input

        if vk == VK_BACK:
            _typed_buffer[0] = "" if _select_all_pending[0] else _typed_buffer[0][:-1]
            _select_all_pending[0] = False
            return

        if vk == VK_DELETE:
            if _select_all_pending[0]:
                _typed_buffer[0] = ""
            _select_all_pending[0] = False
            return

        if vk == VK_RETURN:
            if shift_down:
                _typed_buffer[0] = "\n" if _select_all_pending[0] else _typed_buffer[0] + "\n"
            else:
                # plain Enter sends the message in Claude/ChatGPT, box empties
                _typed_buffer[0] = ""
            _select_all_pending[0] = False
            return

        ch = _vk_to_us_char(vk, shift_down, caps_on)
        if ch is not None:
            _typed_buffer[0] = ch if _select_all_pending[0] else _typed_buffer[0] + ch
            if len(_typed_buffer[0]) > TYPED_BUFFER_MAX_CHARS:
                _typed_buffer[0] = _typed_buffer[0][-TYPED_BUFFER_MAX_CHARS:]
        _select_all_pending[0] = False


def _low_level_keyboard_proc(nCode, wParam, lParam):
    # LLKHF_INJECTED is set on any key event that came from SendInput/
    # SendKeys rather than a real hardware key. Real bug found 2026-07-20:
    # without this check, apply_new_text's own synthetic Ctrl+A/paste would
    # get recorded into the typed buffer as if you'd typed it, corrupting
    # what we think you wrote. Only genuine hardware keys count, here and
    # for idle tracking.
    if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if not (kb.flags & LLKHF_INJECTED):
            _last_keystroke_time[0] = time.time()
            if _typed_buffer_active[0]:
                try:
                    _handle_typed_key(kb.vkCode)
                except Exception:
                    log_exception("_handle_typed_key")
        elif _typed_buffer_active[0] and not _self_injecting[0]:
            # Injected input we didn't cause: dictation or another tool
            # typing into the box. We can't reconstruct it (that's the whole
            # point of the INJECTED filter), so the buffer no longer matches
            # the real text and must not be pasted over it.
            if not _buffer_untrusted[0]:
                _buffer_untrusted[0] = True
                log("external injected input detected (dictation?), typed buffer marked untrusted")
    return ctypes.windll.user32.CallNextHookEx(
        _keyboard_hook_handle[0], nCode, wParam, lParam
    )


_hook_proc_ref = _HOOKPROC(_low_level_keyboard_proc)  # must stay alive, GC'd = crash

ctypes.windll.user32.SetWindowsHookExW.restype = wintypes.HHOOK
ctypes.windll.user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
]
ctypes.windll.user32.CallNextHookEx.restype = wintypes.LPARAM
ctypes.windll.user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
]

# Real bug found 2026-07-20: Chromium apps (Claude, ChatGPT) draw their own
# text cursor instead of using the classic Win32 caret API, so
# GetGUIThreadInfo's rcCaret comes back empty, there's no accessible
# control to anchor the badge to either. The badge was silently falling
# back to the whole window's bottom-right corner, working correctly but
# appearing nowhere near where you're actually typing. Tracking your last
# real left-click position (same INJECTED-filtering as the keyboard hook)
# gives a much better anchor: you almost always click into the box right
# before typing into it.
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MOUSE_DRAG_THRESHOLD_PX = 4
LLMHF_INJECTED = 0x00000001  # mouse hook's own injected-event bit

# Real ask 2026-07-20: badge cursor should read "clickable" (hand2) right up
# until you've genuinely held it down this long, only then does it switch to
# the drag/move cursor (fleur), signaling "this is now a drag."
DRAG_CURSOR_HOLD_MS = 1000

# How far the pointer may drift during a press and still count as a click on
# the badge rather than a drag. Read from Windows' own drag threshold so we
# never disagree with the rest of the OS, floored at 8px because that metric
# defaults to 4 and assumes a mouse; a trackpad click routinely moves more.
try:
    _SM_CXDRAG, _SM_CYDRAG = 68, 69
    BADGE_CLICK_SLOP_PX = max(
        8,
        ctypes.windll.user32.GetSystemMetrics(_SM_CXDRAG),
        ctypes.windll.user32.GetSystemMetrics(_SM_CYDRAG),
    )
except Exception:
    BADGE_CLICK_SLOP_PX = 8


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_last_click_pos = [None]
_mouse_hook_handle = [None]
_mouse_down_pos = [None]
_mouse_drag_detected = [False]


def _low_level_mouse_proc(nCode, wParam, lParam):
    # Real gap found 2026-07-20: the typed-buffer only recognized a
    # selection when you pressed Ctrl+A, so selecting text by clicking and
    # dragging with the mouse (a very common way to clear or edit a box),
    # then hitting Backspace, went completely unnoticed, the tracker just
    # removed one character while the real box cleared everything, leaving
    # the badge stuck on a stale count. Treating any real click-and-drag as
    # "a selection may exist" so the next delete clears the whole tracked
    # buffer instead of just one character, same category of fix as
    # LLKHF_INJECTED, just for mouse-driven selection instead of keyboard.
    if nCode == 0:
        ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        if not (ms.flags & LLMHF_INJECTED):
            if wParam == WM_LBUTTONDOWN:
                _last_click_pos[0] = (ms.pt.x, ms.pt.y)
                _mouse_down_pos[0] = (ms.pt.x, ms.pt.y)
                _mouse_drag_detected[0] = False
            elif wParam == WM_MOUSEMOVE and _mouse_down_pos[0] is not None:
                dx = ms.pt.x - _mouse_down_pos[0][0]
                dy = ms.pt.y - _mouse_down_pos[0][1]
                if abs(dx) > MOUSE_DRAG_THRESHOLD_PX or abs(dy) > MOUSE_DRAG_THRESHOLD_PX:
                    _mouse_drag_detected[0] = True
            elif wParam == WM_LBUTTONUP:
                if _mouse_drag_detected[0] and _typed_buffer_active[0]:
                    with _typed_buffer_lock:
                        _select_all_pending[0] = True
                _mouse_down_pos[0] = None
                _mouse_drag_detected[0] = False
                # Wake the watcher NOW instead of waiting up to 0.7s for its
                # next poll, so the badge follows a click into a different
                # box near-instantly (real ask 2026-07-22). Cheap: just sets
                # a flag, the actual UIA read still happens on the watcher
                # thread, never inside this low-level hook.
                _focus_recheck_event.set()
    return ctypes.windll.user32.CallNextHookEx(
        _mouse_hook_handle[0], nCode, wParam, lParam
    )


# Reuse _HOOKPROC (not a second WINFUNCTYPE) since SetWindowsHookExW's
# argtypes below is pinned to that exact type, both hooks share the same
# (c_int, WPARAM, LPARAM) -> c_int signature anyway.
_mouse_hook_proc_ref = _HOOKPROC(_low_level_mouse_proc)  # must stay alive, GC'd = crash


def get_last_click_rect():
    pos = _last_click_pos[0]
    if pos is None:
        return None
    x, y = pos
    return _SimpleRect(x - 20, y - 10, x + 20, y + 10)

# GetKeyState returns a signed 16-bit SHORT; without an explicit restype
# ctypes defaults to a 32-bit int, which can misread the high bit that
# "is this key currently down" actually depends on.
ctypes.windll.user32.GetKeyState.restype = ctypes.c_short
ctypes.windll.user32.GetKeyState.argtypes = [ctypes.c_int]


WH_MOUSE_LL = 14


THREAD_PRIORITY_HIGHEST = 2


def run_keyboard_idle_watcher():
    """Runs on its own thread with a real Windows message loop, required for
    low-level hooks to receive events at all. Installs both the keyboard
    and mouse hooks here since one thread's message loop can service
    multiple hooks, no need for a second thread."""
    try:
        # The whole process just got dropped to BELOW_NORMAL (see top of
        # file) so our own onnxruntime inference threads don't win CPU
        # arbitration against every other app. But that would also drag
        # THIS thread down with it, and this is the one thread that must
        # keep responding to real keystrokes/clicks no matter what else the
        # process is doing. Raising just this thread back to HIGHEST
        # (relative to our own BELOW_NORMAL base, still well under a normal
        # app's own priority) keeps it winning arbitration against our own
        # inference threads specifically, without asking Windows to
        # prioritize us over the rest of the system.
        try:
            # Same pseudo-handle marshalling bug as SetPriorityClass above,
            # GetCurrentThread() is also a 64-bit pseudo-handle
            # (0xFFFFFFFFFFFFFFFE), needs explicit restype or this silently
            # no-ops too.
            ctypes.windll.kernel32.GetCurrentThread.restype = wintypes.HANDLE
            ctypes.windll.kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
            ctypes.windll.kernel32.SetThreadPriority.restype = wintypes.BOOL
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), THREAD_PRIORITY_HIGHEST
            )
        except Exception:
            pass

        # WH_KEYBOARD_LL/WH_MOUSE_LL specifically want hMod=NULL when the
        # hook proc lives in the current process, not GetModuleHandle,
        # real bug found 2026-07-20 (error 126, module not found).
        _keyboard_hook_handle[0] = ctypes.windll.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, _hook_proc_ref, None, 0
        )
        if not _keyboard_hook_handle[0]:
            log(f"keyboard idle hook failed to install, error={ctypes.GetLastError()}")
            return
        log("keyboard idle hook installed")

        _mouse_hook_handle[0] = ctypes.windll.user32.SetWindowsHookExW(
            WH_MOUSE_LL, _mouse_hook_proc_ref, None, 0
        )
        if not _mouse_hook_handle[0]:
            log(f"mouse hook failed to install, error={ctypes.GetLastError()}")
        else:
            log("mouse click hook installed")

        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
    except Exception:
        log_exception("run_keyboard_idle_watcher")


def idle_seconds():
    last = _last_keystroke_time[0]
    if last == 0.0:
        return 999.0  # no keystroke observed yet this session, treat as idle
    return time.time() - last


def winspell_available():
    """Diagnostic helper so the log can show whether spell-check is live."""
    try:
        import winspell
        return winspell.is_available()
    except Exception:
        return False


# An input box holds a prompt; a whole chat transcript is far bigger. Any
# read past this is treated as "Ctrl+A selected the page, not the field".
CLIPBOARD_READ_MAX_CHARS = 4000
# Floor for the proportionality check, so a short typed buffer doesn't block
# a legitimately longer field (e.g. text pasted in rather than typed).
CLIPBOARD_READ_MIN_ALLOWANCE = 1500


def read_text_via_clipboard(target_hwnd, expected_fragment=None):
    """One-time ground-truth read for apps that expose no readable control.

    Real need 2026-07-21: Claude's Electron build exposes no editable
    control at all (re-verified: its only EditControl is the 261px find
    bar), so the keystroke buffer was the only source, and that buffer
    cannot see dictated text because the hook deliberately ignores injected
    input. Antonio wants dictation supported, so we need the real field
    contents. Select-all + copy is the only way to get them here.

    Deliberately NOT run on a timer: the earlier rejected design polled this
    constantly and made the box flash forever. This runs once, only when the
    badge is actually clicked, then collapses the selection again."""
    # Full-format snapshot, not just text (2026-07-22 market audit): the
    # Ctrl+C below overwrites the clipboard, and a text-only save meant a
    # screenshot or copied files sitting there were silently destroyed.
    saved = _snapshot_clipboard()
    _self_injecting[0] = True
    try:
        force_foreground(target_hwnd)
        time.sleep(0.08)
        auto.SendKeys("{Ctrl}a", waitTime=0.03)
        time.sleep(0.08)
        auto.SendKeys("{Ctrl}c", waitTime=0.03)
        time.sleep(0.25)
        grabbed = _peek_clipboard_text()
        # Collapse the selection so the user isn't left with everything
        # highlighted if they dismiss the card.
        auto.SendKeys("{Right}", waitTime=0.03)
    except Exception:
        log_exception("read_text_via_clipboard")
        grabbed = None
    finally:
        _self_injecting[0] = False
        _restore_clipboard(saved)
    if not grabbed:
        log("clipboard read returned nothing")
        return None

    # Real, dangerous bug found 2026-07-21: in Claude, Ctrl+A only selects
    # the composer when the composer actually holds keyboard focus. When it
    # doesn't, Ctrl+A selects the ENTIRE PAGE, so this read came back with
    # the whole chat transcript. The rules then produced nonsense (dozens of
    # ".c" -> ". c" from the transcript), and an Apply would have pasted the
    # entire conversation into the input box. Antonio hit exactly this
    # ("now it's highlighting everything"). These two checks reject a read
    # that clearly isn't the input field.
    # ALL of these guards, always. Real regression 2026-07-21: this used to
    # be `if expected_fragment: <tail check> elif len > MAX`, so passing a
    # fragment SKIPPED THE SIZE CAP COMPLETELY. And the tail check cannot
    # catch a whole-page selection on its own, because the page CONTAINS the
    # user's own draft (the composer is part of the page), so the tail is
    # always present. Result: a Ctrl+A that selected an entire 9,347
    # character conversation was accepted as "the input box", which is
    # exactly the whole-transcript disaster this function exists to prevent.
    # Antonio saw it as "it's highlighting everything again."
    if expected_fragment:
        tail = expected_fragment.strip()[-12:]
        if tail and tail not in grabbed:
            log(
                f"clipboard read REJECTED ({len(grabbed)} chars): does not contain recently "
                f"typed text, so it selected something other than the input box"
            )
            return None
        # Proportionality: whatever we grabbed should be in the same ballpark
        # as what we watched being typed. Generous multiplier so pasting into
        # the box still works, but a page-sized grab never survives.
        allowance = max(CLIPBOARD_READ_MIN_ALLOWANCE, len(expected_fragment) * 6)
        if len(grabbed) > allowance:
            log(
                f"clipboard read REJECTED: {len(grabbed)} chars is far more than the "
                f"{len(expected_fragment)} we tracked being typed (allowed {allowance}), "
                f"so Ctrl+A selected the page, not the input box"
            )
            return None

    if len(grabbed) > CLIPBOARD_READ_MAX_CHARS:
        log(
            f"clipboard read REJECTED: {len(grabbed)} chars exceeds {CLIPBOARD_READ_MAX_CHARS}, "
            f"looks like a whole page rather than an input box"
        )
        return None

    log(f"read real text via clipboard, length={len(grabbed)}")
    return grabbed


def get_writable_value_pattern():
    """Returns the focused control's ValuePattern if it can be written to,
    else None.

    Real finding 2026-07-21, measured not assumed: most surfaces expose an
    editable control whose text can be read AND written directly through UI
    Automation, verified live against Notepad (WinUI), Chrome and Edge, all
    three returned the exact field text and accepted SetValue. That path is
    strictly better than the clipboard/keystroke dance: no Ctrl+A, no
    clipboard round-trip, no foreground fight, no selection flash, and
    because it reads the real field it is immune to the dictation problem
    that breaks the keystroke buffer. Claude's Electron build is the known
    exception (exposes no editable control at all), which is what the
    clipboard path still exists for.

    Only ever call this for a control you actually mean. Reading "whatever
    has focus right now" from inside Apply is wrong, see
    _writable_value_pattern_for()."""
    try:
        control = auto.GetFocusedControl()
        if control is None:
            return None
        pattern = _safe_pattern(control, PatternId.ValuePattern)
        if pattern is None:
            return None
        if pattern.IsReadOnly:
            return None
        return pattern
    except Exception:
        return None


def _writable_value_pattern_for(control):
    """Writable ValuePattern of ONE SPECIFIC control, or None.

    Real root-cause bug found 2026-07-21: Apply used
    get_writable_value_pattern(), which asks "what has focus right now".
    By the time Apply runs, the thing with focus is our own popup's button,
    not the user's text box. So the direct-write path was being skipped
    even in Chrome/Edge/native fields where SetValue works perfectly, and
    everything fell through to the clipboard + Ctrl+A path unnecessarily.
    The control captured at click time is the right target, always."""
    if control is None:
        return None
    try:
        pattern = _safe_pattern(control, PatternId.ValuePattern)
        if pattern is None or pattern.IsReadOnly:
            return None
        return pattern
    except Exception:
        return None


def _text_tail(text, n=24):
    """A distinctive trailing slice, used to recognise a field by content."""
    return (text or "").strip()[-n:]


def _focus_is_on_expected_field(expected_old_text):
    """Is keyboard focus really inside the field we're about to edit?

    True  = verified yes (the focused control's text still ends the way the
            text we analysed does).
    False = verified no (focus is somewhere else entirely).
    None  = unverifiable, the field exposes no readable text through UIA.

    Real bug found live 2026-07-27 (Antonio, right after the terminal
    fail-safe fix below): a terminal that briefly can't find its own "❯"
    marker now correctly reads as no-usable-text (get_focused_text()
    returns None) instead of the old, dangerous whole-buffer fallback --
    but this call site is reached from apply_new_text right after
    force_foreground(), before the terminal has necessarily finished
    repainting, so a single read landing in that window read as
    "unverifiable" and aborted an otherwise-legitimate Apply. A momentary
    marker miss right after regaining focus is a timing issue, not a real
    "can't find your input line" case, so it's worth a couple of quick
    retries here specifically, rather than weakening the fail-safe itself
    (which must stay strict: never treat an unmarked buffer as the real
    field)."""
    tail = _text_tail(expected_old_text)
    if not tail:
        return None
    for attempt in range(3):
        text, _ = get_focused_text()
        if text is not None:
            return tail in text
        if attempt < 2:
            time.sleep(0.08)
    return None


def _point_is_in_window(pos, hwnd):
    """Is this screen point inside the target top-level window?"""
    if not hwnd or pos is None:
        return False
    try:
        user32 = ctypes.windll.user32
        # POINT is passed by value here, so argtypes matters. Return values
        # stay the file-wide default int so they compare directly against
        # the hwnds from GetForegroundWindow elsewhere.
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        hit = user32.WindowFromPoint(wintypes.POINT(int(pos[0]), int(pos[1])))
        if not hit:
            return False
        GA_ROOT = 2
        return hit == hwnd or user32.GetAncestor(hit, GA_ROOT) == hwnd
    except Exception:
        return False


def _click_at(pos):
    """A real synthetic left click, cursor restored afterwards. Used only to
    put the caret back where the user themselves last clicked."""
    user32 = ctypes.windll.user32
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    saved = wintypes.POINT()
    try:
        user32.GetCursorPos(ctypes.byref(saved))
    except Exception:
        saved = None
    _self_injecting[0] = True
    try:
        user32.SetCursorPos(int(pos[0]), int(pos[1]))
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.03)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.08)
    except Exception:
        log_exception("_click_at")
    finally:
        if saved is not None:
            try:
                user32.SetCursorPos(saved.x, saved.y)
            except Exception:
                pass
        _self_injecting[0] = False


def restore_field_focus(target_hwnd, target_control, expected_old_text):
    """Put real keyboard focus back INSIDE the text box before any Ctrl+A.

    Real bug Antonio hit 2026-07-21: "when I press apply it doesn't apply
    the AI compress to the area I want it to, instead it highlighted
    everything." Root cause: force_foreground() only restores the WINDOW.
    Inside that window, keyboard focus was no longer in the composer,
    because clicking our popup took it away. Ctrl+A in Claude with the
    composer unfocused selects the ENTIRE PAGE, exactly the same failure
    mode already documented for the clipboard READ path, just on the write
    side, where it's worse: the paste lands on the page selection instead
    of the prompt.

    Returns True (verified in the field), None (couldn't verify, but we did
    click back into it, so proceeding is reasonable), or False (focus is
    provably elsewhere, the caller must NOT send Ctrl+A).

    Real bug found live 2026-07-27 (Antonio: "it was working last night,
    what happened" -- right after the terminal marker fail-safe landed):
    the text-based verification below depends on re-finding the "❯"
    marker RIGHT NOW, but the marker is legitimately absent from a
    terminal's own rendering for long stretches while the CLI is actively
    working (tens of seconds, not a brief blink -- confirmed in the log,
    not guessed). A short retry wasn't enough because the gap itself is
    long, not just a one-off race. The text-check was built for a
    DIFFERENT problem though (Electron/browser composers where the same
    window hosts multiple text areas, so confirming the right WINDOW
    isn't enough). A terminal doesn't have that ambiguity -- the whole
    window IS the one interactive surface -- so for a terminal target,
    force_foreground succeeding on the exact hwnd we captured at
    suggestion-time is already sufficient confirmation, without needing a
    second, marker-dependent text re-check that can legitimately be
    unavailable for reasons that have nothing to do with whether focus is
    actually correct."""
    is_terminal_target = _process_name_for_hwnd(target_hwnd) in TERMINAL_HOST_PROCESSES
    landed = force_foreground(target_hwnd)
    if is_terminal_target:
        if landed:
            # Real new finding 2026-07-27 (pre-launch audit, "one final
            # bottleneck"): the tab-name check below confirmed BOTH the good
            # and the stuck reads belonged to the SAME tab (identical
            # original_len, identical tab name) -- this was never a
            # cross-tab mixup. The remaining theory: Windows Terminal's own
            # accessibility view of that tab occasionally snaps to an OLDER
            # SCROLL POSITION instead of the true bottom, right around when
            # our own popup takes focus, and the read then reflects whatever
            # was scrolled into view, not the live prompt. Ctrl+End is
            # Windows Terminal's own built-in "scroll to bottom" action (a
            # terminal-level keybind, not passed through to the running
            # shell/CLI), sent here BEFORE any read so every check below is
            # looking at the true live position. A no-op if already at the
            # bottom, which is the common case.
            auto.SendKeys("{Ctrl}{END}", waitTime=0.01)
            time.sleep(0.05)
            # Real gap found 2026-07-27 (Antonio, pre-launch audit, multi-tab
            # terminal testing): force_foreground only proves SOME window
            # came forward, it does not by itself prove it's still the same
            # one suggestions were computed against.
            #
            # REVERTED same day (attempt 1): tried a UIA RuntimeId identity
            # check here. Live testing showed target_id == current_id every
            # time, even across what were genuinely different tabs/windows --
            # this API doesn't distinguish them, so the check was a no-op.
            #
            # REVERTED same day (attempt 2): tried relying only on
            # apply_new_text's fresh content-tail check instead. A live
            # diagnostic dump then caught the actual mechanism directly: the
            # "stuck" content wasn't stale scrollback at all, it was
            # completely real, live text -- from a DIFFERENT terminal window
            # entirely (confirmed in the raw dump, that window's own name was
            # sitting right there in its border row). With multiple terminal
            # windows open, whatever GetFocusedControl() returns right after
            # force_foreground can belong to a different window than
            # target_hwnd, and its real content can easily still pass a
            # content-tail check by coincidence or bad luck.
            #
            # Real fix: check the one thing that's actually unambiguous --
            # does the currently-focused control's OWNING WINDOW
            # (_owning_hwnd_for_control, already used by get_focused_text's
            # own terminal-detection) match target_hwnd at all. Not identity
            # within a window, not content -- literally "is this even the
            # same top-level window we mean to type into." Only a DEFINITE
            # mismatch (both resolve cleanly and differ) refuses; anything
            # unreadable falls back to trusting force_foreground, same fail-
            # closed-only-when-certain discipline as everywhere else here.
            try:
                current_control = auto.GetFocusedControl()
                current_owner = _owning_hwnd_for_control(current_control) if current_control is not None else None
                mismatch = current_owner is not None and current_owner != target_hwnd
                diag = f"target_hwnd={target_hwnd} current_owner={current_owner} mismatch={mismatch}"
            except Exception as e:
                mismatch = False
                diag = f"EXCEPTION during check: {e!r}"
            log(f"restore_field_focus (terminal): window-identity check: {diag}")
            if mismatch:
                log("restore_field_focus (terminal): focus is on a DIFFERENT terminal window than suggestion-time, refusing to select-all")
                return False
            log("restore_field_focus (terminal): trusting force_foreground, no text re-check needed")
            return True
        log("restore_field_focus (terminal): force_foreground did not land on target, refusing to select-all")
        return False
    verdict = _focus_is_on_expected_field(expected_old_text)
    if verdict is True:
        log("restore_field_focus: focus already inside the target field")
        return True

    # 1. Ask UIA to focus the exact control we captured at click time.
    if target_control is not None:
        try:
            target_control.SetFocus()
            time.sleep(0.12)
        except Exception:
            log_exception("restore_field_focus: SetFocus on captured control")
        verdict = _focus_is_on_expected_field(expected_old_text)
        if verdict is True:
            log("restore_field_focus: focus restored via UIA SetFocus")
            return True

    # 2. Click back exactly where the user last clicked, if that point is
    #    still inside the target window. A real click is the one thing that
    #    reliably puts the caret in an Electron/Chromium composer.
    pos = _last_click_pos[0]
    if _point_is_in_window(pos, target_hwnd):
        _click_at(pos)
        verdict = _focus_is_on_expected_field(expected_old_text)
        if verdict is True:
            log(f"restore_field_focus: focus restored by clicking back in at {pos}")
            return True
        if verdict is None:
            log(
                f"restore_field_focus: clicked back in at {pos}, field isn't "
                f"UIA-readable so focus can't be confirmed, proceeding"
            )
            return None
    log(
        f"restore_field_focus: could NOT put focus back in the field "
        f"(verdict={verdict}, last_click={pos}), refusing to select-all"
    )
    return False


def _sendkeys_escape(text):
    """Escapes literal text for auto.SendKeys's mini-language -- the same
    special characters Windows Forms SendKeys.Send reserves: + ^ % ~ ( ) { }.
    Needed by apply_new_text's terminal branch (2026-07-26), which types
    the replacement out as real keystrokes rather than a clipboard paste;
    without escaping, any of these in the actual text would be misread as
    modifier/grouping syntax instead of the literal character."""
    out = []
    for ch in text:
        if ch in "+^%~(){}":
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)


def apply_new_text(root, popup, new_text, target_hwnd=None, dismiss_after=True,
                   target_control=None, expected_old_text=None, safe_write_only=False,
                   expected_tab_name=None):
    """Writes a suggestion's rewritten text back into whatever box currently
    has real OS focus, same select-all + paste mechanism as the read
    fallback, just in reverse: paste the new text onto the clipboard, select
    everything in the box, paste over it, then restore your real clipboard.
    Works uniformly whether the field exposes accessibility or not, since
    it's driven by the app's own paste handling, not an accessibility API.
    Only ever runs from an explicit button click, never automatically, so
    there's no idle-gating concern here the way there is for reading.

    dismiss_after: real ask 2026-07-20, Apply is now a two-step flow (fix
    spelling/grammar first, THEN optionally compress with AI), so step one
    pastes the cleaned text but keeps the popup open to offer step two,
    only the final step dismisses it.

    Real bug found 2026-07-20: clicking the popup's own "Apply" button (a Tk
    Button) shifts real OS foreground to our own popup window, not Claude,
    confirmed directly via debug.log ("context: not an LLM app
    (tokensaver.exe)" logged the exact same second as a successful
    apply). The select-all+paste was silently landing on our own popup the
    whole time, doing nothing visible in Claude, that's why Apply looked
    completely broken even though it ran without error. target_hwnd is the
    real LLM window's handle, captured back when the rewrite was first
    requested (before this button-click focus-steal can happen).

    Real bug found 2026-07-20, continued: a plain SetForegroundWindow fixed
    the fast (rules-only) path, but Antonio hit "Apply does nothing" again
    once the AI fallback got involved, confirmed via debug.log timing: the
    AI path can take 15-30+ seconds (cold model load + generation) between
    when target_hwnd was captured and when this function actually runs,
    long past Windows' "recent input" grace window that plain
    SetForegroundWindow depends on, so it was silently failing again for
    exactly that slower path. force_foreground() (AttachThreadInput-based)
    replaces the bare calls below, works regardless of how long it's been
    since real input.

    Returns True only when the write actually ran to completion (UIA
    SetValue took, or the clipboard sequence finished without an abort),
    False on every refuse/abort/error path. Added 2026-07-25 (audit):
    callers used to record "tokens saved" BEFORE calling this, so every
    aborted apply -- "lost track of your text box", held clipboard, safe-
    write refusal -- still counted its tokens as saved in history and the
    web UI. Callers now gate the history write on this return; nothing
    else reads it, so the abort paths behave exactly as before."""
    log(f"apply_new_text: starting, target_hwnd={_window_title(target_hwnd)}, new_text length={len(new_text)}")
    try:
        # Preferred path: write straight into the control we captured when
        # the badge was clicked, through UI Automation. Clean, instant, no
        # clipboard or synthetic keystrokes, and it works in Chrome, Edge
        # and normal Windows apps (measured). Using the CAPTURED control
        # rather than "whatever is focused now" is the 2026-07-21 fix, see
        # _writable_value_pattern_for.
        pattern = _writable_value_pattern_for(target_control)
        # The old fallback here -- get_writable_value_pattern(), "whatever
        # control is focused RIGHT NOW" -- is gone (audit 2026-07-25,
        # CRITICAL): with a no-activate card, "focused right now" can be
        # Chrome's address bar or an unrelated Notepad window the user
        # clicked into while the card floated, and SetValue would silently
        # replace that field's entire contents with no verification of any
        # kind. It was only ever masked by the Tk card stealing focus to a
        # pattern-less window of our own. If the CAPTURED control can't take
        # a direct write, fall through to the clipboard path below, which
        # refuses to touch anything until restore_field_focus proves the
        # caret is genuinely back in the user's box.
        if pattern is not None:
            try:
                pattern.SetValue(new_text)
                set_typed_buffer(new_text)
                if dismiss_after:
                    popup.dismiss()
                log(f"applied via UIA SetValue, new text length={len(new_text)}, dismiss_after={dismiss_after}")
                return True
            except Exception:
                log_exception("apply_new_text UIA SetValue, falling back to clipboard")

        # Safe-write-only apps (PowerPoint, real ask 2026-07-22): if the exact
        # SetValue path above didn't work, STOP. Do not fall back to the Ctrl+A
        # clipboard path here, in a slide that would risk selecting and
        # replacing every object, not just the text box. Show the suggestions,
        # but refuse to write rather than possibly wreck the slide.
        if safe_write_only:
            popup.show_error(
                *popup.last_position(),
                "Comprsly can suggest fixes here, but couldn't safely write "
                "into this text box, so it left it untouched. Click directly "
                "into the box and try again, or edit it yourself.",
            )
            log("apply refused: safe-write-only app and SetValue unavailable")
            return False

        # Real simplification 2026-07-20: clipboard operations don't need
        # any window to have focus at all, clipboard is a system-wide
        # resource. Only the SendKeys calls below actually need the target
        # focused, so only force_foreground once, right before those,
        # instead of also here. Calling it twice (the old code did, once
        # here and once below) meant two separate SetForegroundWindow/
        # BringWindowToTop passes in quick succession, a real candidate for
        # the visible "glitch" Antonio reported, the window visibly jumping
        # forward twice for one Apply click.
        # Win32 clipboard, NOT Tkinter's (real root-cause fix 2026-07-20,
        # see _set_clipboard_text): Tk's clipboard needs our event loop
        # running to serve the data, and this function blocks that loop with
        # sleeps, so the paste was coming back empty and Apply only ever
        # produced the select-all highlight.
        #
        # Before anything is selected or pasted, make sure the caret is
        # actually back in the user's text box (2026-07-21 fix). Without
        # this, Ctrl+A hits whatever else holds focus, which in Claude means
        # selecting the entire page.
        focus_state = restore_field_focus(target_hwnd, target_control, expected_old_text)
        if focus_state is False:
            popup.show_error(
                *popup.last_position(),
                "Comprsly lost track of your text box, so it didn't touch "
                "anything.\n\nClick back into the box and press Apply again.",
            )
            log("apply_new_text: ABORTED, focus not in the target field, nothing selected or pasted")
            return False

        # Real ask 2026-07-26 (Antonio, direct): the clipboard+Ctrl+V path
        # below is a genuine OS paste event, which terminals can flag via
        # bracketed paste mode regardless of content length -- that's
        # exactly what was triggering Claude Code CLI's own "large paste"
        # permission dialog and "[Pasted text #N]" placeholder collapse on
        # every Apply, even a short one-line fix. Real terminal behavior,
        # not a Comprsly bug, but avoidable: type the replacement out as
        # REAL KEYSTROKES instead, which reads as fast typing, not a
        # paste, so neither of those fire.
        #
        # Deliberately NOT the Ctrl+A the clipboard path uses below:
        # readline-style terminals bind Ctrl+A to "move to start of line",
        # not "select all" the way a GUI text box does -- reusing it here
        # would silently corrupt the line instead of clearing it.
        # Backspaces clear exactly what was there instead, character by
        # character. Assumes the caret is at the END of the existing text
        # (the normal state right after typing); not exhaustive for a
        # cursor deliberately moved mid-line first.
        if _process_name_for_hwnd(target_hwnd) in TERMINAL_HOST_PROCESSES:
            old_len = len(expected_old_text) if expected_old_text else 0

            # Real bug found live 2026-07-27 (Antonio direct repro: "right
            # as it's about to paste the new text in, it doesn't, and
            # restarts the typing"): the post-type verification below used
            # to take exactly ONE read immediately after SendKeys finished
            # the whole string, no settle time at all. The terminal's own
            # render can briefly lag right after a burst of synthetic
            # input -- already proven and documented on the READ side
            # earlier in this same function -- and a long rewrite makes
            # that gap more likely, not less. An instant read landing mid-
            # render read as "verified != yes" and triggered the retry
            # (clear + retype), which is exactly what looked like the new
            # text getting typed and then visibly restarted from scratch.
            # A few quick re-reads with a short settle delay, same pattern
            # already used for the pre-clear check above, before declaring
            # a real failure and paying that visible cost.
            def _verify_landed(expected_tail):
                text = None
                for _ in range(4):
                    text, _ = get_focused_text()
                    if text is not None and expected_tail and expected_tail in text:
                        return "yes", text
                    time.sleep(0.15)
                return ("unreadable" if text is None else "NO"), text

            # Real ask 2026-07-27 (Antonio, pre-market audit: "is there any
            # way at all" to make terminal Apply feel instant like a paste,
            # without reintroducing the bracketed-paste bug real paste
            # triggers): tried first, ahead of the proven SendKeys path
            # below. Only attempted when the target PID is unambiguous (see
            # _find_unique_terminal_shell_pid); on ANY failure or ambiguity
            # this falls through to the untouched, already-proven SendKeys
            # code below rather than retry or partially commit -- nothing
            # above this point has touched the console yet, so falling
            # through here starts the existing mechanism from exactly the
            # same place it always has.
            fast_pid = _find_unique_terminal_shell_pid(target_hwnd)
            if fast_pid is not None:
                fast_cleared = (not old_len) or _write_console_records(fast_pid, _console_ctrl_u_records())
                fast_typed = fast_cleared and _write_console_records(fast_pid, _console_text_records(new_text))
                if fast_typed:
                    fast_tail = _text_tail(new_text)
                    fast_verified, _ = _verify_landed(fast_tail)
                    log(f"apply_new_text (terminal): fast console path attempted, verified={fast_verified}")
                    if fast_verified == "yes":
                        set_typed_buffer(new_text)
                        if dismiss_after:
                            popup.dismiss()
                        return True
                    log("apply_new_text (terminal): fast console path typed but didn't verify, "
                        "falling back to SendKeys (its own Ctrl+U will clear this first)")
                else:
                    log("apply_new_text (terminal): fast console path write failed, falling back to SendKeys")
            # Real ask 2026-07-26 (Antonio, direct: select-and-delete the
            # existing text like a mouse selection would, not one backspace
            # per character). Home moves to the start of the current input
            # line, Shift+End selects everything from there to the end of
            # the line, Delete removes the selection -- three keystroke
            # events total, regardless of how long the line is. Replaces
            # the earlier {BACK n}-per-character approach, which was also
            # what a bad (too-long) text read used to freeze the app
            # sending -- that whole failure mode is gone now, not just
            # capped, since this never scales with old_len at all.
            # HOME/END/SHIFT/DELETE verified against auto.SpecialKeyNames
            # directly before using them, same discipline as BACK earlier
            # (which turned out not to be the real key name).
            _self_injecting[0] = True
            try:
                # Real gap found by code review 2026-07-27 (same session,
                # after the cross-window buffer-leak fix -- Antonio asked
                # for a full pass on this whole area, not just the one
                # reported symptom): force_foreground() above already
                # confirmed the target window landed in the foreground
                # ONCE, but nothing re-checked that between then and here.
                # A slow AI-compression Apply can take 15-30+ seconds
                # (see apply_new_text's docstring), and with multiple
                # terminal windows open, real user input (alt-tab,
                # clicking another window) during that gap would mean
                # every Ctrl+U/keystroke below lands wherever focus
                # ACTUALLY is now, not necessarily target_hwnd. Cheap,
                # bracketing re-check: if the foreground window has
                # already drifted away before a single keystroke gets
                # sent, abort instead of clearing/typing into whatever
                # the user is now actually looking at.
                if ctypes.windll.user32.GetForegroundWindow() != target_hwnd:
                    log("apply_new_text (terminal): ABORTED, foreground window changed before clearing started")
                    popup.show_error(
                        *popup.last_position(),
                        "Comprsly lost track of your terminal window before applying, "
                        "so it left it untouched.\n\nClick back into the box and press "
                        "Apply again.",
                    )
                    return False
                # Real fix 2026-07-27 (pre-launch audit, the actual root
                # cause behind the terminal tab-switch bug): a live
                # diagnostic dump caught this directly -- Windows Terminal's
                # tabs all share one hwnd, and proved to share the same UIA
                # RuntimeId and owning-window too, so none of those can tell
                # a tab switch apart from staying put. The tab's own NAME is
                # rendered directly into its border row, right before the
                # marker (confirmed live: "...2nd Venture Assistant--[marker]"),
                # which IS distinct per tab. Checked here, before touching
                # anything, regardless of old_len -- an empty box in the
                # WRONG tab is exactly as unsafe to type into as a full one.
                # Unreadable (None) on either side falls back to proceeding,
                # same fail-closed-only-when-certain rule as everywhere else;
                # only a definite, both-sides-readable mismatch refuses.
                if expected_tab_name:
                    get_focused_text()  # refresh _last_terminal_tab_name for the CURRENT read
                    current_tab_name = _last_terminal_tab_name[0]
                    if current_tab_name and current_tab_name != expected_tab_name:
                        log(f"apply_new_text (terminal): ABORTED, active tab changed since suggestion-time "
                            f"(was {expected_tab_name!r}, now {current_tab_name!r}), refusing to clear/type")
                        popup.show_error(
                            *popup.last_position(),
                            "Comprsly noticed you've switched to a different terminal tab, so it left "
                            "that one untouched.\n\nClick back into the original tab and press Apply "
                            "again.",
                        )
                        return False
                if old_len:
                    # Real bug found live 2026-07-27 (pre-launch audit,
                    # confirmed via a live diagnostic run directly against the
                    # real running terminal): right at this exact moment --
                    # freshly regaining foreground -- the terminal's own
                    # rendering can briefly lag, and a read taken right here
                    # can land on an OLDER, already-painted exchange instead
                    # of the live input line. Confirmed directly: the
                    # "leftover" text a failed clear reported was, verbatim,
                    # something said earlier in the conversation, not
                    # anything just typed. Unlike the CLI-busy-for-a-long-
                    # time case (the whole screen is frozen there, so the old
                    # input line's content still matches what was analysed,
                    # and this correctly passes), a wrong-exchange read won't
                    # match the tail of what was actually analysed. A few
                    # quick retries (fractions of a second, nothing like the
                    # tens-of-seconds CLI-busy case the marker-based focus
                    # check was removed for) give the rendering a chance to
                    # catch up; if it still doesn't match, abort rather than
                    # clear-and-type into content that was never the live
                    # input to begin with.
                    expected_tail = _text_tail(expected_old_text)
                    if expected_tail:
                        for verify_attempt in range(3):
                            fresh_text, _ = get_focused_text()
                            if fresh_text is not None and expected_tail in fresh_text:
                                break
                            time.sleep(0.1)
                        else:
                            log("apply_new_text (terminal): ABORTED, fresh read before clearing didn't "
                                "match the analysed text (stale render or content changed), refusing "
                                "to clear/type")
                            popup.show_error(
                                *popup.last_position(),
                                "Comprsly couldn't confirm your terminal input still matches what it "
                                "analysed, so it left it untouched.\n\nClick back into the box and "
                                "press Apply again.",
                            )
                            return False
                    # Real ask 2026-07-26 (Antonio, direct: backspacing is
                    # unappealing, wants instant delete-and-replace like
                    # the browser/app versions already have). Ctrl+U
                    # ("kill line before cursor") is close to a universal
                    # terminal/readline convention -- bash, zsh, and
                    # virtually every Node-based CLI input widget
                    # implements it. Confirmed working live (Antonio: "it
                    # is deleting everything quickly and at once"). No
                    # backspace fallback anymore, on Antonio's explicit
                    # call ("I dont want the backspace") -- Ctrl+U alone,
                    # full stop. Verified the exact key dispatch via a
                    # mocked dry-run (no real input sent) before ever
                    # using it live.
                    #
                    # Real bug found live 2026-07-26 (Antonio, direct
                    # repro: "I went to the second row" -- same
                    # wrapped-line issue that hit the earlier Shift+End
                    # attempt): a single Ctrl+U likely only kills the
                    # CURRENT visual row, not the whole wrapped multi-row
                    # input, leaving earlier rows behind for the new text
                    # to land next to. Repeats it (still just Ctrl+U, no
                    # backspace) with a fresh get_focused_text() check
                    # between presses, stopping as soon as the field
                    # reads effectively empty (len<=1 tolerates the
                    # terminal's own cursor glyph being read back as a
                    # phantom character, same finding as the earlier
                    # backspace-loop bug). Still fast: each press is one
                    # keystroke, and a real prompt only wraps a handful of
                    # rows at most, capped generously so it can't run
                    # away.
                    # Real bug found live 2026-07-27 (Antonio: "it pasted my
                    # new prompt without clearing the first"): get_focused_
                    # text() now correctly returns None when the marker
                    # can't be found (e.g. mid-clear, before the CLI has
                    # repainted), but this loop's exit check treated that
                    # UNREADABLE state exactly the same as CONFIRMED EMPTY --
                    # `not remaining` is True for both "" and None -- so a
                    # single unreadable tick broke the loop after only one
                    # Ctrl+U, before the line was actually cleared, and the
                    # new text landed next to whatever was left. Only a
                    # DEFINITE empty reading (remaining is not None) should
                    # stop early now; an unreadable tick keeps pressing
                    # Ctrl+U up to the existing cap instead of assuming
                    # success.
                    # Real bug found live 2026-07-27 (same session,
                    # later): a fixed cap of 8 Ctrl+U presses assumed
                    # "a real prompt only wraps a handful of rows at
                    # most" -- true for typed prompts, not necessarily
                    # for a long DICTATED or PASTED one (Antonio uses
                    # both), which can wrap into far more rows than
                    # that. Hitting the cap before the line is
                    # actually clear reproduces the exact "pasted
                    # without clearing the first" symptom this loop
                    # exists to prevent, just from a different cause
                    # (cap too low instead of stopping too early).
                    # Scales the cap off old_len instead of a fixed
                    # guess, reusing the same CHARS_PER_LINE_GUESS
                    # wrap-width estimate already relied on elsewhere
                    # in this file for badge positioning -- doubled
                    # for headroom (an estimate, not a measurement, so
                    # it should err toward extra presses, which are
                    # harmless once the line is already clear), floor
                    # of 8 so short prompts behave exactly as before,
                    # hard ceiling of 60 so a pathological old_len
                    # still cannot hang Apply for long (worst case
                    # ~5s, and only ever reached if something is
                    # genuinely stuck, not in normal use).
                    # Real bug found live 2026-07-27 (same session, later
                    # still: Antonio direct repro, "the apply button isn't
                    # doing anything"): this loop used to call
                    # get_focused_text() BETWEEN every single Ctrl+U press
                    # to check for early-exit. Timed directly against the
                    # real terminal in this exact session: a single
                    # get_focused_text() call on a large scrollback buffer
                    # took 2-3 REAL SECONDS (UI Automation's TextPattern
                    # read is genuinely slow at that size, not a logic
                    # bug), so an 8-attempt loop spent up to ~20+ seconds
                    # just re-reading the buffer between keystrokes, not
                    # actually failing to clear anything. That's almost
                    # certainly why Apply looked like it was doing nothing
                    # -- it was still running, burning the clock on
                    # verification reads the loop never needed per-press
                    # in the first place. Fixed by sending the whole
                    # Ctrl+U burst first with no read in between (each
                    # press itself is cheap, and an extra press on an
                    # already-clear line is harmless, per this file's own
                    # established reasoning), then doing exactly ONE
                    # verification read afterward -- the existing
                    # pre_type/confirmed_cleared check right below already
                    # covers safety, it doesn't need a read after every
                    # single keystroke to do that job.
                    # Real bug found live 2026-07-27 (Antonio direct repro,
                    # pre-launch reliability pass): this used to be a single
                    # burst-then-check. Debug.log showed the burst
                    # occasionally lands zero effect at all (field reads the
                    # exact same length after 8 presses as before them),
                    # which looks like the keystrokes missing the input
                    # control that one time rather than Ctrl+U genuinely not
                    # working -- a timing thing, not a logic bug. Retrying
                    # the whole burst a couple more times before giving up
                    # only adds patience; it does NOT touch the "trust
                    # force_foreground, no marker re-check" rule Antonio
                    # locked in above, so it can't reintroduce that bug.
                    estimated_rows = old_len // CHARS_PER_LINE_GUESS + 1
                    clear_attempts = min(max(estimated_rows * 2, 8), 60)
                    max_clear_rounds = 3
                    pre_type = None
                    for round_num in range(1, max_clear_rounds + 1):
                        for _ in range(clear_attempts):
                            auto.SendKeys("{Ctrl}u", waitTime=0.01)
                            time.sleep(0.03)
                        time.sleep(0.1)
                        # Real bug found live 2026-07-27 (pre-launch audit,
                        # multi-tab testing): original_len in the log
                        # correctly matched the right tab's own buffer every
                        # time this "stuck" -- it was grabbing an OLDER
                        # exchange from within that SAME buffer, not a
                        # different tab's. That means Ctrl+U may well have
                        # already worked; the VERIFICATION READ was the
                        # unreliable part, occasionally landing on the wrong
                        # spot in the buffer's history for one call. A second
                        # quick read here, trusted if it shows empty even
                        # when the first didn't, is cheap insurance against
                        # exactly that -- it changes nothing about how many
                        # Ctrl+U presses get sent, only how the result gets
                        # checked.
                        pre_type, _ = get_focused_text()
                        if pre_type is not None and len(pre_type) > 1:
                            time.sleep(0.05)
                            retry_type, _ = get_focused_text()
                            if retry_type is not None and len(retry_type) <= 1:
                                pre_type = retry_type
                        if pre_type is not None and len(pre_type) <= 1:
                            break
                        if round_num < max_clear_rounds:
                            # Diagnostic 2026-07-27 (pre-launch audit, live
                            # repro: field plateaus at a nonzero length
                            # instead of reaching empty, same number every
                            # round) -- logging the actual leftover TEXT, not
                            # just its length, to tell apart "Ctrl+U only
                            # kills the current line of a multi-line prompt"
                            # from any other cause. Antonio's own debug.log,
                            # never sent anywhere.
                            log(f"apply_new_text (terminal): clear round {round_num} "
                                f"did not confirm empty (len={len(pre_type) if pre_type else 'unreadable'}), "
                                f"leftover={pre_type!r}, retrying")
                            _dump_terminal_diagnostic(f"clear round {round_num} stuck")
                    log(f"apply_new_text (terminal): about to type, field reads len={len(pre_type) if pre_type else 0} right before")

                    # Real bug found live 2026-07-27 (same session,
                    # later, Antonio direct repro: a long paste made
                    # the terminal fall back to the keystroke buffer
                    # for suggestions -- source=buffer in debug.log --
                    # and the clearing loop above never once got a
                    # readable state back (zero terminal-extraction log
                    # lines for its whole run), meaning Ctrl+U almost
                    # certainly was not clearing anything at all (most
                    # likely Claude Code CLI's own large-paste handling
                    # -- a confirmation prompt or collapsed placeholder
                    # -- put the box in a state that never matched the
                    # normal bordered-input structure this code
                    # assumes). The old code typed the new text
                    # regardless of whether pre_type ever confirmed
                    # empty -- that fallthrough is the actual gap, not
                    # anything about WHY the field was unreadable this
                    # time. Same fail-closed principle already applied
                    # to the read side (an unreadable marker returns
                    # None instead of guessing): only a DEFINITE empty
                    # reading is good enough to type onto. Anything
                    # else -- still has content, OR still unreadable --
                    # aborts instead of risking a second corrupted
                    # write on top of whatever is actually there.
                    confirmed_cleared = pre_type is not None and len(pre_type) <= 1
                    if not confirmed_cleared:
                        # Real finding 2026-07-27 (post-launch-audit dump
                        # analysis): every "stuck" case caught by
                        # _dump_terminal_diagnostic showed the SAME
                        # byte-for-byte content across many separate Apply
                        # attempts spanning up to 20 minutes, real Ctrl+U
                        # keystrokes and all -- proving this pre-type
                        # "verify empty" READ is the unreliable half of the
                        # equation, not necessarily the clearing itself.
                        # Aborting here on an unreliable read is why Apply
                        # looked completely dead: it never even reached the
                        # typing step. Instead of trusting this read as a
                        # gate, proceed to type anyway (best effort) and
                        # let the ALREADY-EXISTING post-type verification
                        # below -- which checks the one thing that actually
                        # matters, whether the new text is really in the
                        # buffer afterward -- be the real safety net. Worst
                        # case if this read genuinely was right and the
                        # field wasn't clear: new text lands next to old
                        # content, a visibly garbled but recoverable line,
                        # not silent data loss and not a dead button.
                        state_desc = "unreadable" if pre_type is None else f"still has {len(pre_type)} chars, leftover={pre_type!r}"
                        log(f"apply_new_text (terminal): could not confirm the field was cleared before typing "
                            f"({state_desc}), proceeding anyway -- post-type verification below is the real gate")
                # Second bracketing re-check, right before the single
                # most consequential action (typing the actual replacement
                # text) -- see the matching checkpoint above the clearing
                # loop for the full reasoning. The clearing loop itself
                # can take several seconds; re-verify one more time that
                # focus hasn't moved on since.
                if ctypes.windll.user32.GetForegroundWindow() != target_hwnd:
                    log("apply_new_text (terminal): ABORTED, foreground window changed during clearing")
                    popup.show_error(
                        *popup.last_position(),
                        "Comprsly lost track of your terminal window while clearing it, "
                        "so it left it untouched.\n\nClick back into the box and press "
                        "Apply again.",
                    )
                    return False
                auto.SendKeys(_sendkeys_escape(new_text), waitTime=0.01)
            finally:
                _self_injecting[0] = False
            set_typed_buffer(new_text)
            tail = _text_tail(new_text)
            verified, landed_text = _verify_landed(tail)
            log(
                f"applied via terminal keystroke-typing (no clipboard/paste), "
                f"new text length={len(new_text)}, paste_landed={verified}"
            )
            # Real change 2026-07-27 (same audit as the pre-type gate
            # removal above): this used to be logged and ignored, Apply
            # unconditionally returned True regardless of what verified
            # said. This is now the actual safety gate -- it checks the one
            # thing that matters (did the new text really land) instead of
            # a pre-type "is it empty" read that kept proving unreliable.
            # One retry of the whole clear+type before giving up, since a
            # single miss is more likely a timing blip than a hard failure.
            if verified != "yes":
                log("apply_new_text (terminal): first attempt did not verify, retrying clear+type once")
                # Audit fix 2026-07-27 (same change as above): the same
                # bracketing foreground-drift check used before the first
                # attempt applies here too -- this retry can run a couple
                # seconds after the first, plenty of time for alt-tab/click-
                # away, and without this check a drifted focus would send
                # Ctrl+U and the new text into whatever window the user is
                # now actually looking at instead of aborting.
                if ctypes.windll.user32.GetForegroundWindow() != target_hwnd:
                    log("apply_new_text (terminal): ABORTED, foreground window changed before retry")
                    popup.show_error(
                        *popup.last_position(),
                        "Comprsly lost track of your terminal window before it could retry, "
                        "so it left it untouched.\n\nClick back into the box and press Apply "
                        "again.",
                    )
                    return False
                # Audit fix 2026-07-27: the first attempt's Ctrl+U burst and
                # retype run under _self_injecting[0]=True (set at the top of
                # this whole block, cleared in the finally right after the
                # first SendKeys) so _low_level_keyboard_proc doesn't mistake
                # our own injected keystrokes for external input (dictation,
                # another tool) and mark the typed buffer untrusted. This
                # retry runs AFTER that finally already reset the flag to
                # False, so without re-setting it here, every Ctrl+U press
                # below would trip that exact false positive.
                _self_injecting[0] = True
                try:
                    # old_len can be 0 (field was already empty, no
                    # clear_attempts computed above) -- fall back to a sane
                    # default rather than referencing a variable that was
                    # never set in that path.
                    retry_clear_attempts = clear_attempts if old_len else 8
                    for _ in range(retry_clear_attempts):
                        auto.SendKeys("{Ctrl}u", waitTime=0.01)
                        time.sleep(0.03)
                    time.sleep(0.1)
                    auto.SendKeys(_sendkeys_escape(new_text), waitTime=0.01)
                finally:
                    _self_injecting[0] = False
                set_typed_buffer(new_text)
                verified, landed_text = _verify_landed(tail)
                log(f"apply_new_text (terminal): retry verification result: {verified}")
            if verified != "yes":
                popup.show_error(
                    *popup.last_position(),
                    "Comprsly typed your revision but couldn't confirm it landed "
                    "correctly.\n\nPlease check the terminal line before continuing.",
                )
                return False
            if dismiss_after:
                popup.dismiss()
            return True

        # Full-format snapshot, not just text (2026-07-22 market audit): a
        # screenshot/copied-files clipboard used to be destroyed by Apply and
        # never restored, because the text-only peek returned None for it.
        original = _snapshot_clipboard()
        wrote = _set_clipboard_text(new_text)
        verify = _peek_clipboard_text()
        log(
            f"apply_new_text: clipboard write ok={wrote}, "
            f"verified_match={verify == new_text}"
        )
        # ABORT before any keystroke if the clipboard doesn't verifiably hold
        # our text (audit 2026-07-25, HIGH): these results used to be logged
        # and ignored, so with a clipboard manager holding the clipboard past
        # every retry, Ctrl+A selected the user's whole prompt and Ctrl+V
        # pasted their UNRELATED old clipboard over it -- or pasted nothing,
        # leaving the prompt fully selected, one keystroke from deletion.
        # Fail closed instead: their text and their clipboard stay untouched.
        if not wrote or verify != new_text:
            _restore_clipboard(original)
            popup.show_error(
                *popup.last_position(),
                "Comprsly couldn't get access to the clipboard (another app "
                "may be holding it), so it left your text untouched.\n\n"
                "Try Apply again in a moment.",
            )
            log("apply_new_text: ABORTED, clipboard write unverified, nothing selected or pasted")
            return False

        # Real bug found 2026-07-20, continued: Antonio confirmed the
        # select-all now visibly highlights the real box (the foreground fix
        # above worked), but the paste itself didn't stick, the OLD text
        # came back. Root cause: Chromium/Electron's own paste handling is
        # asynchronous, it doesn't necessarily finish reading the clipboard
        # the instant Ctrl+V is sent. The old code restored your original
        # clipboard only 0.2s after the paste keystroke, a race that could
        # easily win against Claude actually reading OUR content first,
        # silently reinserting your original clipboard contents on top and
        # making Apply look like a complete no-op. Re-asserting foreground
        # right before Ctrl+A too (in case anything shifted focus during the
        # clipboard round-trip above) and giving the paste much more room
        # to actually land before touching the clipboard again.
        #
        # 2026-07-21: the second force_foreground that used to sit here is
        # gone. restore_field_focus above already did it, and doing it twice
        # was itself flagged as the likely cause of the visible double-jump
        # glitch. Repeating it here would also risk undoing the click that
        # just put the caret in the composer.
        current_fg = ctypes.windll.user32.GetForegroundWindow()
        log(
            f"apply_new_text: about to send Ctrl+A/Ctrl+V, foreground now "
            f"{_window_title(current_fg)}, focus_verified={focus_state}"
        )

        # Mark our own synthetic keys so the hook doesn't mistake them for
        # dictation and flag the buffer untrusted (see _self_injecting).
        _self_injecting[0] = True
        try:
            auto.SendKeys("{Ctrl}a", waitTime=0.05)
            time.sleep(0.15)
            auto.SendKeys("{Ctrl}v", waitTime=0.05)
            # Real ask 2026-07-21: this used to be a blind 0.6s sleep, the
            # measured worst case for Chromium/Electron to actually read the
            # clipboard before the original gets restored below. That's the
            # right ceiling to keep (still used verbatim by the un-confirmed
            # branch), but always paying the full 0.6s on every Apply is what
            # made the click feel frozen even on the common case, where the
            # paste actually lands in well under that. Poll for it instead
            # and stop as soon as it's confirmed, same safety margin, faster
            # in practice.
            tail = _text_tail(new_text)
            deadline = time.time() + 0.6
            paste_confirmed = False
            while time.time() < deadline:
                time.sleep(0.03)
                check_text, _ = get_focused_text()
                if check_text is not None and tail and tail in check_text:
                    paste_confirmed = True
                    break
            if not paste_confirmed:
                time.sleep(0.05)  # small settle margin even in the worst case
        finally:
            _self_injecting[0] = False

        # Put the user's own clipboard back (Win32 again, same reasoning),
        # whatever format it held: text, image, files.
        _restore_clipboard(original)

        # Real gap found 2026-07-20: the paste itself is a synthetic
        # keystroke, correctly ignored by the anti-self-trigger filter, so
        # without this the tracked buffer would keep believing the OLD
        # text was still in the box after Apply, causing the very next
        # click to run inference on stale content instead of what's
        # actually there now.
        set_typed_buffer(new_text)

        # Read the field back and say plainly in the log whether the paste
        # actually landed. Every past "Apply does nothing" round was slow to
        # diagnose because the success line only proved the function ran
        # without raising. This proves the text is really in the box.
        landed_text, _ = get_focused_text()
        if landed_text is None:
            verified = "unreadable"
        elif _text_tail(new_text) and _text_tail(new_text) in landed_text:
            verified = "yes"
        else:
            verified = "NO"

        if dismiss_after:
            popup.dismiss()
        log(
            f"applied suggestion, new text length={len(new_text)}, "
            f"dismiss_after={dismiss_after}, paste_landed={verified}"
        )
        # paste_landed="unreadable" is still True here on purpose: Claude's
        # composer is exactly the field get_focused_text can't read back
        # (that's why the typed buffer exists), so treating unreadable as
        # failure would drop nearly every real success in the app this tool
        # is for. Every genuine refusal above already returned False.
        return True
    except Exception:
        log_exception("apply_new_text")
        return False


def _safe_pattern(control, pattern_id):
    """Generic pattern lookup that survives control-type mismatches.

    Real root-cause bug found 2026-07-21: this code used the typed helpers
    `control.GetValuePattern()` / `control.GetTextPattern()`. Those only
    exist on certain control classes, so when the focused element was a
    GroupControl (which is exactly what a contenteditable chat box focuses
    as, in Claude AND on the web) they raised AttributeError, the bare
    except swallowed it, and we concluded "this app exposes nothing" and
    fell back to keystroke reconstruction. That single wrong conclusion is
    what caused the dictation blindness, the Ctrl+A-selects-the-whole-page
    transcript disaster, and the clipboard flashing. Verified directly:
    querying PatternId.TextPattern generically on the focused GroupControl
    returns Claude's composer text."""
    try:
        return control.GetPattern(pattern_id)
    except Exception:
        return None


def _owning_hwnd_for_control(control):
    """The real top-level window a UIA control belongs to (2026-07-27, see
    get_focused_text's terminal-detection fix below for the bug this
    exists to close). Many UIA elements -- especially deeply nested ones
    inside a modern terminal's single render surface -- report
    NativeWindowHandle as 0, they aren't backed by their own HWND. Walk up
    the UIA ancestor chain until one is, then resolve that HWND's real
    top-level ancestor the same way _host_window_rect already does
    (GA_ROOT), so a child pane's handle doesn't get mistaken for the
    actual application window."""
    try:
        node = control
        hwnd = 0
        for _ in range(8):  # a real UI tree is never this deep to a window
            if node is None:
                break
            hwnd = getattr(node, "NativeWindowHandle", 0) or 0
            if hwnd:
                break
            node = node.GetParentControl()
        if not hwnd:
            return 0
        GA_ROOT = 2
        return ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    except Exception:
        return 0


def get_focused_text():
    """Text of the currently focused control, i.e. the active chat box,
    whatever app or site it lives in. Returns (text, control).

    Real bug found live 2026-07-26: the terminal input-line extraction
    used to be applied at exactly ONE call site (the watch_loop analysis
    tick), so suggestions looked right, but Apply -- which independently
    calls this same function fresh to capture expected_old_text -- still
    got the terminal's ENTIRE unfiltered buffer, tripping the safety cap
    and refusing to do anything ("apply does nothing"). Patching every
    individual call site is exactly the kind of thing that's easy to miss
    one of; doing the extraction HERE instead means every caller,
    present and future, gets it automatically."""
    try:
        control = auto.GetFocusedControl()
        if control is None:
            return None, None

        # Real bug found live 2026-07-27 (Antonio, screenshot: suggestions
        # for text that wasn't there, garbage like "prompt.S" -> "prompts."
        # showing over an empty terminal input): this used to ask "is the
        # FOREGROUND window a terminal", a SEPARATE query from `control`
        # above. Those two can briefly disagree -- the foreground window and
        # whatever UIA currently calls "the focused control" are tracked
        # independently by Windows and aren't guaranteed to be the same
        # window on every tick. When they disagree, `is_terminal` was
        # computed from the WRONG window while `control`'s own text still
        # came from the terminal, so the terminal-input-line filter got
        # silently skipped and the terminal's ENTIRE raw scrollback buffer
        # was treated as "the current input" instead, running grammar/
        # spelling suggestions against whatever text happened to be on
        # screen. Fixed by asking the SAME control that's about to be read
        # which window it actually belongs to, so the two can never
        # disagree.
        is_terminal = False
        try:
            is_terminal = _process_name_for_hwnd(
                _owning_hwnd_for_control(control)) in TERMINAL_HOST_PROCESSES
        except Exception:
            is_terminal = False

        # Plain fields (textarea, input, native edits) expose ValuePattern.
        value_pattern = _safe_pattern(control, PatternId.ValuePattern)
        if value_pattern is not None:
            try:
                value = value_pattern.Value
                if value:
                    if is_terminal:
                        value = _log_terminal_extraction(value)
                    return value, control
            except Exception:
                pass

        # Rich/contenteditable composers (Claude, ChatGPT, most chat UIs)
        # expose TextPattern instead.
        text_pattern = _safe_pattern(control, PatternId.TextPattern)
        if text_pattern is not None:
            try:
                # 2026-07-27: terminals go through the LIVE pattern object,
                # not a pre-flattened GetText(-1) string -- see
                # _extract_terminal_input_line's docstring for the live
                # diagnostic finding this replaced (naive "\n" splitting
                # silently saw the whole buffer as one line, often).
                if is_terminal:
                    text = _log_terminal_extraction(text_pattern)
                    return text, control
                text = text_pattern.DocumentRange.GetText(-1)
                if text:
                    return text, control
            except Exception:
                pass

        return None, control
    except Exception:
        # UIA throws on plenty of legitimate window/control states
        # (elevated windows, controls that vanish mid-read, etc.), skip
        # this cycle rather than crash the watcher.
        return None, None


# State-change tracker for _log_terminal_extraction below -- re-added
# 2026-07-26 after Apply kept failing even once the marker itself was
# confirmed correct, to see WHY it's still intermittently not matching
# rather than guess a second time.
_gft_terminal_last_logged = [None]

# Real, structural bug found live 2026-07-27 (same session, right after
# v0.9.89 shipped): the whole marker-then-border approach below used to
# work on a PLAIN STRING via text.split("\n"), on the assumption that a
# terminal's rendered rows are separated by real newline characters.
# Confirmed live, via a diagnostic run directly against this exact
# machine's real terminal, that this assumption is simply wrong some (a
# lot) of the time: Windows Terminal's TermControl does NOT reliably
# include "\n"/"\r" characters in TextPattern.DocumentRange.GetText(-1)'s
# output -- a live 5507-character read had ZERO of either anywhere in
# it, meaning text.split("\n") returned the WHOLE flattened buffer as a
# single one-element list, so there were no separate "lines" for the
# marker/border search to compare against at all. This is the real
# reason fixes kept not "staying consistent" -- it wasn't the
# border-matching heuristic being subtly wrong, it was that the data it
# ran against sometimes had no line structure in it whatsoever.
#
# The fix: use UIA's OWN line-unit range navigation instead of string
# splitting -- ExpandToEnclosingUnit(TextUnit.Line) and
# Move(TextUnit.Line, +-1) on a TextPatternRange. Confirmed live against
# the real control that this reliably returns correctly-bounded visual
# rows regardless of whether "\n" characters are present anywhere,
# verified against real GetBoundingRectangles() output matching known
# y-coordinates already used elsewhere in this file for badge
# positioning (e.g. y=961 lining up exactly with box_rect values seen
# in debug.log all session).
#
# Also confirmed live: a real border row is not guaranteed to be 100%
# U+2500 characters end-to-end -- an otherwise-clearly-a-border top row
# was found with non-dash content trailing after roughly the first 30
# characters. The border check now requires only a solid RUN of border
# characters at the START of the line (min_run below), not full-line
# purity, which tolerates that while still correctly rejecting genuine
# prose (which won't start with a long dash run at all).
MAX_TERMINAL_WRAPPED_ROWS = 40


def _is_terminal_border_line(text, min_run=10):
    """A line counts as a border row if it starts with a solid run of at
    least min_run box-drawing horizontal-line characters (U+2500) once
    leading/trailing whitespace is stripped -- see the constant comment
    above for why this is a prefix check, not a full-line purity check."""
    stripped = text.strip()
    if len(stripped) < min_run:
        return False
    return all(ch == "\u2500" for ch in stripped[:min_run])


def _log_terminal_extraction(text_pattern):
    """Runs _extract_terminal_input_line and logs (marker_found,
    original_len, extracted_len) on a state change, never the actual
    text -- same privacy rule as everywhere else. Centralized here (not
    watch_loop) so it covers every get_focused_text() caller, including
    Apply's own fresh capture, not just the analysis tick.

    2026-07-27, twice: first changed to take the LIVE TextPattern object
    instead of a pre-flattened string (fixed a real "\n unreliable" bug),
    then _extract_terminal_input_line was rewritten AGAIN the same day to
    do its actual work via regex over the string instead of further UIA
    calls (fixed a real multi-second-per-call performance bug the first
    rewrite introduced) -- see that function's own docstring for the full
    story. Still takes the pattern object here only so this call site can
    get `doc` for the one cheap GetText(-1) read; nothing downstream does
    further range navigation on it anymore."""
    try:
        doc = text_pattern.DocumentRange
        original_text = doc.GetText(-1)
    except Exception:
        return None
    original_len = len(original_text) if original_text else 0
    extracted = _extract_terminal_input_line(doc, original_text)
    marker_found = extracted is not None
    extracted_len = len(extracted) if extracted is not None else 0
    state = (marker_found, original_len, extracted_len)
    if state != _gft_terminal_last_logged[0]:
        _gft_terminal_last_logged[0] = state
        log(
            f"get_focused_text terminal extraction: marker_found={marker_found}, "
            f"original_len={original_len}, extracted_len={extracted_len}"
        )
    return extracted


_BORDER_RUN_RE = re.compile("\u2500{10,}")
# Real find 2026-07-27 (pre-launch audit): the one signal that actually
# tells Windows Terminal tabs apart -- see _extract_terminal_input_line,
# which populates this on every successful extraction.
_last_terminal_tab_name = [None]
# Generous allowance for the status line(s) that sit between the top
# border and the marker (see the "border, status line, marker, border"
# structure documented above). A few hundred characters comfortably
# covers a couple of wrapped status rows without being loose enough to
# match some unrelated border seen far earlier in scrollback.
_TERMINAL_TOP_BORDER_MAX_GAP = 500


def _extract_terminal_input_line(doc_range, full_text):
    """Best-effort isolation of just the CLI's current input line.

    2026-07-27, rewritten again, same day: the previous version (real
    UIA line-unit navigation via Move(TextUnit.Line, ...) on doc_range)
    was built to fix a genuine bug -- full_text doesn't reliably contain
    "\\n"/"\\r" at all, so naive string splitting silently saw the whole
    buffer as one line. That fix was correct but had a real, separately
    confirmed cost: timed live against this exact machine's terminal,
    EACH individual TextPatternRange navigation call (Move, or
    MoveEndpointByUnit by either a small or a large offset -- both
    measured, both cost the same) took roughly 0.5-1 real second, a
    fixed per-call cost, not proportional to distance moved. A typical
    extraction needing 4-8 such calls (position the marker, check the
    border above, walk forward a few rows to the border below) added up
    to the ~3-7 second Apply/suggestion delays Antonio reported.

    The actual insight that fixes both problems at once: line boundaries
    were never the real requirement. The border rows are made of U+2500
    characters, a distinct, searchable PATTERN, not a line concept -- so
    finding them is a plain regex search over full_text (already fetched
    by ONE fast GetText(-1) call, confirmed live at ~0.001s regardless of
    buffer size), needing zero further UIA calls at all. This is immune
    to the original "\\n unreliable" bug for the same reason line-unit
    navigation was: it never assumes newlines exist either, doc_range is
    kept as a parameter for API-compatibility with existing callers but
    is no longer used here.

    Confirms "border, marker, border" the same way the line-based version
    did (a top border within _TERMINAL_TOP_BORDER_MAX_GAP characters
    before the marker, a bottom border found by searching forward),
    fails closed (returns None) exactly where the old version did: no
    marker, no nearby top border, or no bottom border found within the
    search cap."""
    if not full_text:
        return None
    marker_pos = full_text.rfind("\u276f")
    if marker_pos == -1:
        return None

    # Nearest border run BEFORE the marker must be close enough to be the
    # box's own top border, not some unrelated border seen earlier in
    # scrollback -- same guarantee the old "is the line above a border"
    # check gave, expressed as a proximity search instead.
    top_border = None
    for m in _BORDER_RUN_RE.finditer(full_text, 0, marker_pos):
        top_border = m
    if top_border is None or (marker_pos - top_border.end()) > _TERMINAL_TOP_BORDER_MAX_GAP:
        return None

    # Real find 2026-07-27 (pre-launch audit, live diagnostic dump): Windows
    # Terminal's tabs all share one hwnd AND, it turns out, the SAME UIA
    # RuntimeId and owning-window through every check tried -- but the tab's
    # own NAME is rendered directly into this exact border row, right before
    # the marker (confirmed live: "... 2nd Venture Assistant --[marker]").
    # That's the one signal that actually differs between tabs. Cached here
    # (not returned -- every existing caller of this function keeps working
    # unchanged) so callers that specifically need tab identity can read it
    # via _last_terminal_tab_name right after calling this.
    _last_terminal_tab_name[0] = full_text[top_border.end():marker_pos].strip(" ─")

    # Bottom border: nearest run of border characters after the marker,
    # within a generous search window. Character-based equivalent of the
    # old MAX_TERMINAL_WRAPPED_ROWS row cap, using the same
    # CHARS_PER_LINE_GUESS estimate already relied on elsewhere in this
    # file (badge positioning, the Ctrl+U clear-attempt scaling);
    # computed here rather than as a module-level constant since
    # CHARS_PER_LINE_GUESS is defined later in the file.
    tail_search_cap = MAX_TERMINAL_WRAPPED_ROWS * CHARS_PER_LINE_GUESS
    search_end = min(len(full_text), marker_pos + 1 + tail_search_cap)
    bottom_border = _BORDER_RUN_RE.search(full_text, marker_pos + 1, search_end)
    if bottom_border is None:
        return None

    content = full_text[marker_pos + 1:bottom_border.start()]
    return " ".join(content.split())


def _dump_terminal_diagnostic(reason):
    """Diagnostic only (pre-launch audit, 2026-07-27): writes the CURRENT
    focused control's raw full_text plus exactly where the marker/border
    match landed to a separate local file, never sent anywhere, so a live
    repro of the "stuck on old content" bug can be inspected directly
    instead of guessed at. Called only from the terminal apply path's own
    stuck-detection, never during normal use."""
    try:
        control = auto.GetFocusedControl()
        if control is None:
            return
        text_pattern = control.GetPattern(PatternId.TextPattern)
        if text_pattern is None:
            return
        full_text = text_pattern.DocumentRange.GetText(-1)
        marker_pos = full_text.rfind("❯") if full_text else -1
        top_border = None
        if full_text and marker_pos != -1:
            for m in _BORDER_RUN_RE.finditer(full_text, 0, marker_pos):
                top_border = m
        bottom_border = None
        if full_text and marker_pos != -1:
            tail_search_cap = MAX_TERMINAL_WRAPPED_ROWS * CHARS_PER_LINE_GUESS
            search_end = min(len(full_text), marker_pos + 1 + tail_search_cap)
            bottom_border = _BORDER_RUN_RE.search(full_text, marker_pos + 1, search_end)
        path = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Comprsly", "terminal_diagnostic_dump.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {reason} @ {time.strftime('%H:%M:%S')} ===\n")
            f.write(f"full_text length: {len(full_text) if full_text else 0}\n")
            f.write(f"marker_pos: {marker_pos}\n")
            f.write(f"top_border: {(top_border.start(), top_border.end()) if top_border else None}\n")
            f.write(f"bottom_border: {(bottom_border.start(), bottom_border.end()) if bottom_border else None}\n")
            f.write(f"RAW FULL TEXT:\n{full_text!r}\n")
    except Exception as e:
        log_exception(f"_dump_terminal_diagnostic: {e!r}")


# Small inset from the box's OWN right edge, not a floating gap outside it
# (real ask 2026-07-25, reversing the 2026-07-21 decision below: "Grammarly's
# icon sits within the chat box itself... to the right, and I think that
# looks really nice"). See PersistentBadge._position_for.
#
# ~~Fixed gap between the badge and a known LLM app's input box (real ask
# 2026-07-21). Widened from 12: sitting right at the box's edge read as
# touching/inside it rather than a distinct floating indicator next to
# it.~~ That was the design goal for exactly one version: a badge that visibly
# floats OUTSIDE the box. The 2026-07-25 direction is the opposite -- inside,
# docked to the box's own edge like Grammarly's -- so the old wide gap would
# now read as the badge drifting away from the box instead of nesting in it.
#
# Widened 10 -> 16 (2026-07-26, Antonio, direct: "the badge green circle is
# close to crossing over the line of the chat box"). The heat-status dot
# sits in the badge's own bottom-right corner (see _make_heat_badge_image),
# so it was closer to the box's edge than the 10px inset alone suggests --
# widening the whole badge's inset gives the dot room too, not just the
# badge's own outline.
BADGE_INSIDE_INSET = S(16)

# Real bug found live 2026-07-30 (Antonio, screenshot: ChatGPT Classic desktop
# app -- badge landing directly in the toolbar row, at/on the submit button).
# Root cause: BADGE_WIDEN_RIGHT_SITES widens ChatGPT's detected right edge
# out to the true visual edge of its inline toolbar (mic, submit button),
# then the badge docks BADGE_INSIDE_INSET in from that widened edge. The
# default 16px inset clears Gemini's toolbar fine but isn't enough room on
# ChatGPT's, so it lands on the rightmost element there, the submit button.
# Per-site override on top of the base inset, same "each site gets its own
# explicit slot" philosophy as BADGE_WIDEN_RIGHT_SITES, not a universal
# formula. FIRST-PASS ESTIMATE from the screenshot's proportions, not a
# live pixel measurement (this environment can't see the real floating
# badge, see PersistentBadge._position_for) -- expect to retune once
# confirmed live against the real running app.
#
# "Claude Code" added 2026-07-31 (Antonio, live: "move the code badge to
# the right please, just a little bit"). This site's badge always goes
# through the plain right-edge inset (its TermControl rect always spans
# the full pane width, no toolbar-cluster detection applies to a
# terminal) -- SMALLER inset here means closer to the pane's right edge,
# i.e. further right. 16 -> 6. CONFIRMED CORRECT (Antonio, live, direct:
# "Claude is good now mark that correct... LOCK ALL CLAUDE PARTS NO MORE
# FIXING") -- this covers all three Claude surfaces (plain chat via
# BADGE_TOOLBAR_GAP_OVERRIDES above, Cowork/inline-Send via
# CLAUDE_INLINE_SEND_EXTRA_GAP, and this terminal inset).
# Reopened 2026-08-03 (Antonio, live, direct, by name: "the terminal badge
# placement is amazing but... the badge should just move to the left
# horizontally 1 badge space left" -- an explicit, by-name ask, the only
# thing that authorizes touching this path, see the permanently-scoped
# terminal block further down in this file). LARGER inset = further from
# the pane's right edge = further left. 6 -> 6 + one full design badge
# width (58).
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Lock this, that is
# perfect"). Do not retune without a new, explicit, by-name ask about the
# terminal/CLI specifically -- see this file's permanently-scoped terminal
# block further down for why a general "fix the badge" ask never
# authorizes touching this constant on its own.
BADGE_INSIDE_INSET_OVERRIDES = {"ChatGPT": S(56), "Claude Code": S(6 + DESIGN_BADGE_SIZE)}

# Gap between the badge's right edge and the real toolbar control it's
# docking against once _toolbar_cluster_left finds one (2026-07-30). Small
# and fixed on purpose -- this is "distance from the very next control," a
# different, much smaller problem than BADGE_INSIDE_INSET's "distance from
# a plain box edge," so it deliberately doesn't reuse that constant.
BADGE_TOOLBAR_GAP = S(10)

# Real bug found live 2026-07-30 (Antonio, several screenshots, same spot
# every time): on Claude specifically, the badge kept landing ON TOP of
# "Opus 4.8" -- the model name -- instead of before it, even after
# _walk_toolbar_children was widened from an allowlist to a denylist (see
# _TOOLBAR_WRAPPER_TYPES) to catch plain text labels too. Root cause,
# confirmed via the candidate-dump diagnostic (see _toolbar_cluster_left /
# _below_toolbar_cluster_left's own "candidates:" log line): Claude's
# accessibility tree exposes exactly two ButtonControls in that row (the
# effort dropdown and the mic) and NOTHING for "Opus 4.8" at all -- not
# missing because of a control-type filter, missing because the text
# itself carries no accessible role UIA can see, so no amount of widening
# the type filter can ever find it. The nearest real, detectable control
# (the effort dropdown) is the best anchor available; this adds extra
# clearance past BADGE_TOOLBAR_GAP on top of it so the badge lands before
# the invisible-to-UIA label too, not just before the button after it.
# Retuned six times: 70 -> 90 -> 130 -> 190 -> 210 -> 240 (2026-07-30/31).
# CONFIRMED CORRECT at 240 at the time (Antonio, live, direct: "IT IS
# PERFECT LOCK IT"). This override is PLAIN-CHAT-ONLY (Claude's "Opus
# 4.8"/"Sonnet 5" layout). Never applied to the Cowork/inline-Send layout,
# see CLAUDE_INLINE_SEND_EXTRA_GAP.
# Reopened 2026-08-02 (Antonio, screenshot, live: badge needs to move
# right more -- confirmed this IS the plain-chat layout, "Chat" selected
# not "Cowork", so this is the right constant to touch, not the Cowork
# one). 240 -> 120 overshot: confirmed via a further screenshot the badge
# landed ON TOP of the "Sonnet 5" label text itself (covering the "So").
# 170 STILL overlapped ("S" hidden this time) -- three straight guesses
# by eye all missed, so stopped guessing and measured the real page
# directly (claude-in-chrome, getBoundingClientRect on the actual
# elements) instead of a fourth screenshot-based estimate. Real numbers:
# the detected anchor (toolbar_left) lands on the Send button cluster at
# x=1397, NOT the model-picker label itself, which starts at x=1194 --
# a real gap of 203px is required just to clear the label's own left
# edge, which is why every value below ~200 (120, 170) landed inside the
# text. 240's old margin (250 total) was ~47px of clearance past that;
# 210 keeps it close as asked while staying past the measured threshold.
# Also confirmed live in the same session: Chat and Cowork's toolbars
# render at IDENTICAL coordinates in the common case, so this single
# corrected value covers both, not just plain chat. Confirmed again
# 2026-08-02 after the below-row/inline-send priority swap (see
# _claude_inline_send_button's own call site): this is now the value that
# governs Claude's PLAIN CHAT layout AND Cowork's common (non-deep-task)
# state, both routed through the same below-row detector -- only a true
# Cowork/project task view with nothing findable below-row falls through
# to CLAUDE_INLINE_SEND_EXTRA_GAP below.
# Reverted 2026-08-03: a 210 -> 190 change here was a misread of a "move it
# right" ask that was actually about the Code/"Accept edits" review
# composer (see CLAUDE_CODE_REVIEW_GAP), not this plain-chat/Cowork path.
# Antonio, direct: "i didnt ask you to do that on the claude chat i asked
# you to do that on the claude code not the chat version." Back to 210,
# untouched.
# Real bug found live 2026-08-03 (Antonio, screenshot: the bottom, real-
# conversation composer -- box (793,497,1429,602), the SAME one 210 was
# originally calibrated against -- badge landing right after "+" instead
# of near "Sonnet 5"). Root cause: a SIDE EFFECT of the below_toolbar_
# cluster_left row-selection fix shipped earlier tonight (the one that
# stops accepting a row until it's confirmed to have real candidates).
# That fix reaches a fuller ancestor than the old code ever did, and that
# ancestor's subtree now exposes "Sonnet 5" itself as a real ButtonControl
# at x=1194 -- confirmed via debug.log candidates dump: this exact
# composer used to report only [(1397,...)], now reports [(1194,...),
# (1357,...),(1357,...),(1397,...)]. 1194 exactly matches the label's real
# left edge measured live back when this constant was first tuned ("the
# model-picker label itself... starts at x=1194"), which was undetectable
# by UIA at the time -- so it was never truly invisible, just unreachable
# by the old, narrower row match. 210 was built to jump PAST that
# invisible label from a distant Send-button anchor; now that the label
# itself is the anchor, that entire premise is gone. Small buffer instead.
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "It is now fixed you can
# lock the (claude cowork/chat) no reason to mess with it anymore"). This
# covers both the bottom/deep-conversation composer AND the Home/Cowork
# composer's own fallback -- see CLAUDE_HOME_ROW_GAP for the latter's
# separate, already-locked override. Do not retune without a new real ask.
BADGE_TOOLBAR_GAP_OVERRIDES = {"Claude": S(8)}

# Real ask 2026-08-03 (Antonio, screenshot: Perplexity's Computer/task
# composer, badge overlapping "Orchestrator" -- see
# _perplexity_long_model_row's own comment for why this is scoped to that
# specific label, not a blanket Perplexity override). Move left ~2
# badge-widths, as asked.
# Retuned 2026-08-03 (Antonio, live, right after: "You should move it to
# the right just a little bit more please"). Smaller gap = further right.
# 2x -> 1.7x badge-widths.
# Retuned 2026-08-03 (Antonio, live, right after: "Another badge length to
# the right please"). 1.7x -> 0.7x badge-widths.
#
# Superseded 2026-08-03 -- see PERPLEXITY_COMPUTER_ANCHOR_GAP and
# _perplexity_computer_anchor below. This gap was measured against the
# OLD anchor (the "Model" button, whose real text width UIA can't see at
# all), so it was always going to need retuning again for the next long
# name that showed up. Kept defined (still referenced by the fallback
# path below if the new Computer anchor isn't found for some reason) but
# no longer the primary dial.
PERPLEXITY_LONG_MODEL_GAP = S(0.7 * DESIGN_BADGE_SIZE)

# Small fixed buffer past the "Computer" button's own right edge -- see
# _perplexity_computer_anchor's docstring for why this button (not the
# variable-width "Model" one) is the stable, name-length-independent
# anchor. Same small-buffer magnitude as every other "real, precisely-
# located button" case in this file (e.g. BADGE_TOOLBAR_GAP itself).
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Ok that looks good now
# make sure you lock perplexity now please" -- confirmed via debug.log
# showing computer_right=1023 firing correctly). This covers the
# Computer/Orchestrator task composer; the plain search composer is
# covered separately with zero override, see BADGE_TOOLBAR_BELOW_SITES's
# own Perplexity lock note. Do not retune without a new real ask.
PERPLEXITY_COMPUTER_ANCHOR_GAP = S(10)

# Extra clearance for the Cowork/project layout's inline Send button (see
# _claude_inline_send_button), used ONLY as a fallback since the 2026-08-02
# priority swap -- see that call site's own comment for why. Separate from
# BADGE_TOOLBAR_GAP_OVERRIDES above on purpose: this one is its own dial so
# tuning it can never move the (now much more commonly hit) plain-chat/
# common-Cowork path above. Real ask 2026-07-30 (Antonio, live, right after the
# inline-Send fix shipped: "cowork/chat is in the wrong spot needing to be
# more left" -- explicitly NOT the plain-chat layout). FIRST-PASS estimate,
# expect to retune again once confirmed live.
# Retuned 2026-08-02 (Antonio, screenshot, live: badge correct area but
# needs to move right a bit more, Cowork/chat only -- Claude Code's
# terminal badge is separately locked, see BADGE_INSIDE_INSET_OVERRIDES's
# own comment, and is untouched by this constant). Smaller gap = badge
# sits closer to the Send button = further right. 40 -> 20.
# Retuned again same day: 20 still read as basically unmoved to Antonio
# ("didn't move it to the correct position"), explicitly asked for a
# bigger jump this time, toward the "Opus 4.8" label specifically. Cut to
# 0 -- Cowork now gets the SAME base gap as every other toolbar-anchored
# badge (BADGE_TOOLBAR_GAP alone), no extra Cowork-specific clearance on
# top of it.
# Retuned again same day, after the real _claude_inline_send_button
# scoping bug (see that function's own comment) was fixed and this value
# could finally be judged on Cowork alone, not contaminated by plain
# chat: Antonio asked for a further move right, specifically "two badge
# lengths." bx = toolbar_left - gap - BADGE_ICON_SIZE, so this needs to
# go NEGATIVE (gap subtracted -> a negative gap ADDS) by 2x the badge
# diameter. Deliberately NOT run through S(): that helper floors at 1,
# which would silently discard a negative value entirely. Same
# UI_SCALE math S() itself uses, just without the floor.
# Retuned again 2026-08-02: after the below-row/inline-send priority
# swap, this path is now only reached for a genuine deep Cowork/project
# task view (see the call site's comment), not the common case anymore.
# Antonio asked for one more full badge-length move right on that
# screenshot. -2x -> -3x the badge diameter.
CLAUDE_INLINE_SEND_EXTRA_GAP = -int(round(3 * DESIGN_BADGE_SIZE * UI_SCALE))

# Real bug found live 2026-08-03 (Antonio, screenshot: badge floating
# alone in dead space in the middle of the toolbar row, not tucked
# against either the "Accept edits" cluster or the "Sonnet 5"/"High"
# cluster). This is claude.ai/code's diff-review composer (Claude
# proposed a code change, showing "Accept edits" instead of a normal
# Send button) -- it routes through the same below-row detector as
# plain chat/Cowork and lands on a similarly-positioned anchor
# (toolbar_left=1397 in both, confirmed via debug.log), so it was
# incorrectly sharing BADGE_TOOLBAR_GAP_OVERRIDES["Claude"] (210px,
# tuned to clear a real Send button PLUS an invisible-to-UIA label in
# the plain-chat layout). This composer has no Send button at all
# (Enter submits) and its own invisible-to-UIA label ("Sonnet 5") sits
# much closer to the detected anchor. Confirmed via a live
# claude.ai/code reproduction (getBoundingClientRect): "Sonnet 5"
# starts at x=1358.7, the UIA anchor lands at x=1397 -- only ~38px
# apart, not 203. This dial only governs that narrower gap, detected
# via _claude_code_review_row's "Accept edits" check so it never
# touches the plain-chat/Cowork path above.
# Retuned 2026-08-03 (Antonio, direct: move THIS one right, not the
# plain-chat one -- see the correction on BADGE_TOOLBAR_GAP_OVERRIDES
# above). Real ceiling here, not a free dial: the measured anchor-to-
# label distance is only ~38px (1397 - 1358.7), so anything below ~40
# starts covering "Sonnet 5" text again, the exact failure this
# constant was created to fix. 50 -> 42, close to that floor with a
# small buffer left.
# Real bug found live 2026-08-03 (Antonio, screenshot: "Auto" state,
# badge landing on the "asasas" text line instead of the toolbar row).
# Same side-effect root cause as BADGE_TOOLBAR_GAP_OVERRIDES's own
# 2026-08-03 note: the below_toolbar_cluster_left row-selection fix now
# reaches a fuller ancestor, exposing "Sonnet 5" itself as a real
# ButtonControl (confirmed via debug.log: this composer's candidates now
# include (1193,...), where before only a single distant anchor showed
# up). The whole "~38px, not 203px" premise above was ALREADY the small-
# gap case; this just tightens it further now that the anchor is the
# label itself, not a nearby-but-still-separate button. 42 -> 8, matching
# the plain-chat fix's same small buffer.
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Claude works well. Lock
# all of them please" -- covers both the "Accept edits" and "Auto"
# states). Do not retune without a new real ask.
CLAUDE_CODE_REVIEW_GAP = S(8)

# Real bug found live 2026-08-03 (Antonio, screenshot: Home "How can I
# help you today?" composer, badge landing right after the "Cowork"
# toggle instead of near "Sonnet 5"/"Opus 4.8"). Same root issue as
# CLAUDE_CODE_REVIEW_GAP just above -- see _claude_home_row's own
# docstring for the live measurement (anchor ~1237 vs model button left
# ~1225, not 200px+ apart). Starting from the same measured ballpark as
# the Code-review case since both anchor directly on/near the model
# button rather than a distant Send button; expect to retune once
# confirmed live.
# Retuned 2026-08-03 (Antonio, live, right after shipping: "move it to the
# right a little more please like another badge size to the right, only
# on the center screen chat box"). Goes negative on purpose past this
# point -- same "subtract past zero -> push right of the anchor itself"
# trick as CLAUDE_INLINE_SEND_EXTRA_GAP, so deliberately NOT run through
# S() (that helper floors at 1, which would silently discard the negative
# part). 45 -> one badge-width further right.
# Retuned 2026-08-03 (Antonio, live, right after: "move over to the left
# just a little more another half of a badge space over"). One full
# badge-width right was a slight overshoot -- pull back half a badge.
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "lock the center (claude
# cowork/chat) chatbox please the way you set it up is great"). Do not
# retune this, is_home_row, or _claude_home_row's "cowork" marker without
# a new real ask.
CLAUDE_HOME_ROW_GAP = int(round((45 - 0.5 * DESIGN_BADGE_SIZE) * UI_SCALE))

# Real ask 2026-08-03 (Antonio, live, right after CLAUDE_CODE_REVIEW_GAP
# shipped and the horizontal position was confirmed correct): move the
# badge up 1.5 badge-heights from its row-centred default. Same
# is_code_review scoping as the gap above, so this can't misapply to
# plain chat/Cowork's own row-centred vertical position.
# Real bug found live 2026-08-03 (Antonio, screenshot: "Auto" state,
# badge landing UP on the "asasas" text line, clamped to the very top of
# the box). Root cause: same row-selection fix as CLAUDE_CODE_REVIEW_GAP
# above -- the row it centres on now sits much closer to the box's own
# top than when this 1.5x shift was tuned, so subtracting a fixed 1.5
# badge-heights now overshoots PAST the box's top edge entirely and hits
# the clamp, landing in the text row instead of the toolbar row. That
# clamp only existed to keep the badge inside the box, not to be relied
# on as the real position -- removing the now-stale manual shift and
# trusting the row-centring math directly, same as every other layout
# that doesn't need this extra correction.
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Claude works well. Lock
# all of them please"). Do not retune without a new real ask.
CLAUDE_CODE_REVIEW_VSHIFT = 0

# Real ask 2026-08-03 (Antonio, live, Gemini's Home "What should we focus
# on?" single-line composer: "it should move up a little to be inline
# with flash"). _toolbar_cluster_left's only real candidate for this
# composer is the "Flash" model-picker button's own clickable hit-area
# (row=(556,597), 41px tall), which is taller than the "Flash" text
# actually rendered inside it -- centring on the whole hit-area lands the
# badge a bit lower than the visible text. FIRST-PASS estimate, expect to
# retune once confirmed live.
# Retuned 2026-08-03 (Antonio, live, right after: "It looks as if you
# moved it down. So i think move it up a half a badge size would be the
# best play for this sizing"). Root cause of the "moved down" report:
# the row-centred position was already landing above the box's own top
# edge even with zero vshift, so the clamp was silently absorbing the
# whole 10px and this constant had ZERO real effect -- fixed at the
# source in _position_for (the clamp's top bound now loosens by the
# vshift instead of fighting it), so this value finally reaches the
# screen. 10 -> half a badge width, as asked, now measured in real design
# pixels instead of a guessed constant.
# Retuned 2026-08-03 (Antonio, live, right after: "Maybe move it down a
# quarter of a badge size thats the one. make sure you actually move it
# down exactly that distance"). Now that the clamp fix above makes this
# value a direct, linear 1:1 pixel offset (confirmed via the math: with
# the natural row-centre already above rect.top for this composer, the
# final position collapses to exactly `rect.top - GEMINI_VSHIFT`, no
# other term matters), a straight 0.5x -> 0.25x reduction moves it down
# by precisely 0.25 badge-widths, exactly as asked.
# Retuned 2026-08-03 (Antonio, live, right after: "another 1/4 of the
# badge down please"). 0.25x -> 0x, same direct 1:1 relationship.
# Retuned 2026-08-03 (Antonio, live, right after: "Push the badge up like
# 1/5th of the badge size please you almost have the gemini in line with
# the text"). 0x -> 0.2x, same direct 1:1 relationship.
# Retuned 2026-08-03 (Antonio, live, right after: "move it down 1/6th of
# the badge size please si close"). 0.2x -> (0.2 - 1/6)x, same direct 1:1
# relationship, net move down by exactly 1/6 badge-width.
# Retuned 2026-08-03 (Antonio, live, right after: "Just up a very little").
# Small nudge up, +0.05 badge-widths.
# Retuned 2026-08-03 (Antonio, live, right after: "One more time very very
# little please youre so close"). Tiniest nudge up, +0.02 badge-widths.
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Nice lock that in for the
# single line center page gemini... the center page chatbox is done" --
# covers both the single-line case this constant governs AND the multi-
# line below-row fallback, confirmed working as-is with no further
# tuning needed, see the fallback's own call-site comment). Do not retune
# without a new real ask.
GEMINI_VSHIFT = int(round((0.2 - 1.0 / 6.0 + 0.05 + 0.02) * DESIGN_BADGE_SIZE * UI_SCALE))

# Real ask 2026-08-03 (Antonio, live, screenshot: Grok's Home single-line
# composer only, explicitly NOT the multi-line one -- "the badge isnt
# sitting inline with the Fast next to it... raising up the badge by
# 1/4th the size of the badge itself should get it closer"). Scoped to
# single-line specifically via GROK_SINGLE_LINE_MAX_HEIGHT below, a
# raw-box-height check, so the already-good multi-line composer (a much
# taller raw box once text wraps) can never pick this up.
# Retuned 2026-08-03 (Antonio, live, right after: "you did move it up but
# again you cant move it to up so move it down just a bit to get it
# inline with the Fast"). 0.25x -> 0.15x badge-widths.
# Retuned 2026-08-03 (Antonio, live, right after: "Move it down a 1/4th
# of its own size please"). 0.15x -> -0.10x badge-widths (goes negative
# on purpose, same "subtract past zero -> push down further" relationship
# as every other toolbar_row_vshift dial in this file).
# Retuned 2026-08-03 (Antonio, live, right after: "move it up a 1/6th of
# th badge please"). -0.10x -> (1/6 - 0.10)x badge-widths.
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Ok lock grok that is now
# done"). Covers the single-line composer (this constant) and the multi-
# line composer (already correct with zero override, see
# GROK_SINGLE_LINE_MAX_HEIGHT's own scoping note). Do not retune without
# a new real ask.
GROK_SINGLE_LINE_VSHIFT = int(round((1.0 / 6.0 - 0.10) * DESIGN_BADGE_SIZE * UI_SCALE))

# Real ask 2026-08-03 (Antonio, live, right after Copilot was first wired
# into the below-row detector: "you need to move the badge below about 1
# and a 1/2 badge spaces please"). Negative on purpose -- same "subtract
# past zero -> push down" relationship as every other toolbar_row_vshift
# dial in this file.
# CONFIRMED CORRECT (Antonio, live, 2026-08-03: "Lock it please this is
# great you fixed it" -- covers single-line and multi-line, both routed
# through the same below-row detector once the ancestor-climb depth fix
# let it actually find the real toolbar row, see
# _below_toolbar_cluster_left's own comment on that). Do not retune
# without a new real ask.
COPILOT_VSHIFT = -int(round(1.5 * DESIGN_BADGE_SIZE * UI_SCALE))

# Raw (pre-widen) box height threshold separating Grok's single-line Home
# composer from the multi-line one -- measured single-line real height
# was ~45px (683,486,1315,531); comfortably below where genuine multi-
# line growth starts.
GROK_SINGLE_LINE_MAX_HEIGHT = S(80)

# Real ask 2026-08-03 (Antonio, live, Cowork home composer: "you didnt add
# it to the area i asked it barley got moved i need you to move the badge
# only to the right"), right after the split_left_right fix shipped --
# that fix anchors to the real leftmost control in the right-hand cluster,
# but "Opus 4.8"/"Sonnet 5" itself is invisible to UIA (see
# BADGE_TOOLBAR_GAP_OVERRIDES's own comment, same root issue on the OTHER
# Claude layout), so the base BADGE_TOOLBAR_GAP alone still lands the
# badge short of the label, not clearly past it. Negative on purpose, same
# "subtract a negative -> push right" trick as CLAUDE_INLINE_SEND_EXTRA_GAP.
# Retuned 2026-08-03 (Antonio, live, right after 1.5x shipped: "move it to
# the right a lot more please"). Original ask was "3-4 badge lengths" from
# its pre-fix position -- 1.5x badge was too timid a first guess. 1.5 -> 3.5.
CLAUDE_HOME_ROW_EXTRA_GAP = -int(round(3.5 * DESIGN_BADGE_SIZE * UI_SCALE))

# Approximate height of the CLI's own bordered input box (top border, the
# ">" prompt line, bottom border) within a terminal's single accessible
# TermControl, which otherwise covers the entire pane -- see the raw_rect
# slicing in watch_loop. FIRST-PASS ESTIMATE (Antonio's own screenshot of
# the box, not a measured font/line-height), expect to retune once seen
# live against a real rendered layout.
#
# Real bug found live 2026-08-02 (Antonio, screenshot: badge floating on
# empty black space in Claude's "Code" view, "AI Summer Project" -- the
# view's actual content is compact and sits well above the pane's true
# bottom, so slicing the literal bottom N px of the whole pane landed on
# blank space instead of the real input line). This blind guess only ever
# worked by coincidence, when a pane happened to be full enough of
# scrollback that the input line really was near the bottom -- see
# _find_terminal_input_line_rect below for the real fix, this constant is
# now ONLY the fallback for when that fails.
TERMINAL_INPUT_BOX_HEIGHT_GUESS = S(70)

# Cache for _find_terminal_input_line_rect: real UIA range-navigation
# calls are the exact cost that made the old line-by-line version of
# _extract_terminal_input_line unusable (0.5-1s PER call, see that
# function's own docstring for the full story) -- so this is deliberately
# NOT recomputed every 0.7s watch_loop tick. Time-based, not content-
# based: badge position doesn't need to react within one tick, a couple
# seconds of staleness while actively typing is a fair trade against
# paying UIA's real per-call cost on every single tick regardless of
# whether anything changed.
_TERMINAL_LINE_RECT_CACHE_SECONDS = 2.0
_terminal_line_rect_cache = {"time": 0.0, "hwnd": None, "rect": None}


def _find_terminal_input_line_rect(text_pattern, hwnd):
    """Real screen rect of the terminal's current input line, found via
    UIA's own text-range API instead of the blind "bottom N px of the
    whole pane" guess (TERMINAL_INPUT_BOX_HEIGHT_GUESS) that breaks
    whenever the pane isn't full of content -- see that constant's own
    comment for the live repro this exists to fix.

    Deliberately NOT the line-by-line Move(TextUnit.Line) walk that was
    already tried and reverted for cost in _extract_terminal_input_line
    (0.5-1s PER navigation call from an unknown starting point, stacking
    to a real 3-7s Apply delay). This uses a FIXED, small number of calls
    instead: FindText jumps directly to the marker in one call,
    ExpandToEnclosingUnit and GetBoundingRectangles run ONCE each on that
    one resulting range -- three calls total, not four to eight. Time-
    boxed by the caller's own cache (see _TERMINAL_LINE_RECT_CACHE_SECONDS)
    so even this bounded cost isn't paid on every single tick.

    Returns None (caller falls back to TERMINAL_INPUT_BOX_HEIGHT_GUESS)
    if the marker isn't found, isn't the REAL live one, the range can't
    be expanded, or no rectangle comes back -- same fail-safe every
    terminal detection in this file already uses, so this can never make
    positioning worse than the guess it's replacing.

    Real bug found live 2026-08-02 (Antonio, direct, right after this
    first shipped): FindText(backward=True) returns the LAST "❯" in the
    whole captured buffer, but Claude Code's CLI echoes one for every
    PAST turn in scrollback too -- the exact same stale-marker trap
    _extract_terminal_input_line already solved (2026-07-27) by requiring
    a real border run directly above a marker before trusting it as the
    live one, not just anything reachable in scrollback. This reuses that
    EXACT proven check (_BORDER_RUN_RE / _TERMINAL_TOP_BORDER_MAX_GAP, the
    same constants, not a re-derived guess) against one extra cheap
    GetText(-1) call (confirmed elsewhere in this file at ~0.001s
    regardless of buffer size) before ever trusting FindText's result."""
    now = time.time()
    cache = _terminal_line_rect_cache
    if hwnd == cache["hwnd"] and (now - cache["time"]) < _TERMINAL_LINE_RECT_CACHE_SECONDS:
        return cache["rect"]
    result = None
    try:
        started = time.time()
        doc = text_pattern.DocumentRange
        full_text = doc.GetText(-1)
        marker_is_live = False
        if full_text:
            marker_pos = full_text.rfind("❯")
            if marker_pos != -1:
                top_border = None
                for m in _BORDER_RUN_RE.finditer(full_text, 0, marker_pos):
                    top_border = m
                if top_border is not None and (marker_pos - top_border.end()) <= _TERMINAL_TOP_BORDER_MAX_GAP:
                    marker_is_live = True
        if marker_is_live:
            found = doc.FindText("❯", True, False)
            if found is not None and found.ExpandToEnclosingUnit(auto.TextUnit.Line):
                rects = found.GetBoundingRectangles()
                if rects:
                    left = min(r.left for r in rects)
                    top = min(r.top for r in rects)
                    right = max(r.right for r in rects)
                    bottom = max(r.bottom for r in rects)
                    if right > left and bottom > top:
                        result = _SimpleRect(left, top, right, bottom)
        elapsed = time.time() - started
        # Real timing, not assumed -- this is exactly the measurement that
        # caught the earlier line-by-line approach costing 0.5-1s per call
        # live; logged so the same check can be made on this replacement
        # before trusting it, same discipline every fix in this file uses.
        log(f"_find_terminal_input_line_rect: {elapsed:.3f}s, "
            f"marker_is_live={marker_is_live}, "
            f"{'found' if result is not None else 'not found'}")
    except Exception as e:
        log_exception(f"_find_terminal_input_line_rect: {e!r}")
        result = None
    cache["time"] = now
    cache["hwnd"] = hwnd
    cache["rect"] = result
    return result

# Window-relative fallback ONLY (2026-07-26) -- for a terminal where UIA
# exposes no control at all (unlike Windows Terminal's TermControl, which
# the slicing above now handles as a real box). Kept as a last-resort
# safety net, not the primary path anymore -- confirmed dead for THIS
# terminal live (2026-07-31, debug.log: a real TermControl is always
# found, rect always spans the full pane width), so this was the wrong
# constant to touch for "move the code badge right" -- see
# BADGE_INSIDE_INSET_OVERRIDES instead, which drives the real path.
TERMINAL_STATUS_LEFT_OFFSET = S(230)
TERMINAL_STATUS_BOTTOM_OFFSET = S(25)

# Rough stand-in for "the compose box's right edge" on apps with no
# accessible control to actually measure it from (Claude's Electron
# composer, see watch_loop's no-accessible-control branch) -- an
# approximation, not a measured value like the constant above it, since
# there's no real box rect to measure against here. Picked to clear a
# typical sidebar/nav rail without guessing at any one app's exact layout.
# Mirrors the box's OWN right edge, not the badge's outside-left position
# WINDOW_LEFT_INSET used to name (see BADGE_INSIDE_INSET above for why).
WINDOW_RIGHT_INSET = 40

# Same idea for the vertical axis (2026-07-25, following the dictation
# screenshot: tracking the live caret put the badge on top of moving
# mid-sentence text). Chat composers (Claude, ChatGPT, Gemini) all live
# near the bottom of the window, so anchoring near the bottom edge is far
# more stable than chasing a caret that moves as you type or dictate --
# but a FIXED offset (tried first, still overlapped text) only clears a
# one-line message; the composer grows upward as a message wraps to more
# lines. These estimate that growth from the same typed-buffer text
# already being tracked each tick, rather than a single guessed constant.
# Still an approximation, not a measurement -- there's no accessible
# control here to read the box's real height from.
CHARS_PER_LINE_GUESS = 70
LINE_HEIGHT_GUESS = 26
BOX_PADDING_GUESS = 50
# Caps how far a long paste/dictation can push the badge up the window --
# past this, treat it as "many lines" rather than growing without bound.
MAX_ESTIMATED_WRAP_LINES = 8


class _BadgeRect:
    """A plain-numbers stand-in for a UIA BoundingRectangle, so a
    coordinate the badge is anchored to can be a corrected value (see
    _input_box_left) rather than only ever a live UIA object. Exposes the
    same .left/.top/.right/.bottom the positioning code already reads, so
    it's interchangeable with a real Rect everywhere downstream.

    toolbar_left (2026-07-30) is extra, optional precision on top of that:
    the real left edge of an inline toolbar cluster (see
    _toolbar_cluster_left), when one was found. A real UIA BoundingRectangle
    never has this attribute, so _position_for reads it via getattr(...,
    None), never a direct .toolbar_left, to stay interchangeable with one.

    toolbar_row_top/toolbar_row_bottom (2026-07-30, see
    _below_toolbar_cluster_left) are the further-still precision a
    below-the-text-row toolbar layout needs: that row's OWN vertical span,
    distinct from this whole rect's top/bottom (which for those sites spans
    the text row plus the toolbar row combined). When set, _position_for
    centres the badge on the row instead of the whole box.

    toolbar_extra_gap (2026-07-30, see BADGE_TOOLBAR_GAP_OVERRIDES) is a
    per-OPEN, not per-site, extra pixel gap on top of BADGE_TOOLBAR_GAP --
    set by the caller only when the specific detection path used actually
    needs it (Claude's plain-chat layout, compensating for a label UIA
    can't see), left at 0 for every other path, including Claude's OTHER
    (Cowork) layout, so a fix for one Claude layout can't misapply to the
    other just because they share an app_label."""
    __slots__ = ("left", "top", "right", "bottom", "toolbar_left",
                 "toolbar_row_top", "toolbar_row_bottom", "toolbar_extra_gap",
                 "toolbar_row_vshift")

    def __init__(self, left, top, right, bottom, toolbar_left=None,
                 toolbar_row_top=None, toolbar_row_bottom=None,
                 toolbar_extra_gap=0, toolbar_row_vshift=0):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom
        self.toolbar_left = toolbar_left
        self.toolbar_row_top = toolbar_row_top
        self.toolbar_row_bottom = toolbar_row_bottom
        self.toolbar_extra_gap = toolbar_extra_gap
        # Vertical counterpart to toolbar_extra_gap (2026-08-03, see
        # CLAUDE_CODE_REVIEW_VSHIFT): pixels to shift the row-centred `by`
        # UP before the box-bounds clamp. 0 for every path except the one
        # that explicitly sets it, same per-detection-path scoping as the
        # horizontal gap.
        self.toolbar_row_vshift = toolbar_row_vshift


def _input_box_left(control):
    """Left edge of the VISUAL input box, which is not always the focused
    control's own rect.left.

    Real bug confirmed in debug.log 2026-07-22 (ChatGPT): its focused
    control is the ProseMirror *EditControl*, whose rect starts where the
    TEXT starts, i.e. to the RIGHT of the '+' button and the pill's left
    padding (left=885, while the visual pill starts ~80px further left).
    Placing the badge a fixed gap left of that inset rect dropped it
    straight onto the '+'. Claude's focused control is instead the
    *GroupControl* wrapping the whole box (left=708 already IS the visual
    edge), so it needs no correction. Rather than special-case either app
    by name, walk up a few ancestors and, if one extends meaningfully
    further left on the same row (a real control-zone inset, not mere
    padding, and not a tall full-width page wrapper), use its left.

    Bounded so it is a genuine no-op when there's no real inset, which
    keeps every already-correct app (Claude included) exactly where it is:
      - delta 30..150px only: ignores a few px of padding (Claude), and
        rejects the page wrapper (hundreds of px further left).
      - height band: the ancestor must be roughly the input row's own
        height, so a full-page-tall wrapper that happens to sit within
        150px on the left can't be mistaken for the box."""
    try:
        base = control.BoundingRectangle
        text_left = base.left
        mid_y = (base.top + base.bottom) // 2
        base_h = base.bottom - base.top
        best_left = text_left
        node = control
        for _ in range(6):
            try:
                node = node.GetParentControl()
            except Exception:
                break
            if node is None:
                break
            try:
                r = node.BoundingRectangle
            except Exception:
                continue
            delta = text_left - r.left
            same_row = (r.top <= mid_y <= r.bottom)
            # Not dramatically taller than the input row itself (rejects a
            # page-height wrapper). base_h*4 + 200 tolerates a composer
            # whose container includes a bottom toolbar row.
            reasonable_height = (r.bottom - r.top) <= base_h * 4 + 200
            if 30 <= delta <= 150 and same_row and reasonable_height:
                best_left = min(best_left, r.left)
        return best_left
    except Exception:
        try:
            return control.BoundingRectangle.left
        except Exception:
            return None


# Sites whose toolbar (model selector, mic, voice) sits INLINE to the right
# of the composer, in the same row, outside the UIA-detected control's own
# rect (confirmed live 2026-07-28: ChatGPT/Gemini badge landed mid-toolbar
# instead of at the bar's true right edge). Claude/Perplexity/Copilot put
# that same toolbar row BELOW the input instead, so their detected rect
# already spans the full visual width -- deliberately not in this set (see
# BADGE_WIDEN_DOWN_SITES below for the HEIGHT half of that same "below the
# input" layout, which turned out not to be fine after all). Each site
# gets its own explicit slot (Antonio, direct: "I want llm to have their
# own spot... rather than 1 spot per"), not a universal formula applied to
# every site.
BADGE_WIDEN_RIGHT_SITES = {"Gemini"}

# Sites whose toolbar (Search/Computer picker, Model picker, mic) sits
# BELOW the composer's own single-line text row, in a separate row UIA
# doesn't fold into the focused control's own rect -- confirmed live
# 2026-07-30 (Antonio, screenshots): Perplexity and Copilot both showed the
# badge sitting at the box's top-right CORNER, overlapping the rounded
# border, instead of centred against the whole visual card. The comment
# above BADGE_WIDEN_RIGHT_SITES assumed these two "already span the full
# visual width" -- true for width, but nobody had a screenshot to check
# HEIGHT until now: their detected rect apparently only covers the short
# top text line, so _position_for's vertical centring (box_h // 2) lands
# well above the true visual centre of the taller full card.
#
# FIRST-PASS HYPOTHESIS from screenshot proportions, not a live rect
# measurement (same caveat as BADGE_INSIDE_INSET_OVERRIDES) -- expect to
# retune once confirmed against a real debug.log "badge rect source" line.
#
# Claude, Grok, DeepSeek added same day as BADGE_TOOLBAR_BELOW_SITES below,
# same reasoning -- gives those three a sane widened-box fallback for
# whatever rare tick _below_toolbar_cluster_left doesn't find a row on.
#
# ChatGPT moved here from BADGE_WIDEN_RIGHT_SITES (2026-08-01, real ask:
# "the way it sits in one line is good, but when you add more lines it
# doesn't move to the right place"). Root-caused with real evidence, not
# assumed: queried ChatGPT's live composer via getBoundingClientRect() at
# 1, 3, and 6 lines. Confirmed the toolbar row (Add files / model picker /
# mic / send) sits in its OWN row below the text -- textbox bottom stayed
# ~91-92px the whole time while textbox top climbed from -2 to -107 as
# lines were added (grows UPWARD, exactly Claude's documented shape) --
# and the toolbar row's own top/bottom barely moved (92->88, 128->124).
# ChatGPT was wrongly in the SAME-ROW family (BADGE_WIDEN_RIGHT_SITES /
# _toolbar_cluster_left, built for Gemini's actual same-row layout), which
# explains the reported instability: that function's "same row as the
# text" gate is checking a relationship that was never true for ChatGPT's
# real DOM, so it only ever matched by accident on some ticks.
BADGE_WIDEN_DOWN_SITES = {"Perplexity", "Copilot", "Claude", "Grok", "DeepSeek", "ChatGPT", "Gemini"}

# Sites in BADGE_WIDEN_DOWN_SITES whose badge should ALSO dock left of the
# below-row toolbar's right-hand group (Model dropdown, mic, submit) via
# _below_toolbar_cluster_left, instead of the plain widened-box fallback
# inset. Real ask 2026-07-30 (Antonio, screenshot): Perplexity's badge sat
# crowded between the mic icon and the submit arrow -- move it to before
# "Model" instead.
#
# Widened same day (Antonio, screenshots): Claude, Grok, and DeepSeek all
# showed the identical shape of bug -- a toolbar row (Opus/High, Fast,
# DeepThink/Search) sitting BELOW the composer's own text area, badge
# correct on a short single-line box (where box-centre happens to land
# near the row by coincidence) but floating well above it, sometimes
# mid-text, the moment the box grows past one line. Same layout family as
# Perplexity, same fix. Copilot stays OUT on purpose -- still nobody's
# reported this on Copilot specifically, so it keeps the plain widened-box
# fallback rather than being switched to unconfirmed logic it doesn't need.
#
# Antonio, live, 2026-08-03: "Perplexity is perfect make it locked please
# the center screen is perfect and the bottom is perfect too even with
# the multiple lines" -- true for the plain search composer, both single-
# and multi-line. Turned out NOT to cover every Perplexity composer,
# though: a separate task/Computer-mode layout (see
# BADGE_TOOLBAR_GAP_OVERRIDES's "Perplexity" entry) needed its own real
# gap, caught right before this lock was finalized.
#
# Copilot finally added 2026-08-03 (Antonio, screenshots: badge floating
# fully disconnected from the composer -- top of the "Trending Topics"
# list on the empty single-line box, dead centre of the text area on the
# multi-line one -- explicit real ask: "it should sit next to the send
# arrow... dont move it away from the left side of the arrow when you
# add more lines"). Exactly the "nobody's reported this yet" gap the
# comment above used to describe -- same below-row family as Claude/
# Perplexity/Grok now that it has one.
#
# DeepSeek CONFIRMED CORRECT as-is (Antonio, live, 2026-08-03: "Deepseek
# is also locked and done too") -- plain defaults, no per-site override
# needed, same as Perplexity's own plain search composer.
BADGE_TOOLBAR_BELOW_SITES = {"Perplexity", "Claude", "Grok", "DeepSeek", "ChatGPT", "Copilot"}


def _input_box_right(control, raw_right):
    """Mirrors _input_box_left, widening the RIGHT edge instead of the left,
    for the sites in BADGE_WIDEN_RIGHT_SITES only. Same bounded ancestor walk
    and same delta/row/height gates, just measuring from the opposite edge."""
    try:
        base = control.BoundingRectangle
        mid_y = (base.top + base.bottom) // 2
        base_h = base.bottom - base.top
        best_right = raw_right
        node = control
        for _ in range(6):
            try:
                node = node.GetParentControl()
            except Exception:
                break
            if node is None:
                break
            try:
                r = node.BoundingRectangle
            except Exception:
                continue
            delta = r.right - raw_right
            same_row = (r.top <= mid_y <= r.bottom)
            reasonable_height = (r.bottom - r.top) <= base_h * 4 + 200
            if 30 <= delta <= 250 and same_row and reasonable_height:
                best_right = max(best_right, r.right)
        return best_right
    except Exception:
        return raw_right


def _input_box_bottom(control, raw_bottom):
    """Mirrors _input_box_right, widening the BOTTOM edge instead of the
    right, for BADGE_WIDEN_DOWN_SITES only. Same bounded ancestor walk, but
    gated on horizontal overlap (same COLUMN) instead of vertical (same
    row) -- here the extra toolbar is a row stacked below the text line,
    not a cluster sitting beside it, so "does this ancestor cover the same
    horizontal span" is the right same-widget test instead."""
    try:
        base = control.BoundingRectangle
        mid_x = (base.left + base.right) // 2
        base_w = base.right - base.left
        best_bottom = raw_bottom
        node = control
        for _ in range(6):
            try:
                node = node.GetParentControl()
            except Exception:
                break
            if node is None:
                break
            try:
                r = node.BoundingRectangle
            except Exception:
                continue
            delta = r.bottom - raw_bottom
            same_column = (r.left <= mid_x <= r.right)
            reasonable_width = (r.right - r.left) <= base_w * 4 + 200
            if 20 <= delta <= 200 and same_column and reasonable_width:
                best_bottom = max(best_bottom, r.bottom)
        return best_bottom
    except Exception:
        return raw_bottom


# Real interactive control types the toolbar cluster (model-picker dropdown,
# mic, submit) is actually made of, as opposed to the wrapper Group/Pane
# elements that also happen to cover the same screen area. See
# _toolbar_cluster_left.
# Real direction 2026-07-30 (Antonio, direct, after the TextControl patch
# below fixed Claude but only that one site's specific gap): "find the open
# space on all the chat boxes where what I'm telling you would be" -- stop
# allowlisting individual control types one site-report at a time (Button,
# then ComboBox, then TextControl for Claude's plain-text "Opus 4.8"
# label...) and instead treat almost ANYTHING with a real, visible rect in
# the toolbar band as occupied space to dock BEFORE, the same denylist
# philosophy _NEVER_A_COMPOSER_CONTROL_TYPES already uses below (an
# allowlist means every missed type is a silent per-site bug; a denylist of
# the few types that are never real occupied content is far harder to miss
# a case on). Wrapper/container types are the only exclusion -- they WRAP
# the real content rather than being it, so counting them as candidates
# too would anchor on the wrapper's own (often wider) edge instead of the
# real element inside it; _walk_toolbar_children still recurses into them
# either way to reach what's actually inside.
_TOOLBAR_WRAPPER_TYPES = {
    "PaneControl", "GroupControl", "CustomControl", "WindowControl",
    "DocumentControl",
}

# Control types that can never legitimately be a chat composer. Real bug
# confirmed live 2026-07-30 (Antonio, screenshot): the badge anchored
# directly onto a range-slider's thumb on an unrelated claude.ai Artifact
# page -- app_label_for only answers WHICH SITE this is (domain/title
# match), it never checks WHAT'S ACTUALLY FOCUSED, so any focused control
# on a recognized LLM domain got trusted as "the composer," slider thumbs
# included.
#
# A DENYLIST on purpose, not an allowlist: matching every real composer's
# exact control type across every current and future supported site would
# be guesswork, and a missed type would silently break that site's badge
# entirely. These are instead the few types that can safely be assumed to
# NEVER be a real text composer no matter which site they show up on --
# narrow and low-risk, same spirit as the single-type DocumentControl
# rejection this reuses (see the "whole-page control" comment below).
_NEVER_A_COMPOSER_CONTROL_TYPES = {
    "SliderControl", "ThumbControl", "ButtonControl", "SplitButtonControl",
    "CheckBoxControl", "RadioButtonControl", "ProgressBarControl",
    "ScrollBarControl", "TabControl", "TabItemControl", "MenuItemControl",
    "ToolBarControl", "ImageControl", "SeparatorControl",
}


def _safe_next_sibling(node):
    try:
        return node.GetNextSiblingControl()
    except Exception:
        return None


# Real bug found live 2026-07-31 (Antonio, caught directly in his own
# debug.log): the "unrecognized browser tab" diagnostic below logged a
# Gmail compose ancestor's accessible Name in full -- which turned out to
# be the ENTIRE typed email body (name, phone, email, the works). That
# diagnostic's own comment claimed Name is "structural UI labels, never
# typed content, same privacy standard as the badge-rect logging
# elsewhere" -- an assumption that was never actually verified and turned
# out to be false for at least this one real app. Real UI labels/titles
# are short; mirrored typed content routinely isn't. Capping length is a
# blunt but effective backstop that doesn't require knowing in advance
# which apps do this -- a genuine label still reads fine truncated, a
# leaked paragraph gets cut down to nothing meaningful.
_DIAG_NAME_MAX = 40


def _safe_diag_name(name):
    if not name:
        return name
    name = str(name)
    if len(name) > _DIAG_NAME_MAX:
        return name[:_DIAG_NAME_MAX] + "…[truncated]"
    return name


def _composer_diag_dump(control, tag, depth=3):
    """Structural dump of a composer's own ancestor chain and each
    ancestor's immediate children (type, length-capped name, rect) --
    generalized 2026-07-31 from the Claude-only version that successfully
    found the real cause of several real bugs today (the invisible-to-UIA
    "Opus 4.8" label, the Cowork inline Send button, a UIA staleness
    glitch). Applying the same real-evidence approach to ChatGPT/Gemini's
    "no row found" failure on a taller/expanded composer state instead of
    guessing whether it's a depth problem or a gate-tuning problem.
    `tag` is just the log-line label (e.g. "claude", "widen-right") so
    multiple call sites share this one implementation without their
    output being ambiguous about which composer it came from."""
    try:
        anc = control
        for d in range(depth):
            kids = []
            try:
                child = anc.GetFirstChildControl()
            except Exception:
                child = None
            n = 0
            while child is not None and n < 20:
                try:
                    cr = child.BoundingRectangle
                    kids.append((child.ControlTypeName, _safe_diag_name(child.Name),
                                 (cr.left, cr.top, cr.right, cr.bottom)))
                except Exception:
                    pass
                child = _safe_next_sibling(child)
                n += 1
            # Node's own Name deliberately NOT logged (privacy) -- at
            # depth 0 this IS the focused composer, and some apps mirror
            # typed content into Name (see _safe_diag_name's own comment).
            try:
                r = anc.BoundingRectangle
                anc_desc = (anc.ControlTypeName, (r.left, r.top, r.right, r.bottom))
            except Exception:
                anc_desc = (None, None)
            log(f"{tag} composer diag[{d}]: node={anc_desc} children={kids}")
            try:
                anc = anc.GetParentControl()
            except Exception:
                break
            if anc is None:
                break
    except Exception:
        log_exception(f"{tag} composer diag")


def _walk_toolbar_children(node, raw_right, mid_y, out, depth):
    # Bounded depth -- this only ever walks a single toolbar row's own
    # subtree (a handful of controls), never the wider window, so staying
    # cheap even unbounded in breadth is fine.
    if depth > 4:
        return
    try:
        child = node.GetFirstChildControl()
    except Exception:
        return
    while child is not None:
        try:
            ctype = child.ControlTypeName
            r = child.BoundingRectangle
        except Exception:
            child = _safe_next_sibling(child)
            continue
        real_size = (r.right > r.left) and (r.bottom > r.top)
        # Inside the toolbar cluster (right of the text area's own edge,
        # before any widening) and roughly level with it vertically -- the
        # toolbar row itself, not text wrapped above/below it. Denylist,
        # not allowlist (see _TOOLBAR_WRAPPER_TYPES) -- anything real and
        # visibly sized in this band counts as occupied space to dock
        # BEFORE, whether it's a button, a dropdown, a plain text label, or
        # an icon; only pure wrapper/container types are skipped as
        # CANDIDATES (they're still walked into below either way).
        if (ctype not in _TOOLBAR_WRAPPER_TYPES and real_size
                and r.left >= raw_right - S(4)
                and r.top - S(20) <= mid_y <= r.bottom + S(20)):
            # (left, top, bottom, type) -- real ask 2026-07-30 (Antonio,
            # several screenshots, ChatGPT/Perplexity/Grok all showing the
            # same thing: badge correct on a short single-line composer,
            # wrong -- floating well above the toolbar -- the moment it
            # grows to multiple lines). Used to be just r.left. ctype is
            # extra (2026-07-30, Claude still landing wrong after the
            # denylist widening): callers log the full candidate list now,
            # so the NEXT report has real data on what was actually found
            # instead of another guess. The callers' row_top/row_bottom
            # (see _toolbar_cluster_left / _below_toolbar_
            # cluster_left) were computed from the loosely-matched ANCESTOR
            # row node's own bounding rect, which routinely extends well
            # above the visible icon row (confirmed live, Perplexity: an
            # ancestor spanning y=485..604 for a toolbar that only visually
            # occupies roughly the bottom ~50px of that). These real
            # CHILD controls -- the actual dropdown/mic/submit -- are tight
            # and accurate by construction; deriving the row's vertical
            # span from THEM instead of the ancestor fixes it at the root
            # for every site sharing this helper, not just one at a time.
            out.append((r.left, r.top, r.bottom, ctype))
        _walk_toolbar_children(child, raw_right, mid_y, out, depth + 1)
        child = _safe_next_sibling(child)


def _toolbar_cluster_left(control, raw_right, split_left_right=False):
    """Real left edge of the inline toolbar cluster (model-picker dropdown,
    mic, submit) that sits to the right of the composer's own text area, for
    BADGE_WIDEN_RIGHT_SITES sites -- Gemini's "Flash" dropdown + mic,
    ChatGPT's "Medium" dropdown + mic + submit circle.

    Real bug found live 2026-07-30 (Antonio, screenshots of both sites): the
    badge, docked a fixed pixel inset in from the ROW's widened right edge
    (_input_box_right / BADGE_INSIDE_INSET_OVERRIDES), landed right on top
    of the mic icon on both -- the toolbar cluster's total width differs by
    site (the dropdown's label text: "Flash" vs "Medium") and can change, so
    no single fixed inset clears it reliably. Antonio's explicit ask: dock
    to the LEFT of the dropdown itself, not some guessed distance from the
    row's edge.

    Walks the same bounded ancestor chain _input_box_right uses to find the
    row containing the toolbar, then walks ITS descendants (also bounded,
    see _walk_toolbar_children) for real interactive controls positioned
    inside the toolbar band. Screenshots confirm toolbar order is always
    dropdown, then mic, then submit on both sites, so the LEFTMOST such
    control is the dropdown -- anchoring there puts the badge left of the
    whole cluster, exactly as asked, without needing to know how wide the
    cluster is.

    Returns None if no row or no plausible toolbar control is found, so the
    caller can fall back to the older widened-edge/inset math instead of
    mis-anchoring on a layout this doesn't recognize. Otherwise returns
    (left_x, row_top, row_bottom).

    Real bug confirmed live 2026-07-30 (Antonio, screenshots -- ChatGPT,
    Perplexity, Claude, Grok, DeepSeek all showed the same thing: badge
    correct on a short single-line composer, wrong -- floating well above
    the toolbar, sometimes mid-paragraph -- the moment it grows past one
    line, and confirmed STILL wrong (Antonio, a further screenshot, right
    after the first version of this fix shipped) even for just two lines.
    Root cause, found by reading the actual debug.log this time instead of
    reasoning about it: this used to gate everything -- both which ANCESTOR
    counts as "the row" and which CHILD controls count as toolbar members
    -- on mid_y, the vertical MIDPOINT of the focused EditControl's own
    rect. That rect grows with the text, so mid_y drifts upward as lines
    are added; a real debug.log pair confirmed it works at 1 line
    (row=(966,998), a hit) and returns nothing at 2 lines (row=(None,None),
    a miss) on the exact same composer. Real fix: multiple confirmed
    live examples (Claude, ChatGPT) show these composers grow UPWARD --
    base.bottom stays put (or close to it) as base.top moves up to fit
    more lines, since the toolbar is anchored to the bottom of the
    composer and the text area grows above it. base.bottom is therefore a
    far more stable reference for "roughly where the toolbar is" than a
    midpoint that shifts with every line of text, so both gates below use
    it instead of mid_y.

    split_left_right (2026-08-03, real ask: Claude's Cowork home
    composer, "How can I help you today?"): unlike ChatGPT/Gemini,
    which only ever have ONE trailing cluster in their toolbar row,
    this composer's row has TWO -- a "+/Chat/Cowork" toggle group on
    the left, and "Opus 4.8/High/mic/Send" on the right. Antonio,
    live, screenshot: badge landed right after "Cowork" instead of
    near "Opus 4.8" -- confirmed the left group was satisfying the
    same left-edge gate the right group does, so plain min() picked
    the leftmost thing in the WHOLE row. When True, only controls
    right of the row's own midpoint count as candidates, the same
    left/right split _below_toolbar_cluster_left already does for its
    own two-cluster below-row case. Default False leaves ChatGPT/
    Gemini's already-confirmed-correct behavior untouched."""
    try:
        base = control.BoundingRectangle
    except Exception:
        return None
    y_ref = base.bottom
    base_h = base.bottom - base.top
    row = None
    node = control
    for _ in range(6):
        try:
            node = node.GetParentControl()
        except Exception:
            break
        if node is None:
            break
        try:
            r = node.BoundingRectangle
        except Exception:
            continue
        # Same UIA-staleness fail-safe as _below_toolbar_cluster_left's
        # identical check (see its own comment for the real bug this
        # caught live) -- a glitched query returning a nonsensical rect
        # (tens of thousands of px tall) would otherwise still clear the
        # width/row gates below and get trusted as real.
        sane_height = 0 < (r.bottom - r.top) <= 5000
        sane_coords = -10000 <= r.top <= 10000 and -10000 <= r.bottom <= 10000
        if not (sane_height and sane_coords):
            continue
        delta = r.right - raw_right
        # Real bug found live 2026-08-02 (Antonio, ChatGPT: badge landing
        # low/left of where it should). Root-caused via a live DOM
        # measurement of the actual page, not guessed: the correct
        # ancestor (delta=94, exactly right) was being rejected because
        # its bottom edge sat 3px ABOVE y_ref (887 vs 890) -- a routine
        # CSS padding/border-box difference between the textarea and its
        # wrapping flex container, not a sign this is the wrong element.
        # The zero-tolerance same_row check rejected the right answer over
        # a few pixels of totally normal layout noise. A small tolerance
        # absorbs that without loosening the check enough to start
        # matching genuinely unrelated rows (which sit tens+ px away, not
        # single-digit px away, in every real example seen so far).
        SAME_ROW_TOLERANCE = S(10)
        same_row = (r.top - SAME_ROW_TOLERANCE <= y_ref <= r.bottom + SAME_ROW_TOLERANCE)
        reasonable_height = (r.bottom - r.top) <= base_h * 4 + 200
        if 30 <= delta <= 250 and same_row and reasonable_height:
            row = node
    if row is None:
        # Diagnostic (2026-07-31, Antonio, screenshot: ChatGPT badge
        # floating disconnected mid-box instead of next to "High" -- the
        # same "no row found" gap _below_toolbar_cluster_left already had
        # a diagnostic for, this function didn't yet). Real evidence
        # beats another guess.
        log(f"toolbar_cluster_left: no row found (base={base.left},{base.top},"
            f"{base.right},{base.bottom} raw_right={raw_right} y_ref={y_ref})")
        return None
    candidates = []
    _walk_toolbar_children(row, raw_right, y_ref, candidates, depth=0)
    if split_left_right:
        try:
            rr = row.BoundingRectangle
            row_mid_x = (rr.left + rr.right) // 2
            candidates = [c for c in candidates if c[0] >= row_mid_x]
        except Exception:
            pass
    if not candidates:
        try:
            rr = row.BoundingRectangle
            row_desc = (rr.left, rr.top, rr.right, rr.bottom)
        except Exception:
            row_desc = None
        log(f"toolbar_cluster_left: row found but no candidates -- "
            f"row={row_desc} y_ref={y_ref}")
        return None
    left_x = min(c[0] for c in candidates)
    row_top = min(c[1] for c in candidates)
    row_bottom = max(c[2] for c in candidates)
    # Diagnostic (2026-07-30, Claude still landing wrong after the denylist
    # widening): real candidate data beats another guess. Every real open
    # of a BADGE_WIDEN_RIGHT_SITES composer logs this, not rate-limited --
    # same reasoning as the card _finalize diagnostic elsewhere, this is
    # tied to a real position change (the caller's own dedupe), not a
    # per-tick spam risk.
    log(f"toolbar_cluster_left candidates: {candidates}")
    return left_x, row_top, row_bottom


def _claude_inline_send_button(control):
    """Some Claude composer layouts (the Cowork/project view, confirmed
    live via a real structure dump, 2026-07-30) pin a 'Send' ButtonControl
    as a close SIBLING of the composer's own small wrapper, just 1-3
    ancestor levels up -- real data: node=('GroupControl', (676,945,
    1444,989)) children=[('GroupControl','Prompt',(676,945,1406,989)),
    ('StatusBarControl','',...), ('ButtonControl','Send',(1410,955,1434,
    979))]. NOT reached through the below-row toolbar walk
    _below_toolbar_cluster_left uses for the OTHER Claude layout (plain
    chat, "Opus 4.8 / High"), whose real toolbar sits several levels
    further down a separate branch entirely -- these are two genuinely
    different structures behind the same app_label, not one bug.

    Real ask 2026-07-30 (Antonio, screenshot): dock next to THIS arrow for
    this layout, and since it's pinned to the composer's own small
    fixed-height wrapper rather than the growing text area, returning the
    button's own rect directly (not derived from the text control's height
    at all) means the badge naturally stays put as the box grows -- "while
    it grows it stays there," for free, no extra tracking needed.

    Returns None if no plausible Send-like button is found within 3
    levels, so the caller falls back to _below_toolbar_cluster_left
    instead of mis-anchoring on a layout this doesn't recognize."""
    # Real bug found live 2026-08-02 (Antonio, screenshot: plain chat's
    # "Sonnet 5" badge suddenly landing on top of the mic icon, right after
    # a Cowork-only gap constant was retuned -- a change to ONE layout's
    # spacing should never have been able to move the OTHER). Root cause:
    # this function was never actually scoped to Cowork specifically, it
    # matched ANY "Send"/"submit"-named button within 3 ancestor levels,
    # and plain chat apparently has one reachable there too -- so plain
    # chat was silently riding this function's result (and
    # CLAUDE_INLINE_SEND_EXTRA_GAP) the whole time instead of its own
    # properly-tuned BADGE_TOOLBAR_GAP_OVERRIDES path, just close enough
    # at the old gap value (40) to go unnoticed until the gap shrank to 0.
    # Real fix: the docstring's own captured Cowork structure shows the
    # Send button sitting alongside a StatusBarControl SIBLING -- a marker
    # plain chat's own layout doesn't have. Require both in the same
    # parent's children, not just the button alone, so this can only match
    # the actual Cowork structure it was built for.
    try:
        node = control
        for _ in range(3):
            try:
                node = node.GetParentControl()
            except Exception:
                break
            if node is None:
                break
            try:
                child = node.GetFirstChildControl()
            except Exception:
                continue
            n = 0
            send_rect = None
            has_status_bar = False
            while child is not None and n < 20:
                try:
                    ctype = child.ControlTypeName
                    if ctype == "StatusBarControl":
                        has_status_bar = True
                    elif ctype == "ButtonControl":
                        name = (child.Name or "").lower()
                        if "send" in name or "submit" in name:
                            r = child.BoundingRectangle
                            if r.right > r.left and r.bottom > r.top:
                                send_rect = (r.left, r.top, r.bottom)
                except Exception:
                    pass
                child = _safe_next_sibling(child)
                n += 1
            if send_rect is not None and has_status_bar:
                return send_rect
    except Exception:
        pass
    return None


def _below_toolbar_cluster_left(control, raw_bottom):
    """Real left edge of the toolbar cluster's RIGHT-hand group (model-picker
    dropdown, mic, submit) in a below-the-text-row toolbar layout, for sites
    whose toolbar is a full row stacked below the input rather than beside
    it (see BADGE_WIDEN_DOWN_SITES) -- e.g. Perplexity's "Model" dropdown +
    mic + submit arrow, sitting below a separate LEFT-hand group (+, Search
    picker, Computer picker) in that same below-row.

    Real ask 2026-07-30 (Antonio, screenshot): move the badge off its old
    spot crowded between the mic icon and the submit arrow, to sit before
    the "Model" dropdown instead -- explicitly confirmed as the intended
    target over keeping it near submit with just tighter spacing.

    Mirrors _toolbar_cluster_left's two-stage approach (find the row via a
    bounded ancestor walk, then walk its children for real controls), but
    the ancestor gate is _input_box_bottom's (same COLUMN, widened BOTTOM)
    since this row is stacked below, not beside. The child scan reuses
    _walk_toolbar_children as-is, just fed the below-row's OWN horizontal
    midpoint (instead of raw_right) and OWN vertical band (instead of the
    text row's mid_y) -- that function's existing "left edge past this X,
    roughly level with this Y" gate happens to be exactly what's needed
    here too, just measured against a different row. Passing the row's own
    midpoint as the left-edge cutoff is what separates the LEFT-hand group
    (+/Search/Computer) from the RIGHT-hand one (Model/mic/submit) instead
    of returning the "+" button as the leftmost control in the whole row.

    Real caveat, unlike _toolbar_cluster_left: that function was written
    and then corrected once against real ChatGPT/Gemini screenshots. This
    one hasn't been -- it's a same-pattern extension to a differently
    shaped layout, not yet confirmed against a real debug.log line the way
    every other badge-position fix in this file was before being trusted.

    Real bug confirmed live 2026-07-30 (Antonio, screenshot, right after the
    first version of this function shipped): the horizontal anchor landed
    correctly, but the badge floated ABOVE the Model/mic/submit row instead
    of sitting inline with it -- "the badge should be inline with the rest
    of the tools." Root cause: _position_for's vertical centring uses the
    whole box's top..bottom, which for BADGE_TOOLBAR_BELOW_SITES spans the
    text row PLUS this below-row toolbar combined (see
    BADGE_WIDEN_DOWN_SITES), so its centre sits well above this row's own
    centre whenever the text row is tall. Returning this row's own
    top/bottom alongside the X, so the caller can centre on the ROW instead
    of the whole box, same as an inline (BADGE_WIDEN_RIGHT_SITES) toolbar
    already gets for free since there the row IS the whole box.

    Returns None if no row or no plausible right-half control is found, so
    the caller falls back to the older widened-edge/inset math instead of
    mis-anchoring on a layout this doesn't recognize. Otherwise returns
    (left_x, row_top, row_bottom)."""
    try:
        base = control.BoundingRectangle
    except Exception:
        return None
    mid_x = (base.left + base.right) // 2
    base_w = base.right - base.left
    row = None
    node = control
    # Real bug found live 2026-08-03 (Antonio, screenshots: Copilot's
    # composer, badge floating fully disconnected -- traced to debug.log
    # showing "no row found" every tick). Root cause, confirmed via a
    # live UIA diagnostic full ancestor+descendant dump: Copilot's real
    # toolbar row (Attach/Response-mode/Submit) sits 7 ancestor levels up
    # from the focused text control, but this loop only ever climbed 6 --
    # one level short of ever reaching it at all, so `row` stayed None no
    # matter what the candidate/delta checks below would have found.
    # Every other below-row site (Claude, ChatGPT, Perplexity, Grok,
    # DeepSeek) already finds its real row within 6 levels and `break`s
    # there, so raising the ceiling can't change any of their already-
    # confirmed behavior -- it only matters for a site that needed to
    # climb further than anything seen before Copilot. 6 -> 9, a few
    # levels of headroom past the 7 actually measured.
    for _ in range(9):
        try:
            node = node.GetParentControl()
        except Exception:
            break
        if node is None:
            break
        try:
            r = node.BoundingRectangle
        except Exception:
            continue
        # Real bug found live 2026-07-31 (Antonio, screenshot + diagnostic:
        # badge landed on the submit button, "row found but no candidates"
        # logged row=(444,-152016,2241,1464) -- a UIA staleness glitch, the
        # accessibility node got queried mid-re-render and returned
        # garbage coordinates, not a real screen position). A row this
        # broken still happened to satisfy the other three gates below (a
        # 153480px-tall rect easily clears "same column"), so it got
        # trusted as real, then correctly found zero real children inside
        # something that doesn't actually exist on screen. Same fail-safe
        # spirit as the raw_rect degenerate-size check elsewhere in this
        # file: reject a candidate whose own geometry is nonsensical
        # BEFORE it can ever become `row`, so a glitched tick correctly
        # falls through to the caller's existing locked-position debounce
        # instead of a bogus row silently eating the whole detection.
        sane_height = 0 < (r.bottom - r.top) <= 5000
        sane_coords = -10000 <= r.top <= 10000 and -10000 <= r.bottom <= 10000
        if not (sane_height and sane_coords):
            continue
        delta = r.bottom - raw_bottom
        same_column = (r.left <= mid_x <= r.right)
        reasonable_width = (r.right - r.left) <= base_w * 4 + 200
        # Real bug found live 2026-08-03 (Antonio, screenshot: Grok's
        # plain single-line Home composer, badge falling all the way back
        # to the crude whole-box-centred fallback, "still near the bottom
        # of the chatbox"). Root cause, confirmed via a live UIA
        # diagnostic dump: the real toolbar-containing ancestor sits at
        # delta=16, just 4px under this floor -- the very next ancestor
        # jumps straight to delta=270, so nothing in between ever
        # qualified and _below_toolbar_cluster_left returned None
        # entirely ("no row found" in debug.log, every single tick).
        # Grok's composer is simply more compact than the sites this 20px
        # floor was originally sized against. Safe to loosen now that the
        # REAL correctness guards are the content checks below (must have
        # real candidates, and the row can't sit above the text's own
        # bottom) -- this floor was never the only thing standing between
        # a false match and a true one, just an extra sanity margin. 10
        # still excludes the near-zero-delta case (the text line's own
        # immediate CSS wrapper) the floor originally existed to reject.
        if 10 <= delta <= 200 and same_column and reasonable_width:
            # Real bug found live 2026-08-03 (Antonio, "you didnt fix it at
            # all" -- the Code/"Accept edits" composer's badge, traced to
            # toolbar_left=None entirely: "row found but no candidates --
            # row=(296,177,1910,1032)", a container spanning nearly the
            # WHOLE screen). First attempt at a fix: stop at the first
            # geometrically-plausible ancestor instead of letting a later,
            # wider one silently overwrite it. That broke a DIFFERENT,
            # equally real composer (Antonio, next message, same day: the
            # badge landed on/covering a real button on the Cowork home
            # composer) -- root cause found via a fresh diag dump: that
            # composer's IMMEDIATE parent (787,491,1429,543, just the edit
            # row's own wrapper) also passes these geometric gates but
            # contains no real toolbar children at all, because the actual
            # toolbar is a SIBLING group one level further up (787,554,
            # 1429,587), not a descendant of this parent. Stopping at the
            # first geometric match froze out ever reaching that correct
            # grandparent. Neither "always take the first match" nor
            # "always take the last" is right -- what actually matters is
            # whether an ancestor's subtree contains a REAL toolbar, so
            # check that directly: try _walk_toolbar_children on each
            # candidate as it's found, and stop at the first one that
            # actually yields real candidates. This still can't regress
            # back to the original giant-container bug, because that
            # container had zero real candidates in it either -- it never
            # would have passed this check.
            try:
                row_mid_x = (r.left + r.right) // 2
                row_mid_y = (raw_bottom + r.bottom) // 2
                candidates = []
                _walk_toolbar_children(node, row_mid_x, row_mid_y, candidates, depth=0)
            except Exception:
                candidates = []
            # Reverted 2026-08-03 -- this "row_top can never be above
            # raw_bottom" check was added the same day to reject a
            # spurious Grok candidate (row_top=496 vs raw_bottom=531), but
            # a deeper live UIA diagnostic (full descendant dump, not just
            # the single candidate log line) proved the premise itself
            # wrong: Grok's REAL toolbar buttons (Dictation, Submit)
            # legitimately sit at y=427 while the text control's own
            # reported bottom is y=461 -- the toolbar visually overlaps
            # UP into the text's own vertical band in this composer's
            # compact flex layout, not stacked strictly below it with a
            # clean gap. This check was rejecting the real, correct
            # toolbar every time, which is what actually caused the badge
            # to go completely off the rails right after it shipped
            # (Antonio: "What the hell is this"). The "must have real
            # candidates" check above is the real, still-valid guard;
            # this extra one was never a safe general rule.
            if candidates:
                row = node
                break
    if row is None:
        # Diagnostic (2026-07-31, Antonio, screenshot: badge landed on the
        # submit button -- toolbar_left=None -- on a composer whose "Send"
        # button also wasn't found by _claude_inline_send_button within
        # its 3-level search). Real evidence beats another guess: log
        # exactly what this ancestor walk had to work with when it comes
        # up completely empty, not just that it did.
        log(f"below_toolbar_cluster_left: no row found (base={base.left},{base.top},"
            f"{base.right},{base.bottom} raw_bottom={raw_bottom} mid_x={mid_x})")
        return None
    # Real fix 2026-07-30, same root cause as _toolbar_cluster_left's own
    # comment: row_rect (the loosely-matched ANCESTOR's own bounding box)
    # routinely extends well above the visible toolbar -- confirmed live on
    # Perplexity, an ancestor spanning ~120px for a toolbar only ~50px
    # tall. Derive the row's vertical span from the real CHILD controls
    # found above instead of trusting the ancestor's own rect.
    left_x = min(c[0] for c in candidates)
    row_top = min(c[1] for c in candidates)
    row_bottom = max(c[2] for c in candidates)
    log(f"below_toolbar_cluster_left candidates: {candidates}")
    return left_x, row_top, row_bottom


def _claude_code_review_row(control):
    """True when the focused composer belongs to claude.ai/code (Sonnet 5
    default model) rather than plain chat/Cowork (Opus 4.8 default) -- see
    CLAUDE_CODE_REVIEW_GAP's own comment for why that distinction matters
    even though both share the same below-row detector and land on a
    similarly-positioned anchor.

    Real bug found live 2026-08-03 (Antonio, screenshot: the dead-centre
    floating badge was BACK on a Code-tab composer, right after this
    function's first version shipped and was confirmed fixed). Root
    cause: that first version only checked for "Accept edits", the
    label shown ONLY while reviewing a pending diff -- this screenshot
    was the SAME composer in its other common state, showing "Auto"
    instead (nothing pending to accept), so the check never fired and
    it silently fell back to the wrong (plain-chat) gap again. Checking
    both covers the two known Code-tab left-cluster states.

    Deliberately NOT keyed off the model name ("Sonnet 5" vs "Opus
    4.8") -- tried that first, then caught it live via a fresh
    reproduction before shipping: plain Chat's own home screen can
    default to "Sonnet 5" too depending on the user's last-picked
    model, which has nothing to do with which tab it's in. Model choice
    is independent of surface; these left-cluster labels are the real,
    surface-specific signal."""
    node = control
    for _ in range(6):
        try:
            node = node.GetParentControl()
        except Exception:
            return False
        if node is None:
            return False
        if (_has_named_descendant(node, "accept edits", depth=3)
                or _has_named_descendant(node, "auto", depth=3)):
            return True
    return False


def _claude_home_row(control):
    """True when the focused composer is the top-level Home "How can I
    help you today?" box (Chat/Cowork toggle visible) rather than a real,
    already-started conversation's composer -- both route through
    below_toolbar_cluster_left and land on a similarly-shaped anchor near
    the model picker, so both were sharing BADGE_TOOLBAR_GAP_OVERRIDES
    (210px). Real bug found live 2026-08-03 (Antonio, screenshot: badge
    landing right after the "Cowork" toggle button, nowhere near "Sonnet
    5"/"Opus 4.8" -- confirmed via a live claude.ai/new reproduction that
    the detected anchor (~1237) is already almost ON TOP of the model
    button's own left edge (measured ~1225), not 200px+ before it like
    the mid-conversation composer's Send-button-plus-label case this
    override was tuned for. 210px massively overshoots here, landing the
    badge back near the LEFT-hand Chat/Cowork cluster instead. "Cowork"
    is the one real, stable, UIA-visible marker unique to this composer
    (a real conversation's composer never shows the mode toggle), so
    detected the same way as _claude_code_review_row's own markers."""
    node = control
    for _ in range(6):
        try:
            node = node.GetParentControl()
        except Exception:
            return False
        if node is None:
            return False
        if _has_named_descendant(node, "cowork", depth=4):
            return True
    return False


def _perplexity_long_model_row(control):
    """True when Perplexity's composer has a longer model name selected
    ("Orchestrator" specifically, the Computer/task mode's model) that
    reaches all the way to the detected toolbar anchor, rather than the
    plain search composer's shorter default name that already fits with
    zero extra gap.

    Real bug found live 2026-08-03 (Antonio, screenshot, right before
    finalizing the "Perplexity is perfect, lock it" ask: badge overlapping
    "Orchestrator" in the Computer-task composer). The plain composer was
    genuinely confirmed correct with zero override -- this isn't a
    different composer STRUCTURE, the toolbar-row detection is identical,
    it's a longer label eating into the same fixed gap a short label
    like the default one never needed. Scoped to "Orchestrator"
    specifically (not a blanket per-site override) so the already-locked
    short-name case can never regress. Still used as the GATE for
    PERPLEXITY_COMPUTER_ANCHOR below, even though the anchor itself no
    longer depends on the model name -- keeps the plain composer
    untouched, only switches anchor when this specific case is active."""
    node = control
    for _ in range(6):
        try:
            node = node.GetParentControl()
        except Exception:
            return False
        if node is None:
            return False
        if _has_named_descendant(node, "orchestrator", depth=4):
            return True
    return False


def _perplexity_computer_anchor(control):
    """Right edge of the "Computer" mode-toggle button, or None. Real ask
    2026-08-03 (Antonio, live, right after confirming a dynamic per-
    model-name-width fix isn't possible -- see PERPLEXITY_LONG_MODEL_GAP's
    own comment, a live diagnostic confirmed the "Model" button's
    accessible Name is just the literal string 'Model', never the actual
    selected model text, and its own bounding rect doesn't track the
    rendered text width either): "Maybe you can put it to the right of
    the computer badge rather than the next to the prompt names because
    they can expand and shrink based on the names." "Computer" is its own
    fixed, always-the-same-width label (confirmed live: rect=(914,558,
    1023,591), a real child TextControl reading 'Computer' -- unlike
    "Model", this one's Name genuinely IS its stable visible text), so
    anchoring off IT instead of the variable-width model button makes the
    badge immune to however long the selected model's name is, without
    needing to special-case each one by name."""
    node = control
    for _ in range(6):
        try:
            node = node.GetParentControl()
        except Exception:
            return None
        if node is None:
            return None
        rect = _find_named_descendant_rect(node, "computer", depth=4)
        if rect is not None:
            return rect.right
    return None


def _find_named_descendant_rect(node, name_lower, depth):
    if depth < 0:
        return None
    try:
        child = node.GetFirstChildControl()
    except Exception:
        return None
    while child is not None:
        try:
            if child.Name.strip().lower() == name_lower:
                return child.BoundingRectangle
        except Exception:
            pass
        found = _find_named_descendant_rect(child, name_lower, depth - 1)
        if found is not None:
            return found
        try:
            child = child.GetNextSiblingControl()
        except Exception:
            break
    return None


def _has_named_descendant(node, name_lower, depth):
    if depth < 0:
        return False
    try:
        child = node.GetFirstChildControl()
    except Exception:
        return False
    while child is not None:
        try:
            if child.Name.strip().lower() == name_lower:
                return True
        except Exception:
            pass
        if _has_named_descendant(child, name_lower, depth - 1):
            return True
        try:
            child = child.GetNextSiblingControl()
        except Exception:
            break
    return False


class PersistentBadge:
    """The always-on indicator, anchored to whatever text field currently has
    focus, same idea as Grammarly's little circular icon that's just always
    there while you're in a text box, not something that pops in only when
    it has a suggestion. This is the thing that proves the app is alive and
    watching, separate from the suggestion card, which stays conditional."""

    def __init__(self, root):
        self.root = root
        self.window = None
        self.label = None
        # Not draggable (2026-07-23, Antonio, firmly): the badge ALWAYS sits
        # just left of the focused text box (see _position_for / show_near).
        # A brief drag-to-pin experiment (0.9.27) read as "it's draggable
        # anywhere and gets stuck wherever I drop it," which he explicitly did
        # not want. So user_positioned is never set, and any stale pinned
        # position from that experiment is cleared here so the badge snaps
        # back to the box immediately on this launch.
        self.user_positioned = None
        try:
            os.remove(BADGE_POSITION_PATH)
        except OSError:
            pass
        self._drag_start = None
        # Rebuilt each tick by watch_loop with a closure over the current
        # suggestions, so clicking (not dragging) the badge can pop the
        # review card open on demand, same as clicking Grammarly's own
        # icon, instead of only ever appearing on its own after a pause.
        self.on_click = None
        # The badge shows a plain hand cursor: a click opens the review card,
        # and it is not draggable, so there is no separate drag cursor.
        self._cursor_widgets = []
        self._icon_photo = None  # must stay referenced, Tk drops GC'd images
        self._icon_label = None
        self._last_heat_count = None  # only regenerate the ring when it changes
        # Wired in main() so the open review card is anchored to the badge.
        self.popup = None
        # The last real app box rect (see show_near), kept so the card's
        # window-aware clamp can anchor on a point guaranteed to be under
        # the app window, not on the badge's own topmost floating window
        # (see current_box_rect).
        self._last_box_rect = None
        # Which recognized LLM app/site the badge is currently anchored to
        # (see show_near), so _position_for can look up a per-site inset
        # override (BADGE_INSIDE_INSET_OVERRIDES) without needing every
        # caller of _position_for/popup_anchor to thread app_label through
        # separately -- popup_anchor picks this up for free since it reads
        # the same instance state show_near just set.
        self._current_app_label = None

    def _ensure_window(self):
        if self.window is not None:
            return
        win = tk.Toplevel(self.root)
        # REVERTED 2026-07-26: .transient(self.root) was tried here to stop
        # the taskbar entry, but self.root is the app's hidden, permanently-
        # withdrawn main Tk root -- tying a transient window to a withdrawn
        # owner stopped this window from ever showing at all (real
        # regression, caught immediately: "the pop up on the chat box isn't
        # showing up"). Do not re-add .transient() against self.root.
        # FIXED 2026-07-27 a different way instead: make_window_non_activating
        # below is now passed owner=self.root, which sets the real Win32
        # owner directly via SetWindowLongPtrW/GWLP_HWNDPARENT, bypassing
        # Tk's own .transient() bookkeeping (and the withdrawn-owner
        # auto-hide behavior that lives inside it) entirely. See that
        # function's docstring.
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=BRAND_DARK)
        # -transparentcolor colour-keys BRAND_DARK to true window
        # transparency, so the square corners around the circular badge are
        # genuinely invisible/click-through, only the circle + heat ring
        # render. The heat ring colours (green..red) and the logo's own
        # circle are never BRAND_DARK, so they stay visible.
        win.attributes("-transparentcolor", BRAND_DARK)
        row = tk.Frame(win, bg=BRAND_DARK)
        row.pack()
        # Real ask 2026-07-20: no number anymore, a green->red heat ring
        # around the logo shows how much there is to compact/fix, redder =
        # more. Starts green. The image is regenerated in show_near when the
        # count changes.
        icon_image = _make_heat_badge_image(BADGE_ICON_SIZE, 0)
        if icon_image is not None:
            self._icon_photo = ImageTk.PhotoImage(icon_image)
            icon = tk.Label(row, image=self._icon_photo, bg=BRAND_DARK, cursor="hand2")
        else:
            # Real fallback if PIL or the bundled asset is ever missing.
            icon = tk.Label(
                row, text="C", font=("Segoe UI", 18, "bold"),
                fg=BRAND_PRIMARY, bg=BRAND_DARK, padx=S(6), cursor="hand2",
            )
        icon.pack(side="left")
        self._icon_label = icon

        # Click-only (2026-07-23): press+release opens the review card. NO
        # motion binding, so the badge cannot be dragged, and NO double-click
        # binding, since there's no pin left to reset. The press records the
        # start point purely so a small cursor drift still counts as a click.
        self._cursor_widgets = [win, row, icon]
        for widget in self._cursor_widgets:
            widget.bind("<ButtonPress-1>", self._on_drag_start)
            widget.bind("<ButtonRelease-1>", self._on_drag_end)

        win.update_idletasks()
        make_window_non_activating(win, owner=self.root)
        # Real bug found 2026-07-26: WS_EX_TOOLWINDOW (set above) is meant to
        # keep this window out of the taskbar entirely, but if a taskbar
        # entry shows up anyway on some Windows configs, it fell back to the
        # default Tk/Tcl feather icon since nothing set a real one. Belt and
        # suspenders: set the real logo too, so the wrong icon can never show
        # even if the toolwindow suppression doesn't fully take.
        taskbar_icon = _load_app_icon_image(32)
        if taskbar_icon is not None:
            self._taskbar_icon_photo = ImageTk.PhotoImage(taskbar_icon)
            try:
                win.iconphoto(True, self._taskbar_icon_photo)
            except Exception:
                pass
        # Same taskbar-entry-shows-up-anyway case, but for the hover tooltip
        # text rather than the icon image (real report 2026-07-26: "it says
        # Tk and not Comprsly"). A Toplevel's window title defaults to the
        # literal string "tk" until something sets it -- nobody ever had,
        # since this window's own title bar is hidden by overrideredirect,
        # so it looked like there was nothing to set. The taskbar/Alt-Tab
        # tooltip reads the title regardless of whether a title bar is
        # visible.
        try:
            win.title(BRAND_NAME)
        except Exception:
            pass
        self.window = win

    def rebuild_for_scale(self):
        """Throw the badge window away so it is rebuilt at the new size.

        The badge image is baked at BADGE_ICON_SIZE, so a scale change can't
        be applied to the existing widget. Never does this mid-drag, which
        would drop the pointer grab and strand the badge."""
        if self.window is None or self._drag_start is not None:
            return
        try:
            self.window.destroy()
        except Exception:
            pass
        self.window = None
        self._icon_photo = None
        self._icon_label = None
        self._last_heat_count = None
        self._cursor_widgets = []

    def _update_heat(self, count, checked=True):
        """Regenerate the badge's heat dot for the current suggestion count,
        only when it (or `checked`) actually changed (regenerating a PIL
        image every 0.7s tick otherwise would be wasteful). Cache key is a
        tuple, not just count: count==0 with checked=False (nothing typed
        yet) and count==0 with checked=True (typed enough, genuinely
        clean) must repaint when switching between them even though count
        alone didn't change."""
        key = (count, checked)
        if key == self._last_heat_count or self._icon_label is None:
            return
        img = _make_heat_badge_image(BADGE_ICON_SIZE, count, checked=checked)
        if img is not None:
            self._icon_photo = ImageTk.PhotoImage(img)
            self._icon_label.config(image=self._icon_photo)
        self._last_heat_count = key

    def _on_drag_start(self, event):
        # Records the press point only, so a small cursor drift between press
        # and release still counts as a click (see _on_drag_end). The badge is
        # NOT draggable (2026-07-23), so nothing moves here.
        self._drag_start = (event.x_root, event.y_root)

    def _on_drag_end(self, event):
        if self._drag_start is None:
            return
        start_x, start_y = self._drag_start
        self._drag_start = None
        dx = abs(event.x_root - start_x)
        dy = abs(event.y_root - start_y)
        # Per-axis slop, never tighter than Windows' own drag threshold, with a
        # floor for imprecise trackpads (real bug 2026-07-21: a click that
        # drifted a few px was being dropped). Within slop = a click = open the
        # card; beyond it we simply do nothing (the badge can't be dragged).
        if dx <= BADGE_CLICK_SLOP_PX and dy <= BADGE_CLICK_SLOP_PX:
            if self.on_click is not None:
                log(f"badge clicked (moved {dx},{dy}px), opening the review card")
                self.on_click()
            else:
                log(f"badge clicked (moved {dx},{dy}px) but there's nothing to "
                    f"review yet, needs at least {MIN_TEXT_LENGTH_TO_ANALYZE} characters")

    def _position_for(self, rect):
        """The badge position: INSIDE the focused box, vertically centred.
        Tucked against the real inline toolbar cluster's left edge when one
        was found (rect.toolbar_left, see _toolbar_cluster_left), otherwise
        against the box's own right edge with a fixed inset. Single source
        of truth so the review card can be anchored to it consistently (see
        popup_anchor).

        Real ask 2026-07-25 (Antonio, direct: "Grammarly's icon sits within
        the chat box itself, but to the right... I think that's what we
        should do"), reversing the 2026-07-21/23 direction below: the badge
        used to float OUTSIDE the box's left edge on purpose, a deliberate
        design choice at the time (see BADGE_INSIDE_INSET's history note).
        Docking inside instead removes the whole "is there room to the
        left" question the outside-left placement had on a box near the
        screen's own left edge (a narrow sidebar chat, e.g. Claude's Design
        mode) -- there's always room inside the box's own right side,
        because the badge is never bigger than the box it's docking into
        (real boxes always clear the >=100px check below).

        Still not draggable and never pinned to an arbitrary spot (2026-07-23,
        Antonio, firmly): it always tracks the focused text box. A
        drag-to-pin experiment (0.9.27) was removed because "it's draggable
        anywhere and gets stuck wherever I drop it" was exactly the
        annoyance he did not want.

        Only ever called for a recognized LLM app/site now (2026-07-25, see
        the DEFAULT_SETTINGS note on cat_ai_chat) -- a plain browser field, a
        search engine's box, etc. never reach here at all."""
        width = rect.right - rect.left
        if width >= 100:
            box_h = rect.bottom - rect.top
            toolbar_left = getattr(rect, "toolbar_left", None)
            if toolbar_left is not None:
                # Precise anchor (2026-07-30, see _toolbar_cluster_left):
                # dock just left of the real toolbar cluster (model-picker
                # dropdown, mic, submit) itself, rather than guess a pixel
                # distance from the row's edge -- this already IS the exact
                # spot Antonio asked for, so no further inset on top, EXCEPT
                # where the specific layout detected has an element the
                # toolbar detector can never find (see rect.toolbar_
                # extra_gap and BADGE_TOOLBAR_GAP_OVERRIDES -- set per
                # detection path, not blanket per-site, so this can't
                # misapply to a different layout on the same site).
                gap = BADGE_TOOLBAR_GAP + getattr(rect, "toolbar_extra_gap", 0)
                bx = toolbar_left - gap - BADGE_ICON_SIZE
            else:
                # Fallback: tuck inside the box's own (possibly widened,
                # see BADGE_WIDEN_RIGHT_SITES) right edge, vertically
                # centred, base inset plus a per-site top-up -- see
                # BADGE_INSIDE_INSET_OVERRIDES. Only still reached when
                # _toolbar_cluster_left couldn't find a real toolbar control
                # to anchor to (an unrecognized layout), or for sites that
                # were never widened in the first place.
                inset = BADGE_INSIDE_INSET + BADGE_INSIDE_INSET_OVERRIDES.get(self._current_app_label, 0)
                bx = rect.right - BADGE_ICON_SIZE - inset
            row_top = getattr(rect, "toolbar_row_top", None)
            row_bottom = getattr(rect, "toolbar_row_bottom", None)
            if row_top is not None and row_bottom is not None:
                # Below-row toolbar layout (2026-07-30, see
                # _below_toolbar_cluster_left): centre on the TOOLBAR ROW
                # itself, not the whole (widened) box -- "the badge should
                # be inline with the rest of the tools," confirmed live
                # after the box-centred version floated it above the row.
                by = row_top + (row_bottom - row_top) // 2 - BADGE_ICON_SIZE // 2
                vshift = getattr(rect, "toolbar_row_vshift", 0)
                by -= vshift
                # Real bug found live 2026-08-03 (Antonio, screenshot +
                # exact debug.log correlation: Claude's "Code" browser
                # view, badge sitting visibly below the box's own rounded
                # border). Root cause, measured not guessed: the detected
                # row's own bottom can land a few px PAST the outer box's
                # own (separately, widened) bottom -- confirmed live,
                # row_bottom=1026 vs rect.bottom=1023, a real 3px mismatch
                # between two independently-derived values. The badge is
                # taller than a typical toolbar row, so centering on a
                # short row that itself already overhangs the box pushes
                # the badge's own bottom edge further past the box's real
                # border on top of that (measured: 1031 vs 1023, 8px
                # over). Clamp to the box's OWN bounds as the final,
                # authoritative edge -- the badge must never render
                # outside the box it's supposed to be docked inside,
                # regardless of a small mismatch between two internal
                # measurements of where "the bottom" is.
                #
                # Real bug found live 2026-08-03 (Antonio, Gemini's Home
                # composer: "It looks as if you moved it down" right after
                # GEMINI_VSHIFT shipped). Root cause: the row-centred `by`
                # for this composer was ALREADY landing above rect.top
                # even with zero vshift (confirmed via debug.log: natural
                # by=557 vs rect.top=564), so the clamp below was already
                # silently absorbing the entire vshift -- 557-10=547 still
                # clamps to 564, IDENTICAL to no vshift at all. A vshift
                # is a deliberate "go higher than the naive row-centre"
                # ask; the clamp's own job is only to stop the badge
                # rendering outside the visual box by ACCIDENT, not to
                # silently cancel an intentional shift. Loosen the top
                # bound by the same vshift so the two stop fighting -- the
                # box_bottom-widening fix above is the exact same idea,
                # just for the other edge.
                top_bound = rect.top - max(0, vshift)
                by = max(top_bound, min(by, rect.bottom - BADGE_ICON_SIZE))
            else:
                by = rect.top + box_h // 2 - BADGE_ICON_SIZE // 2
        else:
            # No real box rect (Claude's Electron composer exposes none),
            # just a caret/click point: the fallback that builds this
            # synthetic point (see watch_loop's no-accessible-control
            # branch) already computes it as the intended final badge x,
            # working backward through this same subtraction -- same
            # "cancels out" trick as before, just mirrored to the box's
            # estimated right edge instead of its left.
            bx = rect.left - BADGE_ICON_SIZE - BADGE_INSIDE_INSET
            by = rect.top - 4
        # Real risk once this always sits relative to the box rather than a
        # remembered position (2026-07-21): a narrow box near a screen edge
        # can still put the badge partly off-screen. fit_on_one_monitor is
        # the same clamp already trusted for the review card; reused here
        # so the badge can't disappear off an edge the way the card once
        # could.
        #
        # Window-aware on top of that (2026-07-25, real bug on stream: a
        # snapped half-and-half layout let the badge/card spill into the
        # OTHER window entirely, since the monitor alone still had "room").
        # Anchored on the box's own center, the actual ground truth for
        # which window this box lives in.
        anchor_x = (rect.left + rect.right) / 2
        anchor_y = (rect.top + rect.bottom) / 2
        return fit_within_window_and_monitor(
            bx, by, BADGE_ICON_SIZE, BADGE_ICON_SIZE, anchor_x, anchor_y)

    def popup_anchor(self, rect):
        """Where the review card should open so it reads as attached to the
        badge: directly below it, small consistent gap, on whichever side
        actually has room (see _card_corner).

        Real ask 2026-07-21: used to open to the LEFT of the badge always
        (right edges aligned), never the right -- the badge floated
        outside the box's left edge for most of this app's real use back
        then, and a card growing rightward from there covered whatever
        text was on screen. That reasoning doesn't carry over as-is to the
        2026-07-25 inside-the-box redesign (see _position_for): the badge
        now sits at the box's OWN right edge, so a box that itself lives
        near the screen's left side (a narrow sidebar chat) has no room
        to open a card further left at all. _card_corner picks the side
        with room instead of assuming left always has it. This is only
        the ROUGH initial anchor anyway -- SuggestionPopup._finalize
        recomputes the precise position once real content height is
        known and punches the badge-docking gap into whichever corner
        this matches."""
        x, y = self._position_for(rect)
        anchor_x = (rect.left + rect.right) / 2
        anchor_y = (rect.top + rect.bottom) / 2
        corner = _card_corner(x, y, anchor_x, anchor_y)
        card_x = x + BADGE_ICON_SIZE - POPUP_WIDTH if corner == "right" else x
        return (card_x, y + BADGE_ICON_SIZE + 10)

    def current_badge_rect(self):
        """The badge's live (x, y, w, h), so the card can be placed somewhere
        that doesn't cover it."""
        try:
            if self.window is not None:
                return (self.window.winfo_x(), self.window.winfo_y(),
                        BADGE_ICON_SIZE, BADGE_ICON_SIZE)
        except Exception:
            pass
        if self.user_positioned is not None:
            return (self.user_positioned[0], self.user_positioned[1],
                    BADGE_ICON_SIZE, BADGE_ICON_SIZE)
        return None

    def current_box_rect(self):
        """The real app text box's last known rect (not the badge's own
        window) -- see _last_box_rect. A point guaranteed to land on the
        host app for WindowFromPoint, unlike the badge's own center."""
        return self._last_box_rect

    def current_popup_anchor(self):
        """Anchor based on where the badge physically IS right now, rather
        than where it was when a card was first opened.

        Real bug found 2026-07-20: card coordinates were captured once at
        badge-click time and reused for every follow-up card. Drag the badge
        while a card is open (the card correctly follows) and the NEXT card
        snapped back to the stale original spot, leaving it stranded away
        from the badge, exactly what Antonio's screenshot showed. Reading the
        live window position at display time can't go stale.

        Side choice via _card_corner, same reasoning as popup_anchor above
        -- the window lookup needs a point on the real host app, never the
        badge's own topmost window (see _host_window_rect), so this prefers
        the real box rect over the badge's own coordinates when one is on
        hand."""
        if self.window is None:
            return None
        try:
            bx, by = self.window.winfo_x(), self.window.winfo_y()
        except Exception:
            return None
        box = self.current_box_rect()
        if box is not None:
            anchor_x = (box.left + box.right) / 2
            anchor_y = (box.top + box.bottom) / 2
        else:
            anchor_x, anchor_y = bx, by
        corner = _card_corner(bx, by, anchor_x, anchor_y)
        card_x = bx + BADGE_ICON_SIZE - POPUP_WIDTH if corner == "right" else bx
        return (card_x, by + BADGE_ICON_SIZE + 10)

    def show_near(self, rect, suggestion_count, checked=True, app_label=None):
        self._ensure_window()
        # Which recognized app/site this box belongs to, so _position_for can
        # look up a per-site inset override (BADGE_INSIDE_INSET_OVERRIDES).
        self._current_app_label = app_label
        # Real ask 2026-07-20: the suggestion count is shown as a green->red
        # heat dot on the logo, not a number.
        self._update_heat(suggestion_count, checked=checked)
        # Kept so the card can later find the real host window (see
        # current_box_rect) -- the badge's own rect can't be used for that,
        # it's a topmost window that would just find itself.
        self._last_box_rect = rect
        # Positioning (2026-07-23, Antonio, firmly): the badge ALWAYS sits just
        # left of the focused text box, every time. Not draggable, never
        # pinned to an arbitrary spot (the 0.9.27 drag-to-pin was removed as
        # annoying).
        x, y = self._position_for(rect)
        self.window.geometry(f"+{int(x)}+{int(y)}")
        self.window.deiconify()

    def hide(self):
        if self.window is not None:
            self.window.withdraw()

    def raise_to_front(self):
        """Keep the floating badge visible and ON TOP of the open review card,
        without moving it (2026-07-23). The card is positioned to nest this
        badge in its bottom-right corner and populate BEHIND it, so the badge
        must sit above the card in the z-order. No reposition here: the badge
        stays exactly where it was when the card opened."""
        if self.window is None:
            return
        try:
            self.window.deiconify()
            self.window.lift()
            self.window.attributes("-topmost", True)
        except Exception:
            pass


MAX_SHOWN_SUGGESTIONS = 8

# Grammarly-style popup palette (real ask 2026-07-20: make the card look
# polished and user-friendly, emulate Grammarly's look but with our own
# brand purple and logo). Kept as named constants so the whole card reads as
# one coherent design system, not scattered ad-hoc colors.
# Deep Iris dark palette (2026-07-22 UI redesign): retuned from the near-black
# blocky look to the softer charcoal + Deep Iris system used across the new web
# Settings/Onboarding, so the native review card matches the planned design as
# closely as Tk allows. Surface is a lifted charcoal (#232228) over a darker
# inset (#1d1c23); one restrained violet accent; green reserved for savings.
POPUP_BG = "#232228"
POPUP_BORDER = "#33323c"
POPUP_CARD_BG = "#1d1c23"
POPUP_TEXT = "#ecebf0"
POPUP_SUBTEXT = "#9c99a8"
POPUP_WIDTH = S(DESIGN_POPUP_WIDTH)

# Step two's title, defined once. See the note above _render_step2_offer:
# a longer title overruns the header row wherever a button sits beside it,
# and Tk draws the overrun UNDER the button rather than clipping it. Having
# this as a literal in four render paths meant fixing it three times.
STEP2_TITLE = "Make it concise"
POPUP_MUTED_BTN = "#2c2b34"
ACCENT_VIOLET = "#1b1a21"   # 2026-07-26: monochrome pass, was Deep Iris violet ("too gamified", Antonio) -- now near-black, readable as accent-on-dark and as a button bg with white text
ACCENT_BLUE = "#118afb"
ACCENT_GREEN = "#6e6b7b"    # 2026-07-26: was a savings/success green, now neutral gray to match
ACCENT_AMBER = "#eab308"

# --- Theme-adaptive card palette (2026-07-22) --------------------------------
# The native card follows the same theme setting as the web UI (System / Light
# / Dark). Two Deep Iris palettes; _apply_card_palette() reassigns the
# POPUP_*/ACCENT_* globals the card reads at render time, called right before a
# card opens (see open_suggestions). White button text is readable on both
# accents, so no per-theme button-text handling is needed.
_CARD_DARK = {
    "POPUP_BG": "#232228", "POPUP_BORDER": "#33323c", "POPUP_CARD_BG": "#1d1c23",
    "POPUP_TEXT": "#ecebf0", "POPUP_SUBTEXT": "#9c99a8", "POPUP_MUTED_BTN": "#2c2b34",
    "ACCENT_VIOLET": "#7b61e8", "ACCENT_GREEN": "#4fb980",
}
_CARD_LIGHT = {
    "POPUP_BG": "#ffffff", "POPUP_BORDER": "#eceaf2", "POPUP_CARD_BG": "#fbfafd",
    "POPUP_TEXT": "#1b1a21", "POPUP_SUBTEXT": "#6e6b7b", "POPUP_MUTED_BTN": "#f0eff4",
    # 2026-07-26: monochrome pass, was violet/green ("purple's too gamified", Antonio) -- now black/gray
    "ACCENT_VIOLET": "#1b1a21", "ACCENT_GREEN": "#6e6b7b",
}


def _blend(fg, bg, t):
    """Mix hex colour fg into bg by fraction t (0..1). Used for subtle tints
    like the numbered step circles, so they read as a soft accent wash rather
    than a hard block, matching the web mockup."""
    try:
        fg = fg.lstrip("#"); bg = bg.lstrip("#")
        fr, fgc, fb = int(fg[0:2], 16), int(fg[2:4], 16), int(fg[4:6], 16)
        br, bgc, bb = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
        r = round(fr * t + br * (1 - t))
        g = round(fgc * t + bgc * (1 - t))
        b = round(fb * t + bb * (1 - t))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return bg


def _draw_header_settings_icon(canvas, d, color):
    """The card header's settings icon: three horizontal sliders, each with
    its own knob at a different position (2026-07-26, Antonio, direct: "this
    is what the settings button should look like, rather than the make-shift
    gear"). Drawn on a live Tk Canvas, not a baked PIL image, so it can
    recolour on hover the same way the gear it replaces did."""
    canvas.delete("all")
    margin = d * 0.16
    x0, x1 = margin, d - margin
    track_w = max(1, round(d * 0.06))
    # Real bug caught by screenshotting the actual rendered header icon, not
    # just the isolated PIL preview (Antonio: "the image isn't correct"): at
    # this canvas's real size (~20px), a 0.115*d knob radius and 0.22*d row
    # spacing put adjacent rows' knobs closer together than their own
    # diameter, so they merged into one blob instead of three sliders. Row
    # spacing must clear the knob's full diameter with margin to spare, and
    # both need a hard pixel floor since fractions of ~20px round away to
    # nothing reliable.
    knob_r = max(1.6, d * 0.09)
    rows_y = [d * 0.20, d * 0.50, d * 0.80]
    # Knob position per row as a fraction along the track -- three different
    # spots so it reads as "sliders set to different levels", not one glyph
    # repeated three times.
    fracs = [0.64, 0.30, 0.50]
    rows = list(zip(rows_y, fracs))
    for y, frac in rows:
        canvas.create_line(x0, y, x1, y, fill=color, width=track_w, capstyle="round")
        kx = x0 + (x1 - x0) * frac
        canvas.create_oval(kx - knob_r, y - knob_r, kx + knob_r, y + knob_r, fill=color, outline="")


def _apply_card_palette():
    """Point the card's colour globals at the light Deep Iris palette.

    Light-only (real ask 2026-07-25, Antonio, direct: "get rid of the
    system and dark, only keep light... I only want it to be the white
    display"). Used to resolve a "theme" setting (System→OS, or a forced
    light/dark) and pick between _CARD_LIGHT/_CARD_DARK -- now always
    light, on purpose, not just defaulted there. _CARD_DARK stays defined
    (unused) rather than deleted, in case dark is ever revisited."""
    global POPUP_BG, POPUP_BORDER, POPUP_CARD_BG, POPUP_TEXT, POPUP_SUBTEXT
    global POPUP_MUTED_BTN, ACCENT_VIOLET, ACCENT_GREEN
    p = _CARD_LIGHT
    POPUP_BG = p["POPUP_BG"]; POPUP_BORDER = p["POPUP_BORDER"]; POPUP_CARD_BG = p["POPUP_CARD_BG"]
    POPUP_TEXT = p["POPUP_TEXT"]; POPUP_SUBTEXT = p["POPUP_SUBTEXT"]; POPUP_MUTED_BTN = p["POPUP_MUTED_BTN"]
    ACCENT_VIOLET = p["ACCENT_VIOLET"]; ACCENT_GREEN = p["ACCENT_GREEN"]

# Each suggestion kind gets a friendly category name and an accent color,
# the small colored strip + label on each card, same idea as Grammarly's
# colored underline categories. Correctness (spelling/grammar) uses a red
# accent like Grammarly's own correctness cards; conciseness rules (filler,
# verbose, redundant) use the brand purple, since that's the token-saving
# core of the product.
CORRECTNESS_ACCENT = "#6e6b7b"  # 2026-07-26: monochrome pass -- category color-coding removed
SUGGESTION_CATEGORY = {
    "spelling": ("Spelling", CORRECTNESS_ACCENT),
    "grammar": ("Grammar", CORRECTNESS_ACCENT),
    "filler": ("Wordiness", CORRECTNESS_ACCENT),
    "verbose": ("Wordiness", CORRECTNESS_ACCENT),
    "redundant": ("Redundancy", CORRECTNESS_ACCENT),
}


class SuggestionPopup:
    """Real product pivot 2026-07-20: rules-first, AI-second, reviving the
    itemized Grammarly-style review card (each suggestion independently
    acceptable) that predates the earlier full-AI-rewrite pivot, now backed
    by the rewritten span-based suggestion_engine.py plus content
    protection. One Apply button commits whatever's checked and, only when
    the rules genuinely couldn't confidently handle the text, chains the
    local LLM on top as a fallback, not the default path."""

    def __init__(self, root):
        self.root = root
        self.window = None
        self._suggestion_vars = []  # [(BooleanVar, suggestion_dict), ...] for shown items
        self._extra_suggestions = []  # accepted-by-default overflow beyond MAX_SHOWN_SUGGESTIONS
        self._photos = []  # keep PhotoImage refs alive per-window (Tk GC's them otherwise)
        self._body = None  # inner content frame, everything below the header goes here
        # The two step containers, so a step can be collapsed or swapped in
        # place instead of the whole card being torn down and rebuilt.
        self._step1_frame = None
        self._step2_frame = None
        # Set in main() to PersistentBadge.current_popup_anchor. Every card
        # asks this for its position at display time so it always opens
        # attached to where the badge actually is, even after a drag.
        self.anchor_provider = None
        # Set in main() to PersistentBadge.current_badge_rect, so the card
        # can avoid landing on top of the badge.
        self.badge_rect_provider = None
        # Set in main() to PersistentBadge.current_box_rect. Used ONLY for
        # the window-aware clamp's anchor point (see _finalize) -- the
        # badge's own rect can't serve that role, WindowFromPoint at the
        # badge's own center just finds the badge's own topmost window.
        self.box_rect_provider = None
        self._pos = (0, 0)
        # Which edge of the card stays put as it grows (real ask 2026-07-22).
        # "top": card is below the badge, so it grows DOWNWARD (top edge fixed
        # next to the badge). "bottom": card is above the badge (badge low on
        # screen), so it grows UPWARD (bottom edge fixed next to the badge).
        # Growing away from the badge means a large AI output expands the card
        # in place instead of the whole card jumping up and leaving dead space.
        self._anchor_edge = "top"
        # Set in main() to open_settings, so the card's own gear button
        # (2026-07-24: moved here from the badge at Antonio's direction — "the
        # gear should be in the popup UI, not on the badge") reaches the same
        # Settings path the tray menu does.
        self.on_settings_click = None
        # Recycled-window pool (2026-07-25, real ask: card felt ~0.5s slow to
        # pop up on every click). Measured with cProfile: rebuilding the
        # Toplevel + ~15 header widgets (incl. reloading and re-resizing the
        # logo PNG from disk) from absolute zero on EVERY open, then a full
        # Tk render pass, cost ~400-440ms steady-state, not just a one-time
        # cold start. The header is BYTE-IDENTICAL every time the palette
        # hasn't changed, so tearing it down and rebuilding it per click was
        # pure waste. dismiss() now hides+keeps the window here instead of
        # destroying it; _new_window reuses it when the palette still
        # matches. `self.window` itself still goes back to None on every
        # dismiss exactly as before -- every "is the card open" check
        # elsewhere in this file (~13 of them) reads that, unchanged, so this
        # is purely an internal reuse detail, invisible from outside the class.
        self._pool = None
        self._pool_theme_sig = None
        self._built_theme_sig = None
        # Real ask 2026-07-26: a card shrunk for a small host window looked
        # like the SAME card reflowed narrower (text unchanged -> more
        # wrapping -> taller, not smaller) rather than a true miniature of
        # the original. text_scale drives _fs() below so text shrinks along
        # with the width. Recomputed in _new_window every open from the
        # CURRENT POPUP_WIDTH (itself set per-tick by
        # clamp_popup_width_to_host), so it always reflects the host window
        # this exact open is for.
        self.text_scale = 1.0

    def _fs(self, pt):
        """Scaled point size for card text -- see text_scale's comment in
        __init__. Only ever shrinks (never inflates past the approved
        design size), and floors at 0.65x so small-window text stays
        legible rather than shrinking to nothing."""
        return max(1, round(pt * self.text_scale))

    def _current_theme_sig(self):
        """(theme setting, resolved dark/light, text-scale bucket). Light-
        only now (real ask 2026-07-25, see _apply_card_palette) -- theme is
        a constant. The scale bucket was added 2026-07-26 alongside
        text_scale above: pooling (self._pool_theme_sig == theme_sig in
        _new_window) must fall through to a real rebuild whenever the
        scale actually changes, since font size is baked into each Label/
        Button at construction and a reused pooled window can't pick up a
        new scale on its own. Bucketed to the nearest 0.05 so ordinary
        window-resize jitter doesn't force a rebuild on every single tick,
        only a real size-class change does."""
        return ("light", False, round(self.text_scale, 2))

    def dismiss(self):
        if self.window is not None:
            win = self.window
            self.window = None
            pooled = False
            try:
                if self._pool is not None and self._pool is not win:
                    try:
                        self._pool.destroy()
                    except Exception:
                        pass
                win.withdraw()
                self._pool = win
                self._pool_theme_sig = self._built_theme_sig
                pooled = True
            except Exception:
                pass
            if not pooled:
                try:
                    win.destroy()
                except Exception:
                    pass
                self._pool = None
                # Only the pooled window's header keeps its logo PhotoImage
                # reference alive on purpose (Tk GC's an image with no live
                # Python ref) -- if we're NOT pooling, nothing needs it kept.
                self._photos = []
                self._body = None
        self._suggestion_vars = []
        self._extra_suggestions = []
        self._step1_frame = None
        self._step2_frame = None

    def _trigger_settings(self):
        """Slide the CARD down a bit as a transition cue, then open Settings
        and dismiss the card (real ask: the gear now lives in the card, not
        the badge, but the same 'slides down, then Settings shows up' feel
        applies to whichever UI the gear is actually on)."""
        win = self.window
        if win is None:
            if self.on_settings_click is not None:
                self.on_settings_click()
            return
        try:
            x0, y0 = win.winfo_x(), win.winfo_y()
        except Exception:
            self.dismiss()
            if self.on_settings_click is not None:
                self.on_settings_click()
            return
        drop = int(S(48))
        steps = 7

        def _step(i=0):
            try:
                frac = 1 - (1 - (i + 1) / steps) ** 2   # ease-out: a soft drop
                win.geometry(f"+{x0}+{y0 + int(drop * frac)}")
            except Exception:
                pass
            if i + 1 < steps:
                win.after(14, lambda: _step(i + 1))
            else:
                self.dismiss()
                if self.on_settings_click is not None:
                    self.on_settings_click()
        _step()

    def _badge_rect(self):
        if self.badge_rect_provider is None:
            return None
        try:
            return self.badge_rect_provider()
        except Exception:
            return None

    def last_position(self):
        """Where the card last opened, so a late error can reuse the same
        spot instead of the caller having to thread coordinates through."""
        return self._pos if self._pos is not None else (100, 140)

    def _new_window(self, x, y):
        """Creates (or reuses, see __init__'s pooling note) the card shell
        (border + logo header) shared by every popup state, and returns the
        inner body frame to pack content into. The header keeps the brand
        present in every state, same as Grammarly's own card always showing
        its mark."""
        design_width = S(DESIGN_POPUP_WIDTH)
        self.text_scale = max(0.65, min(1.0, POPUP_WIDTH / design_width)) if design_width else 1.0
        self.dismiss()
        # Prefer the badge's live position over whatever coordinates the
        # caller captured earlier, those go stale the moment the badge is
        # dragged (see PersistentBadge.current_popup_anchor).
        if self.anchor_provider is not None:
            try:
                live = self.anchor_provider()
                if live is not None:
                    x, y = live
            except Exception:
                pass
        self._pos = (x, y)

        theme_sig = self._current_theme_sig()
        dark = theme_sig[1]
        if self._pool is not None and self._pool_theme_sig == theme_sig:
            # Fast path (the common case): the header this window was built
            # with is still correct for the current theme, so reuse the
            # whole Toplevel instead of rebuilding ~15 widgets from scratch.
            # Only the body needs clearing -- _new_window always used to
            # hand back an empty body frame, callers that don't go through
            # _render_review_body (show_loading/show_error) rely on that.
            win = self._pool
            self._pool = None
            self.window = win
            # Destroying the OLD body frame itself (one call, native Tcl
            # recursion over its descendants) then building a fresh empty one
            # is measurably faster than looping over winfo_children() and
            # calling .destroy() on each individually (every one of those is
            # its own Python-level Tkinter call, not just the one C-level
            # recursive teardown a single parent .destroy() gets for free).
            self._body.destroy()
            body = tk.Frame(self._card, bg=POPUP_BG)
            body.pack(fill="both", expand=True)
            self._body = body
            return win
        if self._pool is not None:
            # Stale pool with a mismatched theme signature -- can no longer
            # actually happen now that _current_theme_sig() is a constant
            # (see its docstring), kept as a real guard rather than assumed
            # unreachable. Drop it and build fresh below, same as the
            # pre-pooling behaviour.
            try:
                self._pool.destroy()
            except Exception:
                pass
            self._pool = None
            self._photos = []

        win = tk.Toplevel(self.root)
        # REVERTED 2026-07-26: same regression as the badge window's
        # identical change (see its comment) -- .transient(self.root)
        # against the hidden, withdrawn main root stopped this window from
        # showing at all. FIXED 2026-07-27 the same way as the badge window
        # too -- see the owner=self.root argument below and
        # make_window_non_activating's docstring.
        # Built hidden, then shown in _finalize. make_window_non_activating
        # has to realize the window to work at all (see its docstring), and
        # doing that while visible would flash an empty card at the wrong
        # position first.
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=POPUP_BORDER)  # acts as a 1px border via padding below
        make_window_non_activating(win, owner=self.root)
        # Same belt-and-suspenders fix as the badge window (2026-07-26): if a
        # taskbar entry appears despite WS_EX_TOOLWINDOW, it must never show
        # the default Tk/Tcl feather icon instead of the real logo.
        taskbar_icon = _load_app_icon_image(32)
        if taskbar_icon is not None:
            self._taskbar_icon_photo = ImageTk.PhotoImage(taskbar_icon)
            try:
                win.iconphoto(True, self._taskbar_icon_photo)
            except Exception:
                pass
        # Same tooltip-text fix as the badge window (2026-07-26): a
        # Toplevel's title defaults to the literal "tk" until set, and the
        # taskbar/Alt-Tab tooltip reads that regardless of overrideredirect
        # hiding the title bar itself.
        try:
            win.title(BRAND_NAME)
        except Exception:
            pass

        # Inner white card, inset 1px so POPUP_BORDER shows as a hairline frame.
        card = tk.Frame(win, bg=POPUP_BG)
        card.pack(fill="both", expand=True, padx=S(1), pady=S(1))

        # Brand header: new teardrop logo + wordmark on the left, close on
        # the right, matching Antonio's 2026-07-21 mockup.
        header = tk.Frame(card, bg=POPUP_BG)
        header.pack(fill="x", padx=S(18), pady=(S(14), S(12)))
        # REVERTED 2026-07-26: the plain-text "C/" tried here looked
        # "extremely wrong compared to the settings" once actually seen
        # live. The filled-circle badge mark tried right after THAT still
        # wasn't actually right either -- Settings' own header doesn't use
        # that circular mark at all, it uses mark_dark.png, the bare glyph
        # with no shape behind it (see _load_mark_dark_image). Using that
        # same asset here is what actually makes the two surfaces match,
        # not just superficially resemble each other.
        # "Comprsly" wordmark REMOVED (real ask 2026-07-26, Antonio, direct:
        # "remove the word... increase the size of the icon instead") --
        # the mark carries the header alone now, bigger than it was
        # (26 -> 36) to fill the space the wordmark left.
        logo = _load_mark_dark_image(36)
        if logo is not None:
            photo = ImageTk.PhotoImage(logo)
            self._photos.append(photo)
            tk.Label(header, image=photo, bg=POPUP_BG).pack(side="left")
        close = tk.Label(
            header, text="✕", font=("Segoe UI", self._fs(11)), fg=POPUP_SUBTEXT, bg=POPUP_BG,
            cursor="hand2",
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.dismiss())
        # Settings gear (2026-07-24, moved here from the badge per Antonio: "I
        # don't want the settings gear on the actual badge, I wanted it in the
        # UI that pops up"). Sits beside the close X, top-right of the card.
        gear_d = S(20)
        gear = tk.Canvas(header, width=gear_d, height=gear_d, bg=POPUP_BG,
                         highlightthickness=0, bd=0, cursor="hand2")
        gear.pack(side="right", padx=(0, S(10)))
        _draw_header_settings_icon(gear, gear_d, POPUP_SUBTEXT)

        def _gear_enter(_e):
            _draw_header_settings_icon(gear, gear_d, ACCENT_VIOLET)

        def _gear_leave(_e):
            _draw_header_settings_icon(gear, gear_d, POPUP_SUBTEXT)

        gear.bind("<Enter>", _gear_enter)
        gear.bind("<Leave>", _gear_leave)
        gear.bind("<Button-1>", lambda e: self._trigger_settings())
        # Quick theme toggle removed (real ask 2026-07-25, Antonio, direct:
        # "get rid of the system and dark, only keep light" -- see
        # _apply_card_palette). Used to be a System->Light->Dark->System
        # cycling icon right here; nothing left to cycle to now.
        # Header "On your device" pill REMOVED (real ask 2026-07-26, Antonio,
        # direct: "Remove this from the badge pop-up UI"). The fuller privacy
        # line in _footer_bar ("100% on your device — nothing you type leaves
        # it") stays -- that's the one disclosure kept, not this shorthand
        # duplicate.
        tk.Frame(card, bg=POPUP_BORDER, height=S(1)).pack(fill="x")

        body = tk.Frame(card, bg=POPUP_BG)
        body.pack(fill="both", expand=True)

        self.window = win
        self._card = card  # body's parent, kept so a reuse can recreate just the body (see above)
        self._body = body
        self._built_theme_sig = theme_sig
        return win

    # Colour key for the see-through gap punched around the docked badge.
    # Magenta never appears in the card's content, so ONLY these pixels go
    # transparent (a hole through to the app behind).
    _GAP_KEY = "#ff00fe"

    def _finalize(self, win, x, y):
        """Fixes the card to a consistent width (height auto), so it reads as
        a real designed card instead of shrink-wrapping raggedly to content.

        Badge connection (2026-07-23, Antonio's mockup): the card's bottom
        CORNER (right by default, see _card_corner) sits at the badge's
        CENTRE, so the real 3D badge (its own window, lifted on top)
        protrudes past the corner, and we punch a see-through gap RING into
        the card around it (see _punch_gap) so it reads as a distinct
        circle docked to the card, not embedded in it.

        Corner side is chosen per-open, not hardcoded (real ask 2026-07-25:
        the badge itself moved inside the box to its own right edge, see
        PersistentBadge._position_for, so a box near the screen's left side
        no longer has room to grow a card further left at all -- see
        _card_corner)."""
        win.update_idletasks()
        height = win.winfo_reqheight()
        badge = self._badge_rect()
        self._gap_bw = None
        self._gap_corner = "right"
        if badge is not None:
            bx, by, bw, bh = badge
            # Window-aware (2026-07-25, real bug on stream: a snapped
            # half-and-half layout let the card spill straight into the
            # OTHER app's window, since the monitor alone still had "room").
            # MUST anchor on the real app box's centre, not the badge's own
            # centre: the badge is itself a topmost floating window sitting
            # at exactly that point, so WindowFromPoint(badge centre) just
            # finds the badge's own tiny window and clamps the card into it
            # (found 2026-07-25 night, re-verifying this same fix on install
            # -- the card no longer hugged the badge with the right gap/
            # corner, it landed wherever the badge itself last happened to
            # be). Fall back to the badge centre only if no box rect is on
            # hand (e.g. the badge-rect-only warm-card path).
            box = self.box_rect_provider() if self.box_rect_provider else None
            if box is not None:
                anchor_x = (box.left + box.right) / 2
                anchor_y = (box.top + box.bottom) / 2
            else:
                anchor_x, anchor_y = bx + bw / 2, by + bh / 2
            corner = _card_corner(bx, by, anchor_x, anchor_y)
            self._gap_corner = corner
            # Card corner at the badge centre -> badge half-overlaps (top)
            # / half-protrudes (bottom) on whichever side `corner` picked.
            if corner == "right":
                px = bx + bw // 2 - POPUP_WIDTH
            else:
                px = bx + bw // 2
            host = _host_window_rect(anchor_x, anchor_y)
            # Real bug confirmed live 2026-07-30 (Antonio, screenshots +
            # direct: "the placement when it's [a taller card, e.g. 3
            # fixes] is bad and not corrected to the correct area"): this
            # always opened ABOVE the badge (card's bottom edge at the
            # badge's centre). A short card (1-2 fixes) fits above almost
            # any badge position, so this looked fine -- but a taller card
            # (more fixes, or Step 2 also showing) on a badge sitting
            # mid-screen routinely doesn't fit above at all, went negative,
            # and got clamped straight to the HOST WINDOW'S TOP -- stranding
            # the card far from the badge instead of anywhere near it.
            # Flip below the badge instead (top edge at the badge centre)
            # whenever there's genuinely more room below than above --
            # still not a perfect docked connection (the gap-punch notch is
            # bottom-only, see _punch_gap, so this still reads as
            # disconnected up close, same as any other clamped open below),
            # but "right below the badge" reads as connected at a glance;
            # "at the top of the screen" does not.
            flipped = False
            if host is not None:
                space_above = by - host[1]
                space_below = host[3] - (by + bh)
                if height > space_above and space_below > space_above:
                    flipped = True
            py = (by + bh // 2) if flipped else (by + bh // 2 - height)
            pre_clamp = (px, py)
            px, py = fit_within_window_and_monitor(
                px, py, POPUP_WIDTH, height, anchor_x, anchor_y)
            # Diagnostic only (real ask 2026-07-25: card landing somewhere
            # disconnected from the badge/box on a second, larger monitor --
            # "I like where the badge is... but I do not like how it pops up
            # in that area"). Every real open, not rate-limited (unlike the
            # 0.7s poll-loop diagnostic above) -- opening the card is a rare
            # enough event that this can't spam the log the way a per-tick
            # line would.
            clamped = (px, py) != pre_clamp
            log(f"card _finalize: badge=({bx},{by},{bw},{bh}) "
                f"box_rect={(box.left, box.top, box.right, box.bottom) if box is not None else None} "
                f"anchor=({anchor_x:.0f},{anchor_y:.0f}) corner={corner} flipped={flipped} "
                f"pre_clamp={pre_clamp} host_window={host} "
                f"final=({px:.0f},{py:.0f}) clamped={clamped}")
            self._anchor_edge = "top" if flipped else "bottom"
            # Skip the badge-docking notch entirely when flipped (wrong
            # corner for it, see _punch_gap -- always punches at the
            # BOTTOM) or when the clamp above still had to move the card
            # away from its badge-anchored position (real ask 2026-07-25:
            # an over-constrained screen -- box too close to BOTH edges for
            # the 560px card to fit either way -- would otherwise punch a
            # circular hole in a card corner the badge no longer actually
            # sits behind, showing raw background through it instead of the
            # badge). _card_corner's own room check (now fixed to match
            # this exact math, see its docstring) means the clamped case
            # should be rare, not the common case -- a plain corner in
            # either case reads as "no special treatment here," not broken.
            self._gap_bw = None if (flipped or clamped) else bw
        else:
            # No badge (rare): fall back to the anchored position, grow down.
            px, py = fit_on_one_monitor(self._pos[0], self._pos[1], POPUP_WIDTH, height)
            self._anchor_edge = "top"
        self._pos = (px, py)
        win.geometry(f"{POPUP_WIDTH}x{height}+{int(px)}+{int(py)}")
        if self._gap_bw is not None:
            self._punch_gap(win, POPUP_WIDTH, height, self._gap_bw, self._gap_corner)
        # Only now reveal it, positioned and sized correctly, see _new_window.
        win.deiconify()

    def _punch_gap(self, win, w, h, bw, corner="right"):
        """Punch a see-through gap ring into the card's bottom corner (left
        or right, matching whichever corner _finalize docked the badge at)
        around the docked badge (Antonio's mockup, 2026-07-23). A colour-keyed
        transparent disc, centred on the card corner (= the badge centre), a
        little larger than the badge; the badge window covers the middle, so
        the ring between them shows through to the app behind. Hard-edged oval
        (not a soft image) to keep the keyed edge crisp and halo-free."""
        try:
            win.attributes("-transparentcolor", self._GAP_KEY)
            r_gap = bw / 2 + S(5)
            D = int(r_gap) + S(3)
            if getattr(self, "_gap_canvas", None) is not None:
                try:
                    self._gap_canvas.destroy()
                except Exception:
                    pass
            cv = tk.Canvas(win, width=D, height=D, bg=POPUP_BG,
                           highlightthickness=0, bd=0)
            cv_x = int(w) - D if corner == "right" else 0
            cv.place(x=cv_x, y=int(h) - D)
            # Disc centred at the card's very corner (canvas bottom-right,
            # or bottom-left when the card opened the other way).
            cx = D if corner == "right" else 0
            cy = D
            cv.create_oval(cx - r_gap, cy - r_gap, cx + r_gap, cy + r_gap,
                           fill=self._GAP_KEY, outline="")
            self._gap_canvas = cv
        except Exception:
            log_exception("_punch_gap")

    def _primary_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, font=("Segoe UI Semibold", self._fs(9)), fg="white", bg=ACCENT_VIOLET,
            activebackground=ACCENT_VIOLET, activeforeground="white", relief="flat",
            padx=S(18), pady=S(7), command=command, takefocus=0, cursor="hand2",
            borderwidth=0,
        )

    def _busy_button(self, parent, text, command, busy_text):
        """Same as _primary_button, for a command that does real, slow OS
        work (apply_new_text's focus-restore/clipboard-paste sequence can
        run up to ~1s) synchronously on this same thread. Real ask
        2026-07-21: Fix All and Apply looked frozen because nothing
        repainted, not even the button itself, until that work finished.
        Tk can't preempt a blocked callback, but it CAN paint once before
        the callback starts, so relabel and disable first, force that one
        repaint, then run the real command. The button is about to be
        replaced or torn down by whatever screen this leads to either way,
        so there's no state to restore afterward."""
        btn = self._primary_button(parent, text, None)

        def _wrapped():
            try:
                btn.config(state="disabled", text=busy_text)
                # Real bug found live 2026-07-27 (Antonio, screenshot: a
                # "Dismiss" ghost fragment reading "iss" left hanging next
                # to the button). Root cause: this only repainted the ONE
                # button whose text changed. That's fine on its own, but
                # Step 1 packs this button and Dismiss side-by-side from
                # the left, so when this button's text shrinks (e.g.
                # "Apply 4 fixes" -> "Fixing..."), Dismiss has to physically
                # shift left to stay adjacent -- a SIBLING widget moving,
                # not just this one repainting. update_idletasks() on btn
                # alone doesn't force Windows to repaint the region Dismiss
                # vacated, leaving a stale fragment of its old position
                # behind. Step 2's busy button never showed this because
                # its neighbour is anchored independently from the right,
                # so nothing has to move when its own text changes.
                # Fixed generally, not just for Step 1: update the PARENT
                # row, not just this button, so every sibling that had to
                # reflow gets a real repaint too.
                parent.update_idletasks()
            except Exception:
                pass
            command()

        btn.config(command=_wrapped)
        return btn

    def _fixed_width_apply_holder(self, parent, n):
        """A fixed-size frame for the Step 1 Apply button -- see the real-bug
        note where this is used (the Dismiss ghost-fragment glitch). Sized
        in real pixels (font.measure, not Tk's character-count Button width)
        to the WIDEST label the button can ever show for THIS card instance
        -- "Apply n fixes" (n is already the max possible tick count) or
        "Fixing..." -- so its footprint never changes and Dismiss, packed
        right after it, never has to shift."""
        fnt = tkfont.Font(family="Segoe UI Semibold", size=self._fs(9))
        candidates = ["Fixing..."] + [self._fix_btn_label(k) for k in range(1, max(n, 1) + 1)]
        text_w = max(fnt.measure(t) for t in candidates)
        w = text_w + S(18) * 2 + S(4)  # match _primary_button's padx, plus a small rounding buffer
        h = fnt.metrics("linespace") + S(7) * 2 + S(4)  # match _primary_button's pady
        holder = tk.Frame(parent, width=w, height=h, bg=POPUP_BG)
        holder.pack_propagate(False)
        return holder

    def _muted_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, font=("Segoe UI", self._fs(9)), fg=POPUP_TEXT, bg=POPUP_MUTED_BTN,
            activebackground=POPUP_MUTED_BTN, activeforeground=POPUP_TEXT, relief="flat",
            padx=S(16), pady=S(7), command=command, takefocus=0, cursor="hand2", borderwidth=0,
        )

    def _ghost_button(self, parent, text, command):
        """Transparent text button (the mockup's 'Dismiss'): no fill, muted
        text, so it reads as secondary next to the filled primary."""
        return tk.Button(
            parent, text=text, font=("Segoe UI", self._fs(9)), fg=POPUP_SUBTEXT, bg=POPUP_BG,
            activebackground=POPUP_BG, activeforeground=POPUP_TEXT, relief="flat",
            padx=S(14), pady=S(7), command=command, takefocus=0, cursor="hand2", borderwidth=0,
        )

    def _step_header(self, parent, glyph, glyph_fg, step_label, title, subtitle):
        """One step's heading block, matching the web mockup: a small NUMBERED
        CIRCLE badge (the number taken from step_label, tinted with glyph_fg),
        the title beside it, an explanatory line beneath, and a right-hand slot
        for that step's action button. glyph_fg drives the accent: violet for
        an active step, muted for an idle one."""
        row = tk.Frame(parent, bg=POPUP_BG)
        row.pack(fill="x", padx=S(18), pady=(S(14), S(0)))
        # Pack the action slot FIRST so it reserves its width. Packed last,
        # a long subtitle consumed the whole row and squeezed the Step 2
        # button off the panel entirely (caught in a render check).
        action = tk.Frame(row, bg=POPUP_BG)
        action.pack(side="right", padx=(S(10), S(0)))
        # Numbered circle badge (mockup style) instead of the old text glyph +
        # "Step N:" prefix. Number parsed from step_label ("Step 1:" -> "1").
        num = "".join(c for c in step_label if c.isdigit()) or "•"
        D = S(24)
        badge = tk.Canvas(row, width=D, height=D, bg=POPUP_BG, highlightthickness=0, bd=0)
        badge.pack(side="left", pady=(S(2), 0))
        badge.create_oval(S(1), S(1), D - S(1), D - S(1),
                          fill=_blend(glyph_fg, POPUP_BG, 0.16), outline="")
        badge.create_text(D / 2, D / 2, text=num, fill=glyph_fg,
                          font=("Segoe UI Semibold", self._fs(11)))
        titles = tk.Frame(row, bg=POPUP_BG)
        titles.pack(side="left", padx=(S(10), S(0)), fill="x", expand=True)
        tk.Label(
            titles, text=title, font=("Segoe UI Semibold", self._fs(11)), fg=POPUP_TEXT, bg=POPUP_BG,
            anchor="w",
        ).pack(anchor="w")
        sub = tk.Label(
            titles, text=subtitle, font=("Segoe UI", self._fs(9)), fg=POPUP_SUBTEXT, bg=POPUP_BG,
            # Reserve enough for the WIDEST button that can sit in the action
            # slot, so the subtitle never runs under it. Tk labels don't clip,
            # so an over-wide wraplength only shows up in a render.
            anchor="w", justify="left", wraplength=POPUP_WIDTH - S(205),
        )
        sub.pack(anchor="w", pady=(S(2), S(0)))
        # Exposed so a live refresh can update the count text in place without
        # rebuilding the header (2026-07-23, seamless live update).
        self._hdr_subtitle = sub
        return action

    def _footer_bar(self, parent):
        tk.Frame(parent, bg=POPUP_BORDER, height=S(1)).pack(fill="x", pady=(S(14), S(0)))
        bar = tk.Frame(parent, bg=POPUP_BG)
        bar.pack(fill="x", padx=S(18), pady=(S(10), S(12)))
        # Single green privacy line, matching the web mockup's footer.
        tk.Label(
            bar, text="🔒  100% on your device — nothing you type leaves it",
            font=("Segoe UI", self._fs(8)), fg=ACCENT_GREEN, bg=POPUP_BG,
        ).pack(side="left")

    def show_loading(self, x, y, message="Compressing your prompt with the local AI, this takes a few seconds..."):
        win = self._new_window(x, y)
        tk.Label(
            self._body, text=message, font=("Segoe UI", self._fs(9)), fg=POPUP_TEXT, bg=POPUP_BG,
            padx=S(16), pady=S(14), wraplength=POPUP_WIDTH - S(40), justify="left", anchor="w",
        ).pack(fill="x")
        self._finalize(win, x, y)
        # Real bug found 2026-07-20: Antonio saw the loading card render as a
        # half-blank white box, background and separator painted, but the
        # header and message text never drew, then freeze. Cause: the AI
        # worker thread saturates the CPU the instant it starts, starving the
        # Tk main thread before it finishes painting this card. update_idletasks
        # (in _finalize) does layout but NOT a full repaint; a real update()
        # forces every pending paint to complete NOW, while the CPU is still
        # free, so the card is fully drawn before the heavy work begins. The
        # caller also defers the worker by one event-loop cycle, see
        # compress_with_ai.
        try:
            win.update()
        except Exception:
            pass

    def show_error(self, x, y, message):
        win = self._new_window(x, y)
        tk.Label(
            self._body, text=message, font=("Segoe UI", self._fs(9)), bg=POPUP_BG, fg=CORRECTNESS_ACCENT,
            padx=S(16), pady=S(12), wraplength=POPUP_WIDTH - S(40), justify="left", anchor="w",
        ).pack(fill="x")
        footer = tk.Frame(self._body, bg=POPUP_BG)
        footer.pack(fill="x", padx=S(16), pady=(S(0), S(12)))
        self._muted_button(footer, "Dismiss", self.dismiss).pack(side="right")
        self._finalize(win, x, y)

    def show_suggestions(self, x, y, analysis, ai_enabled, on_apply, text_length):
        """analysis is suggestion_engine.analyze()'s return value for the
        current text. ai_enabled reflects the settings toggle. The card
        always frames Apply as one combined action: rules clean up + (when
        AI is on) the AI compresses the whole prompt. on_apply(checked)
        fires when Apply is clicked. text_length is the raw text's length,
        used to decide whether Step 2 offers to compress at all, see
        _render_step2_offer."""
        win = self._new_window(x, y)
        # Live-refresh bookkeeping (2026-07-23): the card updates in place as
        # the user keeps typing (see refresh()). active flips off once they
        # click Apply/Compress so we stop rebuilding under them.
        self._live = {"on_apply": on_apply, "ai_enabled": ai_enabled,
                      "text_length": text_length,
                      "sig": self._suggestions_sig(analysis), "active": True}
        self._render_review_body(analysis, ai_enabled, on_apply, text_length)
        self._finalize(win, x, y)

    @staticmethod
    def _suggestions_sig(analysis):
        """Cheap identity for the current fix set, so refresh() only rebuilds
        when the fixes actually change, not on every 0.7s poll."""
        return tuple((s.get("kind"), s.get("original"), s.get("replacement"))
                     for s in analysis.get("suggestions", []))

    def refresh(self, analysis, ai_enabled, text_length, text=None):
        """Rebuild the OPEN card's body in place when the fixes change as the
        user types (same window, so no flicker or reposition). Only while the
        card is still in its initial review state; once Apply/Compress fires we
        stop (self._live['active']=False) so the card isn't yanked around.

        `text` is the current field text; it updates the apply state so Apply
        acts on what's actually in the box now, matching the shown fixes."""
        live = getattr(self, "_live", None)
        if self.window is None or not live or not live.get("active"):
            return
        # Keep the apply target in sync with the current text even if the fix
        # set itself didn't change (e.g. text grew but no new fixes yet).
        if text is not None and getattr(self, "_apply_state", None) is not None:
            self._apply_state["text"] = text
        sig = self._suggestions_sig(analysis)
        if sig == live["sig"]:
            return
        suggestions = analysis["suggestions"]
        # Only a STRUCTURAL change (list appears/disappears, or the AI/Step-2
        # state flips) needs a full body rebuild. The common case — new typos
        # while a list is already showing — updates the list INCREMENTALLY:
        # existing rows are untouched, just the new row is added, so there's no
        # white flash and no wholesale "replacement" (2026-07-23, seamless).
        structural = (bool(suggestions) != bool(self._fl_sigs)
                      or ai_enabled != live.get("ai_enabled")
                      or not self._fl)
        live["sig"] = sig
        live["ai_enabled"] = ai_enabled
        live["text_length"] = text_length
        try:
            if structural:
                self._render_review_body(analysis, ai_enabled, live["on_apply"], text_length)
                self._refit()
            else:
                prev_h = self._fl_visible_h()
                self._sync_fixrows(suggestions)
                self._update_fixlabels(len(suggestions))
                # Only resize the window when the visible list height actually
                # changed (first few rows); past the 3-row cap it never resizes.
                if self._fl_visible_h() != prev_h:
                    self._refit()
        except Exception:
            log_exception("card live refresh")

    # ---- fixes list: built once, updated incrementally (seamless) ----------
    @staticmethod
    def _fix_subtitle(n):
        return f"{n} thing{'s' if n != 1 else ''} to clean up · tick the ones to apply"

    @staticmethod
    def _fix_btn_label(n):
        return f"Apply {n} fix{'es' if n != 1 else ''}"

    def _fl_visible_h(self):
        return min(len(getattr(self, "_fl_sigs", [])),
                   getattr(self, "_fl_max", 3)) * getattr(self, "_fl_rowh", S(58))

    def _update_fixlabels(self, n):
        try:
            if getattr(self, "_step1_subtitle", None) is not None:
                self._step1_subtitle.config(text=self._fix_subtitle(n))
        except Exception:
            pass
        self._refresh_apply_count()

    def _refresh_apply_count(self):
        """Keep the primary button showing how many fixes will ACTUALLY apply
        (the ticked ones), not the total found — Tier 3 items start unticked,
        so 'Apply N fixes' must reflect the checked count and track toggles."""
        btn = getattr(self, "_apply_btn", None)
        if btn is None:
            return
        try:
            k = sum(1 for var, _s in self._suggestion_vars if var.get())
            btn.config(text=self._fix_btn_label(k))
        except Exception:
            pass

    def _build_fixlist(self, parent, suggestions):
        """The scrollable fixes list, built ONCE into a STABLE canvas+inner so
        a live refresh can add rows incrementally (see _sync_fixrows) with no
        full rebuild and no flash. Caps at 3 visible rows; the rest scroll,
        with the violet pill thumb."""
        MAX = 3
        ROW_H = S(58)
        SB_W = S(8)
        self._fl_max = MAX
        self._fl_rowh = ROW_H
        holder = tk.Frame(parent, bg=POPUP_BG)
        holder.pack(fill="x", padx=S(17), pady=(S(10), S(0)))
        h0 = min(len(suggestions), MAX) * ROW_H
        canvas = tk.Canvas(holder, bg=POPUP_BG, highlightthickness=0, bd=0, height=h0)
        sb = tk.Canvas(holder, width=SB_W, height=h0, bg=POPUP_BG,
                       highlightthickness=0, bd=0)

        def paint(first, last):
            sb.delete("thumb")
            try:
                first, last = float(first), float(last)
            except Exception:
                return
            if first <= 0.0 and last >= 1.0:
                return
            track = int(canvas.cget("height")) or h0
            r = (SB_W - S(2)) / 2
            pad = S(2)
            usable = track - 2 * pad
            y0 = pad + first * usable
            y1 = pad + last * usable
            if y1 - y0 < 2 * r + S(10):
                y1 = y0 + 2 * r + S(10)
            cx = SB_W / 2
            sb.create_line(cx, y0 + r, cx, y1 - r, fill=ACCENT_VIOLET,
                           width=SB_W - S(2), capstyle="round", tags="thumb")

        canvas.configure(yscrollcommand=paint)
        inner = tk.Frame(canvas, bg=POPUP_BG)
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: (
            canvas.configure(scrollregion=canvas.bbox("all")), paint(*canvas.yview())))
        canvas.bind("<Configure>", lambda e: (
            canvas.itemconfigure(cw, width=e.width), paint(*canvas.yview())))
        sb.bind("<Configure>", lambda _e: paint(*canvas.yview()))
        sb.pack(side="right", padx=(S(4), 0))
        canvas.pack(side="left", fill="x", expand=True)
        sb.after(60, lambda: paint(*canvas.yview()))

        def sb_jump(e):
            frac = max(0.0, min(1.0, e.y / max(int(canvas.cget("height")), 1)))
            canvas.yview_moveto(frac)
        sb.bind("<Button-1>", sb_jump)
        sb.bind("<B1-Motion>", sb_jump)

        def wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._fl = {"canvas": canvas, "inner": inner, "sb": sb, "paint": paint}
        self._fl_sigs = []
        self._sync_fixrows(suggestions)

    def _sync_fixrows(self, suggestions):
        """Bring the list rows in line with `suggestions`. Pure appends (the
        typical case while typing) add ONLY the new tail rows, leaving existing
        rows and their checkbox states untouched — seamless. Any other change
        rebuilds the rows, but confined to the list (the header, Step 2 and
        footer are never touched, so the whole card never flashes)."""
        fl = getattr(self, "_fl", None)
        if not fl:
            return
        inner = fl["inner"]
        new_sigs = [(s["kind"], s["original"], s["replacement"]) for s in suggestions]
        old = self._fl_sigs
        if len(new_sigs) >= len(old) and new_sigs[:len(old)] == old:
            for s in suggestions[len(old):]:
                # Tier 1/2 (safe/objective) start CHECKED; Tier 3 (homophones,
                # stylistic punctuation, style trims) start UNCHECKED so a bulk
                # "Apply" never forces a judgment call (grammar spec v2).
                var = tk.BooleanVar(value=(s.get("tier", 1) != 3))
                self._suggestion_vars.append((var, s))
                self._render_suggestion_card(inner, s, var)
        else:
            for w in inner.winfo_children():
                w.destroy()
            self._suggestion_vars = []
            for s in suggestions:
                # Tier 1/2 (safe/objective) start CHECKED; Tier 3 (homophones,
                # stylistic punctuation, style trims) start UNCHECKED so a bulk
                # "Apply" never forces a judgment call (grammar spec v2).
                var = tk.BooleanVar(value=(s.get("tier", 1) != 3))
                self._suggestion_vars.append((var, s))
                self._render_suggestion_card(inner, s, var)
        self._fl_sigs = new_sigs
        h = min(len(suggestions), self._fl_max) * self._fl_rowh
        fl["canvas"].configure(height=h)
        fl["sb"].configure(height=h)
        inner.update_idletasks()
        fl["canvas"].configure(scrollregion=fl["canvas"].bbox("all"))
        fl["paint"](*fl["canvas"].yview())

    def _render_review_body(self, analysis, ai_enabled, on_apply, text_length):
        """Builds (or, on live refresh, rebuilds) everything below the header:
        Step 1 + Step 2 + footer. Kept separate from show_suggestions so
        refresh() can re-run it into the same window."""
        body = self._body
        for w in body.winfo_children():   # reused by refresh(): clear first
            w.destroy()
        self._suggestion_vars = []
        # Fixes-list refs, rebuilt below when there are fixes to show. Cleared
        # here so a live refresh knows there's no list in the empty state.
        self._fl = None
        self._fl_sigs = []
        self._step1_subtitle = None
        self._apply_btn = None

        suggestions = analysis["suggestions"]
        # Show EVERY fix (each with its own checkbox) inside a height-capped
        # scrollable list, rather than truncating to "+N more" (2026-07-22,
        # matches the web mockup's capped checklist). See the list build below.
        shown, self._extra_suggestions = suggestions, []

        def _fix_clicked():
            live = getattr(self, "_live", None)
            if live:
                live["active"] = False   # user acted; stop live refresh
            checked = [s for var, s in self._suggestion_vars if var.get()]
            checked.extend(self._extra_suggestions)
            on_apply(checked)

        # Nothing-to-do state (real ask 2026-07-22): if there are no grammar
        # fixes AND nothing to compress (box empty/too short, or AI off), do
        # NOT show the confusing "Step 1 done / Step 2: nothing to compress"
        # skeleton. Show one honest line instead. Two numbered steps only make
        # sense when there's actually something for them to do.
        can_compress = ai_enabled and text_length >= MIN_TEXT_LENGTH_TO_ANALYZE
        if not suggestions and not can_compress:
            if text_length < MIN_TEXT_LENGTH_TO_ANALYZE:
                msg = ("Nothing to fix yet. Start typing and Comprsly will "
                       "catch spelling, grammar and punctuation as you go.")
            else:
                msg = "No spelling, grammar or punctuation issues found. Looks clean."
            tk.Label(
                body, text=msg, font=("Segoe UI", self._fs(10)), fg=POPUP_SUBTEXT, bg=POPUP_BG,
                padx=S(18), pady=S(16), wraplength=POPUP_WIDTH - S(40),
                justify="left", anchor="w",
            ).pack(fill="x")
            self._footer_bar(body)
            return

        # Real ask 2026-07-21: the two steps must read as ONE card
        # progressing, not as a card being replaced by a different card.
        # Each step therefore lives in its own container frame, so step one
        # can be swapped for a one-line receipt in place and step two can
        # move up into the space it vacated, without ever destroying and
        # rebuilding the window. See collapse_step1 / _swap_step2.
        step1 = tk.Frame(body, bg=POPUP_BG)
        step1.pack(fill="x")
        self._step1_frame = step1

        # --- Step 1: grammar & clarity -------------------------------------
        n = len(suggestions)
        if not suggestions:
            # Real ask 2026-07-21: with nothing to fix, don't make the user
            # look at an empty Step 1 and work out that it's inert. Show the
            # same one-line receipt the collapsed state uses and let Step 2
            # be the live thing, so the card opens already on the part they
            # actually want.
            tk.Label(
                step1, text="✓  No grammar or spelling issues found",
                font=("Segoe UI Semibold", self._fs(9)), fg="#2e9e5b", bg=POPUP_BG, anchor="w",
            ).pack(fill="x", padx=S(18), pady=(S(14), S(0)))
        else:
            # Buttons go BELOW the fixes list (see after the list), matching the
            # mockup, so the subtitle gets the full width and never runs under a
            # button. The header's right-hand action slot stays empty here.
            self._step_header(
                step1, "✓", ACCENT_VIOLET, "Step 1:", "Fix grammar & clarity",
                self._fix_subtitle(n),
            )
            # Captured so a live refresh can update the count in place.
            self._step1_subtitle = self._hdr_subtitle

        if shown:
            self._build_fixlist(step1, shown)
            # Apply + Dismiss below the list (mockup layout).
            btnrow = tk.Frame(step1, bg=POPUP_BG)
            btnrow.pack(fill="x", padx=S(18), pady=(S(12), S(0)))
            # Real bug found live 2026-07-27, and reproduced again 2026-07-30
            # (Antonio, screenshots both times): a stale "Dismiss" fragment
            # left hanging when this button's label shrinks (e.g. "Apply 4
            # fixes" -> "Fixing..."), because Dismiss -- packed right after
            # it -- has to physically slide left to stay adjacent, and this
            # window's -transparentcolor attribute doesn't always repaint
            # the region it vacates. The 2026-07-27 fix (parent.
            # update_idletasks() in _busy_button) wasn't reliable enough.
            # Real fix: stop Dismiss from ever having to move. Wrap the
            # button in a frame sized to the WIDEST label it can ever show
            # for this card -- "Apply n fixes" or "Fixing..." -- with
            # pack_propagate off, so the button's own footprint is fixed
            # for the Fixing transition AND every per-toggle count change.
            apply_holder = self._fixed_width_apply_holder(btnrow, n)
            apply_holder.pack(side="left")
            self._apply_btn = self._busy_button(
                apply_holder, self._fix_btn_label(n), _fix_clicked, "Fixing...")
            self._apply_btn.pack(fill="both", expand=True)
            self._ghost_button(btnrow, "Dismiss", self.dismiss).pack(side="left", padx=(S(6), 0))
            # Reflect the DEFAULT-checked count (Tier 1/2), since Tier 3 rows
            # start unticked.
            self._refresh_apply_count()

        # --- Step 2: compression -------------------------------------------
        if ai_enabled:
            step2 = tk.Frame(body, bg=POPUP_BG)
            step2.pack(fill="x")
            self._step2_frame = step2
            self._render_step2_offer(step2, waiting_on_step1=bool(suggestions),
                                     on_compress=_fix_clicked,
                                     enough_text=text_length >= MIN_TEXT_LENGTH_TO_ANALYZE)

        self._footer_bar(body)

    # ONE title for step two everywhere. The long form ("Make It Concise
    # (Save Tokens)") overruns the header row whenever a real button sits in
    # the right slot, and Tk labels do not clip, they get drawn under the
    # button. That bug has now been fixed three separate times in three
    # separate render paths, so the variable is gone entirely.
    def _render_step2_offer(self, parent, waiting_on_step1, on_compress, enough_text=True):
        """Step two's resting state. When step one still has fixes pending
        this is inert and just says so; once step one is done the same block
        is re-rendered with a live button (see collapse_step1).

        Real ask 2026-07-21: a near-empty box (one stray keystroke, or just
        the placeholder) still offered a live compress button as if there
        were a real prompt to shorten. Compressing almost nothing isn't a
        meaningful action, so enough_text (same MIN_TEXT_LENGTH_TO_ANALYZE
        threshold the rules stage already uses) gates the live button
        ahead of waiting_on_step1, not after it: not enough text wins even
        once step one is otherwise done."""
        tk.Frame(parent, bg=POPUP_BORDER, height=S(1)).pack(fill="x", padx=S(18), pady=(S(14), S(0)))
        action = self._step_header(
            parent, "◎", ACCENT_VIOLET, "Step 2:", STEP2_TITLE,
            "Shorten it with the local AI, then review the result before applying.",
        )
        if not enough_text:
            tk.Label(
                action, text="nothing to compress", font=("Segoe UI", self._fs(8)),
                fg=POPUP_SUBTEXT, bg=POPUP_BG,
            ).pack()
        elif waiting_on_step1:
            tk.Label(
                action, text="after Step 1", font=("Segoe UI", self._fs(8)),
                fg=POPUP_SUBTEXT, bg=POPUP_BG,
            ).pack()
        else:
            # Real fix 2026-07-25 (button text/placement report): this used
            # to pack a "✦ Optimize Now" button into the header's action
            # slot, TWO bugs at once. (1) Text: collapse_step1's own footer
            # button for the exact same action says "Compress with AI" --
            # two different labels for one action depending on which path
            # rendered it. (2) Placement: the header slot vertically CENTERS
            # its content against the whole title+subtitle block, and this
            # subtitle wraps to two lines, so the button visibly floats
            # mid-text instead of sitting cleanly below it -- measured
            # directly (row height 95px, button centered at y=21..73, deep
            # inside the wrapped second line). collapse_step1's own comment
            # already diagnosed this exact slot as collision-prone ("a
            # footer row cannot collide with the title the way that slot
            # repeatedly has") and moved off it; this path just never got
            # the same fix. Do the same thing here: a footer row below the
            # header, not the header's own action slot.
            footer = tk.Frame(parent, bg=POPUP_BG)
            footer.pack(fill="x", padx=S(18), pady=(S(12), S(0)))
            self._primary_button(footer, "Compress with AI", on_compress).pack(side="right")

    def _refit(self):
        """Resize the existing card to its new content height, growing it from
        the edge next to the badge so it EXPANDS to fit new content (like a
        large AI output) instead of the whole card jumping.

        Real ask 2026-07-22: when the compressed output loaded, the card moved
        higher up to fit it and left dead space. The old code re-anchored the
        TOP to the live y and grew downward, then a clamp shoved the whole
        card up when it ran past the screen bottom, which is the jump. Now the
        edge beside the badge stays fixed (see self._anchor_edge) and the card
        extends AWAY from the badge: down when it sits below the badge, up when
        it sits above (badge low on screen). No reposition, no dead space.

        Reads the LIVE window position, not the stale creation _pos, so a card
        dragged with the badge still resizes where it actually is (2026-07-21).
        """
        win = self.window
        if win is None:
            return
        try:
            win.update_idletasks()
            new_h = win.winfo_reqheight()
            cur_x, cur_y = win.winfo_x(), win.winfo_y()
            cur_h = win.winfo_height()
            if self._anchor_edge == "bottom":
                # Keep the bottom edge fixed; the top rises to make room.
                new_y = (cur_y + cur_h) - new_h
            else:
                # Keep the top edge fixed; the bottom drops to make room.
                new_y = cur_y
            # Still guarantee the card stays wholly on one monitor; this only
            # nudges when the content genuinely can't fit in the grow direction.
            px, py = fit_on_one_monitor(cur_x, new_y, POPUP_WIDTH, new_h)
            win.geometry(f"{POPUP_WIDTH}x{new_h}+{int(px)}+{int(py)}")
            self._pos = (px, py)
            # The bottom corner moved (height changed), so re-place the
            # see-through gap notch there. Same corner as when the card
            # opened (self._gap_corner) -- height changing never moves the
            # card left/right, so the side chosen in _finalize still holds.
            if getattr(self, "_gap_bw", None):
                self._punch_gap(win, POPUP_WIDTH, new_h, self._gap_bw,
                                 getattr(self, "_gap_corner", "right"))
        except Exception:
            log_exception("popup _refit")

    def _swap_step2(self, builder):
        """Replaces step two's contents in place. Returns False if the card
        isn't in the expected state, so callers can fall back to rebuilding
        rather than silently doing nothing."""
        if self.window is None or self._step2_frame is None:
            return False
        try:
            for child in self._step2_frame.winfo_children():
                child.destroy()
            builder(self._step2_frame)
            self._refit()
            return True
        except Exception:
            log_exception("popup _swap_step2")
            return False

    def collapse_step1(self, fixed_count, on_compress, enough_text=True):
        """Step one collapses to a single confirmation line and step two
        moves up into its place, in the same card. Returns False if this
        can't be done, so the caller can fall back to the old rebuild.

        enough_text: same reasoning as _render_step2_offer. Rare here (a fix
        was just applied, so there was at least some real text), but a very
        short corrected prompt ("helo" -> "hello") still isn't worth
        offering to compress."""
        if self.window is None or self._step1_frame is None or self._step2_frame is None:
            return False
        try:
            receipt = tk.Label(
                self._body,
                text=f"✓  Step 1 done · {fixed_count} issue{'s' if fixed_count != 1 else ''} fixed",
                font=("Segoe UI Semibold", self._fs(9)), fg="#2e9e5b", bg=POPUP_BG, anchor="w",
            )
            # `before` is what actually puts the receipt where step one was.
            # Packed without it, the receipt would land underneath step two.
            receipt.pack(fill="x", padx=S(18), pady=(S(14), S(0)), before=self._step2_frame)
            self._step1_frame.destroy()
            self._step1_frame = None

            def build(parent):
                tk.Frame(parent, bg=POPUP_BORDER, height=S(1)).pack(fill="x", padx=S(18), pady=(S(12), S(0)))
                self._step_header(
                    parent, "◎", ACCENT_VIOLET, "Step 2:", STEP2_TITLE,
                    "Shorten this with the local AI, then review the result before applying.",
                )
                # Buttons on their own row, not in the header's action slot.
                # Two reasons: there must be a visible way to stop here after
                # the grammar fixes (Antonio's correction, the compression
                # must never start by itself), and a footer row cannot
                # collide with the title the way that slot repeatedly has.
                footer = tk.Frame(parent, bg=POPUP_BG)
                footer.pack(fill="x", padx=S(18), pady=(S(12), S(0)))
                self._muted_button(footer, "Dismiss", self.dismiss).pack(side="right")
                if enough_text:
                    self._primary_button(footer, "Compress with AI", on_compress).pack(
                        side="right", padx=(S(0), S(8)))
                else:
                    tk.Label(
                        footer, text="nothing to compress", font=("Segoe UI", self._fs(8)),
                        fg=POPUP_SUBTEXT, bg=POPUP_BG,
                    ).pack(side="right", padx=(S(0), S(8)))

            return self._swap_step2(build)
        except Exception:
            log_exception("popup collapse_step1")
            return False

    def step2_loading(self, message="Compressing with the local AI, a few seconds..."):
        """Loading state rendered inside step two rather than as a new card."""
        def build(parent):
            tk.Frame(parent, bg=POPUP_BORDER, height=S(1)).pack(fill="x", padx=S(18), pady=(S(12), S(0)))
            self._step_header(
                parent, "◎", ACCENT_VIOLET, "Step 2:", STEP2_TITLE, message,
            )
        ok = self._swap_step2(build)
        if ok and self.window is not None:
            # update_idletasks does layout but NOT a repaint, and the worker
            # thread saturates the CPU the instant it starts. Without a real
            # update() this card renders half-blank, which is a bug that has
            # already happened once here.
            try:
                self.window.update()
            except Exception:
                pass
        return ok

    def _render_suggestion_card(self, parent, s, var):
        """One fix, styled to match the web mockup as closely as Tk allows:
        a bordered row with a custom Deep Iris checkbox (canvas-drawn, real
        checkmark), the change shown as struck-through old → bold new, and a
        muted category label on the right."""
        cat_name, _accent = SUGGESTION_CATEGORY.get(s["kind"], ("Suggestion", BRAND_PRIMARY))
        card = tk.Frame(parent, bg=POPUP_CARD_BG, highlightbackground=POPUP_BORDER,
                        highlightthickness=1)
        card.pack(fill="x", pady=S(4), padx=S(1))

        # Custom checkbox: a filled Deep Iris square with a white tick when on,
        # a hairline outline when off (the OS Checkbutton can't be themed to
        # match). Clicking it toggles the same BooleanVar _fix_clicked reads.
        cbsz = S(20)
        chk = tk.Canvas(card, width=cbsz, height=cbsz, bg=POPUP_CARD_BG,
                        highlightthickness=0, bd=0, cursor="hand2")
        chk.pack(side="left", padx=(S(10), S(4)), pady=S(10))

        def _redraw():
            chk.delete("all")
            if var.get():
                chk.create_rectangle(S(2), S(2), cbsz - S(2), cbsz - S(2),
                                     fill=ACCENT_VIOLET, outline=ACCENT_VIOLET)
                chk.create_line(S(6), S(10), S(9), S(13), S(15), S(6),
                                fill="white", width=S(2), capstyle="round", joinstyle="round")
            else:
                chk.create_rectangle(S(2), S(2), cbsz - S(2), cbsz - S(2),
                                     fill=POPUP_CARD_BG, outline=POPUP_SUBTEXT)

        def _toggle(_e=None):
            var.set(not var.get())
            _redraw()
            self._refresh_apply_count()   # keep "Apply N fixes" honest
        chk.bind("<Button-1>", _toggle)
        _redraw()

        # Category label, muted, on the right (like the mockup).
        tk.Label(card, text=cat_name.lower(), font=("Segoe UI", self._fs(8)), fg=POPUP_SUBTEXT,
                 bg=POPUP_CARD_BG).pack(side="right", padx=(S(6), S(12)))

        # The change: struck-through old → bold new, on one line.
        def _clip(txt, limit=18):
            txt = " ".join(txt.split())
            return txt if len(txt) <= limit else txt[: limit - 1] + "…"
        row = tk.Frame(card, bg=POPUP_CARD_BG)
        row.pack(side="left", fill="x", expand=True, padx=(S(2), S(6)), pady=S(9))
        tk.Label(row, text=_clip(s["original"]), font=("Segoe UI", self._fs(10), "overstrike"),
                 fg=POPUP_SUBTEXT, bg=POPUP_CARD_BG).pack(side="left")
        tk.Label(row, text="→", font=("Segoe UI", self._fs(10)), fg=POPUP_SUBTEXT,
                 bg=POPUP_CARD_BG).pack(side="left", padx=S(6))
        new = _clip(s["replacement"]) if s["replacement"].strip() else "removed"
        tk.Label(row, text=new, font=("Segoe UI Semibold", self._fs(10)), fg=POPUP_TEXT,
                 bg=POPUP_CARD_BG).pack(side="left")

    def show_compress_offer(self, x, y, on_compress, enough_text=True):
        """Step two of the two-step Apply flow (real ask 2026-07-20): shown
        after the spelling/grammar fixes have already been applied to the
        box. Offers the AI compression of that now-cleaned text as a
        separate, deliberate action, so the AI always works on corrected
        text, never the raw typo'd version."""
        win = self._new_window(x, y)
        body = self._body

        # A small green check chip + title, to signal step one succeeded.
        title_row = tk.Frame(body, bg=POPUP_BG)
        title_row.pack(fill="x", padx=S(16), pady=(S(12), S(4)))
        tk.Label(
            title_row, text="✓", font=("Segoe UI", self._fs(11), "bold"), fg="#2e9e5b", bg=POPUP_BG,
        ).pack(side="left")
        tk.Label(
            title_row, text="Spelling & grammar fixed", font=("Segoe UI Semibold", self._fs(11)),
            fg=POPUP_TEXT, bg=POPUP_BG,
        ).pack(side="left", padx=(S(6), S(0)))

        tk.Label(
            body, text="Now shorten the whole prompt with the local AI, then review it before applying.",
            font=("Segoe UI", self._fs(9)), bg=POPUP_BG, fg=POPUP_SUBTEXT, anchor="w",
            wraplength=POPUP_WIDTH - S(32), justify="left",
        ).pack(fill="x", padx=S(16), pady=(S(0), S(12)))

        footer = tk.Frame(body, bg=POPUP_BG)
        footer.pack(fill="x", padx=S(16), pady=(S(0), S(13)))
        self._muted_button(footer, "Done", self.dismiss).pack(side="right")
        if enough_text:
            self._primary_button(footer, "Compress with AI", on_compress).pack(side="right", padx=(S(0), S(8)))
        else:
            tk.Label(
                footer, text="nothing to compress", font=("Segoe UI", self._fs(8)),
                fg=POPUP_SUBTEXT, bg=POPUP_BG,
            ).pack(side="right", padx=(S(0), S(8)))
        self._finalize(win, x, y)

    def show_compress_result(self, x, y, before_text, after_text, on_apply):
        """Real ask 2026-07-20: the AI-compressed prompt must NOT auto-paste
        into the chat, it should show here first, previewed, with Apply /
        Dismiss, so the compression is reviewable, not instant. Apply pastes
        it; Dismiss leaves whatever's already in the box (the rules-cleaned
        text from step one, or the original)."""
        # Real ask 2026-07-21: same in-place behaviour as step one. If the
        # card is still open with a step-two slot, the result replaces that
        # slot rather than the whole window, so the flow never jumps.
        if self._swap_step2(lambda parent: self._render_compress_result(
                parent, before_text, after_text, on_apply, separator=True)):
            return
        win = self._new_window(x, y)
        self._render_compress_result(self._body, before_text, after_text, on_apply,
                                     separator=False)
        self._footer_bar(self._body)
        self._finalize(win, x, y)

    def _render_compress_result(self, body, before_text, after_text, on_apply, separator):
        before = estimate_tokens(before_text)
        after = estimate_tokens(after_text)
        saved = before - after

        pct = round((saved / before) * 100) if before else 0
        if separator:
            tk.Frame(body, bg=POPUP_BORDER, height=S(1)).pack(fill="x", padx=S(18), pady=(S(12), S(0)))
        # Shorter title here than in the step list: the savings pill sits in
        # the same row and the long form got clipped (caught in a render check).
        action = self._step_header(
            body, "◎", ACCENT_VIOLET, "Step 2:", STEP2_TITLE,
            "Compare both sides. Apply only if nothing important was cut.",
        )
        if saved > 0:
            # Green is our reserved "savings" colour (matches the mockup),
            # not the violet accent.
            tk.Label(
                action, text=f"↓ {saved} tokens · {pct}% shorter", font=("Segoe UI Semibold", self._fs(9)),
                fg=ACCENT_GREEN, bg=POPUP_BG,
            ).pack()

        # Side-by-side Original vs Optimized, per the 2026-07-21 mockup.
        cols = tk.Frame(body, bg=POPUP_CARD_BG, highlightbackground=POPUP_BORDER,
                        highlightthickness=1)
        cols.pack(fill="x", padx=S(18), pady=(S(10), S(0)))
        half = (POPUP_WIDTH - S(40)) // 2

        def column(parent, heading, words, tokens, content, side):
            col = tk.Frame(parent, bg=POPUP_CARD_BG, width=half)
            col.pack(side=side, fill="both", expand=True, padx=S(12), pady=S(10))
            tk.Label(
                col, text=heading, font=("Segoe UI Semibold", self._fs(9)), fg=POPUP_TEXT,
                bg=POPUP_CARD_BG, anchor="w",
            ).pack(fill="x")
            tk.Label(
                col, text=f"{words} words • {tokens} tokens", font=("Segoe UI", self._fs(8)),
                fg=POPUP_SUBTEXT, bg=POPUP_CARD_BG, anchor="w",
            ).pack(fill="x", pady=(S(1), S(6)))

            # Real ask 2026-07-24 (Antonio, after pasting a long redundant test
            # prompt): a long "Original" side just grew this Label (and the
            # whole card, since _finalize sizes off winfo_reqheight()) taller
            # with no ceiling, until it ran off-screen. CAP_H mirrors
            # _build_fixlist's own cap (3 rows * ROW_H) on purpose -- same
            # scrollable-area feel in both places, not two different behaviors
            # in one card. Shrinks to fit short text exactly like the fixes
            # list does; the canvas+scrollbar only gets built past the cap.
            CAP_H = S(58) * 3
            SB_W = S(8)
            wrap_w = half - S(24) - SB_W - S(4)
            holder = tk.Frame(col, bg=POPUP_CARD_BG)
            holder.pack(fill="x")

            probe = tk.Label(holder, text=content, font=("Segoe UI", self._fs(9)), fg=POPUP_TEXT,
                             bg=POPUP_CARD_BG, anchor="nw", justify="left", wraplength=wrap_w)
            probe.pack()
            probe.update_idletasks()
            natural_h = probe.winfo_reqheight()
            probe.destroy()

            if natural_h <= CAP_H:
                tk.Label(
                    holder, text=content, font=("Segoe UI", self._fs(9)), fg=POPUP_TEXT, bg=POPUP_CARD_BG,
                    anchor="nw", justify="left", wraplength=half - S(24),
                ).pack(fill="x")
                return

            h0 = CAP_H
            # width=wrap_w is required here (unlike _build_fixlist's canvas,
            # which has no side-by-side sibling to protect): a canvas with no
            # explicit width requests whatever its embedded window's natural
            # size is on the FIRST layout pass, before any <Configure> event
            # has fired to apply wraplength-constrained sizing. Left unset,
            # that first-pass width can exceed `half` and starve the sibling
            # "Optimized" column of the space it needs, collapsing the
            # two-column layout to one (real bug, caught live 2026-07-24).
            canvas = tk.Canvas(holder, bg=POPUP_CARD_BG, highlightthickness=0, bd=0,
                               height=h0, width=wrap_w)
            sb = tk.Canvas(holder, width=SB_W, height=h0, bg=POPUP_CARD_BG,
                           highlightthickness=0, bd=0)

            def paint(first, last):
                sb.delete("thumb")
                try:
                    first, last = float(first), float(last)
                except Exception:
                    return
                if first <= 0.0 and last >= 1.0:
                    return
                track = int(canvas.cget("height")) or h0
                r = (SB_W - S(2)) / 2
                pad = S(2)
                usable = track - 2 * pad
                y0 = pad + first * usable
                y1 = pad + last * usable
                if y1 - y0 < 2 * r + S(10):
                    y1 = y0 + 2 * r + S(10)
                cx = SB_W / 2
                sb.create_line(cx, y0 + r, cx, y1 - r, fill=ACCENT_VIOLET,
                               width=SB_W - S(2), capstyle="round", tags="thumb")

            canvas.configure(yscrollcommand=paint)
            inner = tk.Frame(canvas, bg=POPUP_CARD_BG)
            cw = canvas.create_window((0, 0), window=inner, anchor="nw")
            tk.Label(
                inner, text=content, font=("Segoe UI", self._fs(9)), fg=POPUP_TEXT, bg=POPUP_CARD_BG,
                anchor="nw", justify="left", wraplength=wrap_w,
            ).pack(fill="x")
            inner.bind("<Configure>", lambda _e: (
                canvas.configure(scrollregion=canvas.bbox("all")), paint(*canvas.yview())))
            canvas.bind("<Configure>", lambda e: (
                canvas.itemconfigure(cw, width=e.width), paint(*canvas.yview())))
            sb.bind("<Configure>", lambda _e: paint(*canvas.yview()))
            sb.pack(side="right", padx=(S(4), 0))
            canvas.pack(side="left", fill="x", expand=True)
            sb.after(60, lambda: paint(*canvas.yview()))

            def sb_jump(e):
                frac = max(0.0, min(1.0, e.y / max(int(canvas.cget("height")), 1)))
                canvas.yview_moveto(frac)
            sb.bind("<Button-1>", sb_jump)
            sb.bind("<B1-Motion>", sb_jump)

            def wheel(e):
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
            canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        column(cols, "Original", len(before_text.split()), before, before_text.strip(), "left")
        tk.Frame(cols, bg=POPUP_BORDER, width=S(1)).pack(side="left", fill="y", pady=S(10))
        column(cols, "Optimized", len(after_text.split()), after, after_text.strip(), "left")

        footer = tk.Frame(body, bg=POPUP_BG)
        footer.pack(fill="x", padx=S(18), pady=(S(12), S(0)))
        self._muted_button(footer, "Dismiss", self.dismiss).pack(side="right")
        self._busy_button(footer, "Apply", on_apply, "Applying...").pack(side="right", padx=(S(0), S(8)))


# Real ask 2026-07-21: "the settings menu is not showing the same UI layout
# scheme as the card, make it look more like that." It had drifted into its
# own palette (#161618 bg, #888888 subtext, BRAND_PRIMARY nav) which read as
# a different product next to the review card. These are now aliases of the
# card's tokens rather than near-miss duplicates, so the two can never drift
# apart again: change POPUP_* and both surfaces move together.
SETTINGS_BG = POPUP_BG
SETTINGS_SIDEBAR_BG = BRAND_DARK
SETTINGS_CARD_BG = POPUP_CARD_BG
SETTINGS_BORDER = POPUP_BORDER
SETTINGS_TEXT = POPUP_TEXT
SETTINGS_SUBTEXT = POPUP_SUBTEXT
SETTINGS_NAV_INACTIVE = "#9a9aa6"
SETTINGS_ACCENT = ACCENT_VIOLET

# Fixed, and deliberately not derived from content. Real ask, same message:
# "make sure it doesn't switch sizes going from page to page." Every section
# renders into a frame of exactly this size with pack_propagate off, so a
# longer page can never push the window wider or taller.
#
# Resized 2026-07-21, Handy's own settings window as the explicit reference
# again (same reference used for the original sidebar-nav layout): "it makes
# no sense why it's so small." Bigger sidebar, bigger content area, and a
# full-width status bar along the bottom (STATUS_BAR_HEIGHT) for the model
# indicator, see _render_status_bar.
SETTINGS_SIDEBAR_W = S(220)
SETTINGS_CONTENT_W = S(780)
# Trimmed 760 -> 600 (2026-07-22): at 760 the window was ~808px tall with the
# status bar, which on a 1080p external monitor eats ~75% of screen height and
# reads as oversized. The content area now SCROLLS (see the canvas in show()),
# so a shorter viewport never clips a longer page -- it was the General tab
# outgrowing the fixed height (5 app-category rows + toggles) that cut off
# "Communication & organization" and hid the rest. Shorter window + scroll is
# comfortable on a 13" laptop and no longer dominates a big monitor, without
# touching the floating badge/card sizing (which stays fixed on purpose).
SETTINGS_HEIGHT = S(600)
STATUS_BAR_HEIGHT = S(48)


class SettingsWindow:
    """Real ask 2026-07-20: a proper settings window, opened by left-
    clicking the tray icon, Handy's own settings UI was the explicit visual
    reference for the sidebar-nav layout. Unlike the badge/popup, this is a
    normal, activatable window (no WS_EX_NOACTIVATE), you open it on
    purpose, it's fine for it to take focus like any other app window."""

    SECTIONS = ["General", "Rules & AI", "Model", "History", "About"]

    def __init__(self, root, badge):
        self.root = root
        self.badge = badge
        self.window = None
        self.content_frame = None
        self.active_section = "General"
        self._nav_labels = {}
        self._icon_photo = None
        self._about_photo = None

    def show(self):
        if self.window is not None:
            try:
                self.window.deiconify()
                self.window.lift()
                self.window.focus_force()
                return
            except Exception:
                self.window = None

        win = tk.Toplevel(self.root)
        win.title(BRAND_NAME)
        win.configure(bg=SETTINGS_BG)
        total_w = SETTINGS_SIDEBAR_W + SETTINGS_CONTENT_W
        win.geometry(f"{total_w}x{SETTINGS_HEIGHT + STATUS_BAR_HEIGHT}")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._on_close)

        icon_image = _load_app_icon_image(S(32))
        if icon_image is not None:
            self._icon_photo = ImageTk.PhotoImage(icon_image)
            try:
                win.iconphoto(True, self._icon_photo)
            except Exception:
                pass

        # Status bar first: packed side="bottom" before anything else claims
        # the cavity, so it's guaranteed the bottom strip across the FULL
        # window width, sidebar included, same as Handy's own model-status
        # bar. Packing order matters here, not just the side= value: a
        # widget packed later only gets what earlier ones left over.
        self._status_frame = tk.Frame(win, bg=SETTINGS_SIDEBAR_BG, height=STATUS_BAR_HEIGHT)
        self._status_frame.pack(side="bottom", fill="x")
        self._status_frame.pack_propagate(False)
        tk.Frame(win, bg=SETTINGS_BORDER, height=1).pack(side="bottom", fill="x")
        self._render_status_bar()

        main_area = tk.Frame(win, bg=SETTINGS_BG)
        main_area.pack(side="top", fill="both", expand=True)

        sidebar = tk.Frame(main_area, bg=SETTINGS_SIDEBAR_BG, width=SETTINGS_SIDEBAR_W)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        # Same brand lockup as the review card's header: the mark, then the
        # wordmark, then a hairline rule.
        brand = tk.Frame(sidebar, bg=SETTINGS_SIDEBAR_BG)
        brand.pack(fill="x", padx=S(20), pady=(S(24), S(18)))
        mark = _load_logo_image(S(28))
        if mark is not None:
            self._sidebar_photo = ImageTk.PhotoImage(mark)
            tk.Label(brand, image=self._sidebar_photo, bg=SETTINGS_SIDEBAR_BG).pack(side="left")
        tk.Label(
            brand, text=BRAND_NAME, font=("Segoe UI Semibold", 16),
            fg=SETTINGS_TEXT, bg=SETTINGS_SIDEBAR_BG, anchor="w",
        ).pack(side="left", padx=(S(10), 0))
        tk.Frame(sidebar, bg=SETTINGS_BORDER, height=1).pack(fill="x", padx=S(20), pady=(0, S(12)))

        self._nav_labels = {}
        for section in self.SECTIONS:
            lbl = tk.Label(
                sidebar, text=section, font=("Segoe UI Semibold", 13), anchor="w",
                fg=SETTINGS_NAV_INACTIVE, bg=SETTINGS_SIDEBAR_BG,
                padx=S(18), pady=S(11), cursor="hand2",
            )
            lbl.pack(fill="x", padx=S(10), pady=S(2))
            lbl.bind("<Button-1>", lambda e, s=section: self._select_section(s))
            self._nav_labels[section] = lbl

        tk.Label(
            sidebar, text="🛡  100% Local & Private", font=("Segoe UI", 9),
            fg=SETTINGS_SUBTEXT, bg=SETTINGS_SIDEBAR_BG, anchor="w", padx=S(20),
        ).pack(side="bottom", fill="x", pady=(0, S(16)))

        # Fixed-size viewport (pack_propagate off stops a long page from
        # resizing the window), with a SCROLLING canvas inside it so a section
        # taller than the viewport is reachable instead of clipped. The
        # General tab outgrew the old fixed height once it gained the app-
        # category rows, which silently cut off everything past the fold
        # (2026-07-22). Sections still render into self.content_frame exactly
        # as before; it's now the canvas's inner frame rather than the
        # viewport itself.
        viewport = tk.Frame(
            main_area, bg=SETTINGS_BG, width=SETTINGS_CONTENT_W, height=SETTINGS_HEIGHT)
        viewport.pack(side="left", fill="both", expand=True)
        viewport.pack_propagate(False)

        canvas = tk.Canvas(viewport, bg=SETTINGS_BG, highlightthickness=0, bd=0)
        canvas.pack(side="left", fill="both", expand=True)
        vbar = tk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        self._settings_canvas = canvas
        self._settings_vbar = vbar

        self.content_frame = tk.Frame(canvas, bg=SETTINGS_BG)
        content_window = canvas.create_window(
            (0, 0), window=self.content_frame, anchor="nw", width=SETTINGS_CONTENT_W)

        self.content_frame.bind("<Configure>", lambda _e: self._refresh_scroll())

        def _on_canvas_config(e):
            # Keep the inner frame's width matched to the visible canvas width
            # (which shrinks when the scrollbar appears), so content reflows
            # rather than being cut horizontally.
            canvas.itemconfigure(content_window, width=e.width)
        canvas.bind("<Configure>", _on_canvas_config)

        # Mousewheel scrolling, bound only while the pointer is over the
        # canvas so it never hijacks the wheel elsewhere.
        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self.window = win
        self._select_section(self.active_section)
        win.lift()
        win.focus_force()
        self._schedule_status_refresh()

    def _refresh_scroll(self):
        """Recompute the scroll extent and show the scrollbar only when the
        current page is taller than the viewport. Compares against the known
        SETTINGS_HEIGHT (deterministic) rather than the canvas's realized
        height, which isn't reliable right after a render."""
        canvas = getattr(self, "_settings_canvas", None)
        if canvas is None:
            return
        canvas.configure(scrollregion=canvas.bbox("all"))
        overflow = self.content_frame.winfo_reqheight() > SETTINGS_HEIGHT
        vbar = self._settings_vbar
        if overflow and not vbar.winfo_ismapped():
            vbar.pack(side="right", fill="y")
        elif not overflow and vbar.winfo_ismapped():
            vbar.pack_forget()

    def _on_close(self):
        # Setting self.window to None below is what stops the pending
        # _schedule_status_refresh chain (it checks for that and returns).
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None

    def _render_status_bar(self):
        """Handy's own settings window has a persistent bottom bar naming
        which model is active with a colour dot, green when it's healthy.
        Real ask 2026-07-21: the explicit visual reference again. Comprsly
        only ever has one local model rather than a user-picked list, so
        this names it and its real state instead of offering a dropdown
        there's nothing to choose from."""
        for w in self._status_frame.winfo_children():
            w.destroy()

        downloaded = local_model.is_model_downloaded()
        ai_on = APP_SETTINGS["ai_enabled"]
        if not downloaded:
            # Honest wording (audit 2026-07-25): "still downloading" was a
            # flat lie for a user who simply declined the model download.
            downloading = local_model.is_downloading() or bool(
                (local_model.download_progress_from_disk() or {}).get("active"))
            dot_color = "#5a5a64"
            label = "Model downloading…" if downloading else "AI model not downloaded"
        elif not ai_on:
            dot_color, label = "#5a5a64", "AI compression off"
        else:
            dot_color, label = "#2e9e5b", local_model.model_label()

        left = tk.Frame(self._status_frame, bg=SETTINGS_SIDEBAR_BG)
        left.pack(side="left", padx=S(18))
        dot_size = S(10)
        dot = tk.Canvas(left, width=dot_size, height=dot_size,
                        bg=SETTINGS_SIDEBAR_BG, highlightthickness=0)
        dot.pack(side="left")
        dot.create_oval(1, 1, dot_size - 1, dot_size - 1, fill=dot_color, outline=dot_color)
        tk.Label(
            left, text=label, font=("Segoe UI Semibold", 10),
            fg=SETTINGS_TEXT, bg=SETTINGS_SIDEBAR_BG,
        ).pack(side="left", padx=(S(8), 0))

        tk.Label(
            self._status_frame, text=f"v{APP_VERSION}", font=("Segoe UI", 9),
            fg=SETTINGS_SUBTEXT, bg=SETTINGS_SIDEBAR_BG,
        ).pack(side="right", padx=S(18))

    def _schedule_status_refresh(self):
        """Keeps the status bar honest while settings is left open: a
        download finishing, or ai_enabled changing in one tab, should be
        reflected without needing to close and reopen the window."""
        if self.window is None:
            return
        try:
            self._render_status_bar()
            self.window.after(2000, self._schedule_status_refresh)
        except Exception:
            pass

    def _select_section(self, section):
        self.active_section = section
        for name, lbl in self._nav_labels.items():
            is_active = name == section
            lbl.config(
                bg=SETTINGS_ACCENT if is_active else SETTINGS_SIDEBAR_BG,
                fg="white" if is_active else SETTINGS_NAV_INACTIVE,
            )
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        {
            "General": self._render_general,
            "Rules & AI": self._render_rules_ai,
            "Model": self._render_model,
            "History": self._render_history,
            "About": self._render_about,
        }[section]()
        # Start each section at the top and recompute the scroll extent /
        # scrollbar visibility for its content height (canvas exists after
        # show()).
        canvas = getattr(self, "_settings_canvas", None)
        if canvas is not None:
            canvas.update_idletasks()
            self._refresh_scroll()
            canvas.yview_moveto(0)

    # ---- shared layout helpers ----

    def _section_header(self, text):
        """Section title plus a hairline rule, mirroring the review card's
        own header treatment."""
        tk.Label(
            self.content_frame, text=text, font=("Segoe UI Semibold", 22),
            fg=SETTINGS_TEXT, bg=SETTINGS_BG, anchor="w",
        ).pack(fill="x", padx=S(28), pady=(S(26), S(14)))
        tk.Frame(self.content_frame, bg=SETTINGS_BORDER, height=1).pack(
            fill="x", padx=S(28), pady=(0, S(6)))

    def _row(self, label_text, subtitle=None):
        """One setting, rendered as a bordered card, the same shape the
        review card uses for each suggestion."""
        card = tk.Frame(self.content_frame, bg=SETTINGS_CARD_BG,
                        highlightbackground=SETTINGS_BORDER, highlightthickness=1)
        card.pack(fill="x", padx=S(28), pady=S(7))
        row = tk.Frame(card, bg=SETTINGS_CARD_BG)
        row.pack(fill="x", padx=S(16), pady=S(13))
        # Pack the action slot FIRST so it reserves its width. Packed after
        # an expanding text column, the column takes everything and the
        # control gets sliced: "Unload now" rendered as "nload no" over the
        # subtitle, and the AI checkbox sat half off the card. Exactly the
        # same failure the review card's _step_header already documents, so
        # the same fix applies here.
        action = tk.Frame(row, bg=SETTINGS_CARD_BG)
        action.pack(side="right", padx=(S(12), 0))
        text_col = tk.Frame(row, bg=SETTINGS_CARD_BG)
        text_col.pack(side="left", fill="x", expand=True)
        tk.Label(
            text_col, text=label_text, font=("Segoe UI Semibold", 13),
            fg=SETTINGS_TEXT, bg=SETTINGS_CARD_BG, anchor="w",
        ).pack(fill="x")
        if subtitle:
            tk.Label(
                text_col, text=subtitle, font=("Segoe UI", 10), fg=SETTINGS_SUBTEXT,
                bg=SETTINGS_CARD_BG, anchor="w",
                wraplength=SETTINGS_CONTENT_W - S(220), justify="left",
            ).pack(fill="x", pady=(S(3), 0))
        # Callers pack their control into this, not into the row.
        return action

    def _toggle(self, parent, variable, command):
        """Pill-style on/off switch, the same visual language as Handy's own
        settings toggles (real ask 2026-07-21, explicit visual reference).
        Tk has no native switch widget, so this draws one on a Canvas: two
        overlapping circles plus a bridging rectangle make the rounded
        track, and a circle slides between its two resting spots for the
        knob. Kept deliberately simple (no animation) since a switch that
        only ever needs to reflect one BooleanVar's current state doesn't
        need to be more than that."""
        w, h = S(42), S(22)
        canvas = tk.Canvas(parent, width=w, height=h, bg=SETTINGS_CARD_BG,
                           highlightthickness=0, cursor="hand2")

        def redraw():
            canvas.delete("all")
            on = variable.get()
            track = SETTINGS_ACCENT if on else "#3a3a42"
            canvas.create_oval(1, 1, h - 1, h - 1, fill=track, outline=track)
            canvas.create_oval(w - h + 1, 1, w - 1, h - 1, fill=track, outline=track)
            canvas.create_rectangle(h / 2, 1, w - h / 2, h - 1, fill=track, outline=track)
            r = h / 2 - 3
            knob_x = (w - h / 2) if on else (h / 2)
            canvas.create_oval(knob_x - r, h / 2 - r, knob_x + r, h / 2 + r,
                               fill="white", outline="white")

        def on_click(_event=None):
            variable.set(not variable.get())
            redraw()
            command()

        canvas.bind("<Button-1>", on_click)
        redraw()
        return canvas

    def _button(self, parent, text, command, primary=False):
        """Same two button styles as the review card, so an action means the
        same thing on both surfaces."""
        return tk.Button(
            parent, text=text, font=("Segoe UI Semibold", 10) if primary else ("Segoe UI", 10),
            fg="white" if primary else POPUP_TEXT,
            bg=SETTINGS_ACCENT if primary else POPUP_MUTED_BTN,
            activebackground=SETTINGS_ACCENT if primary else POPUP_MUTED_BTN,
            activeforeground="white" if primary else POPUP_TEXT,
            relief="flat", padx=S(16), pady=S(7), command=command,
            takefocus=0, cursor="hand2", borderwidth=0,
        )

    # ---- sections ----

    def _render_general(self):
        self._section_header("General")

        # "Launch on login" removed (2026-07-30, Antonio: broken on the
        # Store/MSIX download -- see webui.py Bridge's matching removal for
        # the full root cause). set_launch_on_login/launch_on_login_is_active
        # stay in this file for heal_launch_on_login's sake, only the UI
        # surface is gone, same scope as the web Settings change.

        # Where Comprsly works (2026-07-25: LLM apps only, see the
        # DEFAULT_SETTINGS note on cat_ai_chat). APP_CATEGORIES is down to a
        # single entry now, but this loop is left generic rather than
        # hardcoded to that one row -- it's the same rendering both this Tk
        # fallback and the real web Settings already share.
        self._row(
            "Where Comprsly works",
            "Comprsly only ever activates in a recognized AI chat app or "
            "website -- nowhere else.",
        )
        for cat in APP_CATEGORIES:
            flag = CATEGORY_SETTING[cat]
            row = self._row(CATEGORY_LABEL[cat], CATEGORY_BLURB[cat])
            var = tk.BooleanVar(value=bool(APP_SETTINGS.get(flag)))

            def _toggle_cat(flag=flag, var=var):
                APP_SETTINGS[flag] = var.get()
                save_settings(APP_SETTINGS)

            self._toggle(row, var, _toggle_cat).pack(side="right")

        # "Badge position: Reset" removed (2026-07-30, same audit as
        # "Launch on login" above): the badge hasn't been draggable/pinnable
        # since 2026-07-23 (see PersistentBadge.__init__ -- user_positioned
        # is never set anymore), so there's never a pinned position left to
        # reset. The equivalent web Settings control was already removed for
        # the same reason back on 2026-07-25 (see webui.py Bridge); this Tk
        # fallback had simply drifted out of sync with that until now.

    def _render_rules_ai(self):
        self._section_header("Rules & AI")

        # Real direction 2026-07-20: rules and AI always work together, one
        # combined Apply, no confidence dial. This is the only knob left, a
        # plain on/off for the AI compression stage.
        row = self._row(
            "Use the AI to compress prompts",
            "On: Apply cleans up typos and filler with rules, then the AI compresses the whole prompt "
            "shorter while keeping the meaning. Off: rules-only cleanup, faster and lighter, no compression.",
        )
        ai_var = tk.BooleanVar(value=APP_SETTINGS["ai_enabled"])

        def _toggle_ai():
            APP_SETTINGS["ai_enabled"] = ai_var.get()
            save_settings(APP_SETTINGS)

        self._toggle(row, ai_var, _toggle_ai).pack(side="right")

        self._row(
            "How it works",
            "Rules and the AI cooperate on every Apply, the rules hand a clean prompt to the AI, "
            "the AI does the deeper compression the rules can't. Same behavior for everyone, no dials.",
        )

    def _render_model(self):
        self._section_header("Model")

        downloaded = local_model.is_model_downloaded()
        downloading = local_model.is_downloading()
        self._row("Model", local_model.model_label())

        if downloaded:
            self._row("Status", "Downloaded and ready")
            size_gb = local_model.model_dir_size_bytes() / (1024 ** 3)
            self._row("Size on disk", f"{size_gb:.1f} GB")
        elif downloading:
            st = local_model.download_state()
            mb_done = st["done"] // (1024 * 1024)
            mb_total = (st["total"] // (1024 * 1024)) or local_model._DOWNLOAD_APPROX_MB
            pct = int(st["done"] * 100 / st["total"]) if st["total"] else 0
            self._row("Downloading the AI model",
                      f"{pct}%  ·  {mb_done} MB of ~{mb_total} MB  ·  {st['file']}")
            # Self-refreshing poll, but only while still on this section, so it
            # stops on its own when the download ends or the user navigates away.
            def _poll():
                if self.window is not None and self.active_section == "Model":
                    self._select_section("Model")
            self.window.after(800, _poll)
        else:
            st = local_model.download_state()
            # Real ask 2026-07-22: the installer no longer bundles the ~1GB
            # model, so it's a one-time in-app download here. Everything else
            # (spelling/grammar/punctuation) works without it.
            row = self._row(
                "AI model not installed",
                "The AI “Make it Concise” step needs a one-time ~1 GB "
                "download. Spelling, grammar and punctuation all work without it.")

            def _start_download():
                threading.Thread(target=local_model.download_model, daemon=True).start()
                self.window.after(250, lambda: self._select_section("Model"))

            self._button(row, "Download AI model (~1 GB)", _start_download,
                         primary=True).pack(side="right")
            if st.get("error"):
                self._row("Last attempt failed",
                          st["error"] + " — check your connection and try again")

        self._row("Location", local_model.model_dir())

        if downloaded:
            row = self._row(
                "Currently loaded in memory" if local_model.is_loaded() else "Not currently loaded",
                "Loads while you type in an AI chat, frees its memory about 30 seconds after you stop",
            )

            def _unload_now():
                local_model.force_unload()
                self._select_section("Model")

            self._button(row, "Unload now", _unload_now).pack(side="right")

    def _render_history(self):
        self._section_header("History")
        history = load_history()
        total_saved = sum(h.get("tokens_saved", 0) for h in history)

        tk.Label(
            self.content_frame, text=f"{total_saved:,} tokens saved", font=("Segoe UI Semibold", 28),
            fg=SETTINGS_ACCENT, bg=SETTINGS_BG, anchor="w",
        ).pack(fill="x", padx=S(28), pady=(S(10), 0))
        tk.Label(
            self.content_frame, text=f"across {len(history)} applied rewrites", font=("Segoe UI", 11),
            fg=SETTINGS_SUBTEXT, bg=SETTINGS_BG, anchor="w",
        ).pack(fill="x", padx=S(28), pady=(0, S(16)))

        if history:
            list_frame = tk.Frame(self.content_frame, bg=SETTINGS_BG)
            list_frame.pack(fill="both", expand=True, padx=S(28))
            for entry in reversed(history[-10:]):
                ts = time.strftime("%b %d, %H:%M", time.localtime(entry.get("timestamp", 0)))
                mode = "AI" if entry.get("used_ai") else "rules"
                tk.Label(
                    list_frame, text=f"{ts}   -{entry.get('tokens_saved', 0)} tokens   ({mode})",
                    font=("Segoe UI", 11), fg=SETTINGS_SUBTEXT, bg=SETTINGS_BG, anchor="w",
                ).pack(fill="x", pady=3)

    def _render_about(self):
        self._section_header("About")
        icon_image = _load_badge_icon_image(64)
        if icon_image is not None:
            self._about_photo = ImageTk.PhotoImage(icon_image)
            tk.Label(self.content_frame, image=self._about_photo, bg=SETTINGS_BG).pack(
                padx=S(28), pady=(0, S(12)), anchor="w"
            )
        tk.Label(
            self.content_frame, text=BRAND_NAME, font=("Segoe UI Semibold", 18),
            fg=SETTINGS_TEXT, bg=SETTINGS_BG, anchor="w",
        ).pack(fill="x", padx=S(28))
        tk.Label(
            self.content_frame, text=f"Version {APP_VERSION}", font=("Segoe UI", 11),
            fg=SETTINGS_SUBTEXT, bg=SETTINGS_BG, anchor="w",
        ).pack(fill="x", padx=S(28), pady=(S(3), S(12)))
        tk.Label(
            self.content_frame,
            text=("Compress. Save tokens.\nRules-first, AI-second. Your text stays "
                  "100% on this machine and is never sent anywhere. The only network "
                  "use is the optional one-time AI-model download."),
            font=("Segoe UI", 11), fg=SETTINGS_SUBTEXT, bg=SETTINGS_BG, anchor="w",
            justify="left", wraplength=SETTINGS_CONTENT_W - S(56),
        ).pack(fill="x", padx=S(28))
        # Real ask 2026-07-22: nudge users to reclaim space by deleting the
        # downloaded installer, which isn't needed once installed.
        tk.Label(
            self.content_frame,
            text=("Tip: you can delete the ComprslySetup file you downloaded — "
                  "it isn't needed now that Comprsly is installed, and removing it "
                  "frees up space."),
            font=("Segoe UI", 10), fg=SETTINGS_SUBTEXT, bg=SETTINGS_BG, anchor="w",
            justify="left", wraplength=SETTINGS_CONTENT_W - S(56),
        ).pack(fill="x", padx=S(28), pady=(S(14), 0))


# This exe's own process name (frozen: comprsly.exe; dev: python.exe). Used
# by watch_loop to recognise when one of Comprsly's own web windows holds
# focus so it doesn't mistake that for the user leaving their text box.
_OWN_EXE_NAME = os.path.basename(sys.executable).lower()

# True while the web review card is open. The card floats without stealing
# focus (focus=False), so the text box stays focused and the watch loop would
# otherwise keep re-showing the badge ON TOP of the card. While the card is
# up, the card IS the UI: hide the badge and bring it back when the card
# closes (2026-07-22: badge was overlapping the card header).
_review_card_open = [False]

# Fixed logical size of the warm web card (matches webui._card_wh). Not scaled
# by S(): pywebview sizes in device-independent pixels and WebView2 handles DPI.
WEB_CARD_W = 430
WEB_CARD_H = 560


class WarmReviewCard:
    """Client side of the persistent warm review card (2026-07-23). Launches
    the --review-card-server process once, keeps it warm, and on each badge
    click sends a `show` command (payload + nested position) over stdin so the
    HTML card pops instantly. Apply/dismiss actions come back on stdout and are
    run through the SAME apply_new_text pipeline the native card uses, so the
    delicate focus/paste behaviour is never rewritten. Falls back to the native
    Tk card whenever the server isn't alive."""

    def __init__(self, root, popup):
        self.root = root
        self.popup = popup
        self.proc = None
        self.open = False
        self._ctx = None   # current click's apply-context (hwnd/field/applied)

    def launch(self):
        try:
            cmd = ([sys.executable, "--review-card-server"] if getattr(sys, "frozen", False)
                   else [sys.executable, os.path.abspath(__file__), "--review-card-server"])
            flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1, creationflags=flags)
            threading.Thread(target=self._reader, daemon=True).start()
            log("warm review-card server launched")
            return True
        except Exception:
            log_exception("warm card launch")
            self.proc = None
            return False

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _send(self, obj):
        if not self.is_alive():
            return False
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
            return True
        except Exception:
            log_exception("warm card send")
            return False

    def show(self, payload, badge_rect, ctx):
        self._ctx = ctx
        bx, by, bw, bh = badge_rect
        cmd = {"cmd": "show", "payload": payload,
               "badge": {"x": int(bx), "y": int(by), "w": int(bw), "h": int(bh)}}
        if self._send(cmd):
            self.open = True
            return True
        return False

    def hide(self):
        self.open = False
        self._send({"cmd": "hide"})

    def quit(self):
        self._send({"cmd": "quit"})

    def _reader(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                action = msg.get("action")
                ctx = self._ctx
                if action == "apply" and ctx is not None:
                    new_text = msg.get("text", "")
                    used_ai = msg.get("stage") == "final"
                    prev = ctx["applied"]

                    def do(new_text=new_text, prev=prev, used_ai=used_ai, ctx=ctx):
                        try:
                            # Dormant path today (launch() is commented out in
                            # main, native card is the default), but kept
                            # honest with the live callers (2026-07-25 audit):
                            # the history write only happens after the apply
                            # reports it really landed, never before.
                            ok = apply_new_text(
                                self.root, self.popup, new_text, target_hwnd=ctx["hwnd"],
                                dismiss_after=False, target_control=ctx["field"],
                                expected_old_text=prev, safe_write_only=ctx["safe_write_only"])
                            if ok:
                                append_history({
                                    "timestamp": time.time(),
                                    "tokens_saved": max(estimate_tokens(prev) - estimate_tokens(new_text), 0),
                                    "used_ai": used_ai,
                                })
                        except Exception:
                            log_exception("warm card apply")
                    self.root.after(0, do)
                    ctx["applied"] = new_text
                    if used_ai:      # final apply closes the card (bridge hid it)
                        self.open = False
                elif action == "dismiss":
                    self.open = False
        except Exception:
            log_exception("warm card reader")
        finally:
            # Reader exit means the server is gone (EOF, crash, quit), and
            # whatever card it was showing went with it. Without this,
            # `open` stuck True forever on a dead card: watch_loop's
            # card_open branch kept nesting the badge against a card that
            # no longer exists and kept the model keepalive pinned.
            self.open = False


class WarmSettingsWindow:
    """Client side of the persistent warm Settings window (real ask
    2026-07-25: every tray click booted a brand-new WebView2 engine from
    scratch, 3-4 seconds, EVERY time -- the app's slowest routine action).
    First open still spawns fresh and pays that cost once; the server hides
    on close instead of exiting, so every later open just sends `show` over
    stdin and reuses the already-warm engine. Same client/server IPC shape
    as WarmReviewCard above. Falls back to today's exact one-shot subprocess
    behavior (main.open_settings' `_run`) on ANY failure to spawn or talk to
    the server -- Settings must never become unreachable because of this."""

    def __init__(self, on_closed):
        self.proc = None
        self._on_closed = on_closed   # called (marshaled to Tk) when the user closes the warm window

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def launch(self):
        try:
            cmd = ([sys.executable, "--web-settings-server"] if getattr(sys, "frozen", False)
                   else [sys.executable, os.path.abspath(__file__), "--web-settings-server"])
            flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1, creationflags=flags)
            threading.Thread(target=self._reader, daemon=True).start()
            log("warm settings server launched")
            return True
        except Exception:
            log_exception("warm settings launch")
            self.proc = None
            return False

    def show(self):
        if not self.is_alive():
            return False
        try:
            self.proc.stdin.write(json.dumps({"cmd": "show"}) + "\n")
            self.proc.stdin.flush()
            return True
        except Exception:
            log_exception("warm settings show")
            return False

    def quit(self):
        if self.is_alive():
            try:
                self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self.proc.stdin.flush()
            except Exception:
                pass

    def _reader(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if msg.get("event") == "closed":
                    # Fires the instant the user closes the warm window (it
                    # hides, doesn't exit), same timing as today's
                    # proc.wait()-then-reload for the one-shot fallback, so
                    # settings changes reach APP_SETTINGS just as promptly.
                    self._on_closed()
        except Exception:
            log_exception("warm settings reader")


def watch_loop(popup: SuggestionPopup, badge: PersistentBadge, root, warmcard=None):
    last_text = None
    last_context_label = "<startup>"
    # Throttles the typing-triggered prewarm attempt (2026-07-25). Once warm,
    # is_loaded() short-circuits it for free -- but for a user who never
    # downloaded the model is_loaded() is false FOREVER, and an unthrottled
    # attempt would re-stat the model directory on every 0.7s typing tick.
    last_prewarm_try = [0.0]
    # Real bug found 2026-07-20: this used to get wiped on EVERY switch away
    # from Claude, including a brief trip to the Snipping Tool or anything
    # else, then rebuilt from scratch on return. Your actual typed text in
    # the real box never goes anywhere when you alt-tab away, only our
    # tracking copy of it did, that's what caused the token count to
    # suddenly crash to almost nothing after taking a screenshot mid-typing.
    # Tracked separately from app_label so a round trip through some other
    # app and back to the SAME LLM doesn't count as a fresh conversation,
    # only switching to a genuinely different LLM does.
    last_real_llm_label = None
    # Real bug found live 2026-08-02 (Antonio, screenshot: badge landing
    # on empty space below Claude's "Code" composer, even though the
    # detection for that exact context was independently confirmed stable
    # and correct in debug.log). Root-caused via the log itself: real OS
    # foreground focus was flickering between "Claude" (browser) and
    # "Claude Code" (a genuinely different window/process, terminal-
    # classified) every few seconds -- confirmed this isn't a detection
    # bug, GetForegroundWindow() is truthfully reporting what Windows
    # itself considers foreground at each moment; a documented, known
    # mechanism already exists for OS focus shifting unexpectedly (see
    # get_foreground_window_and_process's own docstring). The REAL bug is
    # what this app did in response: every single context switch, even a
    # one-tick blip, unconditionally reset locked_badge_rect to None --
    # and a None lock skips ALL debounce protection, accepting whatever
    # that one bad tick computed immediately. So a single flickery tick
    # into the wrong context was enough to visibly jump the badge, with
    # none of the position-stability work elsewhere in this file able to
    # stop it, because it never got a chance to run.
    # Fix: debounce the CONTEXT switch itself the same way rect changes
    # already are -- a new context only actually takes effect once it's
    # been seen on 2 consecutive ticks, so a one-tick flicker is filtered
    # out at the source instead of being chased downstream.
    pending_context_label = [None]
    pending_context_count = [0]
    # The badge re-anchoring to wherever you last clicked made it visibly
    # jump around as you clicked different spots while composing a longer
    # message. Locking it to the first position found per message keeps it
    # stuck in one consistent spot, same as Grammarly's icon never
    # wandering around the box.
    locked_badge_rect = None
    # Real bug found live 2026-07-24 (Antonio: drag the host window across
    # monitors while the card is open, and the badge/card are left stranded
    # at the old spot): tracks the rect last accepted WHILE the card has been
    # open, purely to detect a real window drag (see its use below) without
    # reintroducing the typing-jitter re-anchor the no-reposition rule exists
    # to prevent. Reset to None the moment the card closes, so the next open
    # starts a fresh baseline rather than comparing against a stale one.
    card_open_anchor_rect = None
    # Only log a given placeholder once, this loop runs every 0.7s.
    last_placeholder_logged = [None]
    # Rate-limits the "URL-like value ignored" line so it isn't written every
    # 0.7s tick while on a web page (real ask 2026-07-22: it was 65% of the
    # log). Also, the URL text itself is never logged (privacy).
    url_ignored_logged = [False]
    # Diagnostic only (real ask 2026-07-22): logs the focused control's own
    # class/name whenever the badge's rect changes, so a report like
    # "clicked the middle box, badge stayed at the top" is checkable
    # against what UIA actually says was focused, rather than guessed at
    # again. Only logged on change, this loop runs every 0.7s.
    last_logged_rect = [None]
    # Diagnostic only (real ask 2026-07-25, second report of the same class
    # of bug on the SAME machine after a fix already shipped for it): logs
    # win_rect and the accept/reject outcome every time the off-screen-rect
    # check below actually runs, on change only. The fix that shipped for
    # the first report is CONFIRMED not sufficient by itself -- the exact
    # bogus rect pattern (large negative x from Claude's Design/canvas
    # mode) still made it through to "badge rect source" in a live
    # debug.log after that fix was installed and running. Guessing why a
    # second time without seeing win_rect itself would repeat the mistake
    # the first fix already made (assumed a coordinate space instead of
    # measuring it) -- this records the actual GetWindowRect result (or its
    # failure) so the real cause is checkable next time, not theorized.
    last_reject_diag = [None]
    # Rate-limits the "focused control isn't a real composer" line below
    # (see _NEVER_A_COMPOSER_CONTROL_TYPES) the same way last_reject_diag
    # does for the off-screen-rect check -- logged on change only, this
    # loop runs every 0.7s.
    last_rejected_ctype = [None]
    # One-shot-per-distinct-composer diagnostic dump for Claude (2026-07-30,
    # Antonio, screenshot: a DIFFERENT Claude layout -- the Cowork/project
    # view -- has an inline submit arrow pinned to the composer's own top-
    # right corner, wants the badge docked THERE, not chasing the separate
    # "Sonnet 5 / High" row at the bottom the plain chat layout uses. Same
    # app_label, two different real structures -- rather than guess at this
    # one's tree shape too, dump it for real evidence first (see the
    # _NEVER_A_COMPOSER... precedent for "unrecognized browser tab" doing
    # the same thing).
    last_claude_diag_key = [None]
    # Real bug found 2026-07-22, confirmed directly in debug.log rather
    # than theorized: ChatGPT's composer sometimes reports two wildly
    # different bounding rects for the exact same accessible name ("Chat
    # with ChatGPT") from one 0.7s poll to the next, hundreds of pixels
    # apart, for a box that plainly hadn't moved (there's even a distinct
    # 'wcDTda_fallbackTextarea' sharing that name, likely an
    # accessibility-only hidden field UIA sometimes resolves to instead of
    # the real visible one). A new rect only gets trusted once it's read
    # the SAME way twice in a row, filtering that one-tick flicker out
    # while still tracking a genuine reflow within about 1.4s.
    pending_rect_tuple = [None]
    pending_rect_count = [0]
    # Real bug found live 2026-08-02 (Antonio, screenshot: badge frozen at
    # a stale position while actively typing into Claude's "Code" view,
    # box visibly grown but badge not following). Root cause: the
    # confirmation check below used to require the EXACT same rect_tuple
    # twice in a row -- but a box that's actively growing as text wraps
    # changes its own bounds almost every single 0.7s tick, so it can
    # never produce two IDENTICAL readings back to back while the user is
    # typing. The debounce this exists for (see the comment above, a real
    # ChatGPT bug: "hundreds of pixels apart for a box that plainly hadn't
    # moved") was guarding against a WILD single-tick glitch, not a
    # smoothly growing box -- treating "close enough" as confirmation
    # keeps the wild-glitch protection (a true misread is still hundreds
    # of px off, well past this) while letting a real, gradual reflow
    # actually get confirmed instead of freezing forever.
    _RECT_CLOSE_TOLERANCE_PX = 40


    def _rects_close_enough(a, b):
        if a is None or b is None:
            return False
        return all(abs(x - y) <= _RECT_CLOSE_TOLERANCE_PX for x, y in zip(a, b))
    # Real bug found live 2026-07-30 (Antonio, screenshot: the badge showing
    # up bottom-right of a Comprsly-unrelated interactive screen -- a
    # slider-based scoring tool -- with no chat box anywhere in sight).
    # app_label only ever says WHICH SITE/app this is, never whether a real
    # composer is currently reachable on it (see _NEVER_A_COMPOSER_CONTROL_
    # TYPES's own comment) -- when it isn't, the code below falls through to
    # either the last locked position or a window-relative GUESS, on the
    # theory that's just a one-tick blip mid-typing. Fine for a blip; wrong
    # once it persists, which is exactly what happens on a real non-composer
    # view of a recognized app (a canvas/custom-UI feature, a settings
    # screen, anything else that isn't the chat box) -- the badge then just
    # sits there, guessed or stale, for as long as that view stays open.
    # Counts consecutive no-real-composer ticks so a sustained one (not a
    # single blip) can actually hide the badge instead of guessing forever.
    no_real_composer_ticks = [0]
    # Cache for _input_box_left's parent walk (real ask 2026-07-22): the
    # walk is several UIA round trips, wasteful to repeat every 0.7s tick
    # when the box hasn't moved. Recompute only when the raw control left
    # changes.
    box_left_cache_key = [None]
    box_left_cache_val = [None]
    # Same caching idea for _input_box_right (see BADGE_WIDEN_RIGHT_SITES).
    box_right_cache_key = [None]
    box_right_cache_val = [None]
    # Same caching idea for _toolbar_cluster_left (2026-07-30).
    toolbar_left_cache_key = [None]
    toolbar_left_cache_val = [None]
    # Same caching idea for _input_box_bottom (see BADGE_WIDEN_DOWN_SITES).
    box_bottom_cache_key = [None]
    box_bottom_cache_val = [None]
    # Same caching idea for _below_toolbar_cluster_left (BADGE_TOOLBAR_BELOW_SITES).
    below_toolbar_left_cache_key = [None]
    below_toolbar_left_cache_val = [None]
    claude_send_btn_cache_key = [None]
    claude_send_btn_cache_val = [None]
    # Same caching idea for _claude_code_review_row (2026-08-03, see
    # CLAUDE_CODE_REVIEW_GAP).
    claude_code_review_cache_key = [None]
    claude_code_review_cache_val = [None]
    # Same caching idea for _claude_home_row (2026-08-03, see
    # CLAUDE_HOME_ROW_GAP).
    claude_home_row_cache_key = [None]
    claude_home_row_cache_val = [None]
    # Same caching idea for _perplexity_long_model_row (2026-08-03, see
    # PERPLEXITY_LONG_MODEL_GAP).
    perplexity_long_model_cache_key = [None]
    perplexity_long_model_cache_val = [None]
    # Same caching idea for _perplexity_computer_anchor (2026-08-03, see
    # PERPLEXITY_COMPUTER_ANCHOR_GAP).
    perplexity_computer_anchor_cache_key = [None]
    perplexity_computer_anchor_cache_val = [None]
    # Same caching idea for Gemini's below-row fallback (2026-08-03, see
    # its own call-site comment).
    gemini_below_cache_key = [None]
    gemini_below_cache_val = [None]
    # Same caching idea for the Claude same-row home-composer fallback
    # (2026-08-03, see its own call-site comment).
    claude_same_row_cache_key = [None]
    claude_same_row_cache_val = [None]
    # Real bug found live 2026-08-02 (Antonio, screenshots: ChatGPT badge
    # landing well below the visible box on a short single-line composer,
    # reliably, every time). First hypothesis -- a transient UIA read
    # glitch mid-React-re-render -- was checked directly against a live
    # diagnostic and DISPROVEN: the same exact composer state failed on
    # every one of 3 separate attempts, never once succeeding, which isn't
    # what a one-tick glitch looks like. The real cause (found via a live
    # getBoundingClientRect() measurement of the actual ChatGPT page, see
    # the ChatGPT-specific fallback below) is structural: ChatGPT's toolbar
    # sits INLINE with the text for a single-line message, not below it,
    # so the below-row search this cache backs up never had anything to
    # find there in the first place. Kept anyway as a general safety net --
    # a real transient miss on any BADGE_TOOLBAR_BELOW_SITES app is still
    # possible in principle, and remembering the last good reading instead
    # of trusting a crude fallback immediately can't make a correct read
    # worse, it can only help a genuinely-transient future case.
    last_good_below_toolbar_result = {}
    log("watch_loop started")

    while True:
        # Wait up to a full poll interval, but wake immediately if a click
        # set the event (real ask 2026-07-22, snappy box-to-box tracking).
        # wait() returns True when woken by a click, False on timeout.
        woke_on_click = _focus_recheck_event.wait(POLL_INTERVAL_SECONDS)
        if woke_on_click:
            _focus_recheck_event.clear()
            # Let the click's focus change actually land before reading it.
            time.sleep(FOCUS_SETTLE_AFTER_CLICK_SECONDS)
        try:
            # AI model download (2026-07-23 fix, Antonio: "the download isn't
            # working"): Settings/Onboarding run as their own short-lived
            # subprocess and used to start the download thread THERE, so
            # closing that window killed the download mid-stream with no
            # error shown. It now only writes a request; the download always
            # runs HERE, in this persistent process, so it survives whichever
            # window asked for it being closed.
            if local_model.consume_download_request():
                log("AI model download requested, starting in main process")
                threading.Thread(target=local_model.download_model, daemon=True).start()

            # Settings' "Unload from memory" writes a request file (audit
            # 2026-07-25): the warm worker is OUR child, so only this process
            # can actually free it. Same pattern as the download request.
            if local_model.consume_unload_request():
                log("model unload requested from Settings, unloading here")
                try:
                    local_model.force_unload()
                except Exception:
                    log_exception("settings-requested unload")

            llm_hwnd, process_name = get_foreground_window_and_process()

            # Real ask 2026-07-26 (Antonio, direct: his live-transcription
            # dictation app's own floating overlay visually collides with
            # the badge, which should only ever sit at the real LLM chat
            # box -- "make sure it stays in one area, doesn't move
            # anywhere else"). handy.exe was never actually logged as a
            # recognized app anywhere in debug.log (checked directly), so
            # this isn't the allowlist letting it through -- it's an
            # explicit, zero-risk exclusion regardless of exactly which
            # path might otherwise surface it, same shape as
            # BROWSER_PROCESS_NAMES/KNOWN_LLM_PROCESSES above but for the
            # opposite purpose: never treat this process as a focus
            # candidate at all, this early, before anything downstream
            # gets a chance to.
            EXCLUDED_OVERLAY_PROCESSES = {"handy.exe"}
            if process_name in EXCLUDED_OVERLAY_PROCESSES:
                llm_hwnd, process_name = None, None

            # Real ask 2026-07-25: badge too big on any monitor that isn't
            # the laptop panel (see badge_scale_for_dpi). This machinery
            # (apply_scale_for_window, _scale_listeners) already existed
            # from an earlier full-UI-scaling attempt but was never
            # actually CALLED anywhere -- UI_SCALE/POPUP_WIDTH/font sizing
            # stayed pinned at their ship-one-size values regardless, which
            # is exactly what ships them now too (scale_for_dpi still
            # always returns 1.0). Calling it here just wires up the badge
            # half: cheap when the monitor hasn't changed (the dpi==
            # _active_dpi[0] check inside returns immediately), and this is
            # the one place that already runs every tick and always has
            # the real foreground window handle on hand.
            if llm_hwnd:
                apply_scale_for_window(llm_hwnd)
                # REVERTED 2026-07-26: shipped live, caused a real regression
                # Antonio caught immediately -- several of the card's
                # wraplength values are "POPUP_WIDTH minus a FIXED pixel
                # count" (room reserved for a button/badge), tuned for the
                # unshrunk 560px card. Shrinking POPUP_WIDTH without also
                # scaling those fixed subtractions collapsed the remaining
                # wrap width to near-nothing, wrapping text one word per
                # line. text_scale/_fs() (SuggestionPopup) has the same
                # problem in reverse -- it scales font size but nothing
                # reads it back into those fixed subtractions either. Do
                # not re-enable until every "POPUP_WIDTH - <fixed number>"
                # site in SuggestionPopup is audited and fixed to scale
                # proportionally too, and it's been verified with a REAL
                # screenshot of the built card, not just debug.log numbers.
                # clamp_popup_width_to_host(llm_hwnd)

            # Our own web windows (review card / settings / onboarding) run as
            # separate processes that share this exe's name. When one of them
            # is the foreground window, do NOT re-evaluate/hide the badge — it
            # belongs to the AI chat underneath, and the card floating on top
            # must not count as "focus left the text box." Without this, the
            # review card appearing tore the badge down mid-interaction
            # (2026-07-22: "the UI just disappears and shows the drag icon").
            if process_name == _OWN_EXE_NAME:
                # Keepalive while the REVIEW CARD is open: a compress is most
                # likely exactly when no typing ticks fire, so without this
                # the 30s idle unload would tear the model down while the
                # user reads their fixes. Scoped to an actually-open card
                # (audit 2026-07-25): "any window of ours is foreground" also
                # covered SETTINGS, where the unconditional bump kept the
                # warm worker pinned forever -- blocking the 30s auto-unload
                # AND the Remove-from-device button (rmtree vs the worker's
                # live mmap) for anyone sitting in the AI page.
                card_is_open = popup.window is not None or (
                    warmcard is not None and warmcard.open)
                if card_is_open:
                    try:
                        local_model.note_activity()
                    except Exception:
                        pass
                continue

            # While the web review card is open it's the UI — keep the badge
            # hidden so it doesn't float on top of the card's header.
            if _review_card_open[0]:
                badge.root.after(0, badge.hide)
                try:
                    local_model.note_activity()
                except Exception:
                    pass
                continue

            app_label = app_label_for(process_name, llm_hwnd)

            # Real scope change 2026-07-21: Grammarly-style universal
            # coverage. Read the focused control FIRST, then decide whether
            # to activate, because "is there an editable text field here" is
            # the real signal, not "is this one of two hard-coded apps".
            # Measured: Chrome, Edge and native Windows apps all expose the
            # field's real text this way. Known LLM apps (Claude's Electron
            # build exposes nothing) still get the keystroke fallback.
            # Terminal input-line extraction (2026-07-26) now happens
            # INSIDE get_focused_text() itself, not here -- see its
            # docstring for why: Apply independently calls that same
            # function fresh to capture expected_old_text, and patching
            # only this one call site left Apply still reading the
            # terminal's whole unfiltered buffer. Confirmed working via a
            # since-removed codepoint diagnostic (found the real prompt
            # marker is "❯ ", not the originally-guessed ASCII "> ").
            text, control = get_focused_text()

            # Real ask 2026-07-26 (Antonio, direct repro: renaming a chat in
            # Claude Code's sidebar showed the badge there too -- "make sure
            # it stays in one area... the chat box... consistently").
            # get_focused_text() above returns whatever control has focus
            # ANYWHERE in the app's window, with no idea whether that's the
            # real composer or some other editable field (a rename box, a
            # search/filter input) -- app_label only identifies WHICH app,
            # never WHICH control within it. Claude's real composer
            # consistently shows a CSS class containing "ProseMirror" in
            # this exact watch loop's own "badge rect source" diagnostic
            # (checked directly against debug.log); nothing else observed
            # in this app's window has ever carried that class. Checking
            # ClassName, not Name, for the same privacy reason that
            # diagnostic already avoids Name (some apps mirror the typed
            # value into Name -- see its own comment).
            if app_label == "Claude" and control is not None:
                try:
                    is_real_composer = "ProseMirror" in (control.ClassName or "")
                except Exception:
                    # FLIPPED to fail-closed (real leak caught live: a
                    # TreeItemControl -- a sidebar row -- got a badge rect
                    # anyway, right after this check first shipped). The
                    # real composer's ClassName read has never once failed
                    # anywhere in this session's logs, so a read failure
                    # here is itself evidence this ISN'T the composer, not
                    # an ambiguous case to guess generously on.
                    is_real_composer = False
                if not is_real_composer:
                    text, control = None, None

            # Real bug found 2026-07-20: right after switching into Claude,
            # UIA's "focused" element can briefly be some internal
            # route/URL-bearing node, not the actual chat box, this would
            # have shown a token count for a URL instead of your prompt.
            # Treat anything URL-shaped as not a real read.
            if text and URL_LIKE_PATTERN.match(text.strip()):
                # Privacy (real ask 2026-07-22): do NOT log the URL itself,
                # that's the user's browsing. Just note it once, not per tick.
                if not url_ignored_logged[0]:
                    log("focused value was URL-shaped, ignoring (not a chat box)")
                    url_ignored_logged[0] = True
                text = None
                control = None
            else:
                url_ignored_logged[0] = False

            # An empty box still reports its placeholder through UIA. Reading
            # it made Comprsly analyse and even AI-compress "Type / for
            # commands". See PLACEHOLDER_TEXTS. confirmed_empty marks this
            # specific case: not "UIA couldn't read this control" but "UIA
            # read it just fine and it's genuinely empty," a distinction
            # the next block depends on.
            confirmed_empty = False
            if text and is_placeholder_text(text):
                if last_placeholder_logged[0] != text:
                    log(f"ignoring placeholder text {text.strip()!r}, the box is empty")
                    last_placeholder_logged[0] = text
                text = None
                control = None
                confirmed_empty = True

            # Ground truth from the field itself, when the app exposes it.
            # This path is immune to the dictation problem, since it reads
            # what's really there rather than reconstructing keystrokes.
            uia_readable = bool(text)
            text_source = "uia" if uia_readable else None

            # Decide whether Comprsly should be active here at all (real
            # direction 2026-07-25: LLM apps ONLY, see the DEFAULT_SETTINGS
            # note on cat_ai_chat). app_label is app_label_for's answer to
            # "what app/site does this text box actually live in" -- non-None
            # only for a known LLM app or a recognized LLM website tab, never
            # for a generic browser field, Teams/Slack/Word/etc. Known LLM
            # apps stay supported even when UIA exposes no text (Claude's
            # Electron build), via the keystroke fallback -- that's why this
            # doesn't also require uia_readable.
            active = app_label is not None and bool(APP_SETTINGS.get("cat_ai_chat"))

            if not active:
                if last_context_label != process_name:
                    log(f"context: no editable text field in {process_name}, staying hidden")
                    last_context_label = process_name
                    # Diagnostic for browser tabs only (real ask 2026-07-25:
                    # Gemini's Chrome SIDE PANEL never shows the badge). A
                    # side panel is an overlay docked next to a tab -- it
                    # never repaints the top-level window's title, which is
                    # the ONLY signal app_label_for has, so no title hint
                    # could ever catch it, guessing wouldn't fix it. Same
                    # policy as the unverified Perplexity/Copilot hints
                    # above: log the focused control's CLASS and accessible
                    # NAME (structural UI labels, never typed content --
                    # length-capped via _safe_diag_name as a backstop, see
                    # its own comment: this assumption was caught live
                    # being WRONG for at least one real app) so the real
                    # composer identity can be read from debug.log instead
                    # of guessed at twice.
                    if process_name in BROWSER_PROCESS_NAMES:
                        try:
                            diag_ctrl = auto.GetFocusedControl()
                            if diag_ctrl is not None:
                                log(f"unrecognized browser tab, focused control: "
                                    f"{diag_ctrl.ControlTypeName}/{diag_ctrl.ClassName!r} "
                                    f"name={_safe_diag_name(diag_ctrl.Name)!r}")
                                # Real ask 2026-07-25: the single focused-control
                                # line above was already "waiting on real
                                # debug.log evidence" for the Gemini side panel
                                # specifically, with none ever landing -- one
                                # data point wasn't enough to fix it from. A
                                # side panel is its own docked pane, so the
                                # signal (if there is one) is more likely a
                                # few levels UP from the composer, in whatever
                                # wraps it, not the composer itself. Walking
                                # ancestors here means the NEXT time this
                                # fires while the side panel is genuinely
                                # open, debug.log has enough to actually
                                # diagnose it instead of one more guess.
                                anc = diag_ctrl
                                for depth in range(1, 6):
                                    try:
                                        anc = anc.GetParentControl()
                                    except Exception:
                                        break
                                    if anc is None:
                                        break
                                    try:
                                        log(f"  ancestor[{depth}]: "
                                            f"{anc.ControlTypeName}/{anc.ClassName!r} "
                                            f"name={_safe_diag_name(anc.Name)!r}")
                                    except Exception:
                                        break
                        except Exception:
                            pass
                _typed_buffer_active[0] = False
                badge.root.after(0, badge.hide)
                popup.root.after(0, popup.dismiss)
                last_text = None
                continue

            context_label = app_label or process_name
            last_context_label = context_label
            if last_real_llm_label != context_label:
                # Debounced the same way rect changes already are (see
                # pending_rect_tuple's own comment) -- a context switch
                # only actually takes effect once the SAME new label has
                # been seen on 2 consecutive ticks, so a one-tick focus
                # flicker back to the real app before this confirms never
                # resets locked_badge_rect at all, and the existing rect-
                # debounce naturally protects the display in the meantime
                # (a wildly different unconfirmed context's rect won't be
                # "close enough" to what's already locked, so the old,
                # correct position just keeps showing).
                if context_label == pending_context_label[0]:
                    pending_context_count[0] += 1
                else:
                    pending_context_label[0] = context_label
                    pending_context_count[0] = 1
                if pending_context_count[0] >= 2:
                    log(f"context: entered {context_label}")
                    last_real_llm_label = context_label
                    reset_typed_buffer()
                    locked_badge_rect = None
                    pending_context_label[0] = None
                    pending_context_count[0] = 0
            else:
                pending_context_label[0] = None
                pending_context_count[0] = 0

            # Diagnostic dump (see last_claude_diag_key's own comment) --
            # once per distinct composer rect, not every tick, so a real
            # session doesn't get spammed by this every 0.7s.
            #
            # Real bug found live 2026-07-31 (crashed every single tick,
            # "cannot access local variable 'raw_rect'"): raw_rect isn't
            # assigned yet at this point in the function on the path that
            # reaches here -- it's a LOCAL variable first bound further
            # down, so referencing it here before that assignment ever
            # runs is a hard UnboundLocalError, not a None value to guard
            # against. Reads control's OWN rect directly instead; this
            # block never needed raw_rect's corrections/widening anyway,
            # just something stable to dedupe repeated dumps on.
            if control is not None and (app_label == "Claude" or app_label in BADGE_WIDEN_RIGHT_SITES):
                try:
                    _diag_r = control.BoundingRectangle
                    diag_key = (_diag_r.left, _diag_r.top, _diag_r.right, _diag_r.bottom)
                except Exception:
                    diag_key = None
                if diag_key is not None and diag_key != last_claude_diag_key[0]:
                    last_claude_diag_key[0] = diag_key
                    if app_label == "Claude":
                        _composer_diag_dump(control, "claude", depth=3)
                    else:
                        # Real bug found live 2026-07-31 (Antonio,
                        # screenshot: badge floating disconnected on a
                        # TALLER/expanded ChatGPT composer state --
                        # base=(842,640,1804,799), 159px tall vs the
                        # working single-line case's 56px -- "no row
                        # found" within the normal 6-level ancestor walk).
                        # Deeper dump than Claude's (10, not 3) since the
                        # working hypothesis is this taller state nests
                        # the toolbar further away, not just gates it out.
                        _composer_diag_dump(control, "widen-right", depth=10)
            # The keystroke buffer is only needed where UIA can't read the
            # field (Claude). Tracking it elsewhere is pointless work.
            _typed_buffer_active[0] = not uia_readable

            # Accessibility gave us nothing (confirmed real case: Claude
            # desktop's own editor exposes no Name/Value/TextPattern at
            # all): fall back to the live keystroke-reconstructed buffer
            # instead of reading the box. Real bug found 2026-07-20: the
            # old clipboard-read approach visibly select-all-flashed the
            # box, repeatedly, every time it ran. This never touches or
            # selects anything, so there's nothing to flash.
            #
            # Real bug found 2026-07-21: confirmed_empty used to collapse
            # into this exact same "not uia_readable" branch, so proving
            # the box was empty (via its placeholder) fell through to the
            # SAME buffer fallback used when UIA can't read the control at
            # all. The buffer is a keystroke reconstruction with no idea
            # Send just cleared the real box (Send isn't itself a keystroke
            # the reconstruction understands), so it kept serving an old
            # message's text as live, sometimes several messages later.
            # Antonio saw this as the card confidently offering to compress
            # a box that was visibly empty on screen. Positive confirmation
            # beats a reconstruction that can only ever guess: trust it,
            # and reset the buffer so it can't serve this same stale
            # content again on the next tick.
            if confirmed_empty:
                reset_typed_buffer()
            elif not uia_readable:
                # Real bug found live 2026-07-27 (Antonio, direct repro:
                # Apply typed text he'd written in a DIFFERENT terminal
                # window into this one): the keystroke buffer is a single
                # GLOBAL capture from the low-level keyboard hook, with no
                # idea which WINDOW the keys landed in. Its reset only
                # fires on an app-level context change (context_label,
                # e.g. leaving a terminal for Chrome), not when switching
                # between TWO terminal windows that both report the same
                # context_label -- so content typed in one terminal
                # window leaked into another terminal window's
                # suggestions and got typed there by Apply. Terminals now
                # have a real, reliable ground-truth read for every case
                # that matters (_extract_terminal_input_line's UIA
                # line-navigation fix, same day) -- the buffer fallback
                # exists for apps that expose NOTHING via UIA at all
                # (Claude's Electron build), which terminals aren't.
                # Excluding terminals here means an unreadable terminal
                # tick now correctly shows nothing, same fail-safe
                # philosophy as everywhere else in the terminal path,
                # instead of risking cross-window content leakage.
                if process_name not in TERMINAL_HOST_PROCESSES:
                    text = get_typed_buffer() or None
                    text_source = "buffer"

            if not text:
                badge.root.after(0, badge.hide)
                popup.root.after(0, popup.dismiss)
                last_text = None
                locked_badge_rect = None  # next message starts a fresh lock
                continue

            # Predictive model lifecycle (real ask 2026-07-25, live install:
            # "why is this running at 1.4 GB"): the text CHANGING since last
            # tick means the user is actively typing a prompt in an LLM app --
            # the strongest possible "a compress may be coming" signal, and it
            # arrives tens of seconds before any compress click. Start the
            # background load on it (no-op once warm) and count it as model
            # use, so the 30s idle unload measures "stopped typing", not
            # "stopped compressing". Typing stays smooth because the load
            # runs in the BELOW_NORMAL-priority worker, off this process.
            # last_text is not None: the previous tick ALSO saw text in this
            # box, so a change means genuine typing. Without that condition
            # (audit 2026-07-25), merely alt-tabbing back to an LLM window
            # with an untouched draft fired a None -> "whole draft"
            # transition and loaded ~1GB because the user glanced at the
            # window. Cost: the very first keystroke tick doesn't trigger --
            # the second one does, 0.7s later.
            if last_text is not None and text != last_text:
                try:
                    local_model.note_activity()
                    if (APP_SETTINGS.get("ai_enabled")
                            and not local_model.is_loaded()
                            and time.time() - last_prewarm_try[0] >= 10):
                        last_prewarm_try[0] = time.time()
                        local_model.prewarm_via_subprocess()
                except Exception:
                    pass

            # We're in a known LLM app with real text: the badge shows NO
            # MATTER WHAT, this was the 2026-07-20 fix, never conditional
            # on whether there's a suggestion, only on whether there's text.
            # Real pivot 2026-07-20, continued: rules-first, AI-second.
            # analyze() is regex-based and cheap enough to run every tick,
            # so the badge can show a real live count instead of a vague
            # "ready" marker, no model load needed just to know that.
            # Real ask 2026-07-21: "I want it to be clickable whenever."
            # The badge used to be inert below MIN_TEXT_LENGTH_TO_ANALYZE
            # characters, so clicking it did nothing at all with no
            # explanation, which just reads as broken. Grammarly's own icon
            # always opens something. analyze() is regex plus a cached
            # spell-check, 12ms on a clean prompt, so running it on short
            # text costs nothing worth protecting.
            is_long_enough = len(text.strip()) >= MIN_TEXT_LENGTH_TO_ANALYZE
            analysis = suggestion_engine.analyze(text)
            suggestion_count = len(analysis["suggestions"]) if analysis else 0

            # Real bug found 2026-07-21: locked_badge_rect used to be
            # checked FIRST and, once set, reused for the rest of the
            # message no matter what, so a real page reflow (a longer
            # greeting, the "ChatGPT can make mistakes" disclaimer coming
            # and going, the box itself growing as you type more) left the
            # badge glued to where the box USED to be, not where it
            # actually is now. Two screenshots of the visually identical
            # ChatGPT state landed the badge in two different spots,
            # confirming it, since nothing about the box itself had
            # changed, only how stale the lock had gotten. The lock was
            # built to stop CLICK-POSITION jitter (re-anchoring to wherever
            # you last clicked mid-message), not to freeze a real
            # control's own bounding rect, which is trustworthy to re-read
            # every tick. So: read the live control rect first, every
            # time, and only fall back to the lock (or the caret/click
            # guesses) when there's no live control available this tick.
            try:
                raw_rect = control.BoundingRectangle if control is not None else None
            except Exception:
                raw_rect = None

            # Reject a degenerate rect (real bug 2026-07-22: a control briefly
            # reported (0,0,0,0), which would have parked the badge at the
            # top-left screen corner). A real text box always has a positive
            # width and height; anything else falls through to the last good
            # position instead of jumping to the origin.
            if raw_rect is not None and (
                    raw_rect.right - raw_rect.left <= 0
                    or raw_rect.bottom - raw_rect.top <= 0):
                raw_rect = None

            # Real ask 2026-07-26 (Antonio, screenshot of the actual
            # bordered input box): "why don't we just have it sit in the
            # box... sticks to the edge of the box". Windows Terminal DOES
            # expose a real accessible control ("TermControl"), confirmed
            # live -- but its bounding rect covers the WHOLE terminal pane,
            # not just the small bordered input area the CLI draws at the
            # bottom (that box is drawn by the CLI itself inside the same
            # character grid, not a separate UIA element). That's why the
            # badge was landing vertically centred in the entire pane
            # instead of on the input line.
            #
            # PERMANENTLY OUT OF SCOPE, 2026-08-03 (Antonio, direct,
            # explicit, repeated: only the browser/app, never this code
            # path). _find_terminal_input_line_rect is left defined but
            # NOT CALLED, and must not be wired back in again without
            # Antonio explicitly asking to work on the terminal/CLI
            # positioning specifically, by name, in so many words -- a
            # general "fix the badge" or "fix Claude Code" request does
            # NOT authorize touching this block. Plain blind slice only.
            #
            # REOPENED 2026-11-25 by Antonio, by name: "fix the terminal badge
            # and make sure that is the same on all of them... it should not
            # be overlapping the main text ever... it live within the line".
            # See _terminal_badge_rect for the rule. The blind slice below
            # stays as the last fallback only.
            if raw_rect is not None and process_name in TERMINAL_HOST_PROCESSES:
                line_rect = _terminal_badge_rect(control, process_name, llm_hwnd, raw_rect)
                if line_rect is not None:
                    raw_rect = line_rect
                else:
                    raw_rect = _SimpleRect(
                        raw_rect.left, raw_rect.bottom - TERMINAL_INPUT_BOX_HEIGHT_GUESS,
                        raw_rect.right, raw_rect.bottom,
                    )

            # Real bug found live 2026-07-25 (Antonio, screenshot: badge
            # floating in an odd spot -- "everywhere else is fine but on
            # the edge like this it is not good" -- on Claude's own
            # "Design"/canvas mode). debug.log showed why: this control's
            # rect comes back with left=-1548, hundreds of px off every
            # real monitor, then the ancestor-inset walk in
            # _input_box_left (built for ChatGPT's '+' button) saw a
            # nearby ancestor and "corrected" it to an even more negative
            # -1596 -- that heuristic's 30..150px band assumes the base
            # number is already a real screen coordinate, which it never
            # was here.
            #
            # First fix attempt checked this against the combined bounds of
            # every connected monitor (SM_XVIRTUALSCREEN etc.) -- wrong on
            # THIS machine specifically (confirmed via GetSystemMetrics
            # live, not assumed): two monitors, one extending to
            # SM_XVIRTUALSCREEN=-2256, so the whole virtual desktop already
            # covers deeply negative x. The bogus rect (-1596..-453) sits
            # entirely inside that combined span, so a "somewhere on some
            # monitor" test never rejected it -- confirmed still broken by
            # reinstalling and reading the fresh debug.log, not by
            # reasoning about it. The rect isn't garbage because it's off
            # every monitor, it's garbage because it's nowhere near the ONE
            # browser window this control supposedly belongs to -- checked
            # against that instead, with a generous margin (legitimate UIA
            # rects can exceed their own window's bounds a little from
            # scroll/render quirks, this is only meant to catch "hundreds
            # of px away", not "a normal few px off").
            if raw_rect is not None:
                pre_reject_rect = (raw_rect.left, raw_rect.top, raw_rect.right, raw_rect.bottom)
                win_rect = wintypes.RECT()
                got_win_rect = ctypes.windll.user32.GetWindowRect(llm_hwnd, ctypes.byref(win_rect))
                if got_win_rect:
                    margin = 200
                    if (raw_rect.right <= win_rect.left - margin
                            or raw_rect.left >= win_rect.right + margin
                            or raw_rect.bottom <= win_rect.top - margin
                            or raw_rect.top >= win_rect.bottom + margin):
                        raw_rect = None
                else:
                    # Can't verify this rect against anything -- same
                    # fail-safe the degenerate-size check above already
                    # applies (distrust rather than assume good), instead
                    # of the previous behaviour of silently trusting
                    # whatever raw_rect already was whenever this call
                    # happened to fail.
                    raw_rect = None
                diag = (pre_reject_rect,
                        (win_rect.left, win_rect.top, win_rect.right, win_rect.bottom) if got_win_rect else None,
                        raw_rect is None)
                if diag != last_reject_diag[0]:
                    last_reject_diag[0] = diag
                    log(f"off-screen-rect check: control_rect={pre_reject_rect} "
                        f"hwnd={llm_hwnd} got_window_rect={got_win_rect} "
                        f"window_rect={diag[1]} rejected={diag[2]}")

            # A whole-page control is not a real input box, so never anchor
            # to it (real bug confirmed in debug.log 2026-07-22, Google New
            # Tab): its focused control alternates every 0.7s tick between
            # the real 'Ask Google' ComboBox (rect 557..1520) and the
            # full-page 'New Tab' DocumentControl (rect 0..2256). Anchoring
            # to the latter, whose left is 0 and which spans the entire
            # page, threw the badge to a random far-left, vertically-centred
            # spot. Rejecting it here means only the real box ever drives
            # the badge; a page-level tick falls through to the last good
            # box position (locked_badge_rect) instead of jumping.
            page_level = False
            if raw_rect is not None and control is not None:
                try:
                    ctype = control.ControlTypeName
                except Exception:
                    ctype = ""
                if ctype == "DocumentControl":
                    page_level = True
                elif ctype in _NEVER_A_COMPOSER_CONTROL_TYPES:
                    # Real bug 2026-07-30 (see _NEVER_A_COMPOSER_CONTROL_TYPES):
                    # app_label only says WHICH SITE this is (a domain or
                    # title match), never WHAT'S ACTUALLY FOCUSED on it -- a
                    # slider thumb on an otherwise-recognized LLM domain is
                    # exactly as wrong an anchor as the whole-page
                    # DocumentControl case this reuses, so it's rejected the
                    # same way: falls through to the last good box position
                    # instead of jumping to whatever unrelated control just
                    # grabbed focus.
                    page_level = True
                    if ctype != last_rejected_ctype[0]:
                        last_rejected_ctype[0] = ctype
                        log(f"focused control is a {ctype}, not a real chat "
                            f"composer, ignoring it (site is recognized, but "
                            f"this control isn't the chat box)")
                else:
                    last_rejected_ctype[0] = None
                    # Backstop for any other control type that happens to
                    # span nearly the whole screen: still not a real box.
                    area = monitor_work_area((raw_rect.left + raw_rect.right) // 2,
                                             (raw_rect.top + raw_rect.bottom) // 2)
                    if area is not None:
                        aw, ah = area[2] - area[0], area[3] - area[1]
                        if (raw_rect.right - raw_rect.left) >= aw * 0.9 and \
                           (raw_rect.bottom - raw_rect.top) >= ah * 0.6:
                            page_level = True

            # page_level here specifically means "a real control WAS found,
            # but it's explicitly not a composer" (DocumentControl, or
            # _NEVER_A_COMPOSER_CONTROL_TYPES like SliderControl -- see
            # where page_level gets set above). Deliberately NOT keyed on
            # raw_rect being None too: that also covers apps with NO
            # accessible control at all (Claude's Electron composer, a
            # terminal), where the fallback-guess branch below is the
            # correct PERMANENT strategy, not a blip to eventually give up
            # on -- only the "found a control, it's the wrong kind" case
            # should ever count toward hiding.
            if page_level:
                no_real_composer_ticks[0] += 1
            else:
                no_real_composer_ticks[0] = 0
            # ~4 ticks at the ~0.7s loop interval is long enough that a
            # single-tick misread (the scenario the locked-rect fallback
            # exists for) never trips it, short enough that a real
            # non-composer view of a recognized app doesn't leave a stale
            # or guessed badge sitting there for long.
            NO_COMPOSER_HIDE_AFTER_TICKS = 4

            if raw_rect is not None and not page_level:
                # Correct for controls whose OWN rect is inset from the
                # visual box (ChatGPT's '+'-button pill, see
                # _input_box_left, confirmed 2026-07-22). Cached on the raw
                # left so the parent walk isn't re-run every 0.7s tick when
                # nothing has moved.
                raw_left = raw_rect.left
                # Real bug found live 2026-08-03 (Antonio, screenshot: an
                # artifact panel opened alongside Claude's chat, badge
                # jumped deep into the artifact preview on the right,
                # nowhere near the now-narrowed chat composer). Root cause,
                # confirmed via debug.log: the artifact panel narrows the
                # composer horizontally (740-1472 -> 114-847) but its
                # BOTTOM edge coincidentally stayed at the exact same y
                # (941) -- every toolbar-row cache below this point used to
                # key ONLY on raw_bottom (or, for the same-row cases, only
                # raw_right), so they served back the stale result computed
                # for the OLD, wide box (toolbar_left=1237) rather than
                # recomputing for the new narrow one, and 1237 falls well
                # outside the new box entirely. The full raw rect is the
                # only thing that's actually safe to key these on -- ANY
                # geometry change, not just a change in whichever single
                # edge a given cache happened to be keyed on, must
                # invalidate them.
                #
                # CONFIRMED CORRECT (Antonio, live, 2026-08-03: "that is
                # fixed too theres no reasons to fix this one either...
                # you can now confidently lock all of them"). The
                # artifact side-panel composer this fix targeted needed
                # no further, composer-specific work on top of it.
                raw_geom_key = (raw_rect.left, raw_rect.top, raw_rect.right, raw_rect.bottom)
                if raw_left == box_left_cache_key[0]:
                    box_left = box_left_cache_val[0]
                else:
                    box_left = _input_box_left(control)
                    if box_left is None:
                        box_left = raw_left
                    box_left_cache_key[0] = raw_left
                    box_left_cache_val[0] = box_left
                raw_right = raw_rect.right
                toolbar_left = None
                toolbar_row_top = None
                toolbar_row_bottom = None
                toolbar_extra_gap = 0
                is_code_review = False
                is_home_row = False
                if app_label in BADGE_WIDEN_RIGHT_SITES:
                    if raw_right == box_right_cache_key[0]:
                        box_right = box_right_cache_val[0]
                    else:
                        box_right = _input_box_right(control, raw_right)
                        box_right_cache_key[0] = raw_right
                        box_right_cache_val[0] = box_right
                    if raw_geom_key == toolbar_left_cache_key[0]:
                        toolbar_result = toolbar_left_cache_val[0]
                    else:
                        toolbar_result = _toolbar_cluster_left(control, raw_right)
                        toolbar_left_cache_key[0] = raw_geom_key
                        toolbar_left_cache_val[0] = toolbar_result
                    # (left_x, row_top, row_bottom), or None -- see
                    # _toolbar_cluster_left's docstring.
                    if toolbar_result is not None:
                        toolbar_left, toolbar_row_top, toolbar_row_bottom = toolbar_result
                else:
                    box_right = raw_right
                raw_bottom = raw_rect.bottom
                if app_label in BADGE_WIDEN_DOWN_SITES:
                    if raw_bottom == box_bottom_cache_key[0]:
                        box_bottom = box_bottom_cache_val[0]
                    else:
                        box_bottom = _input_box_bottom(control, raw_bottom)
                        box_bottom_cache_key[0] = raw_bottom
                        box_bottom_cache_val[0] = box_bottom
                else:
                    box_bottom = raw_bottom
                # Real ask 2026-08-03 (Antonio, live, Gemini's Home
                # composer: "when you add multiple lines it should stay
                # and stick right at the area of where its at next to
                # Flash"). Symmetric to ChatGPT's own same-row-then-below-
                # row fallback (see BADGE_TOOLBAR_BELOW_SITES's own
                # comment for that real, confirmed-live root cause: the
                # composer's toolbar drops to its OWN row below the text
                # once it grows past one line, so _toolbar_cluster_left's
                # same-row gates correctly stop matching). Gemini's short-
                # box case is already correct via BADGE_WIDEN_RIGHT_SITES
                # above and stays untouched; this only fires as a fallback
                # when that same-row detector found nothing at all, so it
                # can't affect the already-tuned single-line position.
                if app_label == "Gemini" and toolbar_left is None:
                    if raw_geom_key == gemini_below_cache_key[0]:
                        gemini_below_result = gemini_below_cache_val[0]
                    else:
                        gemini_below_result = _below_toolbar_cluster_left(control, raw_bottom)
                        gemini_below_cache_key[0] = raw_geom_key
                        gemini_below_cache_val[0] = gemini_below_result
                    if gemini_below_result is not None:
                        toolbar_left, toolbar_row_top, toolbar_row_bottom = gemini_below_result
                        if toolbar_row_bottom is not None:
                            box_bottom = max(box_bottom, toolbar_row_bottom)
                if app_label in BADGE_TOOLBAR_BELOW_SITES:
                    below_toolbar_result = None
                    # Real bug found live 2026-08-02 (Antonio, screenshot +
                    # live measurement: Claude's "Code" mode, claude.ai/code
                    # -- badge floating disconnected near an unrelated
                    # "Select repo" row, nowhere near the real bottom
                    # toolbar). Root cause: _claude_inline_send_button used
                    # to be tried FIRST for every "Claude" context, and Code
                    # mode happens to have its OWN unrelated button also
                    # literally named "Send" sitting well away from the
                    # actual composer toolbar (confirmed via a live DOM
                    # measurement -- it even coincidentally matches every
                    # other signal that function checks: name, right-edge
                    # proximity, vertical centering on the textbox). Rather
                    # than guess a narrower exclusion rule against a single
                    # example, the priority is inverted instead: the
                    # below-row detector is well-validated across ChatGPT/
                    # Gemini/Claude plain-chat and confirmed via the same
                    # live measurement to correctly find Code mode's REAL
                    # toolbar (Sonnet 5/Effort/Usage, all real ButtonControls
                    # in the right position) -- so it goes first now, and
                    # _claude_inline_send_button (see its own docstring)
                    # becomes the fallback for the narrower case it was
                    # actually built for: a genuine Cowork/project layout
                    # where the below-row walk finds nothing at all (its own
                    # docstring already says its real toolbar sits several
                    # levels down a separate branch the below-row walk
                    # doesn't reach), not a layout the below-row walk
                    # already handles correctly.
                    if raw_geom_key == below_toolbar_left_cache_key[0]:
                        below_toolbar_result = below_toolbar_left_cache_val[0]
                    else:
                        below_toolbar_result = _below_toolbar_cluster_left(control, raw_bottom)
                        below_toolbar_left_cache_key[0] = raw_geom_key
                        below_toolbar_left_cache_val[0] = below_toolbar_result
                        if below_toolbar_result is None:
                            below_toolbar_result = last_good_below_toolbar_result.get(app_label)
                        else:
                            last_good_below_toolbar_result[app_label] = below_toolbar_result
                    # Real bug found live 2026-08-02 (Antonio, screenshots:
                    # ChatGPT badge landing well below a short, single-
                    # line composer, reliably every time). Root-caused
                    # via a live getBoundingClientRect() measurement in
                    # the actual page, not another guess: ChatGPT's
                    # toolbar (Add files / dictation / send) sits LEVEL
                    # with the text row for a single-line message
                    # (textbox y=395-437, toolbar y=391-427 -- nearly
                    # identical, not below at all), the exact SAME-ROW
                    # shape _toolbar_cluster_left was built for (Gemini).
                    # The 2026-08-01 fix that moved ChatGPT into this
                    # below-row family was measuring a genuinely
                    # DIFFERENT, correct case (a multi-line box, where
                    # the toolbar really does drop to its own row below)
                    # but that measurement never covered the single-line
                    # case, which regressed as a side effect -- it used
                    # to work fine back when ChatGPT was still in
                    # BADGE_WIDEN_RIGHT_SITES. Rather than re-litigate
                    # which family ChatGPT "really" belongs to (the
                    # honest answer is both, depending on line count),
                    # fall back to the same-row detector when the
                    # below-row one finds nothing -- each layout gets
                    # matched by whichever detector actually finds it.
                    if below_toolbar_result is None and app_label == "ChatGPT":
                        below_toolbar_result = _toolbar_cluster_left(control, raw_right)
                        if below_toolbar_result is not None:
                            last_good_below_toolbar_result[app_label] = below_toolbar_result
                    # CONFIRMED CORRECT (Antonio, live, 2026-08-02: "now
                    # we are done with chatgpt for now... lock the
                    # position of the chatgpt badge down"). Do not
                    # retune the same_row tolerance, this fallback, or
                    # the last-good cache above without a new real ask.
                    # BADGE_TOOLBAR_GAP_OVERRIDES compensates for
                    # Claude's plain-chat "Opus 4.8" label being
                    # invisible to UIA (see that constant's own
                    # comment) -- only relevant to THIS below-row path.
                    # The Cowork inline Send button below is a real,
                    # precisely-located control with nothing invisible
                    # in front of it, so it must NOT get this same
                    # extra push or it'd land too far left.
                    if below_toolbar_result is not None:
                        toolbar_extra_gap = BADGE_TOOLBAR_GAP_OVERRIDES.get(app_label, 0)
                        if app_label == "Claude":
                            if raw_geom_key == claude_code_review_cache_key[0]:
                                is_code_review = claude_code_review_cache_val[0]
                            else:
                                is_code_review = _claude_code_review_row(control)
                                claude_code_review_cache_key[0] = raw_geom_key
                                claude_code_review_cache_val[0] = is_code_review
                            if is_code_review:
                                toolbar_extra_gap = CLAUDE_CODE_REVIEW_GAP
                            if raw_geom_key == claude_home_row_cache_key[0]:
                                is_home_row = claude_home_row_cache_val[0]
                            else:
                                is_home_row = _claude_home_row(control)
                                claude_home_row_cache_key[0] = raw_geom_key
                                claude_home_row_cache_val[0] = is_home_row
                            if is_home_row:
                                toolbar_extra_gap = CLAUDE_HOME_ROW_GAP
                        elif app_label == "Perplexity":
                            if raw_geom_key == perplexity_long_model_cache_key[0]:
                                is_long_model = perplexity_long_model_cache_val[0]
                            else:
                                is_long_model = _perplexity_long_model_row(control)
                                perplexity_long_model_cache_key[0] = raw_geom_key
                                perplexity_long_model_cache_val[0] = is_long_model
                            if is_long_model:
                                # Real ask 2026-08-03 (Antonio, live, right
                                # after confirming the "Model" button's
                                # real text width is unmeasurable via UIA):
                                # "put it to the right of the computer
                                # badge rather than next to the prompt
                                # names because they can expand and shrink
                                # based on the names." Anchors off
                                # "Computer" instead, whose own label never
                                # changes -- see _perplexity_computer_
                                # anchor's docstring. Solves for the
                                # toolbar_left value that makes
                                # _position_for's own bx = toolbar_left -
                                # gap - BADGE_ICON_SIZE formula land
                                # exactly at computer_right + a small
                                # buffer, instead of restructuring that
                                # shared formula for one site.
                                if raw_geom_key == perplexity_computer_anchor_cache_key[0]:
                                    computer_right = perplexity_computer_anchor_cache_val[0]
                                else:
                                    computer_right = _perplexity_computer_anchor(control)
                                    perplexity_computer_anchor_cache_key[0] = raw_geom_key
                                    perplexity_computer_anchor_cache_val[0] = computer_right
                                log(f"perplexity_computer_anchor: computer_right={computer_right}")
                                if computer_right is not None:
                                    toolbar_left = (computer_right + PERPLEXITY_COMPUTER_ANCHOR_GAP
                                                     + BADGE_TOOLBAR_GAP + BADGE_ICON_SIZE)
                                    toolbar_extra_gap = 0
                                else:
                                    toolbar_extra_gap = PERPLEXITY_LONG_MODEL_GAP
                    # Fallback, not first choice (see the long comment
                    # above this block for why the swap happened
                    # 2026-08-02): only for Claude, only when the
                    # well-validated below-row walk truly found nothing --
                    # the narrow Cowork/project layout _claude_inline_
                    # send_button's own docstring describes, whose real
                    # toolbar the below-row walk genuinely can't reach.
                    if below_toolbar_result is None and app_label == "Claude":
                        if raw_geom_key == claude_send_btn_cache_key[0]:
                            below_toolbar_result = claude_send_btn_cache_val[0]
                        else:
                            below_toolbar_result = _claude_inline_send_button(control)
                            claude_send_btn_cache_key[0] = raw_geom_key
                            claude_send_btn_cache_val[0] = below_toolbar_result
                        if below_toolbar_result is not None:
                            toolbar_extra_gap = CLAUDE_INLINE_SEND_EXTRA_GAP
                    # Real bug found live 2026-08-03 (Antonio, screenshot:
                    # badge floating too high, overlapping "High", on the
                    # top-level Home/Cowork "How can I help you today?"
                    # composer). Root cause: that composer's text area and
                    # its toolbar (Opus 4.8/Sonnet 5, effort, mic) sit in
                    # the SAME row, not stacked -- a genuinely different
                    # shape from every other Claude layout handled above,
                    # which are all below-row. below_toolbar_cluster_left's
                    # delta gate requires the toolbar to sit at least 20px
                    # BELOW the text row, so it correctly finds nothing
                    # here, and _claude_inline_send_button doesn't match
                    # this structure either -- both fall through, landing
                    # on the crude box-centred fallback with no idea where
                    # the real toolbar row is. _toolbar_cluster_left is the
                    # SAME-ROW detector already proven on ChatGPT/Gemini
                    # (see BADGE_WIDEN_RIGHT_SITES); tried here as the last
                    # resort for Claude specifically, since this home
                    # composer's shape matches that family, not the below-
                    # row one every other Claude surface uses.
                    if below_toolbar_result is None and app_label == "Claude":
                        if raw_geom_key == claude_same_row_cache_key[0]:
                            below_toolbar_result = claude_same_row_cache_val[0]
                        else:
                            below_toolbar_result = _toolbar_cluster_left(control, raw_right, split_left_right=True)
                            claude_same_row_cache_key[0] = raw_geom_key
                            claude_same_row_cache_val[0] = below_toolbar_result
                        if below_toolbar_result is not None:
                            toolbar_extra_gap = CLAUDE_HOME_ROW_EXTRA_GAP
                    # (left_x, row_top, row_bottom), or None -- see
                    # _below_toolbar_cluster_left's docstring.
                    if below_toolbar_result is not None:
                        toolbar_left, toolbar_row_top, toolbar_row_bottom = below_toolbar_result
                        # Real bug found live 2026-08-03 (Antonio,
                        # screenshot: badge sitting ON the divider between
                        # the text area and the toolbar row, not inside
                        # either). Root cause of the box's own bottom
                        # clamp (2026-08-02) landing there: box_bottom (a
                        # SEPARATE, independently-widened estimate) can sit
                        # a few px SHORTER than the real detected row's own
                        # bottom -- measured live, 1023 vs row_bottom 1026.
                        # _position_for's clamp was correctly keeping the
                        # badge inside box_bottom, but that pulled it
                        # ABOVE the row it's supposed to be centred on
                        # instead. Real fix, at the source instead of
                        # patching the symptom downstream: the outer box
                        # must never be shorter than the row it contains --
                        # widen it here so both numbers agree, and the
                        # clamp and the row-centring math stop fighting
                        # each other.
                        if toolbar_row_bottom is not None:
                            box_bottom = max(box_bottom, toolbar_row_bottom)
                rect = _BadgeRect(box_left, raw_rect.top, box_right, box_bottom,
                                   toolbar_left=toolbar_left,
                                   toolbar_row_top=toolbar_row_top,
                                   toolbar_row_bottom=toolbar_row_bottom,
                                   toolbar_extra_gap=toolbar_extra_gap,
                                   toolbar_row_vshift=(CLAUDE_CODE_REVIEW_VSHIFT if is_code_review
                                                        else GEMINI_VSHIFT if (app_label == "Gemini" and toolbar_left is not None)
                                                        else GROK_SINGLE_LINE_VSHIFT if (app_label == "Grok" and toolbar_left is not None
                                                                                          and (raw_rect.bottom - raw_rect.top) <= GROK_SINGLE_LINE_MAX_HEIGHT)
                                                        else COPILOT_VSHIFT if (app_label == "Copilot" and toolbar_left is not None)
                                                        else 0))
                # Plain tuple, not the Rect object itself: don't assume it
                # implements __eq__ the way a bare tuple reliably does,
                # that assumption would either miss real changes or log
                # every single tick depending on which way it's wrong.
                rect_tuple = (rect.left, rect.top, rect.right, rect.bottom)
                current_tuple = None
                if locked_badge_rect is not None:
                    current_tuple = (locked_badge_rect.left, locked_badge_rect.top,
                                     locked_badge_rect.right, locked_badge_rect.bottom)

                if locked_badge_rect is None or rect_tuple == current_tuple:
                    # First real reading, or unchanged from what's already
                    # locked: nothing to debounce, accept it outright.
                    locked_badge_rect = rect
                    pending_rect_tuple[0] = None
                    pending_rect_count[0] = 0
                elif _rects_close_enough(rect_tuple, pending_rect_tuple[0]):
                    pending_rect_count[0] += 1
                    if pending_rect_count[0] >= 2:
                        locked_badge_rect = rect
                        pending_rect_tuple[0] = None
                        pending_rect_count[0] = 0
                    else:
                        rect = locked_badge_rect  # not confirmed yet, keep the old one this tick
                else:
                    # A new candidate, different from both the current
                    # position and whatever was pending: start counting it
                    # fresh, and keep using the confirmed old position for
                    # now rather than jump to an unconfirmed one.
                    pending_rect_tuple[0] = rect_tuple
                    pending_rect_count[0] = 1
                    rect = locked_badge_rect

                if rect_tuple != last_logged_rect[0]:
                    # Control TYPE and CSS-like class only, never the accessible
                    # Name: some apps mirror the field's typed value into Name,
                    # which would leak user text into the log (privacy,
                    # 2026-07-22). Type + class are enough to diagnose position.
                    try:
                        ctrl_desc = f"{control.ControlTypeName}/{control.ClassName!r}"
                    except Exception:
                        ctrl_desc = "<error reading control info>"
                    inset = f" (corrected left {raw_left}->{box_left})" if box_left != raw_left else ""
                    if app_label in BADGE_TOOLBAR_BELOW_SITES or app_label in BADGE_WIDEN_RIGHT_SITES:
                        toolbar_note = f" toolbar_left={toolbar_left} row=({toolbar_row_top},{toolbar_row_bottom})"
                    else:
                        toolbar_note = ""
                    bottom_note = f" (widened bottom {raw_bottom}->{box_bottom})" if app_label in BADGE_WIDEN_DOWN_SITES and box_bottom != raw_bottom else ""
                    log(f"badge rect source: control={ctrl_desc} rect={rect_tuple}{inset}{toolbar_note}{bottom_note}")
                    last_logged_rect[0] = rect_tuple
            elif page_level and no_real_composer_ticks[0] >= NO_COMPOSER_HIDE_AFTER_TICKS:
                # Real fix 2026-07-30 (see no_real_composer_ticks' own
                # comment): a REAL control was found and it's been the
                # wrong kind for several ticks running -- not a blip, a
                # genuine non-composer view of a recognized app. Hide
                # instead of showing the last locked position forever.
                rect = None
                if no_real_composer_ticks[0] == NO_COMPOSER_HIDE_AFTER_TICKS:
                    # Fire exactly once at the threshold crossing (hide/
                    # dismiss are idempotent, but there's no reason to
                    # keep re-issuing them for as long as this view stays
                    # open).
                    badge.root.after(0, badge.hide)
                    popup.root.after(0, popup.dismiss)
                locked_badge_rect = None
            elif locked_badge_rect is not None:
                rect = locked_badge_rect
            else:
                # No accessible control (Claude's typed-buffer path).
                # Real bug found live 2026-07-24/25 (Antonio, screenshot:
                # badge sitting ON TOP of mid-sentence text during
                # dictation -- "looks unfinished, not good"): the earlier
                # 2026-07-24 fix only stabilized the LEFT edge; vertical
                # position was still tracking the live caret, which during
                # dictation (or just editing) moves constantly through the
                # middle of the sentence as text gets inserted. Chasing a
                # moving cursor was the wrong approach on EITHER axis, not
                # just the one fixed before.
                #
                # There's no accessible control here to ask "where does
                # the box actually start" (see _input_box_left, used by the
                # branch above that HAS one), so instead of tracking the
                # cursor at all, this anchors to a fixed, WINDOW-RELATIVE
                # guess: bottom-left area of the host window, where chat
                # compose boxes conventionally sit (Claude, ChatGPT, Gemini
                # all put the composer near the bottom). Cruder than a real
                # measurement, but it depends only on the window's own
                # bounds, which don't move while you're typing or
                # dictating, unlike a caret. A caret/click point is still
                # read, but ONLY to identify WHICH window to anchor to (for
                # split-screen correctness via _host_window_rect) -- never
                # for the actual badge coordinates.
                ref = get_caret_screen_rect() or get_last_click_rect()
                # Real report 2026-07-26 (Antonio, live: badge landing
                # "above it... on the far right of the screen" once the new
                # terminal/AI-CLI recognition made a terminal window reach
                # this same "no accessible control" branch): the
                # window-relative bottom-right guess below was built and
                # tuned specifically for Claude/ChatGPT/Gemini's chat
                # composers, which really do always sit near the bottom of
                # their window -- true for a GUI chat app, NOT true for a
                # terminal, where the live cursor can be anywhere the
                # scrolling output currently ends. A terminal has no
                # "composer position" convention to guess at, so this
                # branches off to use the REAL caret position directly
                # instead, the opposite of why the guess replaced
                # caret-chasing for Claude below -- different apps,
                # different right answer.
                is_terminal_case = process_name in TERMINAL_HOST_PROCESSES
                rect = None  # guaranteed default; every branch below either
                             # overrides this with something better or
                             # leaves it None, so nothing downstream can
                             # ever see an unbound `rect` (real terminal
                             # case with no caret AND no last-click point
                             # available falls through to this default,
                             # then the auto.GetForegroundControl() safety
                             # net further below).
                if is_terminal_case:
                    # REVERTED the caret-based approach tried just above
                    # (2026-07-26): live screenshots showed the badge
                    # floating in the middle of the scrollback, nowhere
                    # near the real input line. Windows Terminal is
                    # GPU-composited and evidently doesn't expose an
                    # accurate classic Win32 caret matching where its own
                    # TUI actually draws its cursor -- get_caret_screen_rect
                    # itself already warns this can happen ("common for
                    # GPU-composited apps that draw their own cursor
                    # instead of using the classic Win32 caret API").
                    # Chasing it isn't reliable here.
                    #
                    # Anchored to the WINDOW's bottom edge instead -- same
                    # idea as the Claude-composer heuristic below, but
                    # tuned from Antonio's own screenshots to a DIFFERENT
                    # target: underneath the input line, to the right of
                    # the "auto mode on (shift+tab to cycle)" status text,
                    # not the composer-style bottom-right corner.
                    # FIRST-PASS ESTIMATE, not measured against a real
                    # rendered layout -- flagged as likely needing one more
                    # round of adjustment once actually seen live.
                    try:
                        hwnd = ctypes.windll.user32.GetForegroundWindow()
                        win_rect = wintypes.RECT()
                        if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(win_rect)):
                            host = (win_rect.left, win_rect.top, win_rect.right, win_rect.bottom)
                        else:
                            host = None
                    except Exception:
                        host = None
                    if host is not None:
                        left = host[0] + TERMINAL_STATUS_LEFT_OFFSET
                        top = host[3] - TERMINAL_STATUS_BOTTOM_OFFSET
                        rect = _SimpleRect(left, top, left + 1, top + 1)
                    host = None  # already positioned; skip the composer heuristic below
                else:
                    host = None
                    if ref is not None:
                        host = _host_window_rect(ref.left, ref.top)
                    if host is None:
                        try:
                            hwnd = ctypes.windll.user32.GetForegroundWindow()
                            win_rect = wintypes.RECT()
                            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(win_rect)):
                                host = (win_rect.left, win_rect.top, win_rect.right, win_rect.bottom)
                        except Exception:
                            host = None
                if not is_terminal_case and host is not None:
                    # Real bug found live 2026-07-25 (second report, same
                    # screenshot symptom): TWO separate mistakes, not one.
                    #
                    # (1) _position_for's "no real box" branch computes
                    # bx = rect.left - BADGE_ICON_SIZE - BADGE_INSIDE_INSET --
                    # the previous version set rect.left to the ALREADY-
                    # inset target x, so it landed BADGE_ICON_SIZE+inset
                    # further off than intended, past the window's own
                    # edge. fit_within_window_and_monitor's clamp silently
                    # caught that and pinned it to the window's bare edge
                    # (0px margin, not the intended inset) -- accidentally
                    # stable, but not what WINDOW_RIGHT_INSET was supposed
                    # to produce. Adding BADGE_ICON_SIZE + BADGE_INSIDE_INSET
                    # back here cancels that subtraction out, so the actual
                    # on-screen badge lands exactly at
                    # host_right - WINDOW_RIGHT_INSET - BADGE_ICON_SIZE
                    # (mirrored to the box's estimated RIGHT edge as of
                    # 2026-07-25's inside-the-box redesign; this used to
                    # target host_left + WINDOW_LEFT_INSET when the badge
                    # floated outside the box's left edge instead).
                    #
                    # (2) The vertical guess was a FIXED 90px, sized for a
                    # one-line message. Claude's composer grows upward as
                    # a message wraps to more lines, so a fixed offset
                    # that clears one line doesn't clear three -- exactly
                    # what the screenshot showed. There's no accessible
                    # control to read the box's real height from, so this
                    # estimates it from the same typed-buffer text already
                    # being tracked for this tick: rough chars-per-line and
                    # line-height guesses, capped so a long paste can't
                    # push the badge absurdly far up the window.
                    wrapped_lines = 1
                    if text:
                        wrapped_lines = max(text.count("\n") + 1,
                                             len(text) // CHARS_PER_LINE_GUESS + 1)
                        wrapped_lines = min(wrapped_lines, MAX_ESTIMATED_WRAP_LINES)
                    box_height_guess = wrapped_lines * LINE_HEIGHT_GUESS + BOX_PADDING_GUESS

                    bx_target = host[2] - WINDOW_RIGHT_INSET - BADGE_ICON_SIZE
                    by_target = host[3] - box_height_guess
                    left = bx_target + BADGE_ICON_SIZE + BADGE_INSIDE_INSET
                    top = by_target + 4
                    rect = _SimpleRect(left, top, left + 1, top + 1)
                elif not is_terminal_case:
                    rect = None
                # else: is_terminal_case was True and already set `rect`
                # from the real caret above -- nothing left to do here.
                if rect is None:
                    try:
                        fg = auto.GetForegroundControl()
                        rect = fg.BoundingRectangle
                    except Exception:
                        rect = None
                if rect is not None:
                    locked_badge_rect = rect

            # Badge z-order while the card is open (2026-07-23, Antonio): the
            # card populates BEHIND the real floating badge, which nests in the
            # card's bottom-right corner (see _finalize). So while the card is
            # open, keep the badge visible and ON TOP without repositioning it
            # (raise_to_front) — do NOT re-run show_near, which would re-anchor
            # the badge to the box and pull it off the card corner. Earlier
            # (v0.9.51) this branch HID the badge to kill a drawn duplicate;
            # that duplicate (_dock_badge) is gone now, so the real badge stays.
            card_open = popup.window is not None or (warmcard is not None and warmcard.open)
            if card_open:
                # Real bug found live 2026-07-24 (Antonio: drag the host
                # window across monitors while the card is open, badge/card
                # left behind at the old spot): the no-reposition rule above
                # is right for typing-driven jitter, but a real window drag
                # moves the box by hundreds of px, not a handful -- distinct
                # enough to tell apart from the jitter DRAG_THRESHOLD exists
                # to ignore. On a real drag, move the badge AND shift the
                # already-open card by the same delta (not a full
                # re-_finalize, which would lose its docked-corner offset).
                DRAG_THRESHOLD = S(60)
                # Real follow-up bug caught live (Antonio: dragged to the
                # other monitor, THEN maximized there -- card ended up close
                # but not hooked to the badge's edge). A plain dx,dy shift
                # (below) only stays correct if the box PURELY translates --
                # it measures the left edge's movement alone, so a resize
                # (maximize/restore) that changes the box's WIDTH moves the
                # right edge (where the badge actually docks) by a different
                # amount than dx captures, throwing the corner off by
                # whatever the width changed by. A full _finalize() is
                # unaffected by that since it re-derives everything from the
                # box's CURRENT rect rather than an assumed-still-valid
                # offset, so use it whenever the box's SIZE changed, not
                # just its position.
                RESIZE_THRESHOLD = S(60)
                moved_far = False
                resized = False
                if rect is not None:
                    if card_open_anchor_rect is None:
                        card_open_anchor_rect = rect
                    else:
                        dx = rect.left - card_open_anchor_rect.left
                        dy = rect.top - card_open_anchor_rect.top
                        moved_far = abs(dx) > DRAG_THRESHOLD or abs(dy) > DRAG_THRESHOLD
                        dw = (rect.right - rect.left) - (card_open_anchor_rect.right - card_open_anchor_rect.left)
                        dh = (rect.bottom - rect.top) - (card_open_anchor_rect.bottom - card_open_anchor_rect.top)
                        resized = abs(dw) > RESIZE_THRESHOLD or abs(dh) > RESIZE_THRESHOLD
                if resized:
                    def _resnap(rect=rect, count=suggestion_count, checked=is_long_enough, app_label=app_label):
                        badge.show_near(rect, count, checked=checked, app_label=app_label)
                        if popup.window is not None:
                            try:
                                popup._finalize(popup.window, *popup._pos)
                            except Exception:
                                log_exception("card reposition on host resize")
                    badge.root.after(0, _resnap)
                    card_open_anchor_rect = rect
                elif moved_far:
                    def _follow_drag(dx=dx, dy=dy, rect=rect, count=suggestion_count,
                                      checked=is_long_enough, app_label=app_label):
                        badge.show_near(rect, count, checked=checked, app_label=app_label)
                        win = popup.window
                        if win is not None:
                            try:
                                win.geometry(f"+{win.winfo_x() + dx}+{win.winfo_y() + dy}")
                            except Exception:
                                pass
                    badge.root.after(0, _follow_drag)
                    card_open_anchor_rect = rect
                else:
                    badge.root.after(0, badge.raise_to_front)
                    # Real bug found live 2026-07-25 (screenshot: card said
                    # "Nothing to fix yet" while the badge still showed a
                    # colored dot): raise_to_front only re-shows/re-lifts the
                    # window, it never touches the heat dot, so the dot froze
                    # at whatever it was the moment the card opened and never
                    # tracked live typing after that. The 2026-07-23 fix that
                    # introduced raise_to_front was only ever about NOT
                    # re-anchoring position while the card is open (see its
                    # docstring) -- the heat color is a separate, independent
                    # concern, so updating it here doesn't reintroduce that
                    # bug.
                    badge.root.after(0, badge._update_heat, suggestion_count, is_long_enough)
            else:
                card_open_anchor_rect = None
                if rect is not None:
                    badge.root.after(0, badge.show_near, rect, suggestion_count, is_long_enough, app_label)

            # Live-update the OPEN native review card as the user keeps typing,
            # so new typos appear (and the list grows, then scrolls) in real
            # time (2026-07-23). refresh() no-ops if the fix set is unchanged or
            # the user has already clicked Apply/Compress.
            if popup.window is not None:
                _live_ai = (app_label is not None and APP_SETTINGS.get("ai_enabled")
                            and local_model.is_model_downloaded())
                badge.root.after(0, popup.refresh, analysis, _live_ai,
                                 len(text.strip()), text)

            # One source of truth for where the card opens relative to the
            # badge (see PersistentBadge.popup_anchor). The old hand-rolled
            # offsets here used a 34px gap that the badge had since outgrown,
            # so the card could overlap it.
            if rect is not None:
                popup_x, popup_y = badge.popup_anchor(rect)
            else:
                popup_x, popup_y = 100, 140

            # Captures the exact text at click time, so a slow-arriving AI
            # rewrite (real inference, several seconds even on CPU) always
            # applies against a known-good baseline, not whatever the box
            # happens to say by the time the model finishes.
            text_snapshot = text

            # Captured now, before the Apply button can ever be clicked, since
            # clicking it is what steals foreground away from this hwnd, see
            # apply_new_text.
            hwnd_snapshot = llm_hwnd

            # Real find 2026-07-27 (pre-launch audit, terminal tab-switch
            # bug): the tab name embedded in the terminal's own border row
            # (see _extract_terminal_input_line) is the one signal that
            # actually tells Windows Terminal's tabs apart -- hwnd, UIA
            # RuntimeId, and owning-window all proved identical across tabs
            # in live testing. Captured now, same moment as hwnd_snapshot,
            # so apply_new_text can refuse if the active tab has changed by
            # the time Apply is actually clicked.
            tab_name_snapshot = _last_terminal_tab_name[0]

            source_snapshot = text_source

            # The actual text control, captured here for the same reason as
            # hwnd_snapshot: once the Apply button is clicked, "the focused
            # control" is our own popup, not the user's text box. Apply needs
            # the real one both to write into directly and to put keyboard
            # focus back before any select-all (2026-07-21 fix).
            control_snapshot = control

            # is_llm_snapshot is always True by the time this runs now (2026-
            # 07-25: `active`, checked above, already requires app_label is
            # not None -- LLM apps are the only surface left, see the
            # DEFAULT_SETTINGS note on cat_ai_chat). Kept as an explicit
            # variable rather than inlining `True`, since compress_with_ai
            # below still reads is_llm to decide whether to offer Step 2 at
            # all, and that reads clearer as a named condition than a bare
            # literal. safe_write_only (the PowerPoint-only "SetValue, never
            # Ctrl+A" safety knob) has no process left to apply to now that
            # PowerPoint is never an active category, so it's hardcoded off.
            is_llm_snapshot = app_label is not None
            safe_write_snapshot = False

            def open_suggestions(
                base_text=text_snapshot, base_analysis=analysis,
                x=popup_x, y=popup_y, hwnd=hwnd_snapshot, source=source_snapshot,
                field=control_snapshot, is_llm=is_llm_snapshot,
                safe_write_only=safe_write_snapshot, tab_name=tab_name_snapshot,
            ):
                # Speed (2026-07-22): clicking the badge in an LLM app is a
                # strong signal a compress is coming. Warm the model NOW, in
                # the background, so the one-time ~10s cold load overlaps with
                # the user reading their grammar fixes instead of being paid
                # when they hit Compress. No-op if AI is off, the model isn't
                # downloaded, or the worker is already warm.
                if (is_llm and APP_SETTINGS.get("ai_enabled")
                        and not local_model.is_loaded()):
                    try:
                        local_model.prewarm_via_subprocess()
                    except Exception:
                        pass
                # Where UIA can't read the field (Claude), the badge's live
                # count came from the keystroke buffer, which can't see
                # dictated text. Before doing anything real, grab the ACTUAL
                # field contents once, so fixes are always computed against
                # what's genuinely there. Only on this explicit click.
                # Only pay for the clipboard read when the tracked buffer
                # genuinely can't be trusted. It is the one operation that
                # visibly select-all-flashes the box, and it is the only path
                # that can ever select the whole page, so running it when we
                # already have good ground truth is pure downside. When the
                # buffer IS trusted (nothing dictated or injected since the
                # last reset) it already holds exactly what was typed.
                needs_clipboard_read = source == "buffer" and (
                    _buffer_untrusted[0] or not get_typed_buffer()
                )
                if needs_clipboard_read:
                    # Pass what we tracked being typed so the read can be
                    # verified as actually coming from the input box.
                    real_text = read_text_via_clipboard(hwnd, expected_fragment=get_typed_buffer())
                    if real_text and real_text.strip():
                        base_text = real_text
                        base_analysis = suggestion_engine.analyze(real_text)
                        set_typed_buffer(real_text)
                        _buffer_untrusted[0] = False  # we have ground truth now
                        source = "clipboard"

                # Diagnostic: "it didn't detect my typos" has now been
                # reported twice with no way to tell whether the text or the
                # rules were at fault. Logs what was actually analysed and
                # what came back, so the next report is answerable from the
                # log instead of by guessing. Short preview only.
                kinds = [s["kind"] for s in base_analysis["suggestions"]] if base_analysis else []
                # No text preview in the log (privacy, 2026-07-22): length,
                # suggestion kinds and counts are enough to diagnose "it didn't
                # find my typos" without ever writing what the user typed.
                log(
                    f"open_suggestions: source={source} text_len={len(base_text)} "
                    f"suggestions={len(kinds)} kinds={kinds} "
                    f"spell_ok={winspell_available()}"
                )

                # Real direction 2026-07-20: rules and the AI WORK TOGETHER,
                # not one gating out the other. No confidence variable, one
                # pipeline, same behavior for everyone. The only switch is a
                # plain on/off for the AI stage. When it's on, Apply always
                # runs both stages in sequence, they feed each other.
                #
                # Compression ("Make it Concise") is offered ONLY when:
                #  - this is a known LLM app (is_llm), because "save tokens"
                #    only means something when you're prompting an LLM (real
                #    ask 2026-07-22: grammar-only in Teams/Slack/Discord/etc.),
                #  - the AI stage is enabled in settings, AND
                #  - the model is actually downloaded (no dead "go download"
                #    Step 2). Everywhere else the card is grammar/spelling/
                #    punctuation only.
                ai_enabled = (is_llm and APP_SETTINGS["ai_enabled"]
                              and local_model.is_model_downloaded())

                def _record(source_text, final_text, used_ai):
                    saved = estimate_tokens(source_text) - estimate_tokens(final_text)
                    append_history({
                        "timestamp": time.time(),
                        "tokens_saved": max(saved, 0),
                        "used_ai": used_ai,
                    })

                # Step two (real ask 2026-07-20): compress the already-
                # cleaned text with the AI, as a separate deliberate action.
                # source_text here is always the rules-corrected text, so the
                # model reads "output," never "putput."
                def compress_with_ai(source_text):
                    if not local_model.is_model_downloaded():
                        # Real ask 2026-07-22: the model isn't bundled anymore,
                        # it's a one-time in-app download. Point the user to it
                        # rather than dead-ending. (Left the app tiny to install.)
                        if local_model.is_downloading():
                            msg = ("The AI model is downloading now (one-time, "
                                   "~1 GB). Open Settings → Model to watch progress, "
                                   "then try Compress again.")
                        else:
                            msg = ("The AI “Make it Concise” step needs a one-time "
                                   "~1 GB model download. Open Settings (tray icon) "
                                   "→ Model → Download AI model. Spelling, grammar "
                                   "and punctuation work without it.")
                        popup.show_error(x, y, msg)
                        return
                    # Real ask 2026-07-20: do NOT auto-paste the AI result,
                    # preview it in the card with Apply/Dismiss first, so the
                    # compression is reviewable, not instant. The paste +
                    # history record only happen if the user actually clicks
                    # Apply. Shared by both the cache-hit and freshly-computed
                    # paths below so there's exactly one Apply behavior.
                    def do_apply_result(rewritten):
                        # expected_old_text is the rules-cleaned text, i.e.
                        # exactly what step one already put in the box, so
                        # the focus check recognises the field by what it
                        # really contains right now.
                        applied = apply_new_text(
                            root, popup, rewritten, target_hwnd=hwnd,
                            dismiss_after=True, target_control=field,
                            expected_old_text=source_text,
                            expected_tab_name=tab_name,
                            safe_write_only=safe_write_only,
                        )
                        # Same rule as on_apply below (2026-07-25 audit): only
                        # an apply that landed counts toward saved tokens.
                        if applied:
                            _record(source_text, rewritten, used_ai=True)

                    # Cache hit: this exact source text was already compressed
                    # (most likely the card got dismissed and reopened without
                    # the box's text actually changing -- see _last_compression
                    # above). Reuse it instantly instead of re-running the
                    # model on unchanged input.
                    if (_last_compression["source"] == source_text
                            and _last_compression["rewritten"]):
                        rewritten = _last_compression["rewritten"]
                        popup.show_compress_result(
                            x, y, source_text, rewritten,
                            lambda: do_apply_result(rewritten))
                        return

                    # In-place loading state inside step two; falls back to a
                    # standalone loading card if the step slot isn't there.
                    if not popup.step2_loading():
                        popup.show_loading(x, y)

                    def worker():
                        # Runs the model in a SEPARATE process (2026-07-22), so
                        # this compress can't freeze the UI. Falls back to
                        # in-process automatically if the subprocess can't start.
                        #
                        # The whole body is fenced (2026-07-22 market audit):
                        # every path that dismisses the "Compressing..." card
                        # lives INSIDE this function, so an unexpected raise
                        # (rewrite is heavily guarded, but not provably
                        # raise-free) would strand the loading card on screen
                        # forever with no way to dismiss it programmatically.
                        try:
                            rewritten, error = local_model.rewrite_prompt_via_subprocess(source_text)
                        except Exception:
                            log_exception("compress worker")
                            rewritten, error = None, "unexpected error"
                        if error or not rewritten:
                            # AI failed: the rules-cleaned text is already in
                            # the box from step one, so just close, don't
                            # dead-end or wipe anything.
                            log(f"AI compression stage failed ({error}), keeping the rules-cleaned text")
                            popup.root.after(0, popup.dismiss)
                            return

                        _last_compression["source"] = source_text
                        _last_compression["rewritten"] = rewritten

                        def finish():
                            popup.show_compress_result(
                                x, y, source_text, rewritten,
                                lambda: do_apply_result(rewritten))

                        popup.root.after(0, finish)

                    # Defer the worker one event-loop cycle (real bug fix
                    # 2026-07-20): this lets the loading card fully paint
                    # before the CPU-heavy inference starts and starves the
                    # UI thread, without this the card rendered half-blank.
                    popup.root.after(80, lambda: threading.Thread(target=worker, daemon=True).start())

                # Mutable text the apply works against. The card live-refreshes
                # as the user keeps typing (2026-07-23), so Apply must act on
                # the CURRENT text, not the click-time snapshot; the live
                # refresh updates apply_state["text"] each tick (see
                # popup.refresh / watch_loop) so it always matches the fixes
                # shown. Seeded with the settled base_text.
                apply_state = {"text": base_text}
                popup._apply_state = apply_state

                # Step one (real ask 2026-07-20): apply the spelling/grammar/
                # filler fixes FIRST and visibly, so the box shows the cleaned
                # text. Only then offer the AI compression as step two. This
                # is the staging Antonio asked for, fix the words first, then
                # let the AI improve the corrected version, not one opaque
                # jump straight to the AI.
                def on_apply(checked_suggestions):
                    # Hard guard (real data-loss bug 2026-07-21): if any
                    # input arrived that we couldn't track (dictation, or
                    # another tool injecting text), base_text is only a
                    # fragment of what's really in the box. Applying would
                    # select the REAL full prompt and replace it with that
                    # fragment, destroying the user's text. Refuse instead.
                    if source == "buffer" and _buffer_untrusted[0]:
                        log("on_apply blocked: no ground truth (clipboard read failed and buffer untrusted)")
                        popup.show_error(
                            x, y,
                            "Comprsly couldn't read this text field, so it can't safely "
                            "edit it.\n\nThis usually clears up if you click into the box "
                            "and try again.",
                        )
                        return

                    cur_text = apply_state["text"]
                    # Real bug found live 2026-07-27 (pre-launch audit, the
                    # actual root cause behind the "Apply typed stale
                    # content" reports): apply_state["text"] is refreshed by
                    # popup.refresh() on EVERY watch_loop tick while the card
                    # is open, precisely so Apply stays in sync if you keep
                    # typing after suggestions appear (see refresh()'s own
                    # docstring). That's the right behavior for browsers/apps
                    # (UIA value/text reads there are direct and reliable),
                    # but for terminals it means a single rare misread from
                    # _extract_terminal_input_line -- the same occasional
                    # wrong-bordered-box failure documented on that function
                    # -- can poison this value the moment it happens, and it
                    # then sits there silently until either another good tick
                    # overwrites it or Apply gets clicked while it's still
                    # wrong. There's no guarantee a good tick arrives first.
                    # A fresh read taken right now, at the actual moment of
                    # the click, has been reliable in direct live testing, so
                    # terminals get one here instead of trusting whatever the
                    # last background tick happened to write.
                    if _process_name_for_hwnd(hwnd) in TERMINAL_HOST_PROCESSES:
                        fresh_text, _ = get_focused_text()
                        if fresh_text is not None:
                            cur_text = fresh_text
                    rules_text = suggestion_engine.apply_suggestions(cur_text, checked_suggestions)

                    if checked_suggestions:
                        # There were real rule fixes: apply them to the box,
                        # keep the popup open (dismiss_after=False) to offer
                        # step two. Record AFTER the apply says it landed
                        # (2026-07-25 audit): recording first meant every
                        # aborted apply ("lost track of your text box", held
                        # clipboard) still counted its tokens as saved.
                        applied = apply_new_text(
                            root, popup, rules_text, target_hwnd=hwnd,
                            dismiss_after=False, target_control=field,
                            expected_old_text=cur_text,
                            expected_tab_name=tab_name,
                            safe_write_only=safe_write_only,
                        )
                        if applied:
                            _record(cur_text, rules_text, used_ai=False)
                        if ai_enabled:
                            # Step one collapses to a one-line receipt in the
                            # SAME card and step two rises into its place.
                            #
                            # It briefly auto-started the compression here
                            # ("once step one finishes it should go to the
                            # next process"), reverted same day on Antonio's
                            # correction: it must WAIT for an explicit
                            # Compress or Dismiss. Running a 6-second job that
                            # freezes the UI for ~4 of them is not something
                            # to start on the user's behalf, and grammar-only
                            # is a perfectly normal place to stop.
                            on_compress = lambda: compress_with_ai(rules_text)
                            enough_text = len(rules_text.strip()) >= MIN_TEXT_LENGTH_TO_ANALYZE
                            if not popup.collapse_step1(len(checked_suggestions), on_compress, enough_text):
                                popup.show_compress_offer(x, y, on_compress, enough_text)
                        else:
                            popup.dismiss()
                    else:
                        # No rule fixes to apply (button was "Compress with
                        # AI" directly): compress the original text as-is.
                        compress_with_ai(rules_text)

                # New web-based review card (2026-07-22 UI redesign): spawn it
                # as a frameless WebView2 process positioned by the badge. It
                # handles the UI + compress and EMITS apply-actions on stdout;
                # we route those into the SAME apply_new_text below, so the
                # hard-won Apply/focus logic is never rewritten. Falls back to
                # the native Tk card if the process can't start or the web UI
                # fails, so the feature is never lost.
                def _show_tk_card():
                    # Point the card palette at the current theme (System→OS)
                    # before building, so the card matches light/dark like the
                    # web UI. Set once per open; later states (compress result)
                    # in the same session reuse it.
                    _apply_card_palette()
                    popup.root.after(0, popup.show_suggestions, x, y, base_analysis,
                                     ai_enabled, on_apply, len(base_text.strip()))
                    # Keep the real floating badge visible and ON TOP of the
                    # card (2026-07-23, Antonio): the card is positioned to
                    # nest the badge in its bottom-right corner and populate
                    # BEHIND it, so lift the badge above the just-shown card.
                    # (Runs after show_suggestions on the same after-queue, so
                    # the card exists and is deiconified first.)
                    popup.root.after(0, badge.raise_to_front)

                def launch_web_card():
                    import tempfile
                    try:
                        payload = {
                            "text": base_text,
                            "suggestions": base_analysis["suggestions"],
                            "is_llm": is_llm,
                            "ai_enabled": ai_enabled,
                            "theme": "light",  # light-only now, see _apply_card_palette
                            "width": 430, "height": 560,
                            "rect": {"x": int(x), "y": int(y)},
                        }
                        fd, path = tempfile.mkstemp(suffix=".json", prefix="comprsly_rc_")
                        os.close(fd)
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(payload, f)
                        cmd = ([sys.executable, "--review-card", path] if getattr(sys, "frozen", False)
                               else [sys.executable, os.path.abspath(__file__), "--review-card", path])
                        flags = 0x08000000 if os.name == "nt" else 0
                        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True,
                                                encoding="utf-8", creationflags=flags)
                    except Exception:
                        log_exception("launch web review card")
                        return False

                    # The card is now the UI: hide the badge so it doesn't sit
                    # on top of the card, and flag the watch loop to keep it
                    # hidden until the card process exits.
                    _review_card_open[0] = True
                    badge.root.after(0, badge.hide)

                    st = {"applied": base_text, "actions": 0}

                    def reader():
                        try:
                            for line in proc.stdout:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    msg = json.loads(line)
                                except Exception:
                                    continue
                                if msg.get("action") == "apply":
                                    st["actions"] += 1
                                    new_text = msg.get("text", "")
                                    used_ai = msg.get("stage") == "final"
                                    prev = st["applied"]

                                    def do(new_text=new_text, prev=prev, used_ai=used_ai):
                                        try:
                                            # Dormant path today (the warm
                                            # card / native card front this
                                            # one), but kept honest with the
                                            # live callers (2026-07-25 audit):
                                            # record only after the apply
                                            # reports it really landed.
                                            ok = apply_new_text(
                                                root, popup, new_text, target_hwnd=hwnd,
                                                dismiss_after=False, target_control=field,
                                                expected_old_text=prev, safe_write_only=safe_write_only)
                                            if ok:
                                                append_history({
                                                    "timestamp": time.time(),
                                                    "tokens_saved": max(estimate_tokens(prev) - estimate_tokens(new_text), 0),
                                                    "used_ai": used_ai,
                                                })
                                        except Exception:
                                            log_exception("web card apply")
                                    root.after(0, do)
                                    st["applied"] = new_text
                                elif msg.get("action") == "dismiss":
                                    st["actions"] += 1
                            proc.wait()
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                            if proc.returncode not in (0, None) and st["actions"] == 0:
                                log(f"web review card exited {proc.returncode} with no actions, Tk fallback")
                                _show_tk_card()
                        except Exception:
                            log_exception("web review card reader")
                        finally:
                            # Card closed: let the badge come back on the next
                            # watch-loop tick.
                            _review_card_open[0] = False
                    threading.Thread(target=reader, daemon=True).start()
                    return True

                # Prefer the WARM web card (2026-07-23): the persistent server
                # holds the full HTML design ready, so it pops instantly at the
                # badge without the per-click cold start that made the old web
                # card slow/mispositioned. Falls back to the native Tk card if
                # the server isn't alive or the show command fails.
                def _show_web_card():
                    if warmcard is None or not warmcard.is_alive():
                        return False
                    payload = {
                        "text": base_text,
                        "suggestions": base_analysis["suggestions"],
                        "is_llm": is_llm,
                        "ai_enabled": ai_enabled,
                        "theme": "light",  # light-only now, see _apply_card_palette
                    }
                    # Send the badge rect; the server sizes the card to its
                    # content and nests the badge in the card's bottom-right
                    # corner (the card can't know its own height until it has
                    # rendered, so positioning happens server-side, see
                    # webui._fit_and_show).
                    brect = badge.current_badge_rect() or (x, y, BADGE_ICON_SIZE, BADGE_ICON_SIZE)
                    ctx = {"hwnd": hwnd, "field": field,
                           "safe_write_only": safe_write_only, "applied": base_text}
                    if warmcard.show(payload, brect, ctx):
                        # Badge stays visible and ON TOP (nested in the card
                        # corner), driven by warmcard.open in the card_open
                        # branch. Deliberately NOT _review_card_open, which
                        # hides the badge and skips the tick (old per-click
                        # behaviour) and would tear the badge down here.
                        badge.root.after(0, badge.raise_to_front)
                        return True
                    return False

                if not _show_web_card():
                    _show_tk_card()

            # Always clickable, see the note at is_long_enough above. The
            # card handles "nothing to fix" on its own: it says so, and Step
            # 2 does the same when there isn't enough text to be worth
            # compressing (real ask 2026-07-21, see _render_step2_offer).
            badge.on_click = open_suggestions
            last_text = text
        except Exception:
            log_exception("watch_loop tick")


ctypes.windll.kernel32.CreateMutexW.restype = wintypes.HANDLE
ctypes.windll.kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

def already_running() -> bool:
    """True if another copy of this app is already running. Uses a named
    Win32 mutex, the standard single-instance technique on Windows."""
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS


# Real ask 2026-07-20: clicking the app icon (taskbar/desktop/Start) should
# open the settings window, not pop a "Comprsly is already running" box.
# That box was the single-instance guard: launching the app again detected
# the mutex and just told you it was running. Now the second launch instead
# SIGNALS the already-running copy to show its settings window, then exits
# silently, which is how normal single-instance desktop apps behave.
#
# A named Win32 auto-reset Event is the simplest reliable cross-process
# signal here: the running instance waits on it in a daemon thread, the new
# launch opens it by name and sets it. No sockets, no pipes, no ports.
SHOW_SETTINGS_EVENT_NAME = "ComprslyShowSettingsEvent"
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0x00000000

ctypes.windll.kernel32.CreateEventW.restype = wintypes.HANDLE
ctypes.windll.kernel32.CreateEventW.argtypes = [
    wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR
]
ctypes.windll.kernel32.OpenEventW.restype = wintypes.HANDLE
ctypes.windll.kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
ctypes.windll.kernel32.WaitForSingleObject.restype = wintypes.DWORD
ctypes.windll.kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
ctypes.windll.kernel32.SetEvent.argtypes = [wintypes.HANDLE]
ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def signal_existing_instance_to_show_settings() -> bool:
    """Called by a SECOND launch: tell the already-running copy to open its
    settings window. Returns True if the signal was delivered."""
    handle = ctypes.windll.kernel32.OpenEventW(
        EVENT_MODIFY_STATE, False, SHOW_SETTINGS_EVENT_NAME
    )
    if not handle:
        return False
    try:
        return bool(ctypes.windll.kernel32.SetEvent(handle))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def run_show_settings_listener(on_show_settings):
    """Runs in the ORIGINAL instance: blocks on the named event and opens
    settings every time another launch signals it."""
    try:
        # auto-reset (bManualReset=False) so each signal fires exactly once.
        handle = ctypes.windll.kernel32.CreateEventW(None, False, False, SHOW_SETTINGS_EVENT_NAME)
        if not handle:
            log("show-settings listener: CreateEventW failed")
            return
        log("show-settings listener installed")
        while True:
            if ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == WAIT_OBJECT_0:
                log("show-settings event received, opening settings window")
                on_show_settings()
    except Exception:
        log_exception("run_show_settings_listener")


def make_tray_icon():
    """Real logo now (real ask 2026-07-20), falls back to a plain generated
    circle only if PIL or the bundled asset is somehow unavailable, so the
    tray icon never just silently fails to appear."""
    if Image is not None:
        try:
            return Image.open(resource_path(os.path.join("assets", "icon.png"))).convert("RGBA")
        except Exception:
            pass
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=(100, 113, 219, 255))
    return image


def run_tray_icon(on_quit, on_open_settings):
    if pystray is None:
        log("run_tray_icon: pystray/Pillow not importable, skipping tray icon")
        return  # pystray/Pillow not available, app still works, just no tray icon
    log("run_tray_icon: building icon")
    # Real ask 2026-07-20: left-clicking the tray icon should open the real
    # settings window directly, Handy's own tray behavior was the explicit
    # reference. pystray maps a plain left-click to whichever MenuItem is
    # marked default=True on Windows; right-click still shows the full menu.
    menu = pystray.Menu(
        pystray.MenuItem(BRAND_NAME, on_open_settings, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("comprsly", make_tray_icon(), BRAND_NAME, menu)
    log("run_tray_icon: calling icon.run()")
    icon.run()
    log("run_tray_icon: icon.run() returned (tray stopped)")


def show_ai_onboarding(root, settings_window):
    """One-time first-run prompt (real ask 2026-07-22). The model isn't bundled
    anymore, so on first launch, if it's absent, offer the optional ~1 GB AI
    download right away. Declining is fine: the whole grammar/spelling/
    punctuation engine works with no model, and the download stays available
    from Settings -> Model or the first "Compress with AI" click."""
    try:
        win = tk.Toplevel(root)
        win.title(BRAND_NAME)
        win.configure(bg=POPUP_BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        # This is a real dialog (has its own taskbar entry by design, unlike
        # the badge/card), so it must never show the default Tk/Tcl feather
        # in its title bar or taskbar button either (2026-07-26).
        onboarding_icon = _load_app_icon_image(32)
        if onboarding_icon is not None:
            win._icon_keepalive = ImageTk.PhotoImage(onboarding_icon)
            try:
                win.iconphoto(True, win._icon_keepalive)
            except Exception:
                pass

        tk.Label(win, text=f"Welcome to {BRAND_NAME}", font=("Segoe UI Semibold", 14),
                 fg=POPUP_TEXT, bg=POPUP_BG).pack(anchor="w", padx=S(22), pady=(S(20), S(4)))
        tk.Label(
            win,
            text=("Spelling, grammar and punctuation fixes work right now, "
                  "nothing to download.\n\nThe optional AI “Make it "
                  "Concise” step (compress a prompt to fewer tokens) needs "
                  "a one-time ~1 GB model. It then runs fully offline. Your "
                  "text never leaves this machine."),
            font=("Segoe UI", 10), fg=POPUP_SUBTEXT, bg=POPUP_BG, justify="left",
            wraplength=S(420),
        ).pack(anchor="w", padx=S(22), pady=(0, S(16)))

        row = tk.Frame(win, bg=POPUP_BG)
        row.pack(fill="x", padx=S(22), pady=(0, S(20)))

        def _later():
            win.destroy()

        def _download_now():
            win.destroy()
            threading.Thread(target=local_model.download_model, daemon=True).start()
            try:
                settings_window.show()
                settings_window._select_section("Model")
            except Exception:
                log_exception("ai onboarding -> open settings")

        tk.Button(row, text="Maybe later", font=("Segoe UI", 10), fg=POPUP_TEXT,
                  bg=POPUP_MUTED_BTN, activebackground=POPUP_MUTED_BTN,
                  activeforeground=POPUP_TEXT, relief="flat", padx=S(16), pady=S(7),
                  borderwidth=0, cursor="hand2", command=_later).pack(side="right")
        tk.Button(row, text="Download AI model (~1 GB)", font=("Segoe UI Semibold", 10),
                  fg="white", bg=ACCENT_VIOLET, activebackground=ACCENT_VIOLET,
                  activeforeground="white", relief="flat", padx=S(18), pady=S(7),
                  borderwidth=0, cursor="hand2", command=_download_now).pack(
                      side="right", padx=(0, S(8)))

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
    except Exception:
        log_exception("show_ai_onboarding")


def main():
    log("=== main() starting ===")

    # If Windows UI Automation couldn't load (almost always a missing Visual
    # C++ Redistributable on a fresh machine), there's no point continuing:
    # every text-box read would fail and the badge would never appear. Say so
    # plainly and log it, instead of the app silently doing nothing, which is
    # exactly how the "doesn't pop up on their end" report looked.
    if _UIA_IMPORT_ERROR is not None:
        log(f"FATAL: uiautomation failed to load ({_UIA_IMPORT_ERROR}). "
            f"Likely the Visual C++ Redistributable is missing.")
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "Comprsly couldn't start because a required Windows component "
                "is missing.\n\nPlease install the Microsoft Visual C++ "
                "Redistributable (x64), then reopen Comprsly:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe",
                "Comprsly", 0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        sys.exit(1)

    if already_running():
        # Real ask 2026-07-20: clicking the app icon again should OPEN THE
        # SETTINGS WINDOW on the copy that's already running, not pop a
        # "Comprsly is already running" box (which is what Antonio was
        # hitting and found useless). Signal the original, then exit quietly.
        delivered = signal_existing_instance_to_show_settings()
        log(f"already_running() True, signalled existing instance to show settings: {delivered}")
        if not delivered:
            # Only fall back to a message if the signal genuinely failed,
            # so there's still real feedback instead of silence.
            ctypes.windll.user32.MessageBoxW(
                0, f"{BRAND_NAME} is already running (check your system tray).", BRAND_NAME, 0x40
            )
        sys.exit(0)

    # Correct a stale autostart path left by the Token Saver -> Comprsly
    # folder move (real ask 2026-07-22), a no-op once healed or if the user
    # never enabled login-launch.
    heal_launch_on_login()
    remove_stale_compresly_startup_entry()

    # Cross-process model state (audit 2026-07-25): only THIS process may
    # write the loaded-state file Settings reads, and a progress file left
    # claiming active:true by a previous run's killed daemon thread must be
    # neutralized before any Settings window can trust it (it used to brick
    # the download UI into a frozen "Downloading... N%" forever).
    local_model.enable_status_writes()
    local_model.clear_stale_download_progress()

    log("creating Tk root")
    root = tk.Tk()
    root.withdraw()  # no main window, this app is a background watcher

    # Fonts are specified in POINTS, which Tk converts to pixels using this
    # scaling factor. Left alone it varies by machine, so the text would drift
    # out of proportion with the widths scaled by S(). Pinning it to the same
    # UI_SCALE keeps type and layout locked together on every display.
    # 96/72 is what Tk resolves to on Antonio's machine today, so at
    # UI_SCALE 1.0 this is a no-op and the app looks exactly as it does now.
    def _apply_font_scaling():
        # _active_dpi[0] is set by apply_scale_for_window before this runs
        # via _scale_listeners; only the very first, pre-window call at
        # startup (right below) can still find it None, so fall back to the
        # primary monitor's own DPI the same way BADGE_ICON_SIZE's module-
        # level init does.
        dpi = _active_dpi[0] if _active_dpi[0] is not None else _monitor_dpi()
        try:
            root.tk.call("tk", "scaling", (96.0 / 72.0) * UI_SCALE * font_scale_for_dpi(dpi))
        except Exception:
            pass

    _apply_font_scaling()
    _scale_listeners.append(_apply_font_scaling)
    _startup_dpi = _active_dpi[0] if _active_dpi[0] is not None else _monitor_dpi()
    log(f"startup scale {UI_SCALE:.2f}: card {POPUP_WIDTH}px, badge {BADGE_ICON_SIZE}px, "
        f"text {9 * (96.0/72.0) * UI_SCALE * font_scale_for_dpi(_startup_dpi):.0f}px "
        f"(font profile: {'laptop' if _startup_dpi >= 120 else 'monitor'})")

    popup = SuggestionPopup(root)
    badge = PersistentBadge(root)
    # So dragging the badge carries the open review card with it instead of
    # leaving it stranded (real ask 2026-07-20).
    badge.popup = popup
    # The badge image is baked at BADGE_ICON_SIZE, so a screen change has to
    # rebuild it rather than resize it.
    _scale_listeners.append(lambda: root.after(0, badge.rebuild_for_scale))

    # Real ask 2026-07-26 (Antonio, direct repro: dragged the host app
    # window from one monitor to the other while the review card was
    # already open -- the card never moved or resized for the new screen,
    # "it did not auto-adjust correctly"). _finalize only ever ran once,
    # at the moment a card first opened; nothing re-ran it on a later
    # monitor change while it stayed open. Same listener mechanism the
    # badge's own rebuild_for_scale already uses just above, not a new
    # polling path -- _scale_listeners already fires exactly once per
    # genuine monitor change, via apply_scale_for_window.
    #
    # Real follow-up bug caught live (Antonio: "wasn't able to hook to the
    # correct position to the edge of the circle" -- close, not exact):
    # this listener and the badge's own rebuild_for_scale listener are BOTH
    # queued via root.after(0, ...) in the same synchronous pass, but the
    # badge's TRUE new position for this tick isn't set by rebuild_for_scale
    # at all (that only rebuilds its image/size for the new DPI) -- it comes
    # from watch_loop's regular per-tick badge.show_near(rect, ...) call,
    # which is scheduled LATER in that same pass, further back in the same
    # after(0) queue. Re-finalizing the card immediately anchored it to the
    # badge's STILL-STALE pre-move rect, a moment before show_near actually
    # moved it. A short, imperceptible delay (well under one watch_loop
    # tick) lets that real per-tick reposition land first, so this anchors
    # to where the badge actually ends up, not where it was about to move
    # from.
    def _reposition_open_card_on_scale_change():
        if popup.window is not None:
            try:
                popup._finalize(popup.window, *popup._pos)
            except Exception:
                log_exception("card reposition on scale change")

    _scale_listeners.append(lambda: root.after(150, _reposition_open_card_on_scale_change))
    # Every card positions itself against the badge's live location, so a
    # follow-up card can never reopen at a stale pre-drag spot.
    popup.anchor_provider = badge.current_popup_anchor
    popup.badge_rect_provider = badge.current_badge_rect
    popup.box_rect_provider = badge.current_box_rect
    settings_window = SettingsWindow(root, badge)

    # Review card uses the NATIVE Tk card (2026-07-23, Antonio, firmly): the
    # warm WebView2 card renders the exact design, but it is a real OS window —
    # it lights up the taskbar and "pops up like a window," which he explicitly
    # does not want for a floating overlay. The native card is the same
    # no-taskbar, no-activate, instant overlay tech as the badge, and has been
    # brought visually close to the mockup. The warm-card server + IPC are kept
    # intact but NOT launched, so open_suggestions' `if not _show_web_card()`
    # cleanly falls through to `_show_tk_card()`. Flip this back on (call
    # warmcard.launch()) if the web card is ever revisited.
    warmcard = WarmReviewCard(root, popup)
    # warmcard.launch()  # dormant: native card is the default

    watcher_thread = threading.Thread(target=watch_loop, args=(popup, badge, root, warmcard), daemon=True)
    watcher_thread.start()
    log("watcher_thread started")

    # Settings, unlike the review card, IS launched warm by default (real ask
    # 2026-07-25): it's a real, deliberately-opened OS window (taskbar entry
    # is expected and fine here), not a floating overlay, so none of the
    # no-taskbar/no-activate reasoning that keeps the review card native
    # applies. reload_settings_from_disk is defined just below; passed in
    # this way rather than a forward reference since the class predates it.
    warm_settings = WarmSettingsWindow(lambda: root.after(0, reload_settings_from_disk))

    def quit_app(icon=None, item=None):
        if icon is not None:
            icon.stop()
        try:
            warmcard.quit()
        except Exception:
            pass
        try:
            warm_settings.quit()
        except Exception:
            pass
        root.after(0, root.quit)

    def reload_settings_from_disk():
        # The web settings window runs in a separate process and writes
        # settings.json; pull those changes into the live APP_SETTINGS (in
        # place, so watch_loop's next tick reflects them). Category/AI/badge
        # toggles are read live by the loop; launch-on-login is applied by the
        # settings process itself via the registry.
        try:
            new = load_settings()
            APP_SETTINGS.clear()
            APP_SETTINGS.update(new)
            # Badge is not draggable/pinnable anymore (2026-07-23), so there is
            # no pinned position to resync; keep it firmly on automatic.
            badge.user_positioned = None
            log("settings reloaded after web settings window closed")
        except Exception:
            log_exception("reload_settings_from_disk")

    def open_settings(icon=None, item=None):
        # Real ask 2026-07-25: this took 3-4s on EVERY click, a full cold
        # WebView2 engine boot each time. Fast path now: if the warm server
        # from a previous open is still alive, just tell it to show -- no new
        # process, no new engine, near-instant. Only the very first open in
        # a session (or a recovery after the warm server died) pays the old
        # cold-start cost, via the exact same subprocess spawn as before.
        if warm_settings.is_alive():
            if warm_settings.show():
                return
            log("warm settings show failed, falling back to a fresh spawn")

        # Open the new web-based settings as a subprocess. If it fails for any
        # reason (returns non-zero / can't spawn), fall back to the legacy Tk
        # settings so the control is never unreachable. pystray callbacks run
        # on the tray thread, so this runs off-thread and marshals Tk calls.
        def _run():
            if warm_settings.launch():
                # No explicit show() needed here: the server's window is
                # created with hidden=False, so it appears on its own once
                # pywebview finishes booting, at exactly today's cold-start
                # timing -- this launch call only wires up the WARM PROCESS
                # for every open after this one. Just confirm it didn't die
                # in the first couple seconds (missing WebView2 runtime,
                # import failure inside the subprocess, etc.) before
                # trusting it; a real cold boot easily exceeds this window,
                # so this only catches an immediate, total failure to start.
                for _ in range(20):  # ~2s
                    if not warm_settings.is_alive():
                        break
                    time.sleep(0.1)
                else:
                    return   # still alive past the crash-detection window: trust it
                log("warm settings server died immediately, falling back to one-shot")

            try:
                if getattr(sys, "frozen", False):
                    cmd = [sys.executable, "--web-settings"]
                else:
                    cmd = [sys.executable, os.path.abspath(__file__), "--web-settings"]
                flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
                proc = subprocess.Popen(cmd, creationflags=flags)
                proc.wait()
                if proc.returncode == 0:
                    reload_settings_from_disk()
                else:
                    log(f"web settings exited {proc.returncode}, falling back to Tk settings")
                    root.after(0, settings_window.show)
            except Exception:
                log_exception("open web settings")
                root.after(0, settings_window.show)
        threading.Thread(target=_run, daemon=True).start()

    # The card's own gear button (see SuggestionPopup header) reaches the
    # exact same Settings path as the tray menu, no duplicate open-settings
    # logic (2026-07-23: moved here from the badge, see popup.on_settings_click).
    popup.on_settings_click = open_settings

    tray_thread = threading.Thread(target=run_tray_icon, args=(quit_app, open_settings), daemon=True)
    tray_thread.start()
    log("tray_thread started")

    idle_thread = threading.Thread(target=run_keyboard_idle_watcher, daemon=True)
    idle_thread.start()
    log("idle_thread started")

    # Listens for another launch of the app (clicking its taskbar/desktop
    # icon) and opens settings in THIS instance instead of that launch
    # popping an "already running" box, see run_show_settings_listener.
    settings_listener_thread = threading.Thread(
        target=run_show_settings_listener, args=(open_settings,), daemon=True
    )
    settings_listener_thread.start()
    log("settings_listener_thread started")

    # Real fix 2026-07-20: boost the Tk main (UI) thread above the process
    # base priority, same reasoning as the input-hook thread. The whole
    # process runs at BELOW_NORMAL so the AI inference threads don't hog the
    # machine, but that also dragged the UI thread down, which is why the
    # loading card froze half-painted during generation. Raising just this
    # thread keeps the popup responsive while inference runs, without asking
    # Windows to prioritize the app over the rest of the system.
    try:
        ctypes.windll.kernel32.SetThreadPriority(
            ctypes.windll.kernel32.GetCurrentThread(), THREAD_PRIORITY_HIGHEST
        )
    except Exception:
        pass

    # First-run: offer the optional AI-model download once, only if it isn't
    # already present (real ask 2026-07-22). Flag is persisted immediately so
    # it shows exactly once regardless of how the user dismisses it.
    try:
        if (not APP_SETTINGS.get("ai_onboarding_shown")
                and not local_model.is_model_downloaded()):
            APP_SETTINGS["ai_onboarding_shown"] = True
            save_settings(APP_SETTINGS)

            # Prefer the new web-based first-run window (its own process, same
            # pattern as web settings); fall back to the legacy Tk onboarding
            # if it can't spawn or exits non-zero.
            def _first_run():
                try:
                    if getattr(sys, "frozen", False):
                        cmd = [sys.executable, "--onboarding"]
                    else:
                        cmd = [sys.executable, os.path.abspath(__file__), "--onboarding"]
                    flags = 0x08000000 if os.name == "nt" else 0
                    proc = subprocess.Popen(cmd, creationflags=flags)
                    proc.wait()
                    if proc.returncode == 0:
                        reload_settings_from_disk()
                    else:
                        log(f"web onboarding exited {proc.returncode}, falling back to Tk")
                        root.after(0, lambda: show_ai_onboarding(root, settings_window))
                except Exception:
                    log_exception("web onboarding launch")
                    root.after(0, lambda: show_ai_onboarding(root, settings_window))
            threading.Thread(target=_first_run, daemon=True).start()
    except Exception:
        log_exception("ai onboarding trigger")

    print(f"{BRAND_NAME} desktop watcher running. Focus any text field to test it.")
    print("Press Ctrl+C in this terminal to stop.")
    log("entering root.mainloop()")
    root.mainloop()
    log("root.mainloop() returned (app exiting)")


if __name__ == "__main__":
    # Inference-worker mode (real ask 2026-07-22, kill the UI freeze): the app
    # relaunches this same exe with --inference-worker to run the AI model in a
    # SEPARATE process, so a compress can never freeze the UI. This branch runs
    # BEFORE main(), so it never touches the single-instance mutex or the GUI.
    if "--inference-worker" in sys.argv:
        try:
            local_model.run_inference_worker()
        except Exception:
            log_exception("inference worker")
        sys.exit(0)
    # New web-based Settings window (2026-07-22 UI redesign), runs as its own
    # process so pywebview can own a main thread without fighting Tk/the tray.
    # Returns 0 when the window opened and closed normally, non-zero on any
    # failure so the launcher can fall back to the legacy Tk settings.
    if "--web-settings" in sys.argv:
        try:
            import webui
            sys.exit(webui.run())
        except Exception:
            log_exception("web settings")
            sys.exit(1)
    # Persistent WARM Settings window (real ask 2026-07-25): same shape as
    # the warm review-card server below, but this one hides on close rather
    # than starting hidden, since Settings is a real, deliberately-opened
    # window from the very first click, not an overlay staged in advance.
    if "--web-settings-server" in sys.argv:
        try:
            import webui
            sys.exit(webui.run_settings_server())
        except Exception:
            log_exception("web settings server")
            sys.exit(1)
    if "--onboarding" in sys.argv:
        try:
            import webui
            sys.exit(webui.run_onboarding())
        except Exception:
            log_exception("web onboarding")
            sys.exit(1)
    if "--review-card" in sys.argv:
        try:
            import webui
            i = sys.argv.index("--review-card")
            payload_path = sys.argv[i + 1]
            sys.exit(webui.run_reviewcard(payload_path))
        except Exception:
            log_exception("web review card")
            sys.exit(1)
    # Persistent WARM review card (2026-07-23): one long-lived process holding
    # a hidden WebView2 window the main app shows/hides/refreshes over stdin,
    # so the HTML card pops instantly instead of cold-starting per click.
    if "--review-card-server" in sys.argv:
        try:
            import webui
            sys.exit(webui.run_reviewcard_server())
        except Exception:
            log_exception("web review card server")
            sys.exit(1)
    # One-shot model download, no GUI (real ask 2026-07-24, going-to-market
    # hardening): the installer used to run its OWN separate downloader
    # (Inno Setup's built-in TDownloadWizardPage) to fetch the model during
    # setup, a completely different, less-tested code path than the one the
    # app itself uses from Settings/onboarding. That installer-only path hit
    # two real failures live (a genuine dropped connection at 94%, and once a
    # full, error-free completion that silently re-downloaded from scratch
    # anyway, both undebuggable since TDownloadWizardPage is a closed Inno
    # component). Rather than keep maintaining two divergent downloaders,
    # installer.iss now just runs THIS exe with --download-model right after
    # copying files, reusing local_model.download_model()'s own proven
    # per-file retry+backoff and atomic swap-into-place. Same as
    # --inference-worker: runs BEFORE main(), never touches the
    # single-instance mutex or the GUI. Exit 0 on success (or already
    # downloaded), 1 on any failure; installer.iss polls the same
    # download_progress.json Settings already reads for live progress.
    if "--download-model" in sys.argv:
        try:
            ok, err = local_model.download_model()
            if not ok:
                log(f"--download-model: failed ({err})")
            sys.exit(0 if ok else 1)
        except Exception:
            log_exception("--download-model")
            sys.exit(1)
    try:
        main()
    except Exception:
        log_exception("main()")
        raise
