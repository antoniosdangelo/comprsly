"""Comprsly -- native Windows spell-check.

Real ask 2026-07-20: "theres misspelled words that can use the native spell
check." Uses Windows' own ISpellCheckerFactory COM API (spellcheck.h,
Windows 8+), the same engine Notepad/Edge/Word use, not a bundled
dictionary or another ML model. Genuinely lightweight: already installed
with Windows, ~3ms to create a checker, ~1ms to check a sentence, both
confirmed by direct benchmarking, not assumed.

Hand-defines the COM interfaces via comtypes rather than using
comtypes.client.GetModule, there's no bundled typelib wrapper for this API,
and hand-defining (vs. dynamic typelib generation) also avoids PyInstaller's
usual comtypes packaging pitfalls, nothing here needs the dynamic gen_py
cache. GUIDs verified against the real Windows SDK header values (not
guessed), a first attempt using guessed GUIDs failed with E_NOINTERFACE,
these are confirmed working via direct testing: found real misspellings
("tihs" -> this, "outptu" -> output) with correct suggestions.
"""

import os
import threading
import time

import comtypes
from comtypes import GUID, COMMETHOD, HRESULT, IUnknown
from ctypes import c_wchar_p, c_ulong, POINTER, c_int
from ctypes.wintypes import BOOL

CLSID_SpellCheckerFactory = GUID("{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}")


class ISpellingError(IUnknown):
    _iid_ = GUID("{B7C82D61-FBE8-4B47-9B27-6C0D2E0DE0A3}")
    _methods_ = [
        COMMETHOD([], HRESULT, "get_StartIndex", (["out"], POINTER(c_ulong), "value")),
        COMMETHOD([], HRESULT, "get_Length", (["out"], POINTER(c_ulong), "value")),
        COMMETHOD([], HRESULT, "get_CorrectiveAction", (["out"], POINTER(c_int), "value")),
        COMMETHOD([], HRESULT, "get_Replacement", (["out"], POINTER(c_wchar_p), "value")),
    ]


class IEnumSpellingError(IUnknown):
    _iid_ = GUID("{803E3BD4-2828-4410-8290-418D1D73C762}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Next", (["out"], POINTER(POINTER(ISpellingError)), "value")),
    ]


class IEnumString(IUnknown):
    _iid_ = GUID("{00000101-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD(
            [], HRESULT, "Next",
            (["in"], c_ulong, "celt"),
            (["out"], POINTER(c_wchar_p), "rgelt"),
            (["out"], POINTER(c_ulong), "pceltFetched"),
        ),
        COMMETHOD([], HRESULT, "Skip", (["in"], c_ulong, "celt")),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "Clone", (["out"], POINTER(POINTER(IUnknown)), "ppenum")),
    ]


class ISpellChecker(IUnknown):
    _iid_ = GUID("{B6FD0B71-E2BC-4653-8D05-F197E412770B}")
    _methods_ = [
        COMMETHOD([], HRESULT, "get_LanguageTag", (["out"], POINTER(c_wchar_p), "value")),
        COMMETHOD(
            [], HRESULT, "Check",
            (["in"], c_wchar_p, "text"),
            (["out"], POINTER(POINTER(IEnumSpellingError)), "value"),
        ),
        COMMETHOD(
            [], HRESULT, "Suggest",
            (["in"], c_wchar_p, "word"),
            (["out"], POINTER(POINTER(IEnumString)), "value"),
        ),
    ]


class ISpellCheckerFactory(IUnknown):
    _iid_ = GUID("{8E018A9D-2415-4677-BF08-794EA61F94BB}")
    # Method ORDER here is the vtable order and must match spellcheck.h
    # exactly: get_SupportedLanguages, IsSupported, CreateSpellChecker
    # (verified 2026-07-24 against the SDK header's ISpellCheckerFactoryVtbl
    # in microsoft/win32metadata, generation/WinSDK/RecompiledIdlHeaders/um/
    # spellcheck.h -- the learn.microsoft.com method table is alphabetical
    # and NOT the vtable order). An earlier revision had the first two
    # swapped; it went unnoticed because CreateSpellChecker, the only method
    # actually called, sits in slot 3 either way.
    _methods_ = [
        COMMETHOD([], HRESULT, "get_SupportedLanguages", (["out"], POINTER(POINTER(IEnumString)), "value")),
        COMMETHOD(
            [], HRESULT, "IsSupported",
            (["in"], c_wchar_p, "languageTag"),
            (["out"], POINTER(BOOL), "value"),
        ),
        COMMETHOD(
            [], HRESULT, "CreateSpellChecker",
            (["in"], c_wchar_p, "languageTag"),
            (["out"], POINTER(POINTER(ISpellChecker)), "value"),
        ),
    ]


CORRECTIVE_ACTION_GET_SUGGESTIONS = 1
CORRECTIVE_ACTION_REPLACE = 2

# PER-THREAD, not module-global (real bug found 2026-07-22, market audit):
# an STA COM object is bound to the apartment of the thread that created it.
# The shared checker was created by whichever thread called first (in the
# app, the 0.7s watcher thread), and every OTHER thread's calls then failed
# with RPC_E_WRONG_THREAD -- swallowed by the defensive except blocks below,
# so check() returned [] and is_correct() returned False, SILENTLY. Measured
# directly: the same text produced 2 misspellings on the creating thread and
# 0 on any other. In the app that meant the Tk-thread re-analyze on the
# clipboard path (Claude) quietly lost ALL spelling suggestions, the likely
# root cause of the recurring "it didn't detect my typos" reports. A
# checker per thread (they're ~3ms to create, measured) removes the failure
# mode entirely.
_tls = threading.local()


def _log(message):
    """Writes to the same debug.log main.py uses. Kept local so winspell has
    no import dependency on main."""
    try:
        path = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Comprsly", "debug.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] winspell: {message}\n")
    except Exception:
        pass


def _ensure_checker():
    """Real bug found 2026-07-21: spelling worked when run from source but
    found nothing inside the packaged exe, so a deliberately misspelled
    prompt came back with zero suggestions. Cause: this used
    `comtypes.client.CreateObject`, and importing `comtypes.client` drags in
    the dynamic code-generation machinery (`comtypes.client._generate`,
    `comtypes.tools.codegenerator.*`), which PyInstaller does not bundle
    (they show up in the build's missing-modules warnings). Under the frozen
    build the import failed, `is_available()` returned False, and spelling
    silently did nothing.

    `comtypes.CoCreateInstance` is the low-level call that does the actual
    work, needs none of that codegen, and is what CreateObject delegates to
    anyway once an explicit interface is given.

    Returns THIS THREAD's checker (or None). See the note above _tls: one
    checker per calling thread, because an STA COM object silently fails
    from any thread other than its creator."""
    checker = getattr(_tls, "checker", None)
    if checker is not None or getattr(_tls, "init_error", None) is not None:
        return checker
    try:
        comtypes.CoInitialize()  # idempotent per thread; S_FALSE if repeated
        factory = comtypes.CoCreateInstance(
            CLSID_SpellCheckerFactory, interface=ISpellCheckerFactory
        )
        _tls.checker = factory.CreateSpellChecker("en-US")
        _log(f"spell checker ready (thread {threading.get_ident()})")
        return _tls.checker
    except Exception as e:
        _tls.init_error = f"{type(e).__name__}: {e}"
        _log(f"UNAVAILABLE on thread {threading.get_ident()}, "
             f"spelling disabled -> {_tls.init_error}")
        return None


def is_available():
    return _ensure_checker() is not None


_correct_cache = {}
_CORRECT_CACHE_MAX = 4000


def is_correct(word):
    """Is this single word spelled correctly?

    Needed by the misplaced-space rule, which has to test many candidate
    splits of a word pair. Cached because analyze() runs on every 0.7s poll
    tick and each miss is a real COM round-trip.
    """
    if not word:
        return False
    hit = _correct_cache.get(word)
    if hit is not None:
        return hit
    checker = _ensure_checker()
    if checker is None:
        return False
    try:
        errors = checker.Check(word)
        ok = not bool(errors.Next())
    except Exception:
        # Fail-safe, NOT cached: a transient COM failure here is not a
        # verdict about the word, and caching it would pin a correctly
        # spelled word as "misspelled" until the 4000-entry cache clears.
        # Only real answers from the engine go in the cache.
        return False
    if len(_correct_cache) >= _CORRECT_CACHE_MAX:
        _correct_cache.clear()
    _correct_cache[word] = ok
    return ok


def _utf16_index_map(text):
    """Maps UTF-16 code-unit offsets -> Python code-point offsets.

    Real data-corruption bug found 2026-07-22 (market audit): the COM spell
    checker receives the text as UTF-16 and reports StartIndex/Length in
    UTF-16 CODE UNITS, but Python strings index by CODE POINTS. Any astral
    character (an emoji is the everyday case: one Python code point, TWO
    UTF-16 units) shifts every COM offset after it by one. Measured on
    "hey 🚀 fix teh code": the engine sliced out 'eh ' instead of 'teh',
    asked Windows to fix THAT, and offered garbage ("edh") whose application
    would corrupt the user's text. Emoji are routine in chat prompts, so the
    offsets must be translated, not trusted.

    Table has one entry per UTF-16 unit plus a final end sentinel, so a
    (start + length) one-past-the-end index is always resolvable."""
    table = []
    for i, ch in enumerate(text):
        table.append(i)
        if ord(ch) > 0xFFFF:  # astral char: a surrogate PAIR in UTF-16
            table.append(i)
    table.append(len(text))
    return table


def check(text, max_suggestions=3):
    """Returns a list of (start, length, misspelled_word, [suggestions]),
    with start/length in PYTHON code-point offsets (translated from the
    COM API's UTF-16 units, see _utf16_index_map). Only includes real,
    correctable misspellings (CorrectiveAction is GetSuggestions or
    Replace), skips anything Windows can't actually suggest a fix for."""
    checker = _ensure_checker()
    if checker is None:
        return []
    results = []
    # Only pay for the translation table when the text actually contains an
    # astral character; for pure-BMP text (the overwhelming case) UTF-16 and
    # code-point offsets are identical.
    u16map = _utf16_index_map(text) if any(ord(c) > 0xFFFF for c in text) else None
    try:
        errors_enum = checker.Check(text)
        while True:
            err = errors_enum.Next()
            if not err:  # NULL COM pointer (ctypes POINTER is falsy when NULL)
                break
            action = err.get_CorrectiveAction()
            if action not in (CORRECTIVE_ACTION_GET_SUGGESTIONS, CORRECTIVE_ACTION_REPLACE):
                continue
            start = err.get_StartIndex()
            length = err.get_Length()
            if u16map is not None:
                if start + length >= len(u16map):
                    continue  # defensive: offset past the table, skip it
                end = u16map[start + length]
                start = u16map[start]
                length = end - start
            word = text[start:start + length]

            suggestions = []
            if action == CORRECTIVE_ACTION_REPLACE:
                try:
                    suggestions = [err.get_Replacement()]
                except Exception:
                    pass
            if not suggestions:
                try:
                    sugg_enum = checker.Suggest(word)
                    while len(suggestions) < max_suggestions:
                        s = sugg_enum.Next(1)
                        if not s or not s[0]:
                            break
                        suggestions.append(s[0])
                except Exception:
                    pass

            if suggestions:
                results.append((start, length, word, suggestions))
    except Exception:
        pass
    return results
