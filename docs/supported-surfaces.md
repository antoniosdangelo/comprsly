# Where Comprsly works

What the app actually recognises today, read out of `product/backend/main.py` at
`APP_VERSION = "1.1.1"`, not from memory or the website. Rechecked line by line
on 2026-11-27 against the tables that do the deciding: `KNOWN_LLM_DOMAINS`,
`LLM_TITLE_HINTS`, `TERMINAL_HOST_PROCESSES`, `AI_CLI_DESCENDANT_PROCESSES` and
`AI_CLI_CMDLINE_MARKERS`.

Keep this file honest. It is the source for the website's claims, and the last
time the site described a feature nobody had checked, it told people to switch
terminals on individually in Settings when no such toggle has ever existed.

---

## Confirmed working

Badge placement on these was tested live and signed off on 2026-08-03.

| Surface | How it is recognised |
|---|---|
| Claude (claude.ai) | domain |
| Claude Code, in the browser | domain |
| Claude Code, in a terminal | terminal host process |
| Claude artifact side panel | domain |
| ChatGPT (chatgpt.com, chat.openai.com) | domain |
| Gemini (gemini.google.com) | domain |
| Gemini in the Chrome side panel | the control's accessible name |
| Perplexity (perplexity.ai) | domain |
| Grok (grok.com, x.ai) | domain |
| Copilot (copilot.microsoft.com) | domain |
| DeepSeek (chat.deepseek.com) | domain |

## Recognised, not individually verified

Matched by domain, so they should work, but nobody has sat down and checked
badge placement on each one.

Le Chat (chat.mistral.ai) · Poe · Hugging Face · You.com · Pi (pi.ai) ·
Character.AI

## Terminals

Windows Terminal · PowerShell · pwsh · Command Prompt · Git Bash · WSL · VS Code ·
Cursor · Windsurf

Matched on the host process, so any CLI agent running inside one of these is
covered: Claude Code, Gemini CLI, Codex CLI, Copilot CLI.

**AI CLIs detected inside a terminal**, measured 2026-11-23 with
`tools_measure_cli_trees.py`:

| CLI | How it is found | Why |
|---|---|---|
| Claude Code | `claude.exe` by name | ships a real binary |
| Copilot CLI | `copilot.exe` by name | ships a real binary |
| Codex CLI | `codex.exe` by name | spawns a native vendored binary beside its node shim |
| Gemini CLI | `@google/gemini-cli` in a `node.exe` command line | ships no binary at all; its whole tree is node, conhost, cmd and powershell |

Bare `node.exe` is never matched, and a test enforces that. Matching it would
light the badge under any node process: a dev server, a build, this repo's own
test runner. Command lines are read straight from the PEB rather than via
psutil or WMI, so this adds no dependency and no per tick cost, and it fails
closed: an unreadable command line means no match.

**There is no per terminal switch.** `APP_CATEGORIES = ("ai_chat",)` is the
only toggle in Settings and it covers everything.

---

## Not supported yet

| Surface | Why not | What it would take |
|---|---|---|
| ~~VS Code~~ | **Shipped in 1.1.1**, which is published in the Store. See below. | nothing, it is done |
| ~~Cursor~~ / ~~Windsurf~~ | Shipped on the same code path as VS Code. **Still unverified**, neither has ever been probed. | probe one and confirm the `Terminal ` prefix survives its rebranding |
| **(original note)** | **Not a recognition problem.** `tools_probe_surfaces.py` confirms VS Code exposes a proper focused `EditControl`, readable right now. `app_label_for()` simply returns nothing for `code.exe`. | Recognise `code.exe`, then tell the integrated terminal and chat panes apart from the code editor. Without that split the badge would appear while you are writing code, which is worse than not supporting it. |
| Cursor | same shape as VS Code, both are Electron and VS Code derived | same work, probably the same fix |
| Windsurf | same | same |
| LM Studio | never probed | run the probe while focused on its chat box |
| Claude desktop | Electron, often exposes no accessible control | probe first; may need the guessed position path |
| ChatGPT desktop | same | same |

### VS Code: measured, and now fully specified

Measured 2026-11-22 with `tools_probe_surfaces.py` and
`tools_scan_surfaces.py`. Not inferred.

**The focused control in VS Code's integrated terminal:**

```
EditControl  7x17  rect=(422,-467,429,-450)
name='Terminal 1, [kbd] Orchestrator  Run the command: Toggle Screen Reader...'
```

Three things fall out of that:

1. **VS Code is recognisable.** `app_label_for()` returns nothing for
   `code.exe`, which is the only reason the badge never appears. The input is
   readable the whole time.

2. **The integrated terminal announces itself.** The accessible name begins
   `Terminal <n>,` whenever focus is in the integrated terminal. That is the
   discriminator for the hard part, telling the terminal apart from the code
   editor, so the badge never turns up while you are writing code. It is the
   same mechanism the product already uses for Gemini's Chrome side panel via
   `KNOWN_SIDE_PANEL_NAME_PREFIXES`.

3. **The focused rect is the caret, not the box.** 7x17 pixels, and it moves
   horizontally as you type: successive readings came back at x=1244, 1409,
   1541, 1629, 1684, 1772, all at the same height. Anchoring to it would make
   the badge chase the cursor. The terminal pane is two levels up the ancestor
   chain, a `GroupControl` at 1001x612. The parent directly above the caret
   shares the caret's own 7x17 rect, so the walk has to continue past it.

**Implemented 2026-11-22** on branch `product/vscode-surface`, and **shipped in
1.1.1**, which is published in the Store:

- `code.exe`, `cursor.exe` and `windsurf.exe` joined `TERMINAL_HOST_PROCESSES`,
  so they pass through the same AI-CLI-descendant gate as every other
  terminal. A VS Code window with no AI CLI running under it stays inactive.
- `_vscode_focus_is_terminal()` additionally requires the focused control's
  name to START WITH `Terminal `. Prefix, never substring: this file already
  carries a bug from an anywhere-in-the-title rule firing on the wrong pages.
- `_vscode_terminal_pane_rect()` walks up from the caret to the pane,
  continuing past the parent that shares the caret's own rect.
- Everything fails closed. No focused control, an unreadable name, a UIA
  exception: all return hidden, because a badge over somebody's source code is
  worse than no VS Code support.

Confirmed live on this machine:

```
foreground process:      code.exe
focus is terminal pane:  True
app_label_for ->         'Claude Code'
focused (caret):         EditControl 7x17
resolved pane:           1001x850
```

`test_vscode_surface.py` covers it: 14 tests, weighted to the negative cases
(editor, Settings, empty name, substring near-miss, no control, UIA raising).

**Cursor and Windsurf are unverified.** They are VS Code forks on the same code
path, but neither was running to probe, so nobody has confirmed the `Terminal `
prefix survives their rebranding. Probe before claiming them anywhere.

### An earlier wrong conclusion, corrected twice

Worth recording, because the same mistake nearly got made twice in one hour.

**First wrong conclusion:** `debug.log` said `no editable text field in
code.exe`, which was taken to mean VS Code's input is unreadable. The focused
probe disproved it: a real `EditControl` is there.

**Second wrong conclusion:** the first version of `tools_scan_surfaces.py`
counted `DocumentControl` as an input and duly reported VS Code as
`ADDABLE: exposes a real input`. That control was the whole 1920x1032 window,
which is exactly the false positive `main.py` already rejects in its
`page_level` branch. The scanner now excludes window level controls and applies
the same 60% of window backstop, after which VS Code correctly reports
`HARD: no readable input exposed` on an unfocused walk.

**Both wrong for the same reason:** a tree walked without focus and a tree
walked with focus are different trees. Electron builds the accessible subtree
lazily. The unfocused scan is useful for a quick inventory; only the focused
probe can be trusted for a verdict on a specific app.

---

## The phantom badge

Open bug: the badge has appeared with no chat or terminal on screen.

Most likely cause, from `main.py`'s own comment on the hide logic:

> Deliberately NOT keyed on raw_rect being None too: that also covers apps with
> NO accessible control at all (Claude's Electron composer, a terminal), where
> the fallback-guess branch below is the correct PERMANENT strategy

So when the app recognises the **process** but can nothing readable, it does
not hide. It guesses a position and shows anyway. That is deliberate, because
Electron apps and terminals expose nothing to read, but it means a recognised
process with no visible window can still produce a badge. The recognised list
includes `conhost.exe`, `git.exe` and `wsl.exe`, any of which can be focused
with no terminal on screen.

Supporting evidence from a real `debug.log`: two terminal badge rects came back
as `(0, 1362, 2256, 1432)`, the full width of the screen pinned to the bottom.
That is not a text box, it is a guess.

**Not yet confirmed.** `tools_probe_surfaces.py` flags this case as
`GUESSED POSITION <-- phantom badge risk` on every tick, so the next sighting
is captured rather than reconstructed.

---

## Running the probe

**Broken by the restructure, not yet fixed.** The probe lives in `product/tools/`
now and `main.py` in `product/backend/`, but the script still does
`sys.path.insert(0, HERE)` and then `import main`, so it dies with
`ModuleNotFoundError: No module named 'main'` from any directory. Confirmed
2026-11-27. `tools_measure_cli_trees.py` and `tools_scan_surfaces.py` have the
same one wrong line; `measure_vscode_pane.py` already points at `backend`, which
is the fix to copy.

Once that is fixed, the run is:

```
cd product/tools
"C:/Users/anton/AppData/Local/Python/pythoncore-3.14-64/python.exe" tools_probe_surfaces.py
```

Click into each app, type a few characters, Ctrl+C to stop. Writes
`probe-surfaces.jsonl` next to itself.

It is read only and imports `main.py` without starting it, so it is safe to run
while Comprsly itself is running. It changes no settings, no registry and no
window.
