# Comprsly

Comprsly fixes your spelling and grammar as you type in AI chats, then optionally shortens the whole prompt using a small AI model that runs entirely on your own PC.

Website: [comprsly.com](https://comprsly.com) · Microsoft Store: [Get Comprsly](https://apps.microsoft.com/detail/9N8W5HPJ4DHV)

**Versions.** The Microsoft Store has **1.1.1**, the same version this repo is on, in both `main` and `sandbox`. 1.1.1 is what added Codex CLI, Gemini CLI and Copilot CLI detection, and the integrated terminal in VS Code, Cursor and Windsurf.

**Platforms.** Windows is the only released platform. A macOS version is built and in testing, with no release and no download, see section 7.

## 1. What you need

**Windows 10 or Windows 11.** Comprsly reads Windows text fields directly, so this is what the shipped app runs on. There is no Linux version.

**Fully tested AI chats:** Claude (including Claude Code), ChatGPT, Gemini (including the Chrome side panel), Perplexity, Copilot, Grok, DeepSeek.

**Also recognized:** Le Chat, Poe, Hugging Face, You.com, Pi, Character.AI.

**Terminals:** Windows Terminal, PowerShell, pwsh, Command Prompt, Git Bash, WSL, and the integrated terminal in VS Code, Cursor and Windsurf. VS Code was measured live; Cursor and Windsurf take the same code path but nobody has confirmed them yet.

A terminal only wakes Comprsly up when an AI CLI is actually running in it, so a plain shell prompt stays untouched. The CLIs it finds: **Claude Code, Codex CLI, Copilot CLI, Gemini CLI.**

It works in the browser and in desktop apps. Everywhere else it stays out of the way, by design.

## 2. Install

1. Open the [Microsoft Store listing](https://apps.microsoft.com/detail/9N8W5HPJ4DHV) and click Get.
2. Launch Comprsly once. A short setup screen walks you through it.
3. Close the window. Comprsly keeps running in the background and appears when you type in a supported app.

It is free, and there is no account to create.

## 3. First use

Type or paste anything into a supported AI chat. A small round Comprsly badge appears in the corner of the box. Click it.

**Step 1, spelling and grammar.** You get a list of fixes with the old text struck through and the correction beside it, each tagged with its kind, like spelling or grammar. Confident fixes are already ticked. Less certain ones are left unticked for you to check. Click **Apply** to make the ticked changes, or **Dismiss** to leave your text alone.

**Step 2, make it concise.** This is optional and runs the local AI model. It rewrites your prompt shorter, then shows your original and the shortened version side by side with how many tokens it saved. Nothing is changed until you click **Apply**.

Your text is never altered without you clicking.

## 4. Settings, and turning things off

Right click the Comprsly icon in the system tray and open Settings. There are four pages.

| Page | What is there |
|---|---|
| **General** | Light and dark theme, and the **AI chat apps** toggle |
| **AI** | Turn the shortening step on or off, and manage the model |
| **History** | Your token savings for the last 7 days |
| **About** | Version and links |

**To stop Comprsly appearing anywhere** without uninstalling it, turn off **AI chat apps** on the General page. It is the only such switch: there is no per app or per terminal toggle.

**To keep spelling and grammar but drop the AI shortening**, turn off the toggle on the AI page. Spelling and grammar need no model and keep working.

**To free up space or memory**, the AI page can **Unload from memory** (keeps the model on disk) or **Remove from device** (deletes it, about 1 GB back). You can download it again from the same page later.

## 5. Privacy

**Nothing you type ever leaves your computer.**

- Spelling and grammar run on your PC with a rules engine. No model and no network.
- The shortening step uses a small open model that runs locally on your CPU.
- There is no account, no sign in, and no telemetry.
- The only time Comprsly uses the network is getting the app itself, and downloading the model again if you removed it.

Settings, history and logs live in `%LOCALAPPDATA%\Comprsly`, on your machine only.

Full policy: [comprsly.com/privacy](https://comprsly.com/privacy/)

## 6. Building from source

The app is Python and lives in `product/`.

```
pip install -r product/build/requirements.txt
python product/backend/main.py
```

The tests:

```
python -m unittest discover -s product/backend -p "test_*.py"
```

That is the same command CI runs, on a Windows runner, because `main.py` reaches for a Windows API as it imports. Building the installer and the Microsoft Store package is covered in `docs/Build.md`.

### What is in this repo

| Folder | What it is | Built with |
|---|---|---|
| `product/` | **The app, the main product** | Python |
| `product/backend/` | Its engine: detection, grammar, the local model, and the tests | Python |
| `product/backend/engine/` | The part that is the same on every platform: geometry and storage | Python |
| `product/backend/platform_mac/` | The macOS platform layer, the sibling of `main.py` | Python |
| `product/frontend/` | What you see: the settings and review screens, icons | HTML, CSS |
| `product/build/` | Packaging: the PyInstaller specs, Inno Setup, the Store manifest | |
| `product/tools/` | Dev only scripts, never shipped | Python |
| `docs/` | How to build and release it, and what it recognizes | |
| `.github/workflows/` | Compile, tests and secret scan on every PR, plus the Windows and macOS builds | |

### First time on a new machine

1. `git clone https://github.com/antoniosdangelo/comprsly.git`
2. `cd comprsly`
3. `git config core.hooksPath .githooks` to turn on the secret check and the main branch push guard
4. Install the app's Python dependencies: `pip install -r product/build/requirements.txt`

### Branches

`main` is tested code. `sandbox` is where new work goes first. Work branches are one per side, `backend/...` or `frontend/...`, merged into `sandbox` and then deleted. Full rules in `BRANCHING.md`.

The comprsly.com site is **not in this repo.** It lives in a separate private repo, `comprsly-website`, along with its Cloudflare Worker, its analytics and its contact relay. Every change here is explained in `CHANGELOG.md`.

### Not in this repo on purpose

Secrets (`.env`), built installers and packages, and the large videos in `docs/content`.

## 7. The Mac version

**Built, in testing, not released.** There is no Mac download, no Mac listing, and no date. Do not read this section as an announcement.

What exists today:

- `product/backend/platform_mac/`, the macOS half of what `main.py` does on Windows: Accessibility, the frontmost app, the focused text box, the clipboard, the process tree, launch on login.
- `product/backend/main_mac.py`, which watches and prints what it would badge. `python main_mac.py --check` gives a one shot diagnosis, and its exit code says whether Accessibility works, is being withheld, or whether the build is missing pyobjc.
- `product/build/Comprsly-mac.spec` and `requirements-mac.txt`, which build a `Comprsly.app`. The macOS job in `.github/workflows/macos.yml` runs the shared engine and Mac layer tests, builds the app on a macOS runner and keeps it as an artifact. Signing and notarization are written but switched off until there is a Developer ID.

What is not done: the badge and the review card are Tkinter, and the one thing that genuinely differs between the two platforms is making the badge's square window invisible around the circle. `product/frontend/MACOS_UI.md` explains it and names what has to be looked at on a real Mac first. Nobody has used Comprsly on a Mac yet.

## 8. Troubleshooting

**The badge does not appear.** Check that **AI chat apps** is on in Settings, General. Then check you are in a chat Comprsly recognizes, from the list above. The badge only shows once there is text in the box. In a terminal, it also needs an AI CLI to actually be running.

**The badge is in the wrong place.** Positioning is measured per site. If it looks wrong on a site in the tested list, that is a bug worth reporting, with a screenshot.

**Step 2 is unavailable.** The model is not on your device. Open Settings, AI and download it, about 1 GB.

**It feels slow the first time you shorten something.** The model loads into memory on first use, then stays warm.

**Windows warns you about the app.** The Microsoft Store build is the safe path. A warning on a directly downloaded installer is Windows SmartScreen reacting to an unsigned file, not to anything wrong with your machine.

**Something else.** `%LOCALAPPDATA%\Comprsly\debug.log` records what Comprsly is doing and is the fastest way to see what went wrong.

Questions: [contact@comprsly.com](mailto:contact@comprsly.com)
