# Comprsly

Comprsly: compressed prompts, anywhere you chat with AI. It sits quietly next to Claude, ChatGPT, Gemini, Perplexity and Copilot, fixes your spelling and grammar as you type, and can optionally shrink your whole prompt with a small AI model, entirely on your device.

Live site: https://comprsly.com. This one repo holds every part of it. Every update is explained in `CHANGELOG.md`.

## What it does
- Works next to Claude, ChatGPT, Gemini, Perplexity and Copilot (in the browser and in Windows Terminal).
- Fixes spelling and grammar as you type, with a suggestion card you can apply or ignore.
- Optionally shrinks your whole prompt with a small AI model that runs on your own PC.

## Install (Windows)
1. Get it from the Microsoft Store: https://apps.microsoft.com/detail/9N8W5HPJ4DHV (also linked from https://comprsly.com).
2. Open Comprsly once and follow the short setup screen.
3. It runs quietly in the background and appears when you type in a supported app.

## Do you need an API key?
No. Comprsly does not use any AI service account, yours or anyone else's.
- Spelling and grammar run fully on your PC.
- The optional prompt shrinking uses a small open model that Comprsly downloads once from Hugging Face, then runs offline on your PC. Your text never leaves your computer.

## What is where
| Folder | What it is | Built with |
|---|---|---|
| `desktop/` | The Windows app (the main product) | Python |
| `frontend/` | The comprsly.com pages people see | Plain HTML and compiled React today, to be rebuilt in React and TypeScript |
| `backend/` | The comprsly.com server: page views, store download clicks, the private stats page | Cloudflare Worker (JavaScript) |
| `extension/` | The browser extension | JavaScript |
| `terminal/` | The terminal helper | Node |
| `docs/` | Build notes, handoffs, prompts, marketing content, brand files | |
| `tools/` | One off helper scripts | Python |

## Branches
- `main` is the working, tested code. Nothing is pushed straight to it.
- `sandbox` is where new work goes first and gets tested on your laptop.
- Work branches are named `frontend/...`, `backend/...`, `desktop/...` or `docs/...`.
- Full rules: `BRANCHING.md`.

## First time on a new laptop
1. `git clone https://github.com/antoniosdangelo/comprsly.git`
2. `cd comprsly`
3. `git config core.hooksPath .githooks` (turns on the secret check and the main push guard)
4. Copy `backend/.env.example` to `backend/.env` and fill in the values. Never commit `.env`.

## Running the website on your laptop
1. `cd backend`
2. `npm install` (first time only)
3. `npx wrangler dev` (opens http://localhost:8787, serving the pages from `frontend/public`)

## Running the desktop app
1. `cd desktop`
2. `pip install -r requirements.txt` (first time only)
3. `python main.py`
Building the installer and the Microsoft Store package is described in `docs/Build.md`.

## Publishing
- The website goes live with `npx wrangler deploy` from `backend/`, and only from `main`.
- Every publish needs Antonio's typed "deploy" first.
- The live site is comprsly.com. The database is Cloudflare D1 `comprsly-analytics`.

## Not in this repo on purpose
- Secrets (`.env`, `.env`).
- Built installers (`desktop/installer-output`, `build`, `dist`). They are kept in `archive\Comprsly installers` on Antonio's laptop.
- Videos in `docs/content` (too large for git). They stay in the local folder.
