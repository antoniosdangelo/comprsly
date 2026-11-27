"""Comprsly's portable core: everything that is the same on every OS.

Split out of main.py on 2026-11-26, as step one of the macOS build.

The rule for what belongs here: if it would be written identically on Windows
and on a Mac, it goes in engine/. If it calls an OS API, it stays in the
platform layer. Nothing in this package may import ctypes, uiautomation,
winreg, pywin32 or tkinter, and a test enforces that rather than trusting it.

What is left in main.py is the Windows layer, and it is narrower than its size
suggests. The whole platform seam is:

    find the focused application and the control inside it
    get that control's rectangle on screen
    read the text in it, and write text back into it
    hook the keyboard, and read the clipboard
    walk the process tree, to spot an AI CLI running under a terminal
    set and clear launch on login

Everything else, the rules engine, the local model, the windows drawn with
Tkinter, the geometry below, is already portable. The macOS layer implements
that seam and reuses this package unchanged.

See PLATFORM.md beside this package for the seam in full.
"""
