# Who works on what

| Part | Owner |
|---|---|
| `product/backend/` the engine, `main.py`, `engine/`, `platform_mac/`, the tests | Comprsly dev chat |
| `product/frontend/` the settings, onboarding and review screens, the icons | Comprsly dev chat |
| `product/build/` PyInstaller specs, Inno Setup, the MSIX template, requirements | Comprsly dev chat |
| `product/tools/` dev only scripts | Comprsly dev chat |
| `docs/` | Comprsly dev chat |
| repo setup: `.github/`, `.githooks/`, `.env` layout, `BRANCHING.md`, this file | Orchestrator |

**The website is not in this repo.** It lives in the private `comprsly-website` repo and has its own agents. Nothing here deploys it.

## How agents hand work over

An agent commits locally and stops. It never pushes, never opens a pull request and never merges one.

- Commits are authored as Antonio, with the repo's own git identity, and a plain English message. No `Co-Authored-By`, no session links, no generated-with footer, anywhere.
- Work for one push is **exactly two branches: one `backend/...` and one `frontend/...`**, backend first. Never three, never one combined branch. Fold everything into those two.
- Each branch gets an untracked `PR.md` beside the work saying what changed, why, and how it was tested. It is for Antonio to paste when he opens the pull request. Untracked, so stage explicit paths and never `git add -A`.
- Antonio reviews the branch in VS Code Source Control and pushes it himself.

## How to open an agent

In VS Code: Ctrl+Shift+P, "Tasks: Run Task", then the Comprsly agent. Chat ids are in this repo's local `.env`, which is never committed.

## Labels on GitHub

`agent: ...` names the owner. `side: backend` or `side: frontend` names the form. Backend is merged first.

## The path every change takes

Work branch to a pull request into `sandbox`. Checks run. **Nothing merges automatically**, Antonio merges when he is satisfied. `sandbox` is promoted to `main` on his word only. See `BRANCHING.md`.
