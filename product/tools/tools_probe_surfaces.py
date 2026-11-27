"""
Surface probe: what does Comprsly actually see in each app?

Answers two questions at once, which is why it is one tool:

  1. THE PHANTOM BADGE. The badge has appeared with no chat or terminal on
     screen. This records the real decision, tick by tick, so the next
     sighting is captured in the act rather than reconstructed afterwards.

  2. NEW SURFACES. VS Code, Cursor, Windsurf, LM Studio, the Claude and
     ChatGPT desktop apps. Before any of them can be supported we need to know
     what Windows actually exposes for their input box, which is exactly what
     this prints.

It imports the REAL functions out of main.py rather than reimplementing them,
so what it reports is what the product would decide, not a lookalike. main.py
is guarded by `if __name__ == "__main__"`, so importing it starts nothing.

NOTHING HERE TOUCHES THE SHIPPED APP. It is read only: no settings, no
registry, no badge, no window. Safe to run while Comprsly itself is running.

Run:
    "C:/Users/anton/AppData/Local/Python/pythoncore-3.14-64/python.exe" tools_probe_surfaces.py

Then click into each app you care about and type a few characters. Ctrl+C to
stop. A table and a JSONL log land next to this file.
"""

import ctypes
import json
import os
import sys
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
# main.py lives in product/backend, not beside this file. Inserting HERE
# instead was how all three of these tools died in the 2026-11-26 restructure.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))

try:
    import uiautomation as auto
except ImportError:
    sys.exit("uiautomation is missing. Run: pip install -r ../build/requirements.txt")

# main.py is import safe; its entry point sits behind a __main__ guard.
import main as app

OUT = os.path.join(HERE, "probe-surfaces.jsonl")
POLL_SECONDS = 0.7

# Control types that can genuinely hold typed text. Anything else focused
# means there is no composer here, whatever the app is.
EDITABLE = {"EditControl", "DocumentControl", "TextControl", "ComboBoxControl"}


def foreground():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    return hwnd, app._process_name_for_hwnd(hwnd)


def window_title(hwnd):
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def describe_focus():
    """One observation of whatever currently has focus."""
    hwnd, process = foreground()
    row = {
        "at": datetime.now().strftime("%H:%M:%S"),
        "process": process,
        "title": window_title(hwnd)[:90],
        "app_label": None,
        "control_type": None,
        "control_name": None,
        "rect": None,
        "has_text": None,
        "is_editable": None,
        "verdict": None,
        "why": None,
    }

    try:
        row["app_label"] = app.app_label_for(process, hwnd)
    except Exception as err:
        row["why"] = f"app_label_for raised: {err!r}"

    try:
        node = auto.GetFocusedControl()
    except Exception as err:
        node = None
        row["why"] = f"GetFocusedControl raised: {err!r}"

    if node is not None:
        try:
            row["control_type"] = node.ControlTypeName
            row["control_name"] = (node.Name or "")[:70]
            r = node.BoundingRectangle
            row["rect"] = [r.left, r.top, r.right, r.bottom]
            row["is_editable"] = node.ControlTypeName in EDITABLE
            try:
                pattern = node.GetValuePattern()
                row["has_text"] = bool((pattern.Value or "").strip())
            except Exception:
                row["has_text"] = None
        except Exception as err:
            row["why"] = f"reading the control raised: {err!r}"

    # The product's own rule: a recognized app plus a real editable control.
    if not row["app_label"]:
        row["verdict"] = "HIDDEN (app not recognized)"
    elif row["control_type"] is None:
        # This is the branch behind the phantom badge. main.py treats "no
        # accessible control" as normal for Electron apps and terminals and
        # guesses a position instead of hiding, so a recognized PROCESS with
        # nothing readable can still light up a badge.
        row["verdict"] = "GUESSED POSITION  <-- phantom badge risk"
        row["why"] = "app recognized but no control readable at all"
    elif row["control_type"] in app._NEVER_A_COMPOSER_CONTROL_TYPES:
        row["verdict"] = "HIDDEN after 4 ticks (not a composer)"
    elif not row["is_editable"]:
        row["verdict"] = "HIDDEN (control is not editable)"
    else:
        row["verdict"] = "SHOWN"
    return row


def main():
    print(__doc__.strip().split("Run:")[0].strip())
    print("\n" + "=" * 100)
    print(f"Writing to {OUT}")
    print("Click into each app and type a few characters. Ctrl+C to stop.\n")
    header = f"{'time':<9} {'process':<22} {'label':<13} {'control':<18} {'verdict'}"
    print(header)
    print("-" * 100)

    seen = {}
    last_key = None
    with open(OUT, "a", encoding="utf-8") as fh:
        while True:
            try:
                row = describe_focus()
            except Exception:
                traceback.print_exc()
                time.sleep(POLL_SECONDS)
                continue

            fh.write(json.dumps(row) + "\n")
            fh.flush()

            # Only print when the picture actually changes, so the table stays
            # readable instead of scrolling the same line forever.
            key = (row["process"], row["control_type"], row["verdict"])
            if key != last_key:
                last_key = key
                print(
                    f"{row['at']:<9} {(row['process'] or '?')[:21]:<22} "
                    f"{(row['app_label'] or '-')[:12]:<13} "
                    f"{(row['control_type'] or 'none')[:17]:<18} {row['verdict']}"
                )
            seen.setdefault(row["process"], row)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\nStopped. Full record: {OUT}")
        print("Send that file back and it tells us exactly what each app exposes.")
