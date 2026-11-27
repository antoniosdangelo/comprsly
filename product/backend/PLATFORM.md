# The platform seam

Written 2026-11-26, step one of the macOS build.

Comprsly is split in two: `engine/`, which is the same everywhere, and the
platform layer, which is `main.py` today and will gain a macOS sibling.

## Why the split is narrower than main.py's size suggests

`main.py` is 11,700 lines, but only about 3% of its lines touch a Windows API.
The rest is the review card, the settings window, the badge, the state machine,
all written in Tkinter and plain Python, and all of it already runs on a Mac.

What genuinely has to be rewritten is this, and only this:

| What the app needs | Windows today | macOS equivalent |
|---|---|---|
| Which app is in front | `GetForegroundWindow` + process name | `NSWorkspace.frontmostApplication` |
| The focused text control | UI Automation `GetFocusedControl` | `AXUIElementCopyAttributeValue(kAXFocusedUIElement)` |
| Its rectangle on screen | `BoundingRectangle` | `kAXPositionAttribute` + `kAXSizeAttribute` |
| Reading the text in it | `TextPattern` / `ValuePattern` | `kAXValueAttribute` |
| Writing text back | `SetValue`, else clipboard and Cmd/Ctrl+V | `AXUIElementSetAttributeValue`, else the same paste fallback |
| Knowing what was typed | `SetWindowsHookExW(WH_KEYBOARD_LL)` | `CGEventTap`, needs Accessibility permission |
| The clipboard | Win32 clipboard | `NSPasteboard` |
| Is an AI CLI running here | process tree walk, PEB command lines | `proc_listpids` + `proc_pidpath`, `ps` for arguments |
| Launch on login | Run key, or `StartupTask` when packaged | a `LaunchAgent` plist |
| Where files live | `%LOCALAPPDATA%\Comprsly` | `~/Library/Application Support/Comprsly` |

## What `engine/` already holds

- `geometry.py`, where the badge goes and what colour it is. Pure arithmetic.
- `storage.py`, settings, history and badge position, written atomically.

Two functions there take values that used to be module constants:
`_badge_inset_for` and `_heat_color`. Those numbers are DPI scaled, and DPI is
an OS concept, so the platform supplies them and the maths lives in the engine.
`main.py` keeps wrappers at the original one-argument names, which is why none
of its 11,700 lines of call sites changed.

`storage.py` learns its paths through `configure()`, called once at startup, so
the engine never needs to know what `%LOCALAPPDATA%` is.

## The rule, and it is a test not a convention

Nothing in `engine/` may import `ctypes`, `winreg`, `uiautomation`, `comtypes`,
pywin32, `tkinter`, or `main` itself. `test_engine_is_portable.py` fails if it
does, and also fails on a bare `C:\`, `windll`, `HKEY_` or `.exe` in the text.

That test is the point. A boundary nobody checks is a boundary that lasts until
the first time somebody needs a window handle "just here".

## What has NOT moved, deliberately

The 4,900 lines of Windows-bound code are still in `main.py`. Moving them while
also introducing a macOS path is how you get a behaviour change nobody can see,
and Windows has to stay identical so a Store fix stays cheap. Step two writes
the macOS layer against the table above; it does not reshuffle the Windows one.
