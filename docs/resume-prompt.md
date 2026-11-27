Project folder: `C:\Dev\Claude Code\Projects\Comprsly\comprsly`, the public product repo. Read `README.md` first, then `docs/Build.md`'s CURRENT STATE block. This is a live, shipping product, not a fresh start, and most of `Build.md` below that block is July history.

Comprsly is a Windows desktop app (Python, PyInstaller frozen, Tk UI): grammar and spelling fixes always on, plus an optional on-device AI rewrite that shortens the prompt (Qwen2.5-1.5B-Instruct int4, nothing leaves the machine). It only wakes up in a known AI chat, in a known LLM desktop app, or in a terminal that has an AI CLI actually running in it, which is deliberate. **Version 1.1.1, published in the Microsoft Store** (verified 2026-11-27 with the `msstore` CLI, no pending submission). The repo is public and MIT licensed.

**The website is not here.** It lives in the private `comprsly-website` repo, and nothing in this repo deploys it. A live deploy anywhere needs Antonio's typed "deploy".

Layout: `product/backend/` (the engine, `main.py`, the portable `engine/`, the `platform_mac/` layer, and every test), `product/frontend/` (settings, onboarding and review screens, icons), `product/build/` (PyInstaller specs, Inno Setup, the MSIX template, the two requirements files), `product/tools/` (dev only scripts), `docs/`.

Tests: `python -m unittest discover -s product/backend -p "test_*.py"`. Not pytest, which is not installed on this machine. CI runs that exact line on a Windows runner, because `main.py` imports a Windows API as it loads.

Open, in order: (1) the macOS version is built and in testing, with no release and no download, and nobody has used it on a real Mac yet, so `product/frontend/MACOS_UI.md` names what to look at first. (2) Code signing for the direct download `.exe`/`.msix` is decided (Azure Trusted Signing) and not started; the Store signs its own package for free, so this only affects downloads outside the Store. (3) `docs/supported-surfaces.md` is the honest list of what the app recognises, including what is unverified.

Things to know without re-litigating them: this shell runs on Antonio's own laptop, not a sandbox. Never remove `"claude.exe"` from `KNOWN_LLM_PROCESSES` in `main.py`, because the badge inside Claude Code's own chat box is wanted behaviour. Never match a bare `node.exe` as an AI CLI, because it would light the badge under any node process; a test enforces it. Commit locally on a clearly named branch and stop: Antonio reviews every change and pushes it himself.
