r"""Where Comprsly keeps its files on a Mac.

Windows uses %LOCALAPPDATA%\Comprsly. The macOS convention for an app's own
support files is ~/Library/Application Support/<App>, and for a .app bundle
distributed outside the App Store that directory is writable without any
entitlement, which is why it is used rather than a sandbox container.

engine/storage.py takes these through configure(), so nothing in the shared
engine ever learns an operating system's folder layout.
"""

import os

APP_NAME = "Comprsly"


def support_dir():
    """~/Library/Application Support/Comprsly. Does not create it.

    It used to call makedirs, which meant merely asking where the files go
    created the folder. Harmless on a Mac, where the app wants it anyway, but
    the Windows test run asks too, and there it was quietly building a bogus
    ~/Library/Application Support/Comprsly in the user's home. Creating is now
    a separate thing you have to ask for.
    """
    return os.path.join(os.path.expanduser("~"), "Library",
                        "Application Support", APP_NAME)


def ensure_support_dir():
    """Create the support directory and return it. Called once at startup."""
    base = support_dir()
    os.makedirs(base, exist_ok=True)
    return base


def storage_paths():
    """The five values engine.storage.configure wants, macOS flavoured."""
    d = support_dir()
    return {
        "log_dir": d,
        "settings_path": os.path.join(d, "settings.json"),
        "history_path": os.path.join(d, "history.json"),
        "badge_position_path": os.path.join(d, "badge_position.json"),
    }


def asset_path(name):
    """A file from frontend/assets, wherever it ended up.

    main.py has the Windows twin of this. PyInstaller unpacks datas next to
    the executable in a .app bundle (Contents/MacOS, via sys._MEIPASS), while
    a source tree keeps them in product/frontend/assets. badge_art.configure()
    takes this so the shared drawing code never learns either layout.
    """
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base = os.path.join(os.path.dirname(backend), "frontend")
    return os.path.join(base, "assets", name)


def log_path():
    return os.path.join(support_dir(), "debug.log")


def model_dir():
    """The local model, same relative place as on Windows."""
    return os.path.join(support_dir(), "model", "qwen2.5-1.5b-instruct-int4-cpu")
