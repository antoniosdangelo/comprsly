# Where Comprsly works

What the app actually recognises today, read out of `desktop/main.py` at
`APP_VERSION = "1.0.67"`, not from memory or the website.

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

Windows Terminal · PowerShell · pwsh · Command Prompt · Git Bash · WSL

Matched on the host process, so any CLI agent running inside one of these is
covered: Claude Code, Gemini CLI, Codex CLI, Copilot CLI.

**There is no per terminal switch.** `APP_CATEGORIES = ("ai_chat",)` is the
only toggle in Settings and it covers everything.

---

## Not supported yet

| Surface | Why not | What it would take |
|---|---|---|
| **VS Code** | **Not a recognition problem.** `tools_probe_surfaces.py` confirms VS Code exposes a proper focused `EditControl`, readable right now. `app_label_for()` simply returns nothing for `code.exe`. | Recognise `code.exe`, then tell the integrated terminal and chat panes apart from the code editor. Without that split the badge would appear while you are writing code, which is worse than not supporting it. |
| Cursor | same shape as VS Code, both are Electron and VS Code derived | same work, probably the same fix |
| Windsurf | same | same |
| LM Studio | never probed | run the probe while focused on its chat box |
| Claude desktop | Electron, often exposes no accessible control | probe first; may need the guessed position path |
| ChatGPT desktop | same | same |

### The VS Code finding, in full

An earlier reading of `debug.log` showed `no editable text field in code.exe`
and was taken to mean VS Code's input is unreadable. **That was wrong.** The
probe, which imports the product's own functions rather than guessing, reports:

```
process     control       verdict
code.exe    EditControl   HIDDEN (app not recognized)
```

The field is readable. The app is simply not on the list. That makes VS Code a
much smaller job than it looked, with the real work being to avoid lighting up
in the editor itself.

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

```
cd desktop
"C:/Users/anton/AppData/Local/Python/pythoncore-3.14-64/python.exe" tools_probe_surfaces.py
```

Click into each app, type a few characters, Ctrl+C to stop. Writes
`probe-surfaces.jsonl` next to itself.

It is read only and imports `main.py` without starting it, so it is safe to run
while Comprsly itself is running. It changes no settings, no registry and no
window.
