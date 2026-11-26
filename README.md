# Comprsly

Comprsly fixes your spelling and grammar as you type in AI chats, then optionally shortens the whole prompt using a small AI model that runs entirely on your own PC.

Website: [comprsly.com](https://comprsly.com) · Microsoft Store: [Get Comprsly](https://apps.microsoft.com/detail/9N8W5HPJ4DHV)

**Versions.** The Microsoft Store has 1.0.3.0. This repo's `main` is 1.1.0, which adds Codex CLI, Gemini CLI and Copilot CLI detection, and goes to the Store next. Until then, those three CLIs work only in a build from source.

## 1. What you need

**Windows 10 or Windows 11.** There is no Mac or Linux version yet, because Comprsly reads Windows text fields directly.

**Fully tested AI chats:** Claude (including Claude Code), ChatGPT, Gemini (including the Chrome side panel), Perplexity, Copilot, Grok, DeepSeek.

**Also recognized:** Le Chat, Poe, Hugging Face, You.com, Pi, Character.AI.

**Terminals:** Windows Terminal, PowerShell, Command Prompt, Git Bash, WSL.

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

**To stop Comprsly appearing anywhere** without uninstalling it, turn off **AI chat apps** on the General page.

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

The Windows app is Python and lives in `product/`.

```
cd product/build
pip install -r requirements.txt
python main.py
```

Building the installer and the Microsoft Store package is covered in `docs/Build.md`.

### What is in this repo

| Folder | What it is | Built with |
|---|---|---|
| `product/` | **The Windows app, the main product** | Python |
| `product/backend/` | Its engine: detection, grammar, the local model | Python |
| `product/frontend/` | What you see: the settings and review screens, icons | HTML, CSS |
| `product/build/` | Packaging: PyInstaller spec, Inno Setup, the Store manifest | |
| `product/tools/` | Dev only scripts, never shipped | Python |
| `website/frontend/` | The comprsly.com pages | HTML today, to be rebuilt in React and TypeScript |
| `website/backend/` | The comprsly.com server: page views, download clicks, the private stats page | Cloudflare Worker |
| `extension/` | The browser extension | JavaScript |
| `terminal/` | The terminal helper | Node |
| `docs/` | Build notes, handoffs, prompts, marketing content, brand files | |
| `tools/` | One off helper scripts | Python |

### Running the website locally

```
cd website/backend
npm install
npx wrangler dev
```

That serves the pages from `website/frontend/public` at http://localhost:8787.

### First time on a new machine

1. `git clone https://github.com/antoniosdangelo/comprsly.git`
2. `cd comprsly`
3. `git config core.hooksPath .githooks` to turn on the secret check and the main branch push guard
4. Copy `website/backend/.env.example` to `website/backend/.env` and fill it in. Never commit `.env`.

### Branches

`main` is tested code and the only branch a deploy comes from. `sandbox` is where new work goes first. Work branches are named `frontend/...`, `backend/...`, `product/...` or `docs/...`. Full rules in `BRANCHING.md`. Every change is explained in `CHANGELOG.md`.

### Not in this repo on purpose

Secrets (`.env`), built installers, and the large videos in `docs/content`.

## 7. Troubleshooting

**The badge does not appear.** Check that **AI chat apps** is on in Settings, General. Then check you are in a chat Comprsly recognizes, from the list above. The badge only shows once there is text in the box.

**The badge is in the wrong place.** Positioning is measured per site. If it looks wrong on a site in the tested list, that is a bug worth reporting, with a screenshot.

**Step 2 is unavailable.** The model is not on your device. Open Settings, AI and download it, about 1 GB.

**It feels slow the first time you shorten something.** The model loads into memory on first use, then stays warm.

**Windows warns you about the app.** The Microsoft Store build is the safe path. A warning on a directly downloaded installer is Windows SmartScreen reacting to an unsigned file, not to anything wrong with your machine.

**Something else.** `%LOCALAPPDATA%\Comprsly\debug.log` records what Comprsly is doing and is the fastest way to see what went wrong.

Questions: [contact@comprsly.com](mailto:contact@comprsly.com)
