"""
Surface scanner: inspect every running app at once, without touching focus.

The sibling tool, tools_probe_surfaces.py, watches whatever the user clicks
into. Useful, but it needs someone sitting there clicking. This one instead
enumerates every visible top level window and walks each one's accessibility
tree looking for a real input box, so one run answers "what would Comprsly see
in each of these?" for everything open right now.

What it cannot do: GetFocusedControl only works on the focused window, so this
reports whether an app EXPOSES an editable control, not which one has focus.
That is exactly the question that matters for adding a new surface.

Read only. No settings, no registry, no window, no focus changes. Safe to run
while Comprsly itself is running.

    "C:/Users/anton/AppData/Local/Python/pythoncore-3.14-64/python.exe" tools_scan_surfaces.py
"""

import ctypes
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import uiautomation as auto

import main as app

OUT = os.path.join(HERE, "scan-surfaces.json")

u = ctypes.windll.user32
k = ctypes.windll.kernel32

# DocumentControl is deliberately NOT here. A window level DocumentControl
# matches almost every Electron app and spans the whole window, which is the
# exact false positive main.py already rejects (see its page_level branch).
# Counting it would report "addable" for anything with a web view in it.
EDITABLE = {"EditControl", "ComboBoxControl"}
# TextControl only counts inside a terminal, where the whole screen buffer is
# a TextControl. Elsewhere it is almost always a label.
TERMINAL_TEXT_HINTS = ("termcontrol", "terminal", "console")

# Apps worth a verdict even when they are not recognised yet.
INTERESTING = {
    "code.exe": "VS Code",
    "cursor.exe": "Cursor",
    "windsurf.exe": "Windsurf",
    "lm studio.exe": "LM Studio",
    "lmstudio.exe": "LM Studio",
    "claude.exe": "Claude desktop",
    "chatgpt.exe": "ChatGPT desktop",
    "windowsterminal.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell 7",
    "wt.exe": "Windows Terminal",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "obsidian.exe": "Obsidian",
    "notion.exe": "Notion",
}


def process_for(hwnd):
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = k.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(32768)
        if k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        k.CloseHandle(handle)
    return ""


def title_for(hwnd):
    n = u.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def visible_windows():
    out = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))

    def cb(hwnd, _lp):
        if not u.IsWindowVisible(hwnd):
            return True
        title = title_for(hwnd)
        if not title:
            return True
        out.append((hwnd, process_for(hwnd), title))
        return True

    u.EnumWindows(CB(cb), None)
    return out


def find_inputs(hwnd, budget_seconds=8.0, max_depth=22, max_nodes=12000):
    """Breadth first walk for anything that could hold typed text.

    Bounded hard: some Electron trees are enormous and a full walk would hang
    the scan. Hitting a limit is reported rather than hidden, so a 'none' is
    never confused with 'gave up'.
    """
    started = time.time()
    seen = 0
    hits = []
    truncated = False
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception as err:
        return {"error": repr(err)[:120], "inputs": [], "truncated": False, "nodes": 0}
    if root is None:
        return {"error": "no UIA root", "inputs": [], "truncated": False, "nodes": 0}

    try:
        wr = root.BoundingRectangle
        win_area = max(0, (wr.right - wr.left) * (wr.bottom - wr.top))
    except Exception:
        win_area = 0

    queue = [(root, 0)]
    while queue:
        if time.time() - started > budget_seconds or seen > max_nodes:
            truncated = True
            break
        node, depth = queue.pop(0)
        seen += 1
        try:
            ctype = node.ControlTypeName
            name = (node.Name or "")[:60]
        except Exception:
            continue

        is_input = ctype in EDITABLE
        if ctype == "TextControl" and any(h in name.lower() for h in TERMINAL_TEXT_HINTS):
            is_input = True

        if is_input:
            try:
                r = node.BoundingRectangle
                rect = [r.left, r.top, r.right, r.bottom]
                area = (r.right - r.left) * (r.bottom - r.top)
            except Exception:
                rect, area = None, 0
            # Zero size controls are offscreen or collapsed; not a real box.
            # Same backstop main.py uses: a control covering most of the
            # window is a page, not a box. Measured against the window rather
            # than the monitor, since this walks unfocused windows too.
            if area > 0 and rect and win_area > 0:
                spans_window = area >= win_area * 0.6
                if not spans_window:
                    hits.append({"type": ctype, "name": name, "rect": rect})
                    if len(hits) >= 6:
                        break

        if depth < max_depth:
            try:
                for child in node.GetChildren():
                    queue.append((child, depth + 1))
            except Exception:
                pass

    return {"error": None, "inputs": hits, "truncated": truncated, "nodes": seen}


def main():
    print("Scanning every visible window. Read only, nothing is clicked or focused.\n")
    rows = []
    for hwnd, process, title in visible_windows():
        if not process:
            continue
        try:
            label = app.app_label_for(process, hwnd)
        except Exception:
            label = None

        known_terminal = process in app.TERMINAL_HOST_PROCESSES
        interesting = process in INTERESTING or label or known_terminal
        if not interesting:
            continue

        probe = find_inputs(hwnd)
        inputs = probe["inputs"]

        if label:
            verdict = "SUPPORTED" if inputs else "SUPPORTED, but nothing readable (guessed position)"
        elif inputs:
            verdict = "ADDABLE: exposes a real input, just not recognised"
        elif probe["truncated"]:
            verdict = "UNKNOWN: tree too large to walk in budget"
        else:
            verdict = "HARD: no readable input exposed"

        rows.append({
            "process": process,
            "friendly": INTERESTING.get(process, process),
            "title": title[:70],
            "app_label": label,
            "recognised": bool(label),
            "inputs": inputs,
            "input_count": len(inputs),
            "truncated": probe["truncated"],
            "nodes_walked": probe["nodes"],
            "error": probe["error"],
            "verdict": verdict,
        })

    # One row per process: the window with the most readable inputs wins.
    best = {}
    for r in rows:
        prev = best.get(r["process"])
        if prev is None or r["input_count"] > prev["input_count"]:
            best[r["process"]] = r

    print(f"{'app':<20} {'process':<22} {'label':<12} {'inputs':<7} verdict")
    print("-" * 108)
    for r in sorted(best.values(), key=lambda x: (not x["recognised"], x["process"])):
        print(f"{r['friendly'][:19]:<20} {r['process'][:21]:<22} "
              f"{(r['app_label'] or '-')[:11]:<12} {r['input_count']:<7} {r['verdict']}")

    payload = {"scanned_at": datetime.now().isoformat(timespec="seconds"),
               "app_version": app.APP_VERSION, "rows": list(best.values())}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nFull detail: {OUT}")


if __name__ == "__main__":
    main()
