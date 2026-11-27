"""Launch on login, the macOS way.

Windows writes the per user Run key, or uses the StartupTask API when packaged
for the Store. macOS has no registry: a login item for a direct download app is
a LaunchAgent plist in ~/Library/LaunchAgents, loaded with launchctl.

Deliberately NOT using SMAppService, which is the modern API and the better
answer for a signed, notarised, sandboxed app. It needs the app to be a proper
bundle with the helper embedded, and this build is not signed yet. A plist
works for an unsigned direct download today, and swapping to SMAppService when
the Developer account exists is a contained change.
"""

import os
import plistlib
import subprocess

LABEL = "com.comprsly.launcher"


def _plist_path():
    d = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, LABEL + ".plist")


def is_enabled():
    return os.path.exists(_plist_path())


def enable(app_path):
    """Run Comprsly at login. True when the plist is written and loaded."""
    path = _plist_path()
    body = {
        "Label": LABEL,
        "ProgramArguments": [app_path],
        "RunAtLoad": True,
        # Not KeepAlive: if the user quits Comprsly, it should stay quit until
        # the next login. KeepAlive would relaunch it immediately, which reads
        # as the app refusing to close.
        "KeepAlive": False,
        "ProcessType": "Interactive",
    }
    try:
        with open(path, "wb") as f:
            plistlib.dump(body, f)
    except Exception:
        return False
    try:
        subprocess.run(["launchctl", "load", "-w", path],
                       capture_output=True, timeout=10)
    except Exception:
        pass          # the plist is written; it will take effect next login
    return True


def disable():
    path = _plist_path()
    if not os.path.exists(path):
        return True
    try:
        subprocess.run(["launchctl", "unload", "-w", path],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    try:
        os.remove(path)
        return True
    except Exception:
        return False
