"""Spotting an AI CLI running under a terminal, on macOS.

The Windows layer walks the process tree with Toolhelp32 and reads each
process's command line out of its PEB, because WMI costs about a second and
the watch loop runs every 0.7s. macOS has no PEB; `ps` is the portable way to
get both the parent and the full command line in one call, and it is fast
enough because it is a single process spawn rather than one per candidate.

The matching rules themselves are shared with Windows on purpose. Codex ships
a real binary, Gemini ships none at all and has to be recognised from the node
command line, and bare `node` must NEVER match or the badge appears under any
dev server. That last rule has a test on the Windows side and the same rule is
applied here rather than reinvented.
"""

import subprocess

# Terminal hosts on macOS. VS Code and its forks carry the same caveat as on
# Windows: the window also holds a code editor, so being in one of these is not
# on its own enough, focus has to be in the terminal pane.
TERMINAL_HOST_BUNDLES = {
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "dev.warp.Warp-Stable",
    "co.zeit.hyper",
    "com.microsoft.VSCode",
    "com.todesktop.230313mzl4w4u92",   # Cursor
    "com.exafunction.windsurf",
}

VSCODE_BUNDLES = {
    "com.microsoft.VSCode",
    "com.todesktop.230313mzl4w4u92",
    "com.exafunction.windsurf",
}

# Same names the Windows layer matches, minus the .exe.
AI_CLI_PROCESSES = {
    "claude": "Claude Code",
    "copilot": "Copilot CLI",
    "codex": "Codex CLI",
}

# Gemini ships no binary of its own, so it is recognised from the node command
# line, exactly as on Windows.
AI_CLI_CMDLINE_MARKERS = (
    ("@google/gemini-cli", "Gemini CLI"),
    ("@openai/codex", "Codex CLI"),
)

# Only these have their command line inspected. Never add a bare interpreter
# beyond node, and never match node by name alone.
CMDLINE_CHECK_PROCESSES = {"node"}


def process_table():
    """{pid: (ppid, command_name, full_command_line)} for every process.

    One `ps` call. Returns an empty dict rather than raising, so a failure here
    hides the badge instead of crashing the watch loop.
    """
    try:
        out = subprocess.run(
            ["ps", "-Ao", "pid=,ppid=,comm=,args="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return {}
    table = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        comm = parts[2].rsplit("/", 1)[-1]
        args = parts[3] if len(parts) > 3 else ""
        table[pid] = (ppid, comm, args)
    return table


def descendants(root_pid, table):
    """Every pid under root_pid, breadth first."""
    children = {}
    for pid, (ppid, _c, _a) in table.items():
        children.setdefault(ppid, []).append(pid)
    out, queue, seen = [], list(children.get(root_pid, [])), set()
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        queue.extend(children.get(pid, []))
    return out


def ai_cli_under(root_pid, table=None):
    """The label of an AI CLI running under this terminal, or None.

    Fails closed: no match means no badge.
    """
    table = process_table() if table is None else table
    if not table:
        return None
    for pid in descendants(root_pid, table):
        _ppid, comm, args = table[pid]
        label = AI_CLI_PROCESSES.get(comm)
        if label:
            return label
        if comm in CMDLINE_CHECK_PROCESSES:
            for marker, marker_label in AI_CLI_CMDLINE_MARKERS:
                if marker in args:
                    return marker_label
    return None
