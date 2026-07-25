"""Comprsly -- rules-first token-reduction engine (Python port).

Real product pivot 2026-07-20: rules run first and are the default path,
the local LLM (see local_model.py) is only a fallback for text these rules
can't confidently improve, not the primary mechanism, real priority is
token efficiency, staying fast and lightweight (no multi-second model load,
no multi-GB memory spike) for the common case. Every suggestion here is
per-occurrence and span-based (start/end offsets into the real text), not a
blanket whole-text transform, so the UI can show and accept them one at a
time, Grammarly-style, as well as apply all of them together in one shot.

Same rule *categories* as extension/suggestions.js and terminal/suggestions.js,
kept as a direct port rather than a shared import across languages, each
runtime (browser, Node, Python/native) is sandboxed from the others, so a
small amount of deliberate duplication here is the honest tradeoff, not an
oversight. If the rules change, all three copies need updating together.
"""

import re

try:
    import winspell
except ImportError:
    winspell = None

FILLER_PHRASES = [
    "please note that",
    "i would like you to",
    "i was wondering if you could",
    "if you don't mind",
    "if it's not too much trouble",
    "could you please",
    "can you please",
    "i just wanted to",
    "just to let you know",
    "thank you so much in advance",
    "thanks in advance",
    "i really appreciate it",
    "as you may know",
    "needless to say",
]

VERBOSE_REPLACEMENTS = [
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "because"),
    (re.compile(r"\bat this point in time\b", re.IGNORECASE), "now"),
    (re.compile(r"\bin the event that\b", re.IGNORECASE), "if"),
    (re.compile(r"\bfor the purpose of\b", re.IGNORECASE), "to"),
    (re.compile(r"\bwith regard to\b", re.IGNORECASE), "about"),
    # "in regards to" (plural "regards") is the common but non-standard
    # variant of "with regard to" -- both wordy AND arguably ungrammatical,
    # found 2026-07-25 testing punctuation/grammar edge cases; same fix as
    # the entry above.
    (re.compile(r"\bin regards to\b", re.IGNORECASE), "about"),
    (re.compile(r"\bin the near future\b", re.IGNORECASE), "soon"),
    (re.compile(r"\ba large number of\b", re.IGNORECASE), "many"),
    (re.compile(r"\bon a regular basis\b", re.IGNORECASE), "regularly"),
    (re.compile(r"\bin a timely manner\b", re.IGNORECASE), "promptly"),
    (re.compile(r"\bit is important to note that\b", re.IGNORECASE), ""),
    (re.compile(r"\bit should be noted that\b", re.IGNORECASE), ""),
]

# ---- Content protection ------------------------------------------------
# Real ask 2026-07-20: "protect important content like URLs, numbers, code,
# names, commands, and formatting." A rule-based edit is only ever applied
# if its matched span doesn't overlap any of these, deliberately erring
# toward under-suggesting rather than risking corrupting something the user
# needs verbatim.

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_URL_RE = re.compile(r"\bhttps?://\S+|\bwww\.\S+\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d[\d,.:/apmAPM-]*\b")
_COMMAND_RE = re.compile(r"(?:^|\s)(?:[$>]\s?\S+|--[\w-]+)")
# Conservative "likely a proper noun" heuristic, not real NER: a capitalized
# word that ISN'T the first word of its sentence. Real names overwhelmingly
# look like this; including sentence-initial capitals would false-positive
# on every single sentence.
_NAME_RE = re.compile(r"(?<=[a-z,;:]\s)[A-Z][a-zA-Z]*(?:\s[A-Z][a-zA-Z]*)*")
_FORMATTING_RE = re.compile(
    r"^#{1,6}\s.*$|^\s*[-*+]\s|^\s*\d+\.\s|\*\*[^*\n]+\*\*|__[^_\n]+__|^\|.*\|$",
    re.MULTILINE,
)

# Internal-dot abbreviations ("e.g.", "i.e.", "a.m.", "ph.d.") that the
# missing-space rule would otherwise split at the inner dot ("e.g" -> "e. g").
# Protected as a whole so no rule touches them. Only the unambiguous dotted
# forms are listed; plain-word abbreviations ("etc", "vs") are normally
# followed by a space, so the missing-space rule never fires on them.
_ABBREV_RE = re.compile(r"\b(?:e\.g|i\.e|a\.m|p\.m|u\.s|u\.k|ph\.d)\.?", re.IGNORECASE)

# Filenames (real bug 2026-07-22, market audit): "debug main.py it throws"
# had the missing-space rule fire on the ".p" inside "main.py" and split the
# filename into "main. py". This is a tool for people writing technical
# prompts; filenames must be untouchable. A conservative KNOWN-EXTENSION list
# rather than any word.word shape, because a lowercase letter right after a
# period is otherwise exactly the missing-space typo that rule exists to fix
# ("done.next thing"). Deliberately excluded: .so/.do and other extensions
# that are common English words likelier to follow a sentence period.
_FILENAME_RE = re.compile(
    r"\b\w[\w.-]*\.(?:py|pyw|ipynb|jsx?|tsx?|mjs|jsonl?|md|txt|csv|tsv|"
    r"html?|css|scss|xml|svg|ya?ml|toml|ini|cfg|conf|env|lock|log|"
    r"exe|dll|msi|bat|cmd|ps1|sh|iss|spec|"
    r"pdf|docx?|xlsx?|pptx?|rtf|"
    r"png|jpe?g|gif|webp|ico|bmp|mp3|mp4|wav|mov|avi|"
    r"zip|tar|gz|7z|rar|"
    r"cpp|hpp|cs|java|kt|rs|go|rb|php|swift|sql|lua|c|h)\b",
    re.IGNORECASE)

# Bare domains without a scheme (audit 2026-07-25, CONFIRMED live: the
# missing-space rule split "google.com" into "google. com" at tier 1). A
# conservative KNOWN-TLD list, same philosophy as _FILENAME_RE's extension
# list: "done.next" must still be fixable as a missing space.
_DOMAIN_RE = re.compile(
    r"\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|edu|gov|mil|int|io|ai|co|dev|"
    r"app|me|us|uk|ca|de|fr|au|jp|in|br|info|biz|tv|xyz|cloud|site|online)"
    r"(?:/\S*)?\b", re.IGNORECASE)
# Dotted acronyms ("F.B.I.", "a.k.a.", "Ph.D" beyond the fixed _ABBREV_RE
# list): two or more single-letter-dot groups. Same audit, same tier-1
# splitting failure ("the F. B. I. report").
# No trailing \b after the dot form: \b can't match between "." and a space,
# which silently excluded the FINAL dot of "F.B.I." from the span and let
# the capitalization rule read it as a sentence end ("F.B.I. Called").
_DOTTED_ACRONYM_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}(?:[A-Za-z]\b)?")
# Emoticons (audit 2026-07-25, CONFIRMED live: "sounds good :D thanks"
# became "good: D thanks" via missing-space + space-before-punct). Only when
# preceded by whitespace/start, so real punctuation is never protected.
# The leading whitespace is CONSUMED into the match on purpose: the
# space-before-punct rule's span is just the whitespace before ":" and
# wouldn't otherwise overlap the protected emoticon ("good :D" was still
# losing its space even with ":D" itself protected).
_EMOTICON_RE = re.compile(
    r"(?:^|\s)[:;=8xX][-~']?[)(\[\]DPpOo3*/\\|]+")

# Code identifiers OUTSIDE backtick fences (audit battery 2026-07-25,
# CONFIRMED live: pasting a bare snippet -- the normal way people paste code
# at an LLM -- got "return teh_value" spell-"fixed" to "the_value" at tier 1,
# silently breaking the user's code). English never has interior underscores
# or interior capitals, so both shapes are pure-code signals. Same for a
# line indented 4+ spaces or a tab (the markdown code convention).
_IDENTIFIER_RE = re.compile(r"\b\w+_\w+\b|\b[a-z]+[A-Z]\w*\b")
_INDENTED_CODE_RE = re.compile(r"(?m)^(?: {4,}|\t).*$")

_PROTECTION_PATTERNS = (
    _CODE_FENCE_RE, _INLINE_CODE_RE, _URL_RE, _NUMBER_RE,
    _COMMAND_RE, _NAME_RE, _FORMATTING_RE, _ABBREV_RE, _FILENAME_RE,
    _DOMAIN_RE, _DOTTED_ACRONYM_RE, _EMOTICON_RE,
    _IDENTIFIER_RE, _INDENTED_CODE_RE,
)

# Real bug found 2026-07-25 (testing punctuation edge cases): the terminal-
# punctuation rule reused the FULL protected-span list to decide whether the
# last word is safe to append a mark after, but that list is built for a
# different job (don't let a rule EDIT inside a protected span). Appending
# "." right after a URL or filename really is ambiguous (does the dot belong
# to the domain/extension?), but appending it after a plain number/time
# ("5pm.") or a name ("Sarah.") is completely normal -- yet NUMBER_RE and
# NAME_RE are both real PROTECTION_PATTERNS entries, so any sentence ending
# in a time, a plain number, or a proper name was silently getting NO
# terminal-punctuation suggestion at all. Confirmed: "I need to talk to
# Sarah" and "Lets meet at 5pm" got nothing; "I saw him at the store" (ends
# in an ordinary word) worked fine. This narrower set is used ONLY for that
# one decision; the general `protected` list elsewhere is unchanged.
_TERMINAL_PUNCT_UNSAFE_PATTERNS = (
    _CODE_FENCE_RE, _INLINE_CODE_RE, _URL_RE,
    _COMMAND_RE, _FORMATTING_RE, _ABBREV_RE, _FILENAME_RE,
    # Same dot-ambiguity as URLs/filenames: appending "." right after
    # "google.com" or "F.B.I." is genuinely unclear (2026-07-25).
    _DOMAIN_RE, _DOTTED_ACRONYM_RE, _EMOTICON_RE,
)


def _unsafe_to_punctuate_after(text):
    spans = []
    for pattern in _TERMINAL_PUNCT_UNSAFE_PATTERNS:
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end()))
    return spans


def _protected_spans(text):
    spans = []
    for pattern in _PROTECTION_PATTERNS:
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end()))
    spans.sort()
    return spans


def _overlaps_any(start, end, spans):
    return any(start < e and end > s for s, e in spans)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return -(-len(text.strip()) // 4)  # ceil division, ~4 chars per token


def _make_suggestion(kind, label, start, end, original, replacement):
    saved = estimate_tokens(original) - estimate_tokens(replacement)
    if saved <= 0:
        return None
    return {
        "kind": kind,
        "label": label,
        "start": start,
        "end": end,
        "original": original,
        "replacement": replacement,
        "saved_tokens": saved,
    }


def _find_filler_suggestions(text, protected):
    # Match against the ORIGINAL text with IGNORECASE, with \b anchors
    # (audit 2026-07-25, both CONFIRMED live): matching re.escape(phrase)
    # against text.lower() had no word boundaries, so "hi just wanted to say
    # thanks" matched "i just wanted to" starting inside "hi" and apply
    # produced "H say thanks"; and lower() can CHANGE STRING LENGTH ("İ"
    # lowercases to two code points), shifting every span computed after it
    # ("İzmir is nice, i just wanted to say thanks" applied to "Isay").
    out = []
    for phrase in FILLER_PHRASES:
        pat = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
        for m in pat.finditer(text):
            start, end = m.start(), m.end()
            if _overlaps_any(start, end, protected):
                continue
            s = _make_suggestion(
                "filler", "Drop the pleasantries", start, end,
                text[start:end], "",
            )
            if s:
                out.append(s)
                # Deleting an opener ("Please note that the build fails")
                # leaves its sentence starting lowercase, and the regular
                # capitalization rule can't help: it reads the ORIGINAL text,
                # where the sentence still starts with the filler (audit
                # 2026-07-25, F11, CONFIRMED live). Emit the capitalization
                # of the word promoted to sentence-initial as a companion; it
                # rides this finder's tier through analyze()'s _tag, so a
                # default apply never capitalizes mid-sentence without the
                # deletion it exists for.
                cap = _capitalize_after_deletion(text, start, end, protected)
                if cap:
                    out.append(cap)
    return out


def _find_verbose_suggestions(text, protected):
    out = []
    for pattern, replacement in VERBOSE_REPLACEMENTS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if _overlaps_any(start, end, protected):
                continue
            fixed = replacement
            if fixed and _at_sentence_start(text, start):
                # "In order to proceed" -> "to proceed" was decapitating the
                # sentence (audit 2026-07-25, F11, CONFIRMED live): the
                # replaced opener carried the capital and the canned
                # replacement is lowercase. At a sentence start the
                # replacement takes the capital itself. (A lowercase opener
                # needs no help here: the capitalization rule still fires on
                # its first letter and apply_suggestions folds it in.)
                fixed = fixed[0].upper() + fixed[1:]
            s = _make_suggestion(
                "verbose", "Simplify a wordy phrase", start, end,
                text[start:end], fixed,
            )
            if s:
                out.append(s)
                if not fixed:
                    # The two delete-outright entries ("it is important to
                    # note that ...") decapitate exactly like a filler does;
                    # same companion mechanism (F11).
                    cap = _capitalize_after_deletion(text, start, end, protected)
                    if cap:
                        out.append(cap)
    return out


_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")


def _find_redundant_sentence_suggestions(text, protected):
    """Flags sentences that are exact near-duplicates (after normalizing
    punctuation/case) OR close paraphrases of an earlier sentence, a real
    "repeated instruction," not just literally identical text. The overlap
    check is a cheap word-set ratio, deliberately not ML/embeddings, stays
    local, instant, and explainable."""
    matches = [m for m in _SENTENCE_RE.finditer(text) if m.group().strip()]
    if len(matches) < 2:
        return []

    seen = []  # list of (normalized_text, word_set)
    out = []
    for m in matches:
        raw = m.group()
        stripped = raw.strip()
        if len(stripped) < 8:
            continue
        start = m.start() + (len(raw) - len(raw.lstrip()))
        end = start + len(stripped)
        if _overlaps_any(start, end, protected):
            continue

        normalized = re.sub(r"[^a-z0-9 ]", "", stripped.lower()).strip()
        words = set(normalized.split())
        if not words:
            continue

        is_dupe = False
        for prev_norm, prev_words in seen:
            if normalized == prev_norm:
                is_dupe = True
                break
            overlap = len(words & prev_words) / max(len(words), len(prev_words))
            if overlap >= 0.8:
                is_dupe = True
                break

        if is_dupe:
            s = _make_suggestion(
                "redundant", "Remove a repeated instruction", start, end,
                text[start:end], "",
            )
            if s:
                out.append(s)
        else:
            seen.append((normalized, words))

    return out


# ---- Grammar rules ------------------------------------------------------
# Real ask 2026-07-20: "why can't we build the real grammar corrector."
# Honest answer, not a dismissal: genuine grammar checking (subject-verb
# agreement, tense, etc.) needs real POS tagging to do safely, that's
# either a heavy NLP tool (LanguageTool, a Java process) or another ML
# model, both would reintroduce the exact memory/lag problem this whole
# session was spent fixing, directly against the "lightweight" priority.
# What's real and safe to do with plain rules: a small set of genuinely
# unambiguous, high-confidence patterns, not comprehensive, but honest
# about that limit rather than pretending to be a full grammar checker.

def _make_grammar_suggestion(kind, label, start, end, original, replacement):
    # Unlike the token-reduction rules above, a grammar fix's value is
    # correctness, not compression, some of these (adding a missing space,
    # "a" -> "an") cost a character rather than save one. Never gated on
    # saved_tokens > 0, that check only applies to the compression rules.
    saved = max(estimate_tokens(original) - estimate_tokens(replacement), 0)
    return {
        "kind": kind,
        "label": label,
        "start": start,
        "end": end,
        "original": original,
        "replacement": replacement,
        "saved_tokens": saved,
    }


_REPEATED_WORD_RE = re.compile(r"\b(\w+)([ \t]+)(\1)\b", re.IGNORECASE)


# Grammatical doubles that are correct English (audit 2026-07-25, CONFIRMED
# live: "He had had enough" lost a "had" at tier 1, changing the tense, and
# "I know that that approach is wrong" lost a "that"). Both are textbook
# valid constructions; a REAL accidental double of these is rare enough that
# missing it costs less than silently rewriting correct grammar.
_REPEATED_WORD_ALLOWED = {"had", "that"}


def _find_repeated_word_suggestions(text, protected):
    out = []
    for m in _REPEATED_WORD_RE.finditer(text):
        if m.group(1).lower() in _REPEATED_WORD_ALLOWED:
            continue
        start, end = m.start(), m.end()
        if _overlaps_any(start, end, protected):
            continue
        out.append(_make_grammar_suggestion(
            "grammar", "Remove a repeated word", start, end, text[start:end], m.group(1),
        ))
    return out


_MISSING_SPACE_RE = re.compile(r"[.,!?;:][A-Za-z]")


def _find_missing_space_suggestions(text, protected):
    out = []
    for m in _MISSING_SPACE_RE.finditer(text):
        start, end = m.start(), m.end()
        if _overlaps_any(start, end, protected):
            continue
        matched = m.group()
        out.append(_make_grammar_suggestion(
            "grammar", "Add a missing space", start, end, matched, f"{matched[0]} {matched[1]}",
        ))
    return out


# Deliberately small, real exception lists, not a pronunciation dictionary:
# words where the first letter's usual vowel/consonant class doesn't match
# how the word actually sounds spoken, the actual rule behind "a" vs "an".
# Anything not on these lists falls back to the plain letter check, correct
# for the large majority of English words.
_A_AN_VOWEL_SOUND_EXCEPTIONS = {
    "one", "once", "unicorn", "unicycle", "unique", "unit", "united",
    "university", "usual", "useful", "user", "uniform", "unanimous",
    "european", "eucalyptus", "ewe", "utopia", "utopian",
    # Initialisms spoken letter-by-letter whose first letter NAME starts
    # with a consonant sound ("you-...") -- audit 2026-07-25, CONFIRMED
    # live: "give me a url" was "fixed" to "an url". Core-audience words.
    "url", "urls", "usb", "ui", "ux", "uri", "uris", "utf", "uuid", "uuids",
}
_A_AN_CONSONANT_SOUND_EXCEPTIONS = {
    "hour", "hourly", "honest", "honestly", "honor", "honorable", "honorary", "heir", "heiress",
    # Initialisms whose first letter NAME starts with a vowel sound
    # ("ex-", "aitch-", "en-", "em-", "ess-"): "an xml file" was being
    # "fixed" to "a xml file" (audit 2026-07-25, CONFIRMED live).
    "xml", "html", "http", "https", "sms", "ssl", "ssh", "ssd", "svg",
    "nda", "llm", "llms", "sdk", "sdks", "mri", "fbi", "faq", "faqs",
    "npm", "mvp", "xl", "lp",
}
# Words where BOTH readings are standard ("a SQL query" via "sequel" vs "an
# SQL query" via "ess-cue-ell"): flagging either direction is a false
# positive for half the audience, so the rule skips them entirely.
_A_AN_AMBIGUOUS = {"sql", "suv", "faq"}
_A_AN_RE = re.compile(r"\b([Aa]n?)\s+(\w+)")
_VOWEL_LETTERS = set("aeiouAEIOU")


def _find_a_an_suggestions(text, protected):
    out = []
    for m in _A_AN_RE.finditer(text):
        article, word = m.group(1), m.group(2)
        start, end = m.start(), m.end()
        if _overlaps_any(start, end, protected):
            continue

        word_lower = word.lower()
        if word_lower in _A_AN_AMBIGUOUS:
            continue  # both articles are standard usage; never flag
        starts_with_vowel_letter = word[0] in _VOWEL_LETTERS
        if starts_with_vowel_letter:
            wants_an = word_lower not in _A_AN_VOWEL_SOUND_EXCEPTIONS
        else:
            wants_an = word_lower in _A_AN_CONSONANT_SOUND_EXCEPTIONS

        if wants_an == (article.lower() == "an"):
            continue  # already correct

        base = "an" if wants_an else "a"
        new_article = base.capitalize() if article[0].isupper() else base
        # Preserve the ORIGINAL separator (audit 2026-07-25, CONFIRMED live):
        # \s+ crosses newlines, and a hardcoded " " joined "a\napple" onto
        # one line as a side effect of an article fix.
        sep = text[m.end(1):m.start(2)]
        out.append(_make_grammar_suggestion(
            "grammar", "Fix a/an", start, end, text[start:end], f"{new_article}{sep}{word}",
        ))
    return out


# QWERTY neighbours, incl. diagonals (real ask 2026-07-22). The dominant
# real typo isn't a random wrong word, it's a "fat finger": the intended key
# plus an accidental hit on a physically adjacent one, or two letters typed
# in the wrong order. Windows' spell checker returns candidates in its own
# ranking, and its first pick is sometimes a valid word that isn't what the
# user meant ("od" -> "ad" when they meant "of"). Re-ranking the candidates
# by how plausibly each is a keyboard typo of what was actually typed picks
# the one the user most likely intended, instead of blindly taking [0].
_QWERTY_NEIGHBORS = {
    "q": "was", "w": "qeasd", "e": "wrsdf", "r": "etdfg", "t": "ryfgh",
    "y": "tughj", "u": "yihjk", "i": "uojkl", "o": "ipkl", "p": "ol",
    "a": "qwszx", "s": "qweadzxc", "d": "wersfxcv", "f": "ertdgcvb",
    "g": "rtyfhvbn", "h": "tyugjbnm", "j": "yuihknm", "k": "uiojlm",
    "l": "iopk", "z": "asx", "x": "asdzc", "c": "sdfxv", "v": "dfgcb",
    "b": "fghvn", "n": "ghjbm", "m": "hjkn",
}


def _kbd_adjacent(a, b):
    return b in _QWERTY_NEIGHBORS.get(a, "")


def _typo_distance(typed, candidate):
    """Optimal-string-alignment (Damerau-Levenshtein) edit distance, weighted
    for how keyboards are actually mistyped: an adjacent-key substitution and
    a two-letter transposition each cost 1 (the common fat-finger and
    wrong-order errors), a non-adjacent substitution costs 2 (a less likely
    slip), and a missing/extra keystroke costs 1. Lower means "more plausibly
    a typo of this word." """
    a, b = typed.lower(), candidate.lower()
    la, lb = len(a), len(b)
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            if a[i - 1] == b[j - 1]:
                cost = 0
            elif _kbd_adjacent(a[i - 1], b[j - 1]):
                cost = 1
            else:
                cost = 2
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (prev2 is not None and i > 1 and j > 1
                    and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)  # transposition
        prev2, prev = prev, cur
    return prev[lb]


# Very common English words, used ONLY as a tie-break in _best_typo_candidate
# (second market audit, 2026-07-22): when two candidates are equally plausible
# keyboard typos, prefer the everyday word over Windows' raw order. Measured
# case: "wich" scored "witch" and "which" identically (each one inserted
# letter) and Windows' order picked "witch"; in prompts, "which" is what's
# meant essentially always. Deliberately a SMALL curated set of function
# words and everyday verbs/nouns, not a frequency dictionary: it only needs
# to separate common-vs-exotic at a tie, and a big list would start deciding
# ties it has no business deciding.
_COMMON_WORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "it",
    "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
    "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
    "an", "will", "my", "one", "all", "would", "there", "their", "what",
    "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
    "when", "make", "can", "like", "time", "no", "just", "him", "know",
    "take", "people", "into", "year", "your", "good", "some", "could",
    "them", "see", "other", "than", "then", "now", "look", "only", "come",
    "its", "over", "think", "also", "back", "after", "use", "two", "how",
    "our", "work", "first", "well", "way", "even", "new", "want", "because",
    "any", "these", "give", "day", "most", "us", "should", "need", "much",
    "right", "where", "too", "very", "still", "being", "here", "why",
    "does", "doing", "done", "made", "many", "more", "before", "through",
    "same", "under", "while", "again", "each", "please", "help", "write",
    "read", "find", "keep", "let", "long", "great", "little", "own",
    "since", "both", "between", "never", "another", "around", "however",
    "without", "something", "nothing", "everything", "always", "every",
    # Real bug 2026-07-25 (Antonio): "Helloe" (meant "Hello") was corrected to
    # "Helloed" instead. Windows' own checker offers ['Helloed', 'Helloes',
    # 'Hello'] for "Helloe"; _typo_distance ties all three at 1 (Hello is a
    # trailing-letter deletion, Helloed/Helloes are a trailing-letter
    # insertion, same cost under this model), so the tie fell through to
    # Windows' own order, picking "Helloed" first. This list was built from
    # function/grammar words (the "which" vs "witch" fix) and never covered
    # conversational greetings, which are exactly the kind of everyday word
    # this tie-break exists to prefer. Added only "hello" (the demonstrated
    # case); not guessing at other greetings without a real report.
    "hello",
}


def _best_typo_candidate(typed, candidates):
    """Pick the candidate that is the most plausible keyboard typo of `typed`,
    not just Windows' first suggestion. Ties prefer a common everyday word
    (see _COMMON_WORDS), then keep Windows' own order (its ranking is a
    reasonable last-resort signal), and a candidate that changes the first
    letter is penalised, since typos very rarely land on the wrong first
    key."""
    # Never "correct" a word to an EXACT no-op copy of itself, in case the
    # checker ever hands the original back among its candidates. Compared
    # case-SENSITIVELY on purpose (real bug 2026-07-22): typing "hOw" (an
    # errant shift, a common fat-finger) is a real misspelling whose correct
    # fix is "How" / "how". A case-insensitive guard wrongly threw that fix
    # out as "same word" and left the next candidate ("Howl") to win. A
    # case-only difference IS a valid correction and must stay.
    usable = [c for c in candidates if c != typed] or candidates
    if not usable:
        return None

    def rank(item):
        idx, cand = item
        t, c = typed.lower(), cand.lower()
        first_letter_changed = 0 if (t and c and t[0] == c[0]) else 2
        is_common = 0 if c in _COMMON_WORDS else 1
        return (_typo_distance(t, c) + first_letter_changed, is_common, idx)

    return min(enumerate(usable), key=rank)[1]


# High-frequency function words from the languages Comprsly's users most
# plausibly type (Spanish, French, German, Italian, Portuguese), used ONLY as
# a second signal in the non-English guard below. Deliberately excludes any
# form that is also a common English word ("die", "per", "con", "as", "no"),
# so typo-dense English can never accidentally register two hits.
_FOREIGN_FUNCTION_WORDS = {
    # Spanish
    "el", "los", "las", "una", "uno", "unos", "unas", "que", "por", "para",
    "pero", "como", "esta", "este", "esto", "del", "usted", "gracias",
    # French
    "le", "les", "une", "je", "tu", "il", "elle", "nous", "vous", "avec",
    "pour", "dans", "cette", "qui", "pas", "est", "et", "au", "aux",
    # German
    "der", "das", "und", "ist", "nicht", "ich", "du", "wir", "ein", "eine",
    "mit", "für", "auf", "zu", "den", "dem", "sie", "bitte", "kannst",
    # Italian
    "di", "gli", "non", "sono", "che", "nel", "della", "grazie",
    # Portuguese
    "um", "uma", "não", "em", "com", "você", "por", "para", "obrigado",
}


# Curated misspelling → correction table (grammar spec v2, Step 2). Checked
# BEFORE the OS spell-checker's own candidate ranking, because generic edit
# distance frequently resolves a real typo to the wrong real word ("rong" ->
# "ring" instead of "wrong", "probly" -> "propyl" instead of "probably"). A
# curated table makes these deterministic and correct. Keys are lowercase; the
# original word's leading case is reapplied when the fix is emitted.
_SPELLING_OVERRIDES = {
    "alot": "a lot", "seperate": "separate", "definately": "definitely",
    "recieve": "receive", "recieved": "received", "untill": "until",
    "occured": "occurred", "wich": "which", "dosent": "doesn't",
    "probly": "probably", "rong": "wrong", "supose": "suppose",
    "loosing": "losing", "truely": "truly", "arguement": "argument",
    "neccessary": "necessary", "necessary": None, "embarass": "embarrass",
    "concious": "conscious", "priviledge": "privilege",
    "independant": "independent", "teh": "the", "adn": "and", "thier": "their",
    "becuase": "because", "cant": "can't", "wont": "won't", "dont": "don't",
    # "id" is deliberately NOT here (audit 2026-07-25, CONFIRMED live): the
    # contraction rule already excludes it as ambiguous, but this table ran
    # with no ambiguity guard and rewrote "check the user id" to "user I'd"
    # at tier 1. Same class as its/lets/then: too ambiguous to auto-fix.
    "im": "I'm", "ive": "I've", "youre": "you're",
    "freind": "friend", "beleive": "believe", "goverment": "government",
    "tommorow": "tomorrow", "tomorow": "tomorrow", "wierd": "weird",
    "accross": "across", "agian": "again", "alwasy": "always",
    "calender": "calendar", "cemetary": "cemetery", "changable": "changeable",
    "collegue": "colleague", "comming": "coming", "commited": "committed",
    "completly": "completely", "concious": "conscious", "existance": "existence",
    "familar": "familiar", "finaly": "finally", "gaurd": "guard",
    "grammer": "grammar", "happend": "happened", "immediatly": "immediately",
    "occassion": "occasion", "peice": "piece", "persistant": "persistent",
    "posession": "possession", "prefered": "preferred", "recomend": "recommend",
    "refered": "referred", "relevent": "relevant", "religous": "religious",
    "remeber": "remember", "succesful": "successful", "successfull": "successful",
    "suprise": "surprise", "thourough": "thorough", "tounge": "tongue",
    "unfortunatly": "unfortunately", "usualy": "usually", "wan't": "want",
    "whcih": "which", "yeild": "yield",
    # Internet-speak Windows' own dictionary silently accepts as correct
    # (real bug 2026-07-24, Antonio): "wat" (meaning "what") is a real word
    # to winspell (a name/dialect form), so it's never flagged and this
    # override was previously unreachable no matter what was in the table --
    # see the independent override scan below, which is what actually makes
    # this entry reachable.
    "wat": "what",
}
# A few keys above sit in the dict only for clarity/None-guard; drop those.
_SPELLING_OVERRIDES = {k: v for k, v in _SPELLING_OVERRIDES.items() if v}

# Words that are already correct and must NEVER be "fixed," the opposite of
# _SPELLING_OVERRIDES above (real bug 2026-07-25: the app was auto-correcting
# its OWN name). winspell flags "Comprsly" as misspelled (it's not a
# dictionary word) and _best_typo_candidate's edit-distance ranking picks
# "Complexly" as the closest real word -- a Tier 1 (auto-checked) fix that
# would rewrite the product's own name in Fix All. Reproduced in 3 of 4
# realistic test sentences (sentence-initial "Comprsly ...", lowercase
# "comprsly", both untouched by the _NAME_RE proper-noun protection, which
# only catches a CAPITALIZED word that ISN'T first in its sentence). Checked
# case-insensitively before the flagged-word loop runs _best_typo_candidate
# at all, same as the override table's own reachability fix (2026-07-24).
_KNOWN_CORRECT_WORDS = {
    "comprsly",
    # Common tech initialisms Windows' dictionary flags and then "fixes" to
    # unrelated words by edit distance (audit battery 2026-07-25, live: the
    # a/an probe "write an sql query" ALSO got a tier-1 "sql" -> "sol"). This
    # product's core audience types these constantly. Lowercase forms; the
    # check is case-insensitive.
    "sql", "json", "yaml", "regex", "config", "async", "auth", "npm",
    "repo", "repos", "backend", "frontend", "middleware", "webhook",
    "webhooks", "endpoint", "endpoints", "localhost", "stdout", "stderr",
    "stdin", "kwargs", "args", "bool", "enum", "init",
}

# Fast-typing slip (real bug 2026-07-24, Antonio): dropping the space before
# the pronoun "I" merges it onto the previous word ("afteri" meaning "after
# I"). Left to the generic typo-distance ranking, the flagged word just gets
# its trailing "i" silently dropped ("afteri" -> "after"), losing the pronoun
# entirely rather than restoring it. Gated to a small set of connector words
# that are naturally followed by "I" in real sentences, so this can't misfire
# on a genuine short word that happens to end in "i" -- "taxi"/"ski"/"alibi"/
# "hi" all PASS the dictionary check and never even reach this rule; a
# flagged non-word like "hii" or "toi" isn't in the set either, so it falls
# through to the normal typo-distance guess as before.
_I_MERGE_PRECEDERS = {
    "after", "before", "until", "since", "when", "if", "once", "though",
    "although", "because", "while", "unless", "whether", "that", "so",
    "and", "but", "or", "as", "than", "then",
}


def _dropped_space_before_i(word):
    if len(word) < 3 or word[-1].lower() != "i":
        return None
    prefix = word[:-1]
    if prefix.lower() not in _I_MERGE_PRECEDERS:
        return None
    return _apply_case(word[:1].isupper(), prefix) + " I"


def _find_spelling_suggestions(text, protected):
    """Real ask 2026-07-20: "theres misspelled words that can use the
    native spell check." Uses Windows' own spell checker (winspell.py),
    the same engine Notepad/Edge/Word use, not a bundled dictionary.
    Gracefully finds nothing if winspell isn't available (non-Windows dev
    environment, or the COM object fails to create for some reason), same
    degrade-safely pattern as the pystray/PIL imports elsewhere.

    Candidate CHOICE (real ask 2026-07-22): rather than taking Windows'
    first suggestion, which is sometimes a real word that isn't what the
    user meant, pick the candidate that's the most plausible fat-finger /
    wrong-order typo of what was actually typed. See _best_typo_candidate."""
    if winspell is None or not winspell.is_available():
        return []
    flagged = winspell.check(text)
    # Non-English guard (real bug 2026-07-22, market audit): the checker is
    # en-US, so a Spanish/French/German prompt flags on nearly every word and
    # each gets "fixed" in isolation into confident garbage, measured:
    # "por favor arregla este codigo" -> "Por favor Arreola Este Codi go".
    # When the text reads as not-English, the honest move is to offer nothing.
    # Two signals, either sufficient, both tuned so dense genuine-typo
    # English is never suppressed (measured: a 7-word English sentence with 4
    # real typos sits at 0.57 flagged with zero foreign-marker hits):
    #   a) nearly everything is flagged (>= 75%), which no real English
    #      sentence reaches, or
    #   b) a moderate flag rate (>= 40%) PLUS two distinct high-frequency
    #      foreign function words, which typo-dense English never contains.
    # Unicode-aware tokens here, NOT _WORD_TOKEN_RE ([A-Za-z'] only): that
    # regex splits accented words apart ("für" -> "f", "r"), which both
    # inflates the word count and hides the foreign markers from the lookup.
    words_in_text = [w.lower() for w in re.findall(r"[^\W\d_]{1,20}", text)]
    if len(words_in_text) >= 4 and len(flagged) >= 3:
        ratio = len(flagged) / len(words_in_text)
        foreign_hits = {w for w in words_in_text if w in _FOREIGN_FUNCTION_WORDS}
        if ratio >= 0.75 or (ratio >= 0.40 and len(foreign_hits) >= 2):
            return []
    out = []
    claimed = []

    # Override table scanned INDEPENDENTLY of winspell's own flagging (real
    # bug 2026-07-24, Antonio: "wat" typed for "what" was never touched).
    # winspell's dictionary silently accepts some words we still want to
    # correct ("wat" is apparently a real word/name to it, so it never
    # appears in `flagged` at all -- no override entry was ever reachable for
    # a word winspell itself considers correct). Scanning every token against
    # the table directly, ahead of and regardless of winspell's opinion, is
    # what the spec's "check the override table BEFORE any distance-based
    # guessing" actually requires.
    for m in _WORD_TOKEN_RE.finditer(text):
        word = m.group(0)
        override = _SPELLING_OVERRIDES.get(word.lower())
        if override is None:
            continue
        start, end = m.start(), m.end()
        if _overlaps_any(start, end, protected):
            continue
        out.append(_make_grammar_suggestion(
            "spelling", "Fix spelling", start, end, word,
            _apply_case(word[:1].isupper(), override),
        ))
        claimed.append((start, end))

    for start, length, word, suggestions in flagged:
        end = start + length
        if _overlaps_any(start, end, protected) or _overlaps_any(start, end, claimed):
            continue
        if word.lower() in _KNOWN_CORRECT_WORDS:
            continue
        # Curated override already handled above (independent scan); a word
        # winspell DOES flag but that isn't in the override table falls
        # through to the merge check, then the generic typo-distance guess.
        merge_fix = _dropped_space_before_i(word)
        best = merge_fix if merge_fix is not None else _best_typo_candidate(word, suggestions)
        if not best:
            continue
        out.append(_make_grammar_suggestion(
            "spelling", "Fix spelling", start, end, word, best,
        ))
    return out


_WORD_TOKEN_RE = re.compile(r"[A-Za-z']{1,20}")
# 1-letter halves are almost always a wrong split ("l ikethis"), except for
# the handful of real one-letter English words.
_ONE_LETTER_WORDS = {"a", "A", "I", "i", "O"}
# How far from the current space to look. A genuine misplaced-space typo is
# the space landing exactly ONE keystroke early or late ("lik ethis",
# "tak eto"). Searching further invents plausible-but-wrong re-splits of
# words whose real error is INSIDE one of them: at radius 3, "youre done"
# (where "youre" just needs an apostrophe) glued to "youredone" and split
# into "you redone" because both are real words (real bug 2026-07-22).
# Radius 1 still catches every canonical case and refuses that distance-2
# garbage; a within-word error like "youre" then correctly falls through to
# spell-check ("you're").
_SPLIT_SEARCH_RADIUS = 1


def _plausible_half(part):
    if len(part) == 1:
        return part in _ONE_LETTER_WORDS
    return True


def _find_orphan_letter_join_suggestions(text, protected):
    """Rejoin a word broken by a space one keystroke EARLY, where the first
    fragment is an orphaned 1-2 letter non-word: "t ake" -> "take",
    "th is" -> "this", "wh at" -> "what".

    This is the sibling the misplaced-space rule can't handle: that rule MOVES
    a space to a better split, but "t ake" needs the space DELETED, and moving
    it never yields two real words. Left unfixed it caused a live corruption
    (market audit, 2026-07-22): "t ake screenshots" -> the misplaced-space
    rule gave up, then "t" got capitalized to "T" and the non-word "ake" got a
    garbage spelling fix "Ake", producing "T Ake screenshots".

    Deliberately tight so it can't merge things that shouldn't merge:
      - first fragment is 1-2 chars AND not a real word (so valid short words
        "a", "in", "to", "be", "I" are never eaten -- "a bout of flu",
        "in put it here" stay intact),
      - separated by exactly one space,
      - the no-space join is a real word of length >= 3,
      - and the fragment isn't protected (code, names, etc).
    General merged-word splitting is still NOT done (Build.md §6: github ->
    "git hub"); this only ever JOINS an already-broken fragment, never splits
    a word the user typed whole."""
    if winspell is None or not winspell.is_available():
        return []
    out = []
    consumed = []
    tokens = [(m.group(0), m.start(), m.end())
              for m in _WORD_TOKEN_RE.finditer(text)]
    for (first, s1, e1), (second, s2, e2) in zip(tokens, tokens[1:]):
        if text[e1:s2] != " ":
            continue
        if not (1 <= len(first) <= 2):
            continue
        start, end = s1, e2
        if _overlaps_any(start, end, protected) or _overlaps_any(start, end, consumed):
            continue
        joined = first + second
        if len(joined) < 3 or len(joined) > 24:
            continue
        # Only fire on a genuinely broken fragment: the first piece is not a
        # word on its own. (If it were, e.g. "a"/"in"/"to", the space is real.)
        # A 1-char fragment is checked against the real one-letter words
        # (a/I/o), NOT the spell checker -- Windows treats a bare "t"/"b"/"k"
        # as "correct", which would wrongly skip the exact "t ake" case this
        # rule exists for.
        if len(first) == 1:
            if first in _ONE_LETTER_WORDS:
                continue
        elif winspell.is_correct(first):
            continue
        if winspell.is_correct(joined):
            out.append(_make_grammar_suggestion(
                "spelling", "Fix spacing", start, end,
                text[start:end], joined,
            ))
            consumed.append((start, end))
    return out


def _find_misplaced_space_suggestions(text, protected):
    """Fixes a space typed in the wrong position, e.g. "lik ethis" and
    "tak eto".

    Real bug Antonio hit 2026-07-21: Windows' spell checker corrected
    "tak eto" to "take ego". That is not a spell-checker failure, it is the
    wrong question being asked of it. It sees two independent words and
    fixes each in isolation: "tak" -> "take", "eto" -> "ego". Neither
    correction can see the other, and the actual error is in neither word,
    it is the space between them.

    So this rule asks the right question instead: glue the pair back
    together and find the split where BOTH halves are real words.
    "taketo" -> "take|to". "likethis" -> "like|this".

    Candidates are ordered by distance from the space's current position,
    and ties break toward moving the space RIGHT, because the dominant real
    typo is releasing space one keystroke early ("lik ethis", "tak eto" are
    both exactly that). Without that tie-break "tak eto" is ambiguous:
    "ta|keto" scores identically to "take|to" and "keto" is in modern
    dictionaries.

    Only ever fires when at least one of the two words is already flagged as
    misspelled, so correctly-typed text is never re-split.
    """
    if winspell is None or not winspell.is_available():
        return []
    out = []
    consumed = []
    # Every ADJACENT pair, walked over the token list. A single regex of the
    # form "word word" cannot do this: finditer returns non-overlapping
    # matches, so in "to lik ethis" it consumes "to lik" and never even looks
    # at "lik ethis", which is the exact pair that needs fixing. Caught by a
    # test, and it silently made the rule work on the bare phrase but not
    # inside a real sentence.
    tokens = [(m.group(0), m.start(), m.end()) for m in _WORD_TOKEN_RE.finditer(text)]
    for (first, s1, e1), (second, s2, e2) in zip(tokens, tokens[1:]):
        # Must be separated by exactly one space, nothing else. Punctuation
        # between them means they are not a mis-split word.
        if text[e1:s2] != " ":
            continue
        start, end = s1, e2
        if _overlaps_any(start, end, protected) or _overlaps_any(start, end, consumed):
            continue
        # Only a MISSPELLED FIRST word signals a misplaced space: the letters
        # that belong to the first word landed on the start of the second
        # ("lik ethis", "tak eto"). If the first word is already correct, the
        # error is inside the SECOND word instead (an ordinary typo, e.g. the
        # transposition in "fix teh"), and stealing letters into a correct
        # first word wrecks it ("fix teh" -> "fixt eh", a real 2026-07-22
        # false positive on fat-finger input). Those belong to plain
        # spell-check, not to this rule.
        if winspell.is_correct(first):
            continue

        joined = first + second
        if len(joined) > 24:
            continue
        here = len(first)
        candidates = sorted(
            (i for i in range(1, len(joined)) if i != here
             and abs(i - here) <= _SPLIT_SEARCH_RADIUS),
            # distance first, then prefer moving the space right (i > here)
            key=lambda i: (abs(i - here), 0 if i > here else 1),
        )
        for i in candidates:
            left, right = joined[:i], joined[i:]
            if not (_plausible_half(left) and _plausible_half(right)):
                continue
            if winspell.is_correct(left) and winspell.is_correct(right):
                out.append(_make_grammar_suggestion(
                    "spelling", "Fix spacing", start, end,
                    text[start:end], f"{left} {right}",
                ))
                consumed.append((start, end))
                break
    return out


# ---- Punctuation & capitalization (real ask 2026-07-22) -----------------
# "Find punctuation errors, commas, periods, capitalization ... so we can
# fully form sentences." Three rules that are genuinely unambiguous with
# plain patterns, gated against the same false-positive traps as everything
# else here (protected spans, and an abbreviation guard so a period inside
# "e.g." is never read as the end of a sentence).
#
# Deliberately NOT done: inserting commas where grammar would want them
# (after an introductory clause, before a coordinating conjunction, serial
# commas). That needs real POS understanding; a rule that guesses comma
# placement false-fires constantly and mangles technical prompts, which is
# exactly the line Build.md draws. Comma *spacing* is handled (space before a
# comma is removed here; a missing space AFTER one is the existing
# missing-space rule); comma *placement* is left to the AI pass.

# Words ending in a period that do NOT end a sentence, stored lowercased and
# without the trailing period (internal dots kept, e.g. "e.g"). Keeps
# "see e.g. the docs" from capitalizing "the", and "Mr. Smith" from being
# read as two sentences.
_ABBREVIATIONS = {
    "e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "prof", "sr", "jr",
    "st", "inc", "ltd", "co", "corp", "dept", "est", "fig", "no", "vol",
    "approx", "min", "max", "a.m", "p.m", "u.s", "u.k", "ph.d", "jan", "feb",
    "aug", "sept", "oct", "nov", "dec",
}


def _preceded_by_abbreviation(text, period_pos):
    """Is the '.' at period_pos the tail of a known abbreviation (or a single
    initial like 'A.') rather than a real sentence end?"""
    i = period_pos - 1
    while i >= 0 and (text[i].isalpha() or text[i] == "."):
        i -= 1
    word = text[i + 1:period_pos].lower()
    if not word:
        return False
    if len(word) == 1 and word.isalpha():
        return True  # an initial, e.g. "A." in "A. Smith"
    return word in _ABBREVIATIONS


def _at_sentence_start(text, pos):
    """Is pos the first content of the text, or directly after a sentence
    terminator? Mirrors _SENTENCE_START_RE's idea of a sentence start,
    including its abbreviation guard, for rules that need the answer for an
    arbitrary offset rather than a regex scan (the F11 fixes below)."""
    i = pos - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    if i < 0:
        return True
    if text[i] not in ".!?":
        return False
    if text[i] == "." and _preceded_by_abbreviation(text, i):
        return False
    return True


def _capitalize_after_deletion(text, start, end, protected):
    """Companion suggestion for a whole-phrase DELETION at a sentence start
    (filler trims, the delete-outright verbose entries): capitalize the first
    word the deletion promotes to sentence-initial. Kept as its own
    suggestion, not folded into the deletion's span, so the user still sees
    one honest edit per checkbox; analyze()'s _tag gives it the same tier as
    the deletion it accompanies (audit 2026-07-25, F11)."""
    if not _at_sentence_start(text, start):
        return None
    m = re.match(r"\s*([a-z])", text[end:])
    if not m:
        return None
    pos = end + m.start(1)
    if _overlaps_any(pos, pos + 1, protected):
        return None
    ch = text[pos]
    return _make_grammar_suggestion(
        "grammar", "Capitalize the start of a sentence", pos, pos + 1,
        ch, ch.upper(),
    )


# Conjunctive/sentence adverbs and transitional phrases that, when they OPEN
# a sentence, conventionally take a comma after them (real ask 2026-07-22:
# "add commas"). Deliberately conservative: only words that are almost always
# adverbial at a sentence start. Ordinals ("first", "next", "then") and words
# like "so"/"well"/"still" are EXCLUDED because they're just as often
# adjectives/time words ("first draft", "next week", "still working"), where a
# comma would be wrong. Comma placement anywhere else (compound clauses, lists)
# needs real parsing and rides on the AI pass, not a blunt rule.
_INTRO_TRANSITIONS = [
    "on the other hand", "as a result", "for example", "for instance",
    "in addition", "in conclusion", "in summary", "in contrast", "in general",
    "in fact", "in short", "by the way", "of course", "that said", "even so",
    "however", "therefore", "moreover", "furthermore", "meanwhile",
    "nevertheless", "nonetheless", "consequently", "additionally", "otherwise",
    "similarly", "likewise", "unfortunately",
    "fortunately", "honestly", "basically", "essentially", "ultimately",
    "surprisingly", "interestingly", "importantly", "admittedly",
    "also", "thus", "hence",
    # Opening interjections/acknowledgements (real ask 2026-07-22, "okay so ..."
    # should get a comma). Standard placement is a comma after the interjection:
    # "Okay, so I think ..." (not "Okay so,"). "so" itself is NOT here, since
    # "so much"/"so far"/"so many" would get a wrong comma.
    "okay", "ok", "alright",
    # Deliberately EXCLUDED as too often prepositions/adjectives at a sentence
    # start, where a comma would be wrong: "instead of", "besides that",
    # "regardless of", "overall <noun>", "so <intensifier>". Those ride on the
    # AI pass.
]
# Longest first, so "for example" wins over a bare "for"-style prefix match.
_INTRO_TRANSITIONS.sort(key=len, reverse=True)


def _find_comma_after_intro_suggestions(text, protected):
    """Insert a comma after a transitional word/phrase that opens a sentence,
    e.g. "However i think" -> "However, i think" (capitalization then folds it
    to "However,"). Only fires at a real sentence start, only for the curated
    adverbial list, and only when a whole word (not "insteadof") with more
    sentence following and no comma already there."""
    starts = [re.match(r"\s*", text).end()]
    for m in re.finditer(r"[.!?]\s+", text):
        starts.append(m.end())
    low = text.lower()
    n = len(text)
    out = []
    for s in starts:
        for phrase in _INTRO_TRANSITIONS:
            if not low.startswith(phrase, s):
                continue
            after = s + len(phrase)
            # Must be a whole word: the char right after is whitespace (then
            # more sentence). A letter there means it's a longer word.
            if after >= n or text[after] not in " \t":
                break
            if after + 1 >= n or not text[after + 1].isalpha():
                break
            if _overlaps_any(s, after, protected):
                break
            # Non-adverbial readings (audit 2026-07-25, all CONFIRMED live at
            # Tier 1), each a case where the opener isn't the sentence adverb:
            #   - "however <pronoun>": "however you look at it" means "in
            #     whatever way you look at it". With a pronoun right after,
            #     the two readings are genuinely ambiguous, and precision
            #     says stand down ("however the tests pass" still fires).
            #   - "thus far": a fixed collocation ("so far"), never "Thus,
            #     far" ("thus we should deploy" still fires).
            #   - "also known as": a fixed collocation, never "Also, known".
            tail = re.match(r"[ \t]+([A-Za-z']+)(?:\s+([A-Za-z']+))?",
                            text[after:])
            w1 = tail.group(1).lower() if tail else ""
            w2 = (tail.group(2) or "").lower() if tail else ""
            if phrase == "however" and w1.split("'")[0] in (
                    "you", "we", "i", "they", "he", "she", "it"):
                break
            if phrase == "thus" and w1 == "far":
                break
            if phrase == "also" and w1 == "known" and w2 == "as":
                break
            orig = text[s:after]
            out.append(_make_grammar_suggestion(
                "grammar", "Add a comma after the opening word",
                s, after, orig, orig + ","))
            break  # matched the longest phrase at this start; done
    return out


# Start of text (after any leading space) OR after a sentence-ender + space,
# followed by a lowercase letter that should be capitalized.
_SENTENCE_START_RE = re.compile(r"(?:^\s*|[.!?]\s+)([a-z])")


def _find_capitalization_suggestions(text, protected):
    out = []
    for m in _SENTENCE_START_RE.finditer(text):
        letter_pos = m.start(1)
        # The boundary punctuation is the match's first char UNLESS the match
        # is the start-of-text form (then it's whitespace or the letter).
        boundary = text[m.start()] if m.start() < letter_pos else ""
        if boundary == "." and _preceded_by_abbreviation(text, m.start()):
            continue
        # A boundary period INSIDE a protected span isn't a sentence end
        # (audit follow-up 2026-07-25): "the F.B.I. called" capitalized
        # "called" because the acronym's final dot read as end-of-sentence.
        # Same logic would misfire after domains and filenames.
        if boundary and _overlaps_any(m.start(), m.start() + 1, protected):
            continue
        if _overlaps_any(letter_pos, letter_pos + 1, protected):
            continue
        ch = text[letter_pos]
        out.append(_make_grammar_suggestion(
            "grammar", "Capitalize the start of a sentence",
            letter_pos, letter_pos + 1, ch, ch.upper(),
        ))
    return out


# A space (or spaces) sitting BEFORE a closing punctuation mark, e.g.
# "the report ,and the summary ." -> "the report, and the summary."
# The punctuation is a lookahead, NOT part of the match, on purpose: if the
# span included the comma it would overlap the missing-space-AFTER fix (which
# starts at that same comma), and apply_suggestions would drop one of them,
# leaving "report,and" with no space after. Matching only the whitespace lets
# both fixes apply and produce "report, and".
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+(?=[.,!?;:])")


def _find_space_before_punct_suggestions(text, protected):
    out = []
    for m in _SPACE_BEFORE_PUNCT_RE.finditer(text):
        start, end = m.start(), m.end()
        if _overlaps_any(start, end, protected):
            continue
        out.append(_make_grammar_suggestion(
            "grammar", "Remove the space before punctuation",
            start, end, text[start:end], "",
        ))
    return out


# Doubled commas (Build.md pending item 4; the tiering decision, applied
# 2026-07-25): a run of 2+ commas is never intentional -- unlike doubled
# "?"/"!", which ARE deliberate emphasis and deliberately get NO rule, the
# other half of that same decision -- so it collapses to one comma at Tier 1.
# The match keeps the FINAL comma and deletes the ones before it, so the
# span can't collide with the missing-space fix that may start at that kept
# comma: "home,,and" needs both edits (drop a comma AND add the space) and
# overlapping spans would force apply_suggestions to drop one.
_DOUBLED_COMMA_RE = re.compile(r",+(?=,)")


def _find_doubled_comma_suggestions(text, protected):
    out = []
    for m in _DOUBLED_COMMA_RE.finditer(text):
        start, end = m.start(), m.end()
        # end + 1 so the KEPT comma is checked too: a doubled comma inside a
        # protected number ("1,,2") must stay untouched.
        if _overlaps_any(start, end + 1, protected):
            continue
        out.append(_make_grammar_suggestion(
            "grammar", "Remove the doubled comma", start, end,
            text[start:end], "",
        ))
    return out


# Inferring the RIGHT terminal mark (real ask 2026-07-22: "it should be a
# question mark but it didn't notice ... we need to infer exclamation points
# too"). Detected from how the last sentence OPENS, high-precision on purpose:
# a wrong "?" or "!" is worse than a plain ".", so anything uncertain stays a
# period. Real grammar-level question detection needs POS/parsing (out of
# scope, see §7), so this is the honest rule-based subset.
_WH_WORDS = {"how", "what", "why", "where", "when", "who", "whom", "whose",
             "which"}
_AUX_WORDS = {"is", "are", "am", "was", "were", "do", "does", "did", "can",
              "could", "would", "should", "will", "shall", "may", "might",
              "must", "have", "has", "had"}
_SUBJECT_WORDS = {"i", "you", "we", "they", "he", "she", "it", "there",
                  "this", "that", "these", "those"}
_EXCLAM_OPENERS = {"wow", "congrats", "congratulations", "yay", "hooray",
                   "awesome", "amazing", "yikes", "oops", "hurray", "woohoo"}
# Contracted wh-openers ("what's the status", "how's it going") are still
# questions; the classifier runs on the raw text before contraction fixes,
# so both "whats" and "what's" reduce to these once apostrophes are stripped.
_WH_CONTRACTIONS = {"whats", "hows", "wheres", "whos", "whens", "whys"}
# Discourse fillers that commonly precede the real question ("hey can you...",
# "so what is...", "please could you..."). Skipped before classifying.
_FILLER_OPENERS = {"hey", "hi", "hello", "so", "ok", "okay", "well", "um",
                   "uh", "please", "yo", "hmm"}
# A comma clause opening with a coordinator CONTINUES the previous clause
# ("can you review it, and send it over") rather than starting a new one, so
# the comma-splice walk below steps back over it instead of classifying it.
_COORD_OPENERS = {"and", "or", "but", "nor"}
# How far (in words) a question-shaped OPENER is trusted to speak for the
# sentence END. Past this, in a comma-separated sentence, the ending clause
# is classified instead -- see _infer_terminal_mark.
_SPLICE_OPENER_REACH = 8


def _clause_words(clause):
    """Lowercased words of one clause, leading discourse fillers dropped, so
    "hey can you..." classifies as the real "can you..." underneath."""
    words = [w.strip("'") for w in re.findall(r"[A-Za-z']+", clause.lower())]
    i = 0
    while i < len(words) and words[i] in _FILLER_OPENERS:
        i += 1
    return words[i:]


def _classify_clause(words):
    """'?', '!', or '.' for ONE clause, from its (filler-stripped) words.
    Returns '.' whenever it isn't confident: a wrong '?'/'!' at Tier 1 is the
    real harm, a plain '.' on a missed question is the accepted cost."""
    if not words:
        return "."
    w0 = words[0]
    w1 = words[1] if len(words) > 1 else ""
    if w0 in _EXCLAM_OPENERS:
        return "!"
    if w0 == "what" and w1 in ("a", "an"):
        return "!"                       # "what a great idea" (exclamatory)
    if w0 in _WH_CONTRACTIONS:
        return "?"                       # "whats the status" -- aux built in
    if w0 in _WH_WORDS:
        if w0 == "how" and w1 == "to":
            return "."                   # "how to X" is a topic, not a question
        # A wh-opener alone is NOT interrogative structure (audit 2026-07-25,
        # both CONFIRMED live: "when I run the build it fails" and "what I
        # need is a smaller bundle" got '?'). A real wh-question fronts an
        # auxiliary/modal -- "when WILL...", "what IS...", "how DO I..." --
        # while a wh-word followed by a plain pronoun/noun is a fronted
        # declarative clause. Subject questions ("who called you") are
        # knowingly given up by this gate: '.' on a missed question costs
        # less than '?' stamped on a statement.
        if w1 in _AUX_WORDS:
            return "?"
        return "."
    # Yes/no question: an auxiliary/modal fronting a subject ("do you",
    # "is it", "should we", "would you"). Requiring the subject word excludes
    # imperatives that also start with these ("do your homework", "have a day").
    if w0 in _AUX_WORDS and w1 in _SUBJECT_WORDS:
        # But "do/have" + a demonstrative is an IMPERATIVE, not a question:
        # "Do that", "Do this", "Have this" are commands (real bug 2026-07-22,
        # "Do that and send it over" wrongly got a "?"). "Does that work",
        # "Is this right" stay questions because their auxiliary isn't
        # imperative-capable.
        if w0 in ("do", "have") and w1 in ("this", "that", "these", "those", "it"):
            # "it" added 2026-07-25 (audit, CONFIRMED live): "Do it before
            # Friday" was getting a "?" -- same imperative shape as "Do that".
            return "."
        return "?"
    return "."


def _infer_terminal_mark(sentence):
    """'?', '!', or '.' for a sentence with no terminal punctuation. Returns
    '.' whenever it isn't confident.

    Comma-splice handling (audit 2026-07-25, CONFIRMED live): "can you check
    the report, I finished it yesterday, the team is waiting on the final
    numbers" got '?' from the "can you" opener nine words away, even though
    the clause the mark actually lands after is a statement. When the
    sentence is comma-spliced -- 3+ comma clauses, or two clauses in a
    sentence long enough that the opener is out of reach of the end -- the
    LAST clause is what the mark punctuates, so that's what gets classified.
    A tail clause that is only filler ("..., please") or opens with a
    coordinator ("..., and send it over") isn't an independent clause; the
    walk steps back over those instead. The split skips digit-adjacent
    commas so "1,000,000" never fabricates clauses."""
    clauses = [c for c in re.split(r";|,(?!\d)", sentence) if c.strip()]
    if len(clauses) >= 2:
        total_words = len(re.findall(r"[A-Za-z']+", sentence))
        if len(clauses) >= 3 or total_words > _SPLICE_OPENER_REACH:
            for clause in reversed(clauses):
                words = _clause_words(clause)
                if not words:
                    continue             # filler-only tail ("..., please")
                if words[0] in _COORD_OPENERS:
                    continue             # coordination, not a new clause
                return _classify_clause(words)
            return "."
    return _classify_clause(_clause_words(sentence))


def _find_terminal_punctuation_suggestions(text, protected):
    """Add terminal punctuation to a sentence that ends without any, so a
    quickly-typed prompt reads as a fully-formed sentence. The MARK is
    inferred (?/!/.) from the last sentence, see _infer_terminal_mark.
    Conservative: only when the text ends in an ordinary word (a letter), is
    more than a two-word fragment, and that final word isn't protected."""
    stripped = text.rstrip()
    if not stripped:
        return []
    last = stripped[-1]
    # Already terminated, or ends in punctuation where a period would be wrong
    # (a trailing colon introduces a list; a comma/semicolon is mid-thought).
    if last in ".!?:;,\"')]}":
        return []
    if not last.isalpha():
        return []  # ends in a number, symbol, etc. -> leave it alone
    if len(re.findall(r"\S+", stripped)) < 3:
        return []  # a short label or one-word command, not a sentence
    pos = len(stripped) - 1
    if _overlaps_any(pos, pos + 1, _unsafe_to_punctuate_after(stripped)):
        return []  # last word is a URL/filename/code snippet/etc.
    # Classify the LAST sentence (from the last . ! ? or newline to the end).
    bounds = list(re.finditer(r"[.!?\n]", stripped))
    last_sentence = stripped[bounds[-1].end():] if bounds else stripped
    mark = _infer_terminal_mark(last_sentence)
    label = {"?": "End the question with a question mark",
             "!": "End with an exclamation point"}.get(mark,
             "End the sentence with a period")
    return [_make_grammar_suggestion(
        "grammar", label, pos, pos + 1, last, last + mark,
    )]


_LOWER_I_RE = re.compile(r"(?<![\w'])i(?![\w'])")


def _find_lowercase_i_suggestions(text, protected):
    """Standalone lowercase "i" should be "I". Unambiguous in English and
    extremely common in quickly-typed prompts. Added 2026-07-21 after
    Antonio's mockup flagged exactly this and the engine missed it. The
    negative lookarounds keep it from touching "i" inside words or
    contractions, and protected spans still shield code, URLs and the rest,
    so things like a variable named `i` are left alone."""
    out = []
    for m in _LOWER_I_RE.finditer(text):
        start, end = m.start(), m.end()
        if _overlaps_any(start, end, protected):
            continue
        out.append(_make_grammar_suggestion(
            "grammar", "Capitalize I", start, end, text[start:end], "I",
        ))
    return out


# Missing-apostrophe contractions (real ask 2026-07-22). Left to plain
# spell-check, "youre" becomes "your" (Windows ranks the real possessive word
# first), which is grammatically wrong for the intended "you're". This rule
# gives the right apostrophe form directly. Deliberately ONLY the forms whose
# no-apostrophe spelling is either NOT a real word, or a real word so rare/
# archaic that the contraction is overwhelmingly what was meant:
#   - ADDED 2026-07-22 after an audit flagged them: "cant"->"can't" and
#     "wont"->"won't". "cant" (a slope/jargon) and "wont" (archaic "habit")
#     are vanishingly rare in prompts; the contraction is what's meant ~always.
#   - STILL EXCLUDED because they're genuinely common BOTH ways, where a blunt
#     fix would visibly corrupt real text: its ("its color"), lets ("this lets
#     you"), were, well, id, wed, then/than. Those need context -> AI pass.
_CONTRACTIONS = {
    "youre": "you're", "theyre": "they're", "im": "I'm", "ive": "I've",
    "youve": "you've", "youll": "you'll", "youd": "you'd",
    "theyll": "they'll", "theyve": "they've", "weve": "we've",
    "dont": "don't", "doesnt": "doesn't", "didnt": "didn't",
    "isnt": "isn't", "arent": "aren't", "wasnt": "wasn't",
    "werent": "weren't", "couldnt": "couldn't", "wouldnt": "wouldn't",
    "shouldnt": "shouldn't", "hasnt": "hasn't", "havent": "haven't",
    "hadnt": "hadn't", "hes": "he's", "shes": "she's",
    "thats": "that's", "whats": "what's", "wheres": "where's",
    "theres": "there's", "heres": "here's", "hows": "how's",
    "cant": "can't", "wont": "won't",
    # Added 2026-07-22 (second market audit, mis-correction class): these
    # were falling through to spell-check, which confidently picked a WRONG
    # real word. "whos" -> "whose" (tie on typo distance, Windows' order
    # won) when the apostrophe-drop "who's" is the dominant intent, same
    # pattern as whats/hows/theres already here; "whos" is not a real word,
    # so it meets the inclusion rule. "dosent"/"doesent" -> "docent" (an
    # adjacent-key substitution scored better than the apostrophe+transpose
    # to "doesn't"); both are common misspellings of "doesn't" and neither
    # is a real word.
    "whos": "who's", "dosent": "doesn't", "doesent": "doesn't",
}
_CONTRACTION_RE = re.compile(
    r"(?<![\w'])(" + "|".join(_CONTRACTIONS) + r")(?![\w'])", re.IGNORECASE)


def _find_contraction_suggestions(text, protected):
    out = []
    for m in _CONTRACTION_RE.finditer(text):
        start, end = m.start(), m.end()
        if _overlaps_any(start, end, protected):
            continue
        word = m.group(1)
        fixed = _CONTRACTIONS[word.lower()]
        # Preserve a leading capital ("Dont" -> "Don't"); "I'm"/"I've" keep
        # their inherent capital I regardless of how the user typed it.
        if word[0].isupper():
            fixed = fixed[0].upper() + fixed[1:]
        out.append(_make_grammar_suggestion(
            "grammar", "Add the missing apostrophe", start, end, text[start:end], fixed,
        ))
    return out


# ---- Confusable words / agreement (real ask 2026-07-22, third audit pass) --
# The category a writing tool is JUDGED on and the engine caught none of:
# homophones ("your going", "to hard", "better then") and the few
# subject-verb slips ("he dont", "she have"). The whole file's ethos holds --
# a false positive is worse than a miss, technical prompts must survive
# untouched -- so every pattern here is gated to a construction where the
# error reading is overwhelmingly dominant, and each was checked against a
# false-positive corpus of legitimate prompts before shipping (see
# tools_eval_confusables). Anything that needs real parsing to disambiguate
# ("your car" vs "you're carrying") is deliberately NOT attempted and rides
# on the AI pass, same line Build.md §7 draws for comma placement.

# 1. Modal + "of" -> "have". The standout: "should of/could of/would of/
#    must of/might of" is one of the most common written-English errors and
#    "of" NEVER legitimately follows a bare modal, so false positives are
#    essentially impossible. High value, zero risk.
# "of course"/"of all" are real idioms ("must of course be positive",
# "could of all people") -- exclude them, or the rule mis-reads the idiom as
# the error (real FP found in the precision corpus 2026-07-22).
_MODAL_OF_RE = re.compile(
    r"\b(should|would|could|must|might|may)\s+(of)\b(?!\s+(?:course|all)\b)",
    re.IGNORECASE)

# 2. Third-person-singular subject + "dont"/"have" -> "doesn't"/"has". Fixes
#    the interaction bug the 2nd audit surfaced: the plain contraction rule
#    turned "he dont" into "he don't" (apostrophe right, agreement still
#    wrong). After he/she/it/this/that, "dont" is always "doesn't" and "have"
#    is always "has". A closed, safe set of subjects.
# "that" is deliberately absent from the subject set (audit 2026-07-25,
# CONFIRMED live): as a RELATIVE pronoun its antecedent can be plural --
# "skip the tests that dont pass" was rewritten to "that doesn't pass" when
# the right fix was the plain contraction "don't" (which now claims it).
# "this" stays: it can't head a relative clause the same way.
_SV_DONT_RE = re.compile(
    r"\b(he|she|it|this)\s+(dont|doesnt|dosent|doesent)\b", re.IGNORECASE)
_SV_HAVE_RE = re.compile(r"\b(he|she|it)\s+(have)\b", re.IGNORECASE)
# Real compounding bug 2026-07-24 (Antonio): the plain spelling fix for
# "dosent"/"doesent" always targets "doesn't" (the phonetically closer real
# word), which is right after he/she/it but produces ungrammatical "I
# doesn't" after I/you/we/they. This claims the span FIRST (confusables run
# before the plain spelling/contraction fixes in analyze()), the same way
# _SV_DONT_RE above already claims priority over the plain "dont"->"don't"
# contraction for the opposite subject set.
_SV_DOESNT_TO_DONT_RE = re.compile(
    r"\b(I|you|we|they)\s+(doesnt|dosent|doesent)\b", re.IGNORECASE)

# 3. "to" -> "too" before a degree word. "to much/many/late/hard/..." is
#    almost always the "too" error; the risk is the preposition reading
#    ("I sent it to many people"), so this is gated to the ADVERBIAL/adjective
#    words where that reading is rare, and further guarded below by requiring
#    that "to" not directly follow a verb of motion/transfer (go/talk/listen/
#    send/give/...), which is where a legit "to X" mostly lives.
_TOO_WORDS = {
    "much", "many", "late", "early", "soon", "hard", "easy", "big", "small",
    "long", "short", "expensive", "cheap", "fast", "slow", "old", "young",
    "hot", "cold", "tired", "busy", "difficult", "far", "high", "low",
    "heavy", "light", "loud", "quiet", "strong", "weak", "close",
}
# "to X" is only read as the "too" error when a linking/copular verb sits
# right before it ("this IS to hard", "there ARE to many", "that FEELS to
# slow"). Requiring that predecessor is what separates the error from the
# ordinary preposition ("I sent it to many teams", "we need to much detail"),
# both real FPs from the precision corpus. Costs some recall (e.g. "its to
# late" with no visible verb) in exchange for near-zero false positives, the
# right trade for a floating writing tool.
_TO_LINKING_PRECEDERS = {
    "is", "are", "was", "were", "am", "be", "been", "being", "im", "its",
    "thats", "theres", "hes", "shes", "feels", "feel", "seems", "seem",
    "looks", "look", "gets", "get", "got", "getting", "become", "becomes",
    "became", "way", "not", "so", "too", "still", "always", "really",
}
_TO_TOO_RE = re.compile(r"\b(to)\s+(" + "|".join(_TOO_WORDS) + r")\b",
                        re.IGNORECASE)

# 4. "then" -> "than" in a comparative frame. Gated to an explicit comparative
#    trigger earlier in the clause (a -er word, or more/less/better/worse/
#    rather/other/etc.), because bare "then" is far more often the correct
#    sequential word ("do this then that").
_COMPARATIVE_TRIGGERS = {
    "more", "less", "better", "worse", "rather", "other", "greater", "fewer",
    "larger", "smaller", "faster", "slower", "higher", "lower", "bigger",
    "older", "younger", "sooner", "later", "cheaper", "easier", "harder",
    "stronger", "weaker", "longer", "shorter", "closer", "further", "farther",
    "nicer", "safer", "richer", "poorer", "warmer", "cooler",
}
_THEN_RE = re.compile(r"\b(then)\b", re.IGNORECASE)
# Conditional-imperative guard for the rule above (audit 2026-07-25,
# CONFIRMED live: "if this performs better then deploy it" -- that 'then' is
# the sequential "if X, then do Y" one, comparative before it notwithstanding).
# A verb directly after 'then' marks the sequential reading, so the rule
# stands down. Bare imperative-position verbs this audience actually chains
# after "then"; inflected -s/-es forms are folded in by the check itself.
_THEN_ACTION_VERBS = {
    "deploy", "go", "do", "run", "try", "use", "check", "test", "ship",
    "merge", "commit", "push", "send", "stop", "start", "call", "make",
    "take", "add", "remove", "delete", "keep", "switch", "move", "revert",
    "restart", "rerun", "retry", "apply", "save", "close", "open", "submit",
    "release", "update", "upgrade", "install", "skip", "wait", "proceed",
    "continue", "launch", "build", "rebuild", "fix", "escalate", "notify",
    "email", "ping", "ask", "tell", "let", "leave", "come", "see", "pick",
    "choose", "write", "read", "review", "verify", "report",
}

# 5. "your" -> "you're" ONLY in the constructions where the possessive reading
#    is vanishingly rare: "your welcome" (idiom), and "your" directly before a
#    clear predicate adjective/state or a gerund-plus-"to" ("your going to").
#    Deliberately NOT the general case -- "your right" (your right hand),
#    "your parking" (your parking spot) etc. are real possessives, left alone.
_YOURE_RE = re.compile(
    r"\b(your)\s+(welcome|gonna|about\s+to)\b", re.IGNORECASE)
# "your <gerund> to" -> "you're <gerund> to" (your going to, your coming to).
# The trailing "to" is what makes it safe: a possessive "your Xing" is almost
# never followed by "to".
_YOURE_GERUND_RE = re.compile(
    r"\b(your)\s+(\w+ing)\s+to\b", re.IGNORECASE)

# 6. "except" used as a VERB ("should except the offer") -> "accept". Real
# "except" (excluding) almost never sits directly after a modal or infinitive
# "to" ("everyone except John" has nothing before it); "except" is basically
# never a genuine verb in casual writing, so a modal/infinitive right before
# it is the tell, same modal-position gate as _MODAL_OF_RE above.
_ACCEPT_RE = re.compile(
    r"\b(should|would|could|will|can|must|to)(?:n't|\s+not)?\s+(except)\b",
    re.IGNORECASE)

# 7. "were" -> "where" after a small set of verbs that almost always
# introduce a LOCATION clause (stay were I am, dont know were it is). A real
# past-tense "were" needs a subject directly after it ("we/they/you were"),
# not immediately after one of these verbs, so this set is the gate rather
# than a general "were" scan.
_WHERE_PRECEDERS = {
    "know", "knew", "see", "saw", "ask", "asked", "wonder", "wondered",
    "find", "found", "tell", "told", "remember", "remembered", "forgot",
    "forget", "stay", "stayed", "live", "lived", "remain", "remained",
    "wait", "waited", "meet", "met", "park", "parked", "sit", "sat",
}
_WERE_RE = re.compile(r"\b(were)\b", re.IGNORECASE)
# The preceder-verb gate's premise breaks on reduced relative clauses (audit
# 2026-07-25, CONFIRMED live: "the bugs I found were minor issues" -- 'found'
# closes a relative clause on a plural head noun and 'were' is real
# past-tense BE). Two extra checks, both suppression-only:
#   - a plural-looking noun anywhere earlier in the clause means 'were' has
#     a plural subject to agree with, so stand down; and
#   - the word right after 'were' must open a location clause the way a real
#     "where" does (a subject pronoun or determiner: "were IT is", "were THE
#     file went") -- a predicate like "were minor issues" can't.
# s-ending words that aren't plural nouns, so dense normal prose doesn't
# suppress the rule's true positives ("I always wondered were she goes").
# -ss endings ("across", "unless") are already exempt in _looks_plural.
_PLURAL_EXEMPT = {
    "is", "was", "has", "does", "its", "his", "hers", "ours", "yours",
    "theirs", "this", "thus", "plus", "yes", "lets", "thats", "whats",
    "theres", "heres", "wheres", "hows", "whos", "always", "perhaps",
    "sometimes", "besides", "towards", "afterwards", "backwards",
    "forwards", "whereas", "anyways",
}
_WHERE_CLAUSE_OPENERS = {
    "i", "you", "we", "they", "he", "she", "it", "the", "a", "an", "my",
    "our", "your", "his", "her", "its", "their", "this", "that", "these",
    "those",
}


def _looks_plural(word):
    w = word.lower().strip("'")
    return (len(w) >= 3 and w.endswith("s") and not w.endswith("ss")
            and w not in _PLURAL_EXEMPT)

# 8. "its" -> "it's" (real ask 2026-07-24, Antonio, repeated miss). General
# its/it's is deliberately still excluded (needs real context -- "its color"
# is common and correct), but three constructions are unambiguous regardless
# of context, the same kind of narrow carve-out already used for your/you're:
#   - "its been" -- "been" is a participle that never directly follows a
#     possessive determiner ("its been raining" can only be "it's been").
#   - "its a/an/the" -- two determiners in a row is impossible ("its a book"
#     doesn't parse as a possessive at all).
#   - "its" + a closed set of predicate adjectives/states -- none of these
#     are nouns, so "its X" cannot be a possessive ("its unfair" has no
#     possessed noun).
_ITS_BEEN_RE = re.compile(r"\b(its)\s+been\b", re.IGNORECASE)
_ITS_DETERMINER_RE = re.compile(r"\b(its)\s+(?=(?:a|an|the)\b)", re.IGNORECASE)
_ITS_PREDICATE_WORDS = {
    "not", "gonna", "unfair", "fair", "great", "awesome", "cool", "fine",
    # "working" and "safe" removed (audit 2026-07-25, CONFIRMED live): the
    # premise "none of these can follow a possessive" is false for
    # adjective+noun compounds this audience types daily -- "check its
    # working directory" and "boot into its safe mode" both got a wrong
    # "it's". The rest of the list doesn't form common technical compounds.
    "ready", "done", "over", "broken", "raining", "snowing",
    "hot", "cold", "late", "early", "funny", "weird", "crazy", "amazing",
    "terrible", "awful", "good", "bad", "nice", "perfect", "obvious",
    "clear", "true", "false", "possible", "impossible", "important",
    "necessary", "worth", "better", "worse", "easier", "harder",
    "difficult", "easy", "hard", "simple", "complicated", "fun", "boring",
    "interesting", "annoying", "frustrating", "exciting", "scary",
    "dangerous", "useful", "useless", "pointless",
    # Adverbs: also can't follow a possessive determiner (nothing to modify),
    # so this is the same safety argument as the adjectives above.
    "probably", "definitely", "certainly", "actually", "really", "clearly",
    "obviously", "apparently", "surely", "literally", "honestly", "finally",
    "currently", "generally", "usually", "basically", "technically",
    # Added 2026-07-25 (testing punctuation/grammar edge cases): "its already
    # planned" was silently uncorrected -- same adverb argument as the rest
    # of this group, just missing. Verified: "its already-scheduled meeting"
    # (a hyphenated compound adjective) would still misfire the same way
    # every other adverb here already can on that construction; not a new
    # risk class, just the same accepted, pre-existing edge case.
    "already",
}
_ITS_PREDICATE_RE = re.compile(
    r"\b(its)\s+(" + "|".join(_ITS_PREDICATE_WORDS) + r")\b", re.IGNORECASE)

# 9. "you're" -> "your" (the REVERSE of rule 5 above -- neither direction was
# covered before this). Gated to "you're NOUN is/are/was/were", where the
# trailing be-verb is what makes it safe: "you're bag is heavy" can't parse
# as "you are bag is heavy" (two verbs), so "bag" must be a possessed noun's
# subject -- "your bag is heavy". A curated noun list (not a generic
# any-word gate) avoids the real false positive this would otherwise cause:
# "you're smart is what everyone says" -- "smart" completes the you're
# clause, "is" starts a new one, and a generic gate would wrongly rewrite it.
_YOURE_TO_YOUR_NOUNS = {
    "bag", "car", "phone", "keys", "wallet", "house", "room", "book",
    "jacket", "coat", "shoes", "laptop", "computer", "dog", "cat", "friend",
    "family", "mom", "dad", "mother", "father", "sister", "brother", "job",
    "boss", "teacher", "doctor", "appointment", "meeting", "flight",
    "ticket", "order", "package", "account", "password", "email", "name",
    "address", "number", "code", "seat", "table", "desk", "chair", "bike",
    "watch", "ring", "shirt", "pants", "hat", "glasses", "headphones",
    "charger", "luggage", "suitcase", "passport", "license", "card", "rent",
    "lease", "apartment", "kitchen", "bathroom", "garden", "yard", "garage",
    "neighbor", "roommate", "partner", "spouse", "husband", "wife", "kid",
    "kids", "child", "children", "pet", "homework", "assignment", "project",
    "presentation", "resume", "interview", "subscription", "membership",
    "warranty", "receipt", "invoice", "bill", "payment",
}
_YOURE_TO_YOUR_RE = re.compile(
    r"\b(you're)\s+(?:" + "|".join(_YOURE_TO_YOUR_NOUNS) + r")\s+(?:is|are|was|were)\b",
    re.IGNORECASE)

# 10. "principle" -> "principal" when it refers to a school/institution's
# head, not a rule or belief. Gated to "principle of THE/A/AN <institution>",
# which is specific enough that the rule-or-belief reading essentially never
# occurs there ("principle of least effort" has no institution noun after
# "of"). The reverse (a genuine "principal" meaning a rule) is NOT attempted
# -- rarer, and forcing it wrong would be worse than leaving it.
_PRINCIPAL_INSTITUTIONS = {
    "school", "schools", "university", "universities", "college", "colleges",
    "academy", "academies", "company", "companies", "firm", "firms",
    "office", "agency", "bank", "department", "district",
}
_PRINCIPLE_TO_PRINCIPAL_RE = re.compile(
    r"\b(principle)\s+of\s+(?:the\s+|an?\s+)?(?=(?:" +
    "|".join(_PRINCIPAL_INSTITUTIONS) + r")\b)", re.IGNORECASE)
# Value-reading adjectives (audit 2026-07-25, CONFIRMED live: "the guiding
# principle of the company is transparency"). One of these right before
# "principle" marks the rule-or-belief sense even with an institution after
# "of"; the person sense is bare ("the principal of the school").
_PRINCIPLE_VALUE_ADJECTIVES = {
    "guiding", "basic", "core", "first", "general", "founding",
    "fundamental", "key", "main", "central", "underlying", "organizing",
    "governing", "primary",
}

# 11. "led" -> "lead" in a fixed noun-phrase role ("led singer", "led
# guitarist"). This is the OPPOSITE direction from the classic "led" error
# (past-tense "I lead the team yesterday" should be "led") -- here "lead" is
# functioning as a modifier meaning "main/principal", and "led" only makes
# sense as a past-tense VERB, which a bare role noun right after can't be.
# Gated to a small set of role nouns this modifier pattern actually occurs
# with.
_LEAD_ROLE_NOUNS = {
    "singer", "guitarist", "vocalist", "actor", "actress", "role", "dancer",
    "performer", "character", "writer", "designer", "engineer", "developer",
    "programmer", "author", "artist", "drummer", "bassist", "researcher",
    "scientist", "investigator", "detective", "attorney", "counsel",
    "architect", "consultant",
}
# The role noun is captured (not a lookahead) so the gates below can see
# what follows it (audit 2026-07-25, CONFIRMED live: "Sarah led developer
# onboarding last year" -- 'led' really was the verb and 'developer' just
# opened a compound object). The modifier reading lives inside a
# determiner-fronted noun phrase, so the rule now requires BOTH:
#   - a determiner/possessive right before "led" ("the led singer", "our
#     led developer"; a name or pronoun there means past-tense verb), and
#   - the role noun be terminal, punctuated, or followed by a function word
#     ("of the band", "is on leave") -- another plain word after it
#     ("developer ONBOARDING") is a compound noun the verb reading owns.
_LED_TO_LEAD_RE = re.compile(
    r"\b(led)\s+(" + "|".join(_LEAD_ROLE_NOUNS) + r")\b", re.IGNORECASE)
_LEAD_MODIFIER_DETERMINERS = {
    "the", "a", "an", "our", "your", "their", "his", "her", "its", "my",
    "this", "that", "new", "former", "current",
}
_LEAD_ROLE_FOLLOWERS = {
    "of", "in", "at", "on", "for", "from", "with", "by", "to", "into",
    "about", "over", "during", "since", "until", "before", "after", "as",
    "than", "is", "was", "are", "were", "has", "had", "have", "will",
    "would", "can", "could", "should", "does", "did", "who", "whose",
    "whom", "which", "when", "where", "while",
}

# 12. "less" -> "fewer" before a countable plural noun (the single
# best-known instance of this error in English). A curated noun list rather
# than a generic "any plural" gate, deliberately: English mass-noun
# exceptions ("less news", "less stress") are common enough that a generic
# plural-detector would misfire on them.
_FEWER_NOUNS = {
    "people", "items", "things", "cars", "books", "dollars", "minutes",
    "days", "students", "employees", "calories", "points", "problems",
    "options", "choices", "opportunities", "jobs", "chances", "friends",
    "followers", "customers", "users", "clicks", "views", "likes",
    "comments", "replies", "messages", "emails", "files", "photos",
    "pictures", "images", "songs", "videos", "episodes", "pages", "words",
    "letters", "characters", "steps", "tasks", "errors", "bugs", "issues",
    "complaints", "requests", "orders", "sales", "units", "products",
    "cases", "incidents", "accidents", "crashes", "deaths", "injuries",
}
_LESS_TO_FEWER_RE = re.compile(
    r"\b(less)\s+(?=(?:" + "|".join(_FEWER_NOUNS) + r")\b)", re.IGNORECASE)


def _apply_case(template_first_upper, replacement):
    """Uppercase replacement's first letter if the original started upper."""
    if template_first_upper and replacement:
        return replacement[0].upper() + replacement[1:]
    return replacement


def _find_confusable_suggestions(text, protected):
    """Homophones and subject-verb slips, each gated to a high-precision
    construction. Every match is a whole-span replacement of the two-word
    frame so downstream rules (contractions, spelling) don't also fire on the
    corrected word."""
    out = []

    def add(start, end, replacement, label, tier=None):
        if _overlaps_any(start, end, protected):
            return
        s = _make_grammar_suggestion(
            "grammar", label, start, end, text[start:end], replacement)
        # Rules 1/2/2c below are objectively-correct grammar fixes (spec
        # Tier 2: subject-verb agreement, "should of"->"have"), not judgment
        # calls, so they stamp their own tier here rather than inheriting
        # this whole finder's blanket Tier 3 in analyze() (see _tag's
        # setdefault). Everything else in this function IS a genuine
        # homophone/judgment call and stays Tier 3 as before.
        if tier is not None:
            s["tier"] = tier
        out.append(s)

    # 1. modal + of -> modal + have (Tier 2: spec lists this explicitly —
    # "always correct... never intentional")
    for m in _MODAL_OF_RE.finditer(text):
        # Noun-reading guard (audit 2026-07-25, CONFIRMED live): "might" is
        # also a noun and "May" a month, and both take a genuine "of" -- "the
        # might of the empire", "I started in May of 2023" were rewritten to
        # "might have"/"May have" at tier 2. A determiner/preposition right
        # before the modal word means it's being used as a NOUN (an actual
        # modal verb can't follow "the"/"in"), so skip those. Real errors
        # ("you should of seen it", "he might of left") never have one.
        before = text[:m.start(1)].rstrip().lower()
        prev_word = before.rsplit(None, 1)[-1] if before else ""
        if prev_word in ("the", "a", "an", "in", "of", "this", "that",
                         "their", "its", "his", "her", "our", "your", "my",
                         "last", "next", "early", "late", "mid"):
            continue
        of_s, of_e = m.start(2), m.end(2)
        add(of_s, of_e, _apply_case(text[of_s].isupper(), "have"),
            "Use “have”, not “of”", tier=2)

    # 2. he/she/it/this/that + dont -> doesn't ; he/she/it + have -> has
    # (Tier 2: subject-verb agreement, spec's own example of an objectively-
    # correct fix, not a judgment call)
    for m in _SV_DONT_RE.finditer(text):
        v_s, v_e = m.start(2), m.end(2)
        add(v_s, v_e, _apply_case(text[v_s].isupper(), "doesn't"),
            "Subject-verb agreement", tier=2)
    for m in _SV_HAVE_RE.finditer(text):
        v_s, v_e = m.start(2), m.end(2)
        add(v_s, v_e, _apply_case(text[v_s].isupper(), "has"),
            "Subject-verb agreement", tier=2)
    # 2c. I/you/we/they + a "doesn't"-family word -> "don't" (see
    # _SV_DOESNT_TO_DONT_RE above).
    for m in _SV_DOESNT_TO_DONT_RE.finditer(text):
        v_s, v_e = m.start(2), m.end(2)
        add(v_s, v_e, _apply_case(text[v_s].isupper(), "don't"),
            "Subject-verb agreement", tier=2)

    # 3. to -> too before a degree word, unless (a) "to" follows a
    #    motion/transfer verb ("talked to many people"), or (b) the degree
    #    word is followed by "of" ("to many OF my coworkers" is a partitive
    #    "to" phrase, not the "too" error). Both are real FPs from the corpus.
    for m in _TO_TOO_RE.finditer(text):
        to_s, to_e = m.start(1), m.end(1)
        prev = re.search(r"([\w']+)\s*$", text[:to_s])
        if not prev or prev.group(1).lower().replace("'", "") not in _TO_LINKING_PRECEDERS:
            continue
        # Degree word followed by "of" is a partitive ("to many OF them").
        if re.match(r"\s*of\b", text[m.end(2):], re.IGNORECASE):
            continue
        add(to_s, to_e, _apply_case(text[to_s].isupper(), "too"),
            "Use “too” (excessively)")

    # 4. then -> than, ONLY when the word immediately before "then" is an
    #    explicit comparative ("better then", "more then", "rather then").
    #    An earlier attempt scanned the whole clause and used a generic "-er
    #    ending" test; it fired on ordinary nouns ("add the header THEN the
    #    footer") and on sequential "then" after a distant "rather" ("would
    #    rather you review it then merge"). Adjacency-only is the precision
    #    win: it costs "more expensive then" (word between), accepted, because
    #    a wrong "than" mid-sentence is worse than a missed one.
    for m in _THEN_RE.finditer(text):
        then_s, then_e = m.start(1), m.end(1)
        prev = re.search(r"(\w+)\s*$", text[:then_s])
        if not (prev and prev.group(1).lower() in _COMPARATIVE_TRIGGERS):
            continue
        # Sequential-'then' guard, see _THEN_ACTION_VERBS. "rather" is
        # exempt: "rather than run the risk" legitimately puts a bare verb
        # after "than", so the guard would wrongly suppress its one fix.
        if prev.group(1).lower() != "rather":
            nxt = re.match(r"\s*([A-Za-z']+)", text[then_e:])
            nxt_w = nxt.group(1).lower() if nxt else ""
            if (nxt_w in _THEN_ACTION_VERBS
                    or (nxt_w.endswith("es") and nxt_w[:-2] in _THEN_ACTION_VERBS)
                    or (nxt_w.endswith("s") and nxt_w[:-1] in _THEN_ACTION_VERBS)):
                continue
        add(then_s, then_e, _apply_case(text[then_s].isupper(), "than"),
            "Use “than” (comparison)")

    # 5. your -> you're (idiom / gerund-to only)
    for m in _YOURE_RE.finditer(text):
        y_s, y_e = m.start(1), m.end(1)
        add(y_s, y_e, _apply_case(text[y_s].isupper(), "you're"),
            "Use “you’re” (you are)")
    for m in _YOURE_GERUND_RE.finditer(text):
        # Noun-gerund guard (audit 2026-07-25, CONFIRMED live: "add your
        # meeting to the calendar" got "you're meeting"). A gerund acting as
        # a NOUN takes "to <noun phrase>" or ends the sentence there ("your
        # meeting to the calendar", "move your meeting to my calendar",
        # "send your writing to Sarah's inbox"), and then "your" is a real
        # possessive -- so anything that heads a noun phrase after "to"
        # (determiner, possessive, a capitalized name) stands the rule down.
        # A plain verb after "to" ("your going to love it") is the
        # future-tense error this rule exists for.
        after_to = re.match(r"\s*([A-Za-z']+)", text[m.end():])
        if not after_to:
            continue
        follower = after_to.group(1)
        if (follower.lower() in ("the", "a", "an", "my", "our", "your",
                                 "his", "her", "its", "their", "this",
                                 "that", "these", "those")
                or follower[0].isupper()
                or follower.lower().endswith("'s")):
            continue
        y_s, y_e = m.start(1), m.end(1)
        add(y_s, y_e, _apply_case(text[y_s].isupper(), "you're"),
            "Use “you’re” (you are)")

    # 6. except -> accept (modal/infinitive position)
    for m in _ACCEPT_RE.finditer(text):
        e_s, e_e = m.start(2), m.end(2)
        add(e_s, e_e, _apply_case(text[e_s].isupper(), "accept"),
            "Use “accept”, not “except”")

    # 7. were -> where (location-clause verb precedes it, and the clause
    #    around it doesn't read as past-tense BE -- see _PLURAL_EXEMPT /
    #    _WHERE_CLAUSE_OPENERS for the reduced-relative-clause gates)
    for m in _WERE_RE.finditer(text):
        w_s, w_e = m.start(1), m.end(1)
        prev = re.search(r"(\w+)\s*$", text[:w_s])
        if not (prev and prev.group(1).lower() in _WHERE_PRECEDERS):
            continue
        clause_start = max(text.rfind(ch, 0, w_s) for ch in ".!?,;:\n")
        clause = text[clause_start + 1:w_s]
        if any(_looks_plural(w) for w in re.findall(r"[A-Za-z']+", clause)):
            continue
        nxt = re.match(r"\s*([A-Za-z']+)", text[w_e:])
        if not nxt or nxt.group(1).lower() not in _WHERE_CLAUSE_OPENERS:
            continue
        add(w_s, w_e, _apply_case(text[w_s].isupper(), "where"),
            "Use “where” (location)")

    # 8. its -> it's (been / determiner collision / predicate word)
    for m in _ITS_BEEN_RE.finditer(text):
        i_s, i_e = m.start(1), m.end(1)
        add(i_s, i_e, _apply_case(text[i_s].isupper(), "it's"),
            "Use “it’s” (it has/is)")
    for m in _ITS_DETERMINER_RE.finditer(text):
        i_s, i_e = m.start(1), m.end(1)
        add(i_s, i_e, _apply_case(text[i_s].isupper(), "it's"),
            "Use “it’s” (it is)")
    for m in _ITS_PREDICATE_RE.finditer(text):
        i_s, i_e = m.start(1), m.end(1)
        add(i_s, i_e, _apply_case(text[i_s].isupper(), "it's"),
            "Use “it’s” (it is)")

    # 9. you're -> your (before a possessed noun's own be-verb)
    for m in _YOURE_TO_YOUR_RE.finditer(text):
        y_s, y_e = m.start(1), m.end(1)
        add(y_s, y_e, _apply_case(text[y_s].isupper(), "your"),
            "Use “your” (possessive)")

    # 10. principle -> principal (school/institution head; a value-reading
    #     adjective right before means it's a rule/belief, not a person)
    for m in _PRINCIPLE_TO_PRINCIPAL_RE.finditer(text):
        p_s, p_e = m.start(1), m.end(1)
        prev = re.search(r"([\w']+)\s*$", text[:p_s])
        if prev and prev.group(1).lower() in _PRINCIPLE_VALUE_ADJECTIVES:
            continue
        add(p_s, p_e, _apply_case(text[p_s].isupper(), "principal"),
            "Use “principal” (person)")

    # 11. led -> lead (fixed role-noun phrase, e.g. "the lead singer"; both
    #     gates documented at _LED_TO_LEAD_RE)
    for m in _LED_TO_LEAD_RE.finditer(text):
        l_s, l_e = m.start(1), m.end(1)
        prev = re.search(r"([\w']+)\s*$", text[:l_s])
        if not prev or prev.group(1).lower() not in _LEAD_MODIFIER_DETERMINERS:
            continue
        follow = re.match(r"\s*([A-Za-z']+)", text[m.end(2):])
        if follow and follow.group(1).lower() not in _LEAD_ROLE_FOLLOWERS:
            continue
        add(l_s, l_e, _apply_case(text[l_s].isupper(), "lead"),
            "Use “lead” (main/principal)")

    # 12. less -> fewer (countable plural noun)
    for m in _LESS_TO_FEWER_RE.finditer(text):
        l_s, l_e = m.start(1), m.end(1)
        add(l_s, l_e, _apply_case(text[l_s].isupper(), "fewer"),
            "Use “fewer” (countable)")

    return out


def _tag(suggs, tier, reason=""):
    """Stamp a confidence tier (and, for Tier 2/3, a plain-language reason) on
    a finder's suggestions (grammar spec v2). Tier 1 = auto-safe; Tier 2 =
    single objectively-correct grammar fix; Tier 3 = judgment call (homophones,
    stylistic punctuation, style trims) that the UI leaves UNCHECKED so a bulk
    'Apply all' never forces it — it waits for the user to tick it.

    setdefault, not overwrite: `_find_confusable_suggestions` mixes genuine
    judgment calls (homophones) with objectively-correct grammar fixes
    (subject-verb agreement, "should of"->"have" -- spec explicitly tiers
    these as Tier 2, not 3) in one finder, and stamps its own tier on the
    latter directly (see `add(..., tier=2)` there). Overwriting unconditionally
    here would silently downgrade those back to 3."""
    for s in suggs:
        s.setdefault("tier", tier)
        if reason and not s.get("reason"):
            s["reason"] = reason
    return suggs


def analyze(text: str):
    """Returns {"total_estimate": int, "suggestions": [...]}. Every
    suggestion is span-based and independently acceptable. Suggestions can
    legitimately overlap in rare cases (e.g. a redundant sentence that also
    contains a verbose phrase); apply_suggestions() below defensively drops
    overlaps rather than assuming the caller already resolved them."""
    if not text:
        return {"total_estimate": 0, "suggestions": []}

    protected = _protected_spans(text)
    suggestions = []
    suggestions.extend(_tag(_find_filler_suggestions(text, protected),
                            3, "Optional style trim"))
    suggestions.extend(_tag(_find_verbose_suggestions(text, protected),
                            3, "Optional wording change"))
    suggestions.extend(_tag(_find_redundant_sentence_suggestions(text, protected),
                            3, "Looks repeated, review before removing"))
    suggestions.extend(_tag(_find_repeated_word_suggestions(text, protected), 1))
    suggestions.extend(_tag(_find_missing_space_suggestions(text, protected), 1))
    suggestions.extend(_tag(_find_space_before_punct_suggestions(text, protected), 1))
    suggestions.extend(_tag(_find_doubled_comma_suggestions(text, protected), 1))
    suggestions.extend(_tag(_find_a_an_suggestions(text, protected),
                            2, "a/an agreement"))
    suggestions.extend(_tag(_find_lowercase_i_suggestions(text, protected), 1))
    suggestions.extend(_tag(_find_capitalization_suggestions(text, protected), 1))
    # Real ask 2026-07-24 (Antonio, explicit override of the earlier Tier 3
    # call): auto-check these instead of waiting for review. Moved to Tier 1
    # so the checkbox defaults ON and a bulk "Apply all" includes them; the
    # reason string is kept (harmless, currently unused by the UI, but free
    # documentation if a future card ever surfaces it).
    suggestions.extend(_tag(_find_comma_after_intro_suggestions(text, protected),
                            1, "Optional comma"))
    suggestions.extend(_tag(_find_terminal_punctuation_suggestions(text, protected),
                            1, "Add end punctuation?"))
    # Confusables/agreement claim their spans FIRST, so the plain contraction
    # rule can't turn "he dont" into "he don't" (agreement still wrong) over
    # the top of the "he dont -> he doesn't" fix, and spell-check can't touch
    # a corrected homophone. Same priority pattern as contractions below.
    confusables = _tag(_find_confusable_suggestions(text, protected),
                       3, "Depends on meaning, review before applying")
    suggestions.extend(confusables)
    confusable_spans = [(s["start"], s["end"]) for s in confusables]
    protected = protected + confusable_spans
    # Contractions claim their spans BEFORE spell-check, so "youre" is fixed
    # to "you're" (the right apostrophe form) instead of spell-check's blunt
    # "your". Same priority pattern as the misplaced-space rule below.
    contractions = _tag(_find_contraction_suggestions(text, protected),
                        2, "Missing apostrophe")
    suggestions.extend(contractions)
    contraction_spans = [(s["start"], s["end"]) for s in contractions]
    # Misplaced-space fixes must run BEFORE per-word spelling and then
    # suppress it over the spans they claim. Otherwise the two rules fight:
    # "tak eto" would offer "fix the space -> take to" alongside the very
    # wrong per-word "tak -> take" and "eto -> ego" that motivated this rule.
    # Contraction spans are protected from it too, or "hows it" gets glued and
    # split into "how sit" instead of becoming "how's it" (real bug 2026-07-22).
    # Orphan-letter joins ("t ake" -> "take") claim their span first, so the
    # broken fragment isn't separately capitalized/spell-"fixed" into garbage
    # ("T Ake"). Same priority pattern as the misplaced-space rule.
    orphan = _tag(_find_orphan_letter_join_suggestions(
        text, protected + contraction_spans), 1)
    suggestions.extend(orphan)
    orphan_spans = [(s["start"], s["end"]) for s in orphan]
    spacing = _tag(_find_misplaced_space_suggestions(
        text, protected + contraction_spans + orphan_spans), 1)
    suggestions.extend(spacing)
    spelling_protected = protected + [(s["start"], s["end"]) for s in spacing] \
        + contraction_spans + orphan_spans
    suggestions.extend(_tag(_find_spelling_suggestions(text, spelling_protected), 1))
    # F20 (audit 2026-07-25, CONFIRMED live): a spelling fix that rewrites
    # the FINAL word contains the 1-char terminal-punctuation span inside it,
    # and apply_suggestions keeps only the longer edit -- "fix the codee"
    # came out "Fix the code" with no period. The mark isn't in conflict with
    # the spelling fix, it belongs AFTER it, so fold it into the (equally
    # Tier 1) spelling replacement and drop the standalone suggestion.
    # Deliberately ONLY for kind-"spelling" hosts: folding into a Tier 2/3
    # host (a contraction, a filler trim) would make the Tier 1 mark hostage
    # to a checkbox the user may leave unticked.
    end_pos = len(text.rstrip())
    term = next((s for s in suggestions
                 if s["kind"] == "grammar" and s["end"] == end_pos
                 and s["end"] - s["start"] == 1
                 and len(s["replacement"]) == 2
                 and s["replacement"][0] == s["original"]
                 and s["replacement"][1] in ".!?"), None)
    if term is not None:
        host = next((s for s in suggestions
                     if s["kind"] == "spelling"
                     and s["start"] <= term["start"] and s["end"] >= term["end"]),
                    None)
        if host is not None:
            host["replacement"] += term["replacement"][1]
            host["saved_tokens"] = max(
                estimate_tokens(host["original"])
                - estimate_tokens(host["replacement"]), 0)
            suggestions.remove(term)
    # Two rules can propose the IDENTICAL edit (real case 2026-07-22, market
    # audit: a sentence-initial "i" gets "Capitalize I" from the lowercase-i
    # rule AND "Capitalize the start of a sentence", same span, same
    # replacement). apply_suggestions would resolve the overlap fine, but the
    # card showed both as separate checkboxes and counted 2 issues for 1 fix.
    # The kept copy takes the LOWEST tier on offer: the F11 companion (rides
    # its deletion's Tier 3) can collide with the Tier-1 lowercase-i rule on
    # the same "i" -> "I", and first-wins would silently demote an auto-safe
    # fix to a manual tick.
    seen_edits = {}
    deduped = []
    for s in suggestions:
        key = (s["start"], s["end"], s["replacement"])
        if key in seen_edits:
            idx = seen_edits[key]
            if s.get("tier", 3) < deduped[idx].get("tier", 3):
                deduped[idx] = s
            continue
        seen_edits[key] = len(deduped)
        deduped.append(s)
    suggestions = deduped
    suggestions.sort(key=lambda s: s["start"])
    return {"total_estimate": estimate_tokens(text), "suggestions": suggestions}


def _is_pure_capitalization(s):
    """A 1-character edit that only upppercases a letter (sentence-start cap
    or standalone 'i' -> 'I'), nothing else."""
    o, r = s["original"], s["replacement"]
    return len(o) == 1 and o != r and o.upper() == r


def apply_suggestions(text: str, suggestions) -> str:
    """Applies a set of span-based suggestions to text in one pass. Drops
    any suggestion whose span overlaps one already kept before editing, so
    callers never need to pre-resolve overlaps themselves, then edits
    highest-offset-first so earlier offsets stay valid.

    Two refinements over naive first-wins (both real 2026-07-22 fixes):
      - Same start offset: the LONGER edit wins, so a substantial content fix
        (e.g. a misplaced-space fix spanning a whole word pair) isn't dropped
        by a 1-char capitalization sitting at the same spot.
      - A capitalization that would otherwise be dropped for overlapping a
        kept edit is FOLDED into that edit (its first letter is uppercased),
        so "lik ethis" at a sentence start becomes "Like this", not the
        lowercase "like this" that dropping the capital would leave."""
    ordered = sorted(suggestions, key=lambda s: (s["start"], -(s["end"] - s["start"])))
    kept = []
    last_end = -1
    for s in ordered:
        if s["start"] < last_end:
            if _is_pure_capitalization(s):
                for k in kept:
                    if k["start"] == s["start"]:
                        r = k["replacement"]
                        for i, ch in enumerate(r):
                            if ch.isalpha():
                                k["replacement"] = r[:i] + ch.upper() + r[i + 1:]
                                break
                        break
            continue
        kept.append(dict(s))  # copy: folding must not mutate the caller's dict
        last_end = s["end"]

    out = text
    # kept[] is in ascending start order; apply highest-offset-first so
    # earlier offsets stay valid.
    for i in range(len(kept) - 1, -1, -1):
        s = kept[i]
        out = out[: s["start"]] + s["replacement"] + out[s["end"]:]
        # Normalize doubled spaces AT THIS EDIT'S SEAM only (a filler removal
        # leaves the space from each side: "hello  world"). This used to be a
        # whole-text re.sub(r"[ \t]{2,}", " ") and that was a real bug found
        # in the 2026-07-22 market audit: it flattened indentation inside
        # fenced code blocks and any aligned columns ANYWHERE in the text the
        # moment a single unrelated one-char fix was applied, silently
        # editing content the user never approved. Protection guards where
        # suggestions may LAND, but this ran after, over everything. Scoped
        # to the whitespace run touching the seam, it can never reach text
        # the user didn't ask to change. [ \t] only, so it never crosses a
        # newline and never touches another line's leading indentation.
        #
        # floor: never expand left into the PREVIOUS kept edit's span. Its
        # offsets are still original coordinates (it hasn't applied yet), and
        # collapsing whitespace inside it would shift the text out from under
        # its start/end (real near-miss caught writing this: a space-before-
        # punct fix adjacent to a missing-space-after fix).
        floor = kept[i - 1]["end"] if i > 0 else 0
        lo = s["start"]
        while lo > floor and out[lo - 1] in " \t":
            lo -= 1
        hi = s["start"] + len(s["replacement"])
        while hi < len(out) and out[hi] in " \t":
            hi += 1
        seam = re.sub(r"[ \t]{2,}", " ", out[lo:hi])
        out = out[:lo] + seam + out[hi:]

    # Round-trip verification (grammar spec v2, Correction Application Safety):
    # rebuild the result a SECOND way — splice the kept edits onto the immutable
    # original, highest-offset-first, with NO seam collapse — and confirm it
    # matches `out` once whitespace runs are normalized on both sides. If any
    # content OUTSIDE the intended spans changed (a drifting span or an over-
    # eager seam collapse eating a real character), fail safe: return the
    # original text unchanged rather than emit corrupted text.
    strict = text
    for i in range(len(kept) - 1, -1, -1):
        s = kept[i]
        strict = strict[: s["start"]] + s["replacement"] + strict[s["end"]:]

    def _norm(z):
        return re.sub(r"[ \t]+", " ", z)

    if _norm(out) != _norm(strict):
        return text.strip()
    return out.strip()


def confidence_ratio(text: str, suggestions) -> float:
    """Fraction of the text's estimated tokens the rules found real,
    protected-content-safe savings for. Used to decide whether the rules
    alone are "confident" enough or whether the local LLM fallback should
    run, real ask 2026-07-20: the LLM should only run when rules can't
    confidently produce the improvement, not by default."""
    total = estimate_tokens(text)
    if total == 0:
        return 1.0
    saved = sum(s["saved_tokens"] for s in suggestions)
    return saved / total


def rules_found_useful_fixes(suggestions) -> bool:
    """Real bug found 2026-07-20: confidence_ratio measures token *savings*
    only, but spelling and grammar fixes correct the text without saving
    tokens (fixing "tihs"->"this" is the same length). So a prompt full of
    typos but no compressible filler scored confidence 0, which tripped the
    LLM fallback ("needs a deeper think"), the slow, glitchy path, even
    though the rules had already found the exact right fixes. That was the
    real cause of Antonio's "why does it say needs deeper think when it
    could just fix the typos." The right question for "did rules succeed"
    isn't "did they save tokens," it's "did they find ANY useful fix at
    all," which includes zero-token spelling/grammar corrections."""
    return len(suggestions) > 0
