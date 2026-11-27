# Contributing

Thanks for looking. Comprsly is a Windows desktop app written in Python, with a Tkinter interface and a small local AI model.

## Get it running

You need Python 3.12 or newer on Windows 10 or 11.

```
git clone https://github.com/antoniosdangelo/comprsly.git
cd comprsly
pip install -r product/build/requirements.txt
python product/backend/main.py
```

The app starts in the system tray. Type in a supported AI chat and the badge appears.

The first run downloads the local model, about 1 GB, unless you already have it. Spelling and grammar work without it.

## Run the tests

```
python -m unittest discover -s product/backend -p "test_*.py"
```

That is `unittest`, not pytest. The same line runs on every pull request, on Windows, because the app calls into Windows as it loads. Some tests skip themselves on other systems and say so.

## Where things live

| Folder | What is in it |
|---|---|
| `product/backend/` | The app: detection, grammar, the local model, and the tests |
| `product/backend/engine/` | The parts that are the same on every platform |
| `product/backend/platform_mac/` | The macOS layer, still in testing |
| `product/frontend/` | The settings, first run and review screens, and the icons |
| `product/build/` | Packaging: the PyInstaller specs, Inno Setup and the Store manifest |
| `product/tools/` | Developer scripts, never shipped |

## Packaging

The installer is built with PyInstaller and Inno Setup from `product/build`:

```
cd product/build
python -m PyInstaller Comprsly.spec --noconfirm --clean
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

`Comprsly-mac.spec` builds the macOS app bundle, which is not released yet.

## Opening a pull request

- Branch from `sandbox`, not from `main`. Work branches are named `backend/<what>` or `frontend/<what>`.
- Run the tests before you open it, and say in the description what you checked.
- Keep the description in plain words: what changed, why it matters, and how you tested it.
- `git config core.hooksPath .githooks` once per clone turns on the local checks that keep secrets out of a commit.

Bugs and questions: open an issue, or email [contact@comprsly.com](mailto:contact@comprsly.com). A screenshot and the last few lines of `%LOCALAPPDATA%\Comprsly\debug.log` make a bug report much easier to act on.
