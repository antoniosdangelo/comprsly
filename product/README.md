# Comprsly, the product

Comprsly fixes your spelling and grammar as you type in AI chats, then optionally shortens the whole prompt with a small AI model that runs on your own machine. Nothing you type leaves it.

**Windows 10 or 11.** Version 1.1.1, live in the Microsoft Store: [Get Comprsly](https://apps.microsoft.com/detail/9N8W5HPJ4DHV). Free, no account. A macOS version is built and in testing, not released.

**Website:** https://comprsly.com

## What is in here

| Folder | What it is |
|---|---|
| `backend/` | The engine: detection, grammar, the local model, the tests, and `platform_mac/` |
| `frontend/` | The settings, onboarding and review screens, and the icons |
| `build/` | The PyInstaller specs, Inno Setup, the Store manifest, the requirements files |
| `tools/` | Dev only scripts, never shipped |

## Running it from source

```
pip install -r build/requirements.txt
python backend/main.py
```

Tests: `python -m unittest discover -s backend -p "test_*.py"`.

The installer is PyInstaller (`build/Comprsly.spec`) plus Inno Setup (`build/installer.iss`); `build/Comprsly-mac.spec` makes the `.app`. Full instructions are in [CONTRIBUTING.md](../CONTRIBUTING.md).

Installing a release build is covered in `SETUP-README.txt`. Everything else, including versions, what Comprsly recognizes and how to build it, is in the repo's main [README](../README.md).

## License

MIT, see `LICENSE`.
