# Comprsly

Comprsly is a Windows desktop app that helps you write better prompts in AI chat apps (Claude, ChatGPT, Gemini, Perplexity, Copilot, etc). It runs a local on-device grammar and compression engine, no prompt text ever leaves your machine.

**Website:** https://comprsly.com

## Status

Currently in private beta, testing builds are shared directly with early users. Public release, including code signing, is planned but not live yet.

## Requirements

- Windows 10/11
- ~50 MB for the installer, plus a one-time in-app model download

## Installation

Download `ComprslySetup.exe` from the latest release and run it. See `SETUP-README.txt` for details.

## Building from source

```
pip install -r requirements.txt
python main.py
```

The installer is built with PyInstaller (`Comprsly.spec`) and Inno Setup (`installer.iss`).

## License

All rights reserved. See `LICENSE`.
