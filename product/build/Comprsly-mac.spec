# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the macOS build.

Separate from Comprsly.spec rather than branching inside it: the two have
different entry points, different hidden imports and different bundle rules,
and a spec full of `if sys.platform` is how one platform's build quietly
breaks the other. Windows has a Store submission pending, so its spec is left
alone entirely.

Produces Comprsly.app. Unsigned until the Apple Developer account exists, so
Gatekeeper will refuse to open it on a download: the user has to right click,
Open, and confirm once. That is an install instruction, not a bug.
"""

import os

block_cipher = None

# icon.icns is generated from icon.png by the macOS workflow, using iconutil,
# which exists only on macOS. Build without an icon rather than fail when it is
# absent, so the spec still works for a local test build.
_ICON = '../frontend/assets/icon.icns'
if not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(SPEC)), _ICON)):
    _ICON = None

a = Analysis(
    ['../backend/main_mac.py'],
    pathex=['../backend'],
    binaries=[],
    datas=[('../frontend/assets', 'assets'), ('../frontend/webui', 'webui')],
    hiddenimports=[
        'engine', 'engine.geometry', 'engine.storage',
        'platform_mac', 'platform_mac.accessibility', 'platform_mac.input',
        'platform_mac.processes', 'platform_mac.autostart', 'platform_mac.paths',
        'AppKit', 'Quartz', 'ApplicationServices', 'objc',
        # The badge: shared artwork, drawn with PIL, shown through Tk.
        'badge_art', 'suggestion_engine',
        'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageTk',
        'tkinter',
    ],
    hookspath=[],
    runtime_hooks=[],
    # Windows only, and importing them here would fail the build outright.
    excludes=['uiautomation', 'comtypes', 'pythonnet', 'clr', 'winspell', 'win32api'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Comprsly',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name='Comprsly',
)

app = BUNDLE(
    coll,
    name='Comprsly.app',
    icon=_ICON,
    bundle_identifier='com.comprsly.app',
    info_plist={
        'CFBundleName': 'Comprsly',
        'CFBundleDisplayName': 'Comprsly',
        'CFBundleShortVersionString': '1.1.1',
        'CFBundleVersion': '1.1.1',
        'NSHighResolutionCapable': True,
        # No Dock icon: Comprsly lives in the menu bar and floats a badge. A
        # Dock icon would imply a window it does not have.
        'LSUIElement': True,
        'LSMinimumSystemVersion': '12.0',
        # Shown in the permission dialog, so it has to say something true and
        # specific. macOS gives the user this sentence and nothing else.
        'NSAppleEventsUsageDescription':
            'Comprsly reads the text box you are typing in so it can suggest a '
            'shorter prompt. Nothing you type leaves your Mac.',
    },
)
