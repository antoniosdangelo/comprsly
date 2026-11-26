"""Dump the real ancestor chain above VS Code's terminal caret.

_vscode_terminal_pane_rect picks the first ancestor whose area is at least 20x
the caret's. Live logs show that choice landing on a DIFFERENT node as the
caret moves, which is why the badge never holds still. This prints the whole
chain with rects so the right rule can be chosen from data instead of guessed.

Read only. Run it while the terminal has focus; it does not steal focus.

    python measure_vscode_pane.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))

import uiautomation as auto


def dump(tag):
    try:
        node = auto.GetFocusedControl()
    except Exception as e:
        print("  no focused control: %r" % (e,))
        return
    if node is None:
        print("  no focused control")
        return
    try:
        r = node.BoundingRectangle
    except Exception as e:
        print("  unreadable caret: %r" % (e,))
        return
    caret_area = max(1, (r.right - r.left) * (r.bottom - r.top))
    print("\n[%s] caret name=%r rect=(%d,%d,%d,%d) area=%d"
          % (tag, (node.Name or "")[:40], r.left, r.top, r.right, r.bottom, caret_area))
    chosen = None
    cur = node
    for i in range(1, 11):
        try:
            cur = cur.GetParentControl()
        except Exception:
            break
        if cur is None:
            break
        try:
            pr = cur.BoundingRectangle
        except Exception:
            break
        area = (pr.right - pr.left) * (pr.bottom - pr.top)
        ratio = area / caret_area
        mark = ""
        if chosen is None and ratio >= 20:
            chosen = i
            mark = "   <-- what the code picks today"
        print("  up %-2d %-22s %-28s rect=(%5d,%5d,%5d,%5d) %4dx%-4d ratio=%7.1f%s"
              % (i, cur.ControlTypeName, repr((cur.Name or "")[:24]),
                 pr.left, pr.top, pr.right, pr.bottom,
                 pr.right - pr.left, pr.bottom - pr.top, ratio, mark))


print("Focus the terminal and type. Sampling 4 times over 12 seconds.")
print("If the chosen row changes between samples, that is the bug.")
for n in range(4):
    dump("sample %d" % (n + 1))
    time.sleep(4)
