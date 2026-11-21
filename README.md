# Comprsly

Comprsly makes writing shorter and clearer on Windows. This one repo holds every part of it.

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
4. Copy `backend/.dev.vars.example` to `backend/.dev.vars` and fill in the values. Never commit `.dev.vars`.

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
- Secrets (`.dev.vars`, `.env`).
- Built installers (`desktop/installer-output`, `build`, `dist`). They are kept in `archive\Comprsly installers` on Antonio's laptop.
- Videos in `docs/content` (too large for git). They stay in the local folder.
