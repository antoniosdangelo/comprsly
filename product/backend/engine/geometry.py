"""Where things go on screen, and what colour the badge is.

Arithmetic on rectangles and numbers. No OS call, no window handle, no toolkit,
so this is identical on macOS and it is the easiest part of the app to test.

Two functions take values that used to be read from module constants in
main.py. That is deliberate: those constants are DPI scaled, and DPI is an
operating system concept, so the numbers belong to the platform layer and the
maths belongs here. The platform passes them in.

_pane_bottom_row carries the most history in this file. The terminal badge was
reported three times for moving around, and the first two attempts anchored it
to the caret's line, which moves. Read its docstring before changing it.
"""

import colorsys


class _SimpleRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


# Terminal badge rule (2026-11-25, Antonio, by name): on every terminal the
# badge sits at the RIGHT END OF THE INPUT LINE, inside the pane, and never on
# top of typed text. Measured from the live log first: in VS Code the focused
# control is the 11 px wide caret, and _position_for treats anything under
# 100 px wide as "dock just LEFT of it", so the badge rode on top of the text
# the user had just typed. _vscode_terminal_pane_rect existed for exactly this
# and was never called.
#
# REWRITTEN 2026-11-26 after Antonio's screenshot. Putting the badge on the
# caret's own line and then checking whether text had reached it was the wrong
# shape of fix: the badge is 38 px and a terminal line is 17, so it bled a line
# up and a line down whatever column it was in, and it sat on a word on the
# line above. Both of that day's screenshots are that, not a column error.
#
# The row ONE LINE BELOW the caret is the input box's bottom border. In every
# CLI that draws a box you type on the last line, so that row is decoration and
# can never hold text. Aim there and the collision question stops existing:
# nothing to detect, nothing to dodge, nothing to get wrong by a few pixels. It
# is a fixed offset from the caret rather than a check that flips, so the badge
# also stops hopping, which is the other half of what he reported.
#
# The badge is drawn at the line's own height (see PersistentBadge._size) so it
# fits that row exactly.
def _pane_bottom_row(left, right, pane_bottom, line_h):
    """The last row of the terminal pane, docked right.

    REWRITTEN AGAIN 2026-11-26, third attempt, and this time against the only
    complaint Antonio has actually repeated: "why can't it just stay in one
    place", and "can it sit below the terminal lines".

    The first two attempts both tied the badge to the CARET's line, once
    directly and once one row below it. Both move, because the caret moves:
    every wrap, every newline, every time the input box grows, the badge jumps
    with it. Dropping a row made it collide less, it did not make it hold
    still, so it never addressed what he was asking for.

    The pane's own bottom row does not move while you type. The input box
    grows upward from it, the caret travels around above it, and this row
    stays exactly where it is for as long as the window is that size. It is
    also below every line of input, which is literally what he asked for, and
    the one row no typed text ever reaches, so the collision question stays
    closed.

    The only thing that lives on this row is the CLI's own status line, which
    is short and left aligned, so the right end of it is empty.
    """
    return _SimpleRect(left, pane_bottom - line_h, right, pane_bottom)


def _heat_color(count, heat_max):
    """Green (clean) -> red (lots to fix), through yellow/orange. Uses HSV
    hue 120deg->0deg so it passes through natural yellow/orange rather than
    the muddy brown a straight green->red RGB blend would give."""
    t = min(count / heat_max, 1.0) if heat_max > 0 else 0.0
    hue = (120.0 - 120.0 * t) / 360.0  # 120=green, 0=red
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.88)
    return (int(r * 255), int(g * 255), int(b * 255), 255)


def _badge_inset_for(app_label, base_inset, overrides):
    """Distance from the box's right edge to the badge's right edge.

    One source of truth, because two places need the same number: _position_for
    puts the badge there, and _terminal_badge_rect has to know which column it
    landed in to keep typed text out from under it. Those two drifted apart on
    the first pass (the terminal one left the override out) and let Claude Code
    type about seven characters under its own badge.
    """
    return base_inset + overrides.get(app_label, 0)
