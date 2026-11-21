# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('C:\\Users\\anton\\AppData\\Local\\Python\\pythoncore-3.14-64\\Lib\\site-packages\\uiautomation\\bin\\UIAutomationClient_VC140_X64.dll', 'uiautomation/bin'), ('C:\\Users\\anton\\AppData\\Local\\Python\\pythoncore-3.14-64\\Lib\\site-packages\\uiautomation\\bin\\UIAutomationClient_VC140_X86.dll', 'uiautomation/bin')],
    datas=[],
    hiddenimports=[],
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
    name='TokenSaverDebug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
