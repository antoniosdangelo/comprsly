"""
Measure the real process tree of an AI CLI.

Answers the only question that matters for detection: when Codex or Gemini is
running in a terminal, what processes actually exist underneath it, and what
are their command lines?

Measurement only. Nothing here ships, and it may use tools the product cannot
(PowerShell CIM for command lines) precisely so the shipped code does not have
to guess.

    python tools_measure_cli_trees.py codex
    python tools_measure_cli_trees.py gemini
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import main as app

SHIMS = {
    "codex": r"C:\Users\anton\AppData\Roaming\npm\codex.cmd",
    "gemini": r"C:\Users\anton\AppData\Roaming\npm\gemini.cmd",
}


def cmdlines_by_pid():
    """pid -> command line, via CIM. Measurement only; never used in-product."""
    ps = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, timeout=120,
    ).stdout
    try:
        rows = json.loads(out)
    except Exception:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    return {r["ProcessId"]: (r.get("Name") or "", r.get("CommandLine") or "") for r in rows}


def descendants(root_pid, snapshot):
    kids = {}
    for pid, (parent, _name) in snapshot.items():
        kids.setdefault(parent, []).append(pid)
    out, queue, seen = [], list(kids.get(root_pid, [])), set()
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        queue.extend(kids.get(pid, []))
    return out


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "codex").lower()
    shim = SHIMS.get(which)
    if not shim or not os.path.exists(shim):
        sys.exit(f"no shim for {which!r}")

    print(f"Launching {which} and letting it settle...")
    proc = subprocess.Popen(
        ["cmd.exe", "/c", shim],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=0x00000008 | 0x08000000,   # DETACHED_PROCESS | NO_WINDOW
    )
    try:
        time.sleep(9)
        snapshot = app._process_tree_snapshot()
        cmds = cmdlines_by_pid()
        pids = descendants(proc.pid, snapshot)

        print(f"\nlauncher pid {proc.pid}, {len(pids)} descendants\n")
        print(f"{'pid':<8} {'process':<26} command line")
        print("-" * 118)
        for pid in pids:
            name = snapshot.get(pid, (None, "?"))[1]
            cl = cmds.get(pid, ("", ""))[1]
            print(f"{pid:<8} {name:<26} {cl[:78]}")

        print("\n--- what a detector could match on ---")
        names = sorted({snapshot.get(p, (None, "?"))[1] for p in pids})
        print("process names:", ", ".join(names) or "(none)")
        for marker in ("@openai/codex", "@openai\\codex", "@google/gemini-cli", "@google\\gemini-cli"):
            hits = [p for p in pids if marker in cmds.get(p, ("", ""))[1]]
            if hits:
                print(f"cmdline marker {marker!r} matches pids {hits}")
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
        print("\ncleaned up.")


if __name__ == "__main__":
    main()
