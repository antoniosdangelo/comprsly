# Comprsly change log

Every update to this repo, oldest first, in plain words. The short code is the commit id on GitHub.
Older commits keep their original messages; this file explains them so nothing has to be rewritten.

## July 25, 2026: first version on GitHub (branch `main`)
- **4c4eff6** First upload of the Comprsly desktop app.
- **e841e3e** License changed to MIT.
- **9673895** Added an automatic build that turns the Python app into a Windows installer (PyInstaller and Inno Setup). Code signing not connected yet.
- **4a1dfdf** The build's signing step now points at Azure Trusted Signing instead of SignPath (still a placeholder).
- **447fbd5** Fix: the app looked for a Windows UI library at one fixed folder that only existed on the original laptop, so it failed everywhere else. It now finds the library wherever it is installed. **This is what `main` holds today.**

## July 27, 2026: fixes made on the laptop, never uploaded until Nov 21
- **391c86f** Two days of work in one save: better grammar and dictation cleanup, protection for tech words so they are not "corrected", and a serious terminal safety fix (an unreadable terminal could let Apply type over the whole terminal history). Also version 0.9.82 to 0.9.89, installer version kept in sync, and preparation for the Microsoft Store package.
- **c698b59** Version 0.9.90. Root fix for terminal input detection: Windows Terminal often returns its text without line breaks, so the old method saw one giant line. It now reads the terminal line by line the way Windows itself measures rows.
- **c7f3b74** Versions 0.9.91 and 0.9.92. Fixed text from one terminal window being typed into another, and Apply now stops with an error if you switch windows while it is still working, instead of typing into the wrong window.

## November 21, 2026: reorganized into one repo (branch `sandbox`)
- **4d6a971** Saved the desktop work that was sitting on the laptop uncommitted since July 27: installer, Store package template, main app, suggestion engine, web screens, version info and the Microsoft Store logos. Added the secret check and the main branch push guard.
- **5e5f10f** Moved the desktop app into `desktop/`. File locations only, no code changes.
- **daeffeb** Added the website (`frontend/` pages, `backend/` server), the browser extension, the terminal helper, docs and tools, plus the README, branch rules, ignore rules and the settings list (names only).
- **8290b1f** The repo moved from the Comprsly organization to Antonio's account, so links in the docs now point at `antoniosdangelo/comprsly`.
- Naming and descriptions: README description matches the GitHub description, website package renamed `comprsly-website`, and this change log added.
- README now explains what Comprsly does, how to install it from the Microsoft Store, and that it needs no API key (everything runs on the user's PC).

## How updates work from now on
New work goes to `sandbox` first, gets tested, and only then is merged into `main` (production) when Antonio approves. See `BRANCHING.md`.
