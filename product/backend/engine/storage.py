"""Settings, history and the badge position, written so a crash cannot eat them.

`open(path, "w")` empties the real file before writing a byte. Kill the process
in that gap, which for a tray app people close by hand is not rare, and the
file is left empty. Every loader here catches that and quietly returns a
default, so the symptom was settings resetting themselves, or a whole history
of token savings vanishing, with nothing in the log.

Everything goes through _write_json_atomically for that reason, and it is
portable as written: os.replace is atomic on Windows and on POSIX both.

Where the files live is the platform's business, not this module's, so the
paths arrive through configure() once at startup rather than being imported
from a Windows module.
"""

import json
import os

_CFG = {}


def configure(log_dir, settings_path, history_path, badge_position_path,
              default_settings, history_max_entries):
    """Called once by the platform layer before anything else here is used."""
    _CFG.update(
        log_dir=log_dir, settings_path=settings_path, history_path=history_path,
        badge_position_path=badge_position_path, default_settings=default_settings,
        history_max_entries=history_max_entries,
    )


def _write_json_atomically(path, data):
    """Write JSON so a crash can never leave a half written or empty file.

    `open(path, "w")` truncates the real file the instant it is called, before
    a single byte of the new content is written. Kill the process in that gap,
    which for a tray app people close by hand is not a rare event, and the file
    is left empty. Every loader here catches the error and quietly returns a
    default, so the symptom is settings resetting themselves or a whole
    history of token savings vanishing, with nothing in the log.

    Writing beside the file and renaming over it closes that gap: os.replace is
    atomic on Windows and on POSIX, so a reader sees either the old file or the
    new one, never a torn one. Same approach the log rotation here already
    uses. Returns True when the data is safely on disk.
    """
    try:
        os.makedirs(_CFG["log_dir"], exist_ok=True)
        tmp = "%s.tmp%d" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        # Best effort cleanup; a stray .tmp is harmless, a crash here is not.
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def load_settings():
    merged = dict(_CFG["default_settings"])
    data = {}
    try:
        with open(_CFG["settings_path"], "r", encoding="utf-8") as f:
            data = json.load(f)
        merged.update({k: v for k, v in data.items() if k in _CFG["default_settings"]})
    except Exception:
        data = {}
    return merged


def save_settings(settings):
    _write_json_atomically(_CFG["settings_path"], settings)


def load_history():
    try:
        with open(_CFG["history_path"], "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_history(entry):
    history = load_history()
    history.append(entry)
    history = history[-_CFG["history_max_entries"]:]
    # Rewrites all _CFG["history_max_entries"] rows every time, which is fine at this
    # size and is why the atomic write matters: the blast radius of a torn
    # write here is the whole history, not one row.
    _write_json_atomically(_CFG["history_path"], history)


def save_badge_position(x, y):
    _write_json_atomically(_CFG["badge_position_path"], {"x": x, "y": y})
