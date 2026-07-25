# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# The new web-based Settings UI (2026-07-22) renders in WebView2 via pywebview,
# which drives the WebView2 SDK through pythonnet (clr). Bundling these into
# the frozen exe needs ALL of each package's data files + native DLLs + the
# platform backend module, so collect_all is the reliable way rather than
# hand-listing. If the web UI ever fails to load in the frozen build, the app
# falls back to the legacy Tk settings, so this can't brick the exe.
_wv_d, _wv_b, _wv_h = collect_all('webview')
_pn_d, _pn_b, _pn_h = collect_all('pythonnet')
_cl_d, _cl_b, _cl_h = collect_all('clr_loader')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('C:\\Users\\anton\\AppData\\Local\\Python\\pythoncore-3.14-64\\Lib\\site-packages\\uiautomation\\bin\\UIAutomationClient_VC140_X64.dll', 'uiautomation/bin'), ('C:\\Users\\anton\\AppData\\Local\\Python\\pythoncore-3.14-64\\Lib\\site-packages\\uiautomation\\bin\\UIAutomationClient_VC140_X86.dll', 'uiautomation/bin')] + _wv_b + _pn_b + _cl_b,
    datas=[('assets', 'assets'), ('webui', 'webui')] + _wv_d + _pn_d + _cl_d,
    # winspell drives the Windows spell-check COM API through comtypes.
    # Naming these explicitly stops PyInstaller silently omitting parts of
    # comtypes, which is what disabled spelling in the packaged build.
    hiddenimports=['comtypes', 'comtypes.automation', 'comtypes._post_coinit', 'winspell',
                   'webui', 'clr', 'webview', 'webview.platforms.edgechromium'] + _wv_h + _pn_h + _cl_h,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Comprsly',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # upx=False deliberately (2026-07-22 market audit): UPX-packed exes are
    # a classic antivirus/SmartScreen heuristic trigger, and this binary is
    # already unsigned + PyInstaller-built. A few MB of size is not worth
    # extra AV false positives on an app whose #1 distribution blocker is
    # already SmartScreen reputation.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
    # Names the app to Windows itself (Task Manager, taskbar tooltip, file
    # properties). The exe file name alone is what the OS falls back to
    # without this, which is why it still said TokenSaver everywhere.
    version='version_info.txt',
)
