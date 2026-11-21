"""Comprsly -- web-based UI host (2026-07-22, UI redesign).

The new UI is HTML/CSS (the approved mockups) rendered in a real WebView2
window via pywebview, keeping the entire hardened Python engine underneath.
This module hosts the SETTINGS window and exposes the real engine to the page
through a js_api bridge (window.pywebview.api.*).

Runs as its OWN process (main.py dispatches `--web-settings` here), which
sidesteps the fact that pywebview.start() must own the main thread while the
running app already owns it with Tk + the tray. The settings process reads and
writes the real settings.json and calls local_model directly; the main app
reloads settings.json when this process exits (see main.open_settings). The
floating badge and the review card stay native for now (Phase 3/4).
"""
import base64
import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import webview          # pywebview  (Edge WebView2 backend on Windows)
import main as app      # settings schema + helpers (module-level only, no GUI)
import local_model


def _asset_uri(name):
    """base64 data: URI for an asset PNG, so the page is fully self-contained
    (no file-path resolution issues, works the same frozen or from source)."""
    try:
        with open(os.path.join(_HERE, "assets", name), "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""


_window = [None]   # the live pywebview window, so js_api can close it


def _screen_center(width, height):
    """Top-left (x, y) that centers a width x height window on the PRIMARY
    monitor's work area. Real ask 2026-07-25 (Antonio, on stream): the
    Settings window kept opening off to one side. pywebview's own default
    (FormStartPosition.CenterScreen, confirmed in the installed package's
    platforms/winforms.py) should already center it at CREATION -- but the
    new warm-server 'show' path (2026-07-25) reuses the SAME window instead
    of creating a fresh one, and re-showing an existing WinForms window does
    NOT re-apply StartPosition, so wherever it drifted to (or wherever it
    was left after the very first show) is where it stays. Centering
    explicitly, on every show, removes the ambiguity instead of relying on
    a one-time default that only ever applies once per process."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                        ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

        MONITOR_DEFAULTTOPRIMARY = 1
        u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        u.MonitorFromPoint.restype = ctypes.c_void_p
        hmon = u.MonitorFromPoint(wintypes.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        u.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi))
        wr = mi.rcWork
        cx = wr.left + max(0, (wr.right - wr.left - width) // 2)
        cy = wr.top + max(0, (wr.bottom - wr.top - height) // 2)
        return cx, cy
    except Exception:
        return None


def _move_window_by_title(title, x, y):
    """Moves a top-level window by exact title using SetWindowPos directly.

    Real bug found live 2026-07-25, on the shipped exe (never reproduced in
    dev-python testing, which is exactly why it slipped through): pywebview's
    OWN Window.move() (webview/platforms/winforms.py) calls
    `windll.user32.SetWindowPos(hwnd, None, x, y, None, None, SWP_NOSIZE|...)`
    -- passing None for the cx/cy parameters. SWP_NOSIZE means Windows ignores
    those two values, but ctypes still has to MARSHAL them into the call, and
    with no argtypes declared on that shared ctypes function object, it can't
    convert None to the integer SetWindowPos actually expects there --
    confirmed via debug.log: "argument 5: TypeError: 'NoneType' object cannot
    be interpreted as an integer". This bypasses pywebview's move() entirely
    with our own correctly-typed call: real integers (0, 0) for cx/cy (safe,
    since SWP_NOSIZE ignores them regardless), and explicit argtypes so
    ctypes marshals HWND-typed None correctly instead of guessing.

    Coordinates are physical pixels (GetMonitorInfoW's native units, same as
    _screen_center above); this process is DPI-aware (main.py sets
    SetProcessDpiAwareness at import, and webui.py always imports main), so
    no logical/physical scaling step is needed here."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowW.restype = wintypes.HWND
        hwnd = u.FindWindowW(None, title)
        if not hwnd:
            return False
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_SHOWWINDOW = 0x0040
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos.restype = wintypes.BOOL
        return bool(u.SetWindowPos(hwnd, None, int(x), int(y), 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_SHOWWINDOW))
    except Exception:
        return False


def _clamp_to_monitor(x, y, w, h):
    """Keep the whole card on the monitor that contains (x, y). The badge is
    often near the bottom/right of the screen (e.g. Claude's composer), and a
    560px card placed at the badge's y would run off-screen and appear not to
    open at all (2026-07-22 bug). Returns an on-screen top-left."""
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                        ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

        u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        u.MonitorFromPoint.restype = ctypes.c_void_p
        hmon = u.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # NEAREST
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        u.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(mi))
        wr = mi.rcWork
        cx = max(wr.left, min(int(x), wr.right - w))
        cy = max(wr.top, min(int(y), wr.bottom - h))
        return cx, cy
    except Exception:
        return int(x), int(y)


def _load_html(name):
    with open(os.path.join(_HERE, "webui", name), "r", encoding="utf-8") as f:
        html = f.read()
    return (html
            .replace("__BADGE_URI__", _asset_uri("badge.png"))
            .replace("__LOGO_URI__", _asset_uri("logo.png"))
            .replace("__MARK_DARK_URI__", _asset_uri("mark_dark.png")))


class Bridge:
    """Everything the settings page can call. Reads/writes the REAL settings
    and drives the real model. Kept small and synchronous; anything slow
    (download) is fired on a background thread."""

    # ---- read ----
    def get_state(self):
        s = app.load_settings()
        cats = [{
            "id": c, "flag": app.CATEGORY_SETTING[c], "label": app.CATEGORY_LABEL[c],
            "blurb": app.CATEGORY_BLURB[c], "on": bool(s.get(app.CATEGORY_SETTING[c])),
        } for c in app.APP_CATEGORIES]
        return {
            "version": app.APP_VERSION,
            "ai_enabled": bool(s.get("ai_enabled")),
            "categories": cats,
            "model": self.get_model(),
            "history": self.get_history(),
        }

    def get_model(self):
        dl = local_model.is_model_downloaded()
        # The download always runs in the PERSISTENT main app process now
        # (2026-07-23 fix — see local_model.request_download), never in this
        # settings/onboarding subprocess, so this process's own in-memory
        # is_downloading()/download_state() are never the ones actually moving.
        # Read the disk progress file the main process writes; fall back to
        # this process's own state (harmless if it's ever the same process).
        st = local_model.download_progress_from_disk() or local_model.download_state()
        downloading = bool(st.get("active")) or local_model.is_downloading()
        return {
            "label": local_model.model_label(),
            "downloaded": dl,
            "downloading": downloading,
            # Cross-process read (audit 2026-07-25): the warm worker is the
            # MAIN process's child; this subprocess's own is_loaded() said
            # "Not loaded" while Task Manager showed 1.4GB.
            "loaded": local_model.is_loaded_cross_process(),
            "size_gb": round(local_model.model_dir_size_bytes() / (1024 ** 3), 1) if dl else 0.0,
            "pct": (int(st["done"] * 100 / st["total"]) if st.get("total") else 0),
            "error": st.get("error"),
        }

    def get_history(self):
        h = app.load_history()
        total = sum(e.get("tokens_saved", 0) for e in h)
        # last 7 LOCAL calendar days, oldest -> newest. Calendar days, not
        # rolling 24h windows: the bars carry weekday letters, so an entry
        # from yesterday 11PM must land under yesterday's letter, not
        # today's (fixed 2026-07-24 -- the old `age // 86400` binning put
        # it under today). mktime normalises an out-of-range tm_mday, so
        # "today minus k days" is real calendar arithmetic (month/year
        # boundaries safe); noon as the sample time keeps a DST-shifted
        # hour from sliding the sample into the wrong day.
        now = time.time()
        buckets = [0] * 7
        labels = []
        lt_now = time.localtime(now)
        day_index = {}
        for i in range(7):
            t = time.mktime((lt_now.tm_year, lt_now.tm_mon,
                             lt_now.tm_mday - (6 - i), 12, 0, 0, 0, 0, -1))
            d = time.localtime(t)
            day_index[(d.tm_year, d.tm_yday)] = i
            labels.append(time.strftime("%a", d)[:1])
        for e in h:
            lt = time.localtime(e.get("timestamp", now))
            i = day_index.get((lt.tm_year, lt.tm_yday))
            if i is not None:
                buckets[i] += e.get("tokens_saved", 0)
        recent = []
        for e in reversed(h[-8:]):
            recent.append({
                "when": time.strftime("%b %d, %H:%M", time.localtime(e.get("timestamp", 0))),
                "saved": e.get("tokens_saved", 0),
                "ai": bool(e.get("used_ai")),
            })
        return {"total": total, "count": len(h), "days": buckets, "labels": labels, "recent": recent}

    # ---- write ----
    def set_setting(self, key, value):
        s = app.load_settings()
        if key in app.DEFAULT_SETTINGS:
            s[key] = value
            app.save_settings(s)
            return True
        return False

    def finish_onboarding(self, get_ai):
        """First-run choice: mark onboarding done; if they want the AI, enable
        it and REQUEST the one-time download; then close the window.

        Real bug fixed 2026-07-23: this used to start the download in a thread
        HERE, in the onboarding subprocess, then destroy this same window a few
        lines down — killing that thread within moments of it starting. The
        download now runs in the persistent main app process (see
        local_model.request_download); it survives this window closing."""
        s = app.load_settings()
        s["ai_onboarding_shown"] = True
        if get_ai:
            s["ai_enabled"] = True
        app.save_settings(s)
        if get_ai:
            local_model.request_download()
        w = _window[0]
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass
        return True

    # set_launch removed (real ask 2026-07-30, Antonio: the "Launch on
    # login" toggle doesn't work on the Store/MSIX download). Root cause:
    # a packaged build routes through Windows.ApplicationModel.StartupTask
    # (see app.set_launch_on_login), which only works if a matching
    # <desktop:StartupTask TaskId="ComprslyStartupTask"> extension is
    # declared in the packaging project's AppxManifest.xml -- a packaging
    # step outside this codebase that was apparently never added, so the
    # call silently fails on every Store install. Rather than chase that
    # manifest, the toggle itself is gone. app.set_launch_on_login /
    # launch_on_login_is_active / heal_launch_on_login stay in main.py
    # untouched -- they're still what keeps autostart working for anyone
    # on the older unpackaged (Inno Setup) install who already turned it
    # on before this toggle disappeared.

    # ---- update check (real ask 2026-07-28) ----
    def get_update_status(self):
        return app.check_for_update()

    def start_update(self):
        return app.start_store_update()

    # ---- "you're now updated" one-time notice (real ask 2026-07-30) ----
    def get_version_status(self):
        return app.consume_version_update_flag()

    # ---- model actions ----
    def download_model(self):
        # Real bug fixed 2026-07-23: this used to start the download in a
        # thread INSIDE this settings subprocess. Closing the Settings window
        # (entirely reasonable — nobody watches a ~1GB download for 10+
        # minutes) killed that thread instantly, silently, with no error and
        # no partial-file cleanup: "the download isn't working." The download
        # now runs in the persistent main app process (see
        # local_model.request_download); this only asks for it to start.
        local_model.request_download()
        return True

    def delete_model(self):
        # The warm worker holding the model's mmap belongs to the MAIN
        # process (audit 2026-07-25): deleting from this subprocess while it
        # lived hit WinError 32 every time. Ask the main process to unload
        # first, wait for its status file to confirm (it polls requests every
        # 0.7s and now waits out the worker's death), THEN remove the files.
        local_model.request_unload()
        for _ in range(50):  # up to ~5s
            if not local_model.is_loaded_cross_process():
                break
            time.sleep(0.1)
        ok, err = local_model.delete_model()
        return {"ok": ok, "error": err}

    def unload_model(self):
        # Request-file to the main process, same pattern as downloads (audit
        # 2026-07-25: the old local force_unload() freed a model THIS settings
        # subprocess never had -- a silent no-op against the 1.4GB it was
        # built to answer). Brief poll so the button can report honestly.
        local_model.request_unload()
        for _ in range(30):  # up to ~3s; main loop consumes within ~0.7s
            if not local_model.is_loaded_cross_process():
                return True
            time.sleep(0.1)
        return not local_model.is_loaded_cross_process()

    # reset_badge_position removed (real ask 2026-07-25): its own control
    # ("Badge position: Reset") in settings.html is gone -- the badge hasn't
    # been draggable since 2026-07-23, so there was never a pinned position
    # for this to actually reset. BADGE_POSITION_PATH/save_badge_position in
    # main.py already had zero callers per the 2026-07-25 audit; this was
    # the last live caller of the file-delete side.

    # ---- About page (2026-07-23, first real implementation: these links were
    # static HTML with no click handler at all before, not a regression) ------
    def get_acknowledgements(self):
        """Structured ACKNOWLEDGEMENTS.txt for the About page's in-app viewer.

        Real gap found 2026-07-24: this used to os.startfile() the raw .txt,
        which just opened it in Notepad -- worked, but reads as "the app
        broke and dumped you into a text editor," not a real part of the
        product. Parses the SAME file the installer ships (still one source
        of truth for licence text) into sections/entries so the page can
        render it with the rest of Settings' own visual language instead.
        Lives in the INSTALL dir (see app.install_dir_path), not the
        PyInstaller bundle."""
        try:
            path = app.install_dir_path("ACKNOWLEDGEMENTS.txt")
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as e:
            return {"ok": False, "error": str(e)}

        lines = raw.splitlines()
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines):
            i += 1  # title line
        if i < len(lines) and lines[i].strip().startswith("="):
            i += 1  # underline

        intro_lines = []
        sections = []
        cur = [None]
        entry = [None]

        def flush_entry():
            if entry[0] and cur[0] is not None:
                entry[0]["desc"] = " ".join(entry[0]["desc"]).strip()
                cur[0]["entries"].append(entry[0])
            entry[0] = None

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            # Section header: an unindented, non-blank line immediately
            # followed by a line of only dashes.
            if stripped and not line[:1].isspace() and nxt and set(nxt) == {"-"}:
                flush_entry()
                cur[0] = {"title": stripped, "entries": []}
                sections.append(cur[0])
                i += 2
                continue
            if cur[0] is None:
                if stripped:
                    intro_lines.append(stripped)
                i += 1
                continue
            if not stripped:
                i += 1
                continue
            if not line[:1].isspace():
                # New entry header, e.g. "Name    Licence" (2+ spaces apart).
                flush_entry()
                parts = re.split(r"\s{2,}", stripped, maxsplit=1)
                name = parts[0].strip()
                lic = re.sub(r"^-+\s*", "", parts[1].strip()) if len(parts) > 1 else ""
                entry[0] = {"name": name, "license": lic, "desc": []}
            elif entry[0] is not None:
                entry[0]["desc"].append(stripped)
            i += 1
        flush_entry()

        # Prose-only sections (no entry ever picked up a licence or
        # description) are plain paragraphs, not a library list -- collapse
        # them into free text instead of one fake one-line "entry" per
        # source line the .txt happened to wrap at.
        for s in sections:
            if s["entries"] and not any(e["license"] or e["desc"] for e in s["entries"]):
                s["text"] = " ".join(e["name"] for e in s["entries"])
                s["entries"] = []

        return {"ok": True, "intro": " ".join(intro_lines).strip(), "sections": sections}

    @staticmethod
    def _downloads_dir():
        """The REAL Downloads folder, from the shell's known-folder registry
        (SHGetKnownFolderPath, FOLDERID_Downloads). `~/Downloads` is only a
        guess: under OneDrive Known Folder Move (or any manual relocation)
        the actual folder lives elsewhere and the guess is an empty or
        missing directory. Falls back to the old guess on any failure."""
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
            fid = _GUID(0x374DE290, 0x123F, 0x4565,
                        (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            out = ctypes.c_wchar_p()
            hr = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(fid), 0, None, ctypes.byref(out))
            if hr == 0 and out.value:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)  # docs: the caller frees this
                return path
        except Exception:
            pass
        return os.path.join(os.path.expanduser("~"), "Downloads")

    def reveal_installer(self):
        """Finds ComprslySetup*.exe in Downloads and selects it in Explorer,
        so the user can delete it themselves to free space. Never deletes it
        automatically, that's a destructive action only the user should take.
        Falls back to just opening Downloads if the exact file isn't found
        there (it may have been moved, renamed, or already deleted)."""
        try:
            downloads = self._downloads_dir()
            if not os.path.isdir(downloads):
                return {"ok": False, "error": "no Downloads folder found"}
            candidates = [
                os.path.join(downloads, n) for n in os.listdir(downloads)
                if n.lower().startswith("comprslysetup") and n.lower().endswith(".exe")
            ]
            if candidates:
                candidates.sort(key=os.path.getmtime, reverse=True)
                subprocess.Popen(["explorer", "/select,", candidates[0]])
            else:
                subprocess.Popen(["explorer", downloads])
            return {"ok": True, "found": bool(candidates)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_website(self):
        """Opens comprsly.com in the user's default browser. The site is
        live (2026-07-26), this was the "Coming soon" placeholder link."""
        try:
            import webbrowser
            webbrowser.open("https://comprsly.com")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def report_issue(self):
        """Opens a pre-filled mailto: to contact@comprsly.com (real mail,
        relays through Resend as of the 2026-07-27 deliverability fix --
        see Build.md SS10t). Added for Microsoft Store Policy 11.16
        (generative-AI content needs "a means for users to report
        inappropriate content to the developer") -- the AI compress
        feature has never had one until now. Version is pre-filled since
        it's the first thing support needs and the user would otherwise
        have to go find it themselves."""
        try:
            import urllib.parse
            import webbrowser
            subject = urllib.parse.quote(f"Comprsly issue report (v{app.APP_VERSION})")
            body = urllib.parse.quote(
                "Describe what happened, and what you expected instead:\n\n\n"
                f"(App version {app.APP_VERSION} -- feel free to leave this line in)"
            )
            webbrowser.open(f"mailto:contact@comprsly.com?subject={subject}&body={body}")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def run():
    """Entry point for the `--web-settings` process. One-shot fallback ONLY
    (real ask 2026-07-25): the primary path is now run_settings_server below,
    kept warm between opens. This still exists so a failure to launch/talk to
    the warm server degrades to exactly today's known-working behavior,
    never a hard failure -- same fallback discipline as the AI worker."""
    try:
        center = _screen_center(1000, 680)
        kwargs = {"x": center[0], "y": center[1]} if center else {}
        _window[0] = webview.create_window(
            "Comprsly — Settings",
            html=_load_html("settings.html"),
            js_api=Bridge(),
            width=1000, height=680, min_size=(860, 600),
            **kwargs,
        )
        webview.start()   # blocks until the window closes; owns this process's main thread
        return 0
    except Exception as e:
        local_model._log(f"web settings failed: {e}")
        return 1


_settings_inp = [None]
_settings_outp = [None]


def _settings_closing_handler():
    """Intercepts the OS close button on the WARM settings window: hide
    instead of destroy, so the already-booted WebView2 engine survives for
    an instant re-show next time. Returning False cancels pywebview's own
    close -- verified against the real source (webview/event.py: Event.set()
    cancels only when a handler returns exactly False, webview/platforms/
    winforms.py: on_closing sets args.Cancel from that same result), not
    assumed from memory."""
    try:
        _window[0].hide()
    except Exception:
        pass
    try:
        if _settings_outp[0] is not None:
            _settings_outp[0].write(json.dumps({"event": "closed"}) + "\n")
            _settings_outp[0].flush()
    except Exception:
        pass
    return False


def _settings_server_loop():
    """Runs in a pywebview background thread once the GUI is up (same shape
    as _server_loop below for the review card). Reads JSON command lines
    from stdin and drives the warm Settings window."""
    inp = _settings_inp[0]
    if inp is None:
        local_model._log("settings server: no stdin, idle")
        return
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except Exception:
            continue
        c = cmd.get("cmd")
        try:
            if c == "show":
                # Real bug found live 2026-07-25: this used to call JS
                # `window.location.reload()`, which produced a BLANK BLACK
                # WINDOW on every second+ open. Root cause, verified against
                # pywebview's actual source (edgechromium.py): this window's
                # content was loaded via `html=`, which WebView2 renders
                # through CoreWebView2.NavigateToString -- there is no real
                # backing document URL for `location.reload()` to refetch,
                # so it reloaded to nothing. Window.load_html() is pywebview's
                # own real API for re-supplying content into an existing
                # window (it also resets the loaded/before_load events), so
                # the page's on-load get_state() call fires again correctly.
                _window[0].load_html(_load_html("settings.html"))
                # Re-center explicitly (real ask 2026-07-25): re-showing an
                # EXISTING WinForms window doesn't re-apply the creation-time
                # StartPosition, so without this it reopens wherever it last
                # was rather than centered. Uses _move_window_by_title, NOT
                # pywebview's own .move() -- that one is broken in this
                # installed version (see its docstring); before .show() so
                # there's no visible jump.
                center = _screen_center(1000, 680)
                if center:
                    _move_window_by_title("Comprsly — Settings", *center)
                _window[0].show()
            elif c == "quit":
                break
        except Exception as e:
            local_model._log(f"settings server cmd '{c}' failed: {e}")
    try:
        _window[0].destroy()
    except Exception:
        pass
    os._exit(0)


def run_settings_server():
    """Entry point for `--web-settings-server`: one long-lived warm Settings
    window (real ask 2026-07-25: tray click -> Settings visible took 3-4s
    EVERY time, a full cold WebView2 engine boot per click, the app's own
    slowest routine action). The first launch still pays that cost once --
    it's a genuinely new process and engine -- but the window then HIDES on
    close instead of exiting, so every later open reuses the warm engine and
    is near-instant. Same warm-process shape as run_reviewcard_server below,
    minus the badge-relative positioning this window doesn't need."""
    try:
        try:
            _settings_inp[0] = os.fdopen(0, "r", encoding="utf-8", errors="replace")
        except Exception:
            _settings_inp[0] = sys.stdin
        try:
            _settings_outp[0] = os.fdopen(1, "w", encoding="utf-8", errors="replace")
        except Exception:
            _settings_outp[0] = sys.stdout

        center = _screen_center(1000, 680)
        kwargs = {"x": center[0], "y": center[1]} if center else {}
        _window[0] = webview.create_window(
            "Comprsly — Settings",
            html=_load_html("settings.html"),
            js_api=Bridge(),
            width=1000, height=680, min_size=(860, 600),
            **kwargs,
        )
        try:
            _window[0].events.closing += _settings_closing_handler
        except Exception:
            # No close-interception available for some reason -- the window
            # will genuinely close and take the process with it, same as
            # today's `run()`. The client side's is_alive() check catches
            # that on the NEXT click and falls back to a fresh spawn, so
            # this degrades to today's exact behavior, never breaks it.
            pass
        webview.start(_settings_server_loop)
        return 0
    except Exception as e:
        local_model._log(f"settings server failed: {e}")
        return 1


class ReviewBridge:
    """Drives the web review card. Critically, it does NOT write to the user's
    text field itself — it EMITS apply-actions on stdout for the main process
    to perform with its captured control + the hard-won apply_new_text logic
    (Build.md §4), so that delicate focus/paste behavior is never rewritten.
    Compress runs here (reuses the shared model)."""

    def __init__(self, payload):
        self.p = payload
        self._cleaned = payload.get("text", "")

    def set_context(self, payload):
        """Persistent-server path (2026-07-23): reuse ONE bridge across every
        card open. Called right before the warm window is shown, so get_payload
        / apply_grammar / compress all see the current click's text + fixes."""
        self.p = payload or {}
        self._cleaned = self.p.get("text", "")

    def _emit(self, obj):
        # Raw fd 1 in the frozen windowed build (sys.stdout is None there), same
        # reason as the inference worker. _outp is bound by run_reviewcard_server.
        out = _outp[0] or sys.stdout
        try:
            out.write(json.dumps(obj) + "\n")
            out.flush()
        except Exception:
            pass

    def get_payload(self):
        return self.p

    def set_height(self, h):
        """Called from the page (window.__sync) after every re-render so the
        window re-fits to the new content height, keeping the badge corner
        fixed (see _fit_and_show)."""
        try:
            _fit_and_show(float(h))
        except Exception:
            pass
        return True

    def apply_grammar(self, idx):
        import suggestion_engine
        sugs = self.p.get("suggestions", [])
        chosen = [sugs[i] for i in idx if 0 <= i < len(sugs)]
        self._cleaned = suggestion_engine.apply_suggestions(self.p.get("text", ""), chosen)
        self._emit({"action": "apply", "stage": "grammar", "text": self._cleaned})
        return self._cleaned

    def compress(self):
        src = self._cleaned or self.p.get("text", "")
        try:
            out, err = local_model.rewrite_prompt_via_subprocess(src)
        except Exception as e:
            out, err = None, str(e)
        if err or not out:
            return {"optimized": None, "error": err or "empty"}
        import suggestion_engine
        s_tok = suggestion_engine.estimate_tokens(src)
        o_tok = suggestion_engine.estimate_tokens(out)
        return {"optimized": out, "original": src, "saved": max(s_tok - o_tok, 0),
                "src_tok": s_tok, "out_tok": o_tok}

    def apply_text(self, text, close=True):
        self._emit({"action": "apply", "stage": "final", "text": text})
        if close:
            self._close()
        return True

    def dismiss(self):
        self._emit({"action": "dismiss"})
        self._close()
        return True

    def _close(self):
        # Persistent server: HIDE the warm window, never destroy it, so the
        # next click can show it instantly. (The per-click card destroyed here;
        # that path is gone.) Hiding never activates, so no focus concern.
        _hide_window()


def run_reviewcard(payload_path):
    """Entry point for `--review-card <payload.json>`. Frameless, always-on-top
    window positioned by the badge; Win11 rounds/shadows it via DWM. Emits
    apply-actions on stdout (see ReviewBridge)."""
    try:
        with open(payload_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        local_model._log(f"review card: bad payload ({e})")
        return 1
    try:
        r = payload.get("rect") or {}
        # focus=False is load-bearing: the review card floats over the user's
        # AI chat and must NOT steal foreground, or the main app's watch loop
        # sees "focus left the text box" and tears the badge down (the card
        # vanishing bug, 2026-07-22). This is the same no-activate behavior the
        # old Tk card had via WS_EX_NOACTIVATE.
        w, h = int(payload.get("width", 412)), int(payload.get("height", 520))
        kwargs = dict(frameless=True, easy_drag=False, on_top=True, focus=False, width=w, height=h)
        if "x" in r and "y" in r:
            kwargs["x"], kwargs["y"] = _clamp_to_monitor(r["x"], r["y"], w, h)
        _window[0] = webview.create_window(
            "Comprsly", html=_load_html("reviewcard.html"),
            js_api=ReviewBridge(payload), **kwargs)
        webview.start()
        return 0
    except Exception as e:
        local_model._log(f"review card failed: {e}")
        return 1


# ---- persistent warm review card (2026-07-23) ------------------------------
# The per-click --review-card process above cold-started a whole WebView2 on
# every badge click: slow to appear, mispositioned, focus juggling. The warm
# server below creates the window ONCE (hidden), then just shows/moves/refreshes
# it on command, so it pops instantly with the full HTML design. Commands arrive
# as JSON lines on stdin; apply/dismiss actions still leave on stdout.
_outp = [None]        # raw fd-1 writer (bound in run_reviewcard_server)
_hwnd = [None]        # cached native window handle
_card_wh = [430, 560]
_anchor = [100, 100, 58, 58]   # badge rect (x, y, w, h) from the last show
_CARD_M = 12                    # inset: badge nests this far inside the corner
_CARD_MIN_H = 130
_CARD_MAX_H = 900

_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_HWND_TOPMOST = -1
_SW_HIDE = 0
# "Hidden" = parked far off-screen, NOT ShowWindow(SW_HIDE). A truly hidden
# WebView2 window stops compositing, so when shown via raw Win32 it paints
# blank even though its DOM is fully rendered (confirmed 2026-07-23: bd had
# 1250 chars, dark bg, yet the screen was white). Kept visible-but-off-screen,
# the controller keeps painting, so an on-screen move shows real content.
_OFFSCREEN = -32000
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080     # keep it out of the taskbar / alt-tab
_WS_EX_NOACTIVATE = 0x08000000     # show without stealing the text box's focus

# Declare Win32 signatures ONCE. Without argtypes, ctypes passes HWND as a
# 32-bit int and truncates it on 64-bit Windows, so SetWindowPos/ShowWindow
# silently hit the wrong window (the warm card never appeared, 2026-07-23).
import ctypes as _ct
from ctypes import wintypes as _wt
_U32 = _ct.windll.user32
_U32.SetWindowPos.argtypes = [_wt.HWND, _wt.HWND, _ct.c_int, _ct.c_int,
                              _ct.c_int, _ct.c_int, _wt.UINT]
_U32.SetWindowPos.restype = _wt.BOOL
_U32.ShowWindow.argtypes = [_wt.HWND, _ct.c_int]
_U32.ShowWindow.restype = _wt.BOOL
_U32.GetWindowThreadProcessId.argtypes = [_wt.HWND, _ct.POINTER(_wt.DWORD)]
_U32.GetWindowThreadProcessId.restype = _wt.DWORD
_U32.GetWindowTextW.argtypes = [_wt.HWND, _wt.LPWSTR, _ct.c_int]
_U32.GetWindowTextW.restype = _ct.c_int
_U32.GetWindowTextLengthW.argtypes = [_wt.HWND]
_U32.GetWindowTextLengthW.restype = _ct.c_int
_U32.EnumWindows.argtypes = [_ct.c_void_p, _wt.LPARAM]
_U32.EnumWindows.restype = _wt.BOOL
_U32.GetWindowLongPtrW.argtypes = [_wt.HWND, _ct.c_int]
_U32.GetWindowLongPtrW.restype = _ct.c_ssize_t
_U32.SetWindowLongPtrW.argtypes = [_wt.HWND, _ct.c_int, _ct.c_ssize_t]
_U32.SetWindowLongPtrW.restype = _ct.c_ssize_t
try:
    _U32.GetDpiForWindow.argtypes = [_wt.HWND]
    _U32.GetDpiForWindow.restype = _wt.UINT
except Exception:
    pass


def _dpi_scale(hwnd):
    """Monitor DPI scale (1.0 at 96 dpi). Badge coords come from Win32 in
    PHYSICAL pixels, but the card's CSS is in logical px, so the window's
    physical size must be scaled by this or it lands wrong / clipped on a
    HiDPI display (2026-07-23)."""
    try:
        return (_U32.GetDpiForWindow(hwnd) or 96) / 96.0
    except Exception:
        return 1.0


def _card_hwnd():
    """The warm window's HWND. Tries pywebview's native handle first, then
    falls back to enumerating this process's top-level windows by caption."""
    if _hwnd[0]:
        return _hwnd[0]
    w = _window[0]
    try:
        # WinForms Form.Handle is a System.IntPtr; ToInt64() is 64-bit safe.
        h = int(w.native.Handle.ToInt64())
        if h:
            _hwnd[0] = h
            return h
    except Exception:
        pass
    try:
        pid = _ct.windll.kernel32.GetCurrentProcessId()
        found = []

        @_ct.WINFUNCTYPE(_ct.c_bool, _wt.HWND, _wt.LPARAM)
        def _cb(hwnd, _lp):
            wpid = _wt.DWORD()
            _U32.GetWindowThreadProcessId(hwnd, _ct.byref(wpid))
            if wpid.value == pid:
                n = _U32.GetWindowTextLengthW(hwnd)
                buf = _ct.create_unicode_buffer(n + 1)
                _U32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value == "Comprsly":
                    found.append(hwnd)
            return True

        _U32.EnumWindows(_cb, 0)
        if found:
            _hwnd[0] = found[0]
            return found[0]
    except Exception as e:
        local_model._log(f"card hwnd lookup failed: {e}")
    return None


def _make_toolwindow():
    """Overlay window styles: TOOLWINDOW keeps it out of the taskbar/alt-tab,
    NOACTIVATE lets it show without stealing focus from the user's text box
    (so they can keep typing while it's up) — the same behaviour the native
    card gets from make_window_non_activating."""
    hwnd = _card_hwnd()
    if not hwnd:
        return
    try:
        ex = _U32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
        _U32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE,
                               ex | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE)
    except Exception as e:
        local_model._log(f"card overlay style failed: {e}")


def _fit_and_show(h_css):
    """Size the window to the content height (CSS px) and place it nested at
    the badge — card grows UP and LEFT so the badge sits in its bottom-right
    corner. Physical pixels throughout (SetWindowPos), DPI-scaled from the CSS
    height, so it lands right on HiDPI displays. Called on the initial show and
    on every re-render (Step 1->2, compress result); the badge corner stays
    fixed so the card grows/shrinks upward like the native card's _refit."""
    h_css = max(_CARD_MIN_H, min(int(h_css), _CARD_MAX_H))
    hwnd = _card_hwnd()
    _make_toolwindow()   # re-assert no-taskbar / no-activate styles
    # pywebview show() flips the WebView2 controller visible so it paints
    # (raw Win32 alone leaves it blank); SetWindowPos then forces the exact
    # physical geometry, overriding pywebview's logical-pixel placement.
    try:
        _window[0].show()
    except Exception as e:
        local_model._log(f"card show failed: {e}")
    if not hwnd:
        return
    scale = _dpi_scale(hwnd)
    pw = round(_card_wh[0] * scale)
    ph = round(h_css * scale)
    m = round(_CARD_M * scale)
    bx, by, bw, bh = _anchor
    x = bx + bw + m - pw
    y = by + bh + m - ph
    x, y = _clamp_to_monitor(x, y, pw, ph)
    _U32.SetWindowPos(hwnd, _HWND_TOPMOST, int(x), int(y), pw, ph,
                      _SWP_NOACTIVATE | _SWP_SHOWWINDOW)


def _hide_window():
    try:
        _window[0].hide()
    except Exception:
        pass


def _server_loop():
    """Runs in a pywebview background thread once the GUI is up. Reads JSON
    command lines from stdin and drives the warm window."""
    _make_toolwindow()   # keep it out of the taskbar/alt-tab
    _hide_window()       # park off-screen until the first show
    bridge = _bridge[0]
    inp = _inp[0]
    if inp is None:
        local_model._log("review-card server: no stdin, idle")
        return
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except Exception:
            continue
        c = cmd.get("cmd")
        try:
            if c == "show":
                bridge.set_context(cmd.get("payload") or {})
                b = cmd.get("badge") or {}
                _anchor[0] = int(b.get("x", 100)); _anchor[1] = int(b.get("y", 100))
                _anchor[2] = int(b.get("w", 58));  _anchor[3] = int(b.get("h", 58))
                # Wait for the page's JS (window.__load) to exist before pushing
                # the payload; the first show can arrive before the DOM is ready.
                _ready.wait(timeout=8)
                # Render + measure while still parked off-screen (layout/measure
                # are valid even when not painting), then fit the window to the
                # content height and show it nested at the badge — so there's no
                # dead space and the position is right regardless of height.
                r = _window[0].evaluate_js(
                    f"(function(){{if(window.__load){{window.__load({json.dumps(bridge.p)});"
                    f"return String(window.__measure());}}return '0';}})()")
                try:
                    h = int(float(r))
                except Exception:
                    h = _card_wh[1]
                    local_model._log(f"card measure failed -> {r}")
                _fit_and_show(h)
            elif c == "hide":
                _hide_window()
            elif c == "quit":
                break
        except Exception as e:
            local_model._log(f"review-card server cmd '{c}' failed: {e}")
    try:
        _window[0].destroy()
    except Exception:
        pass
    os._exit(0)


_bridge = [None]
_inp = [None]
import threading as _threading
_ready = _threading.Event()


def run_reviewcard_server():
    """Entry point for `--review-card-server`: one long-lived warm window."""
    try:
        # Bind raw pipe fds like the inference worker (windowed frozen build
        # sets sys.stdin/std out to None).
        try:
            _inp[0] = os.fdopen(0, "r", encoding="utf-8", errors="replace")
        except Exception:
            _inp[0] = sys.stdin
        try:
            _outp[0] = os.fdopen(1, "w", encoding="utf-8", errors="replace")
        except Exception:
            _outp[0] = sys.stdout

        _bridge[0] = ReviewBridge({"text": "", "suggestions": [], "ai_enabled": False,
                                   "theme": "light"})
        _window[0] = webview.create_window(
            "Comprsly", html=_load_html("reviewcard.html"),
            js_api=_bridge[0], frameless=True, easy_drag=False, on_top=True,
            focus=False, width=_card_wh[0], height=_card_wh[1], hidden=True)
        # Signal the command loop once the DOM/JS is ready, so the first show
        # doesn't push a payload into a page that hasn't defined window.__load.
        try:
            _window[0].events.loaded += lambda: _ready.set()
        except Exception:
            _ready.set()
        webview.start(_server_loop)
        return 0
    except Exception as e:
        local_model._log(f"review-card server failed: {e}")
        return 1


def run_onboarding():
    """Entry point for the `--onboarding` process (first-run welcome)."""
    try:
        _window[0] = webview.create_window(
            "Welcome to Comprsly",
            html=_load_html("onboarding.html"),
            js_api=Bridge(),
            width=470, height=624, resizable=False,
        )
        webview.start()
        return 0
    except Exception as e:
        local_model._log(f"web onboarding failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
