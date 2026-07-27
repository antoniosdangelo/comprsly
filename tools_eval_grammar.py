"""Measured evaluation of the rules-first grammar/spelling engine
(suggestion_engine.py), same discipline as tools_eval_compression.py for the
AI path: change the rules, run this before and after, never ship on
reasoning alone.

Unlike the AI path this engine is deterministic, so cases assert an EXACT
expected output (apply_suggestions(text, analyze(text)["suggestions"]) must
equal `expected` character for character), not a fuzzy retention score.

Two case kinds, both required for any new rule:
  - fix cases:  a real error must be corrected. `expected` is the fully
                cleaned text.
  - guard cases: `expected` intentionally equals `text` unchanged -- a
                false positive here is worse than a missed fix, so these
                are not optional extras, they're the other half of the
                spec for every new pattern.

Run:  python tools_eval_grammar.py
      python tools_eval_grammar.py --json results.json
"""
import argparse
import json
import sys

import suggestion_engine as se


# ---- Spoken (dictated) filler removal (2026-07-27) -----------------------
# Real ask: "let anyone ramble into the mic and get the best output."
# FILLER_PHRASES only ever covered written politeness phrases; these cases
# are the actual product use case, dictated speech filler.
FILLER_CASES = [
    {
        "name": "filler_sentence_start_comma",
        "text": "Um, I need help with the report.",
        "expected": "I need help with the report.",
    },
    {
        "name": "filler_bare_dictation",
        "text": "so um i need help with the report can you fix the formatting",
        "expected": "So I need help with the report can you fix the formatting.",
    },
    {
        "name": "filler_mid_sentence_bracketed",
        "text": "I need, um, help with this.",
        "expected": "I need help with this.",
    },
    {
        "name": "filler_clause_end",
        "text": "I need help with this, um.",
        "expected": "I need help with this.",
    },
    {
        "name": "filler_uh_bracketed",
        "text": "So, uh, can you review the pull request before tomorrow?",
        "expected": "So can you review the pull request before tomorrow?",
    },
    {
        "name": "filler_you_know_sentence_start",
        "text": "You know, I think we should just ship it.",
        "expected": "I think we should just ship it.",
    },
    {
        "name": "filler_hmm_bare",
        "text": "hmm i think we should wait",
        "expected": "I think we should wait.",
    },
    {
        "name": "filler_uh_huh_compound",
        "text": "uh huh yeah lets do that",
        "expected": "Yeah lets do that.",
    },
    {
        "name": "filler_uh_huh_hyphenated",
        "text": "uh-huh that works for me",
        "expected": "That works for me.",
    },
    {
        "name": "filler_protects_sql_in_middle",
        "text": "I ran the SQL query and it timed out, um, twice.",
        "expected": "I ran the SQL query and it timed out twice.",
    },
    {
        # Real bug found live 2026-07-27: "you know" and "i mean" matching
        # as two SEPARATE fillers left the word between them orphaned --
        # "outdated you know what i mean" corrupted into "outdated what".
        "name": "filler_you_know_what_i_mean_compound",
        "text": "its kinda outdated you know what i mean",
        "expected": "Its kind of outdated",
    },
]

# The other half of the spec: real content that must survive untouched.
FILLER_GUARD_CASES = [
    {
        "name": "guard_uh_uh_negative",
        "text": "uh-uh that's not right",
        "expected": "Uh-uh that's not right.",  # cap + terminal punct only
    },
    {
        "name": "guard_umbrella_not_um",
        "text": "Give the user an umbrella and a hat.",
        "expected": "Give the user an umbrella and a hat.",
    },
    {
        "name": "guard_hummed_not_hmm",
        "text": "I hummed a tune while I worked.",
        "expected": "I hummed a tune while I worked.",
    },
    {
        "name": "guard_alumni_not_um",
        "text": "the alumni event is important",
        "expected": "The alumni event is important.",
    },
    {
        "name": "guard_important_not_um",
        "text": "This is important, not urgent.",
        "expected": "This is important, not urgent.",
    },
]

# ---- Existing spelling/confusable spot checks (regression guard) --------
# Not new work, just confirming nothing above interacts badly with what
# already ships.
# ---- Tech/business jargon protection (2026-07-27) ------------------------
# Real bug found live: dozens of common acronyms and product names Windows'
# spell checker doesn't know get "corrected" to an unrelated real word by
# edit distance -- "api" -> "apio", "postgres" -> "postures", "vp" ->
# "vape", "llm" -> "llama", "gpt" -> "got". A representative sample of the
# ~55 confirmed mangles, not the full sweep (see suggestion_engine.py's
# _KNOWN_CORRECT_WORDS for the complete list).
JARGON_CASES = [
    {
        "name": "jargon_api",
        "text": "can you help me with the api today",
        "expected": "Can you help me with the api today?",
    },
    {
        "name": "jargon_postgres",
        "text": "can you help me with postgres today",
        "expected": "Can you help me with postgres today?",
    },
    {
        "name": "jargon_vp",
        "text": "can you help me with the vp today",
        "expected": "Can you help me with the vp today?",
    },
    {
        "name": "jargon_llm_gpt",
        "text": "the llm uses gpt under the hood",
        "expected": "The llm uses gpt under the hood.",
    },
]

EXISTING_SPELLING_CASES = [
    {
        "name": "existing_spelling_overrides",
        "text": "I definately need to seperate these files, wich is annoying.",
        "expected": "I definitely need to separate these files, which is annoying.",
    },
    {
        "name": "existing_should_of",
        "text": "You should of told me sooner.",
        "expected": "You should have told me sooner.",
    },
    {
        "name": "existing_sv_agreement",
        "text": "He dont know the answer.",
        "expected": "He doesn't know the answer.",
    },
]


def run_case(case):
    text = case["text"]
    result = se.analyze(text)
    applied = se.apply_suggestions(text, result["suggestions"])
    ok = applied == case["expected"]
    return ok, applied


def run_eval(cases, label):
    print(f"\n-- {label} ({len(cases)} cases) --")
    passed = 0
    results = []
    for case in cases:
        ok, applied = run_case(case)
        results.append({"name": case["name"], "ok": ok, "got": applied,
                         "expected": case["expected"]})
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {case['name']}")
        if not ok:
            print(f"        IN:       {case['text']!r}")
            print(f"        EXPECTED: {case['expected']!r}")
            print(f"        GOT:      {applied!r}")
        if ok:
            passed += 1
    print(f"  {passed}/{len(cases)} passed")
    return results, passed, len(cases)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="save results to this path")
    args = parser.parse_args()

    all_results = {}
    total_passed = 0
    total_cases = 0
    for cases, label, key in [
        (FILLER_CASES, "Spoken filler removal", "filler"),
        (FILLER_GUARD_CASES, "Spoken filler false-positive guards", "filler_guard"),
        (JARGON_CASES, "Tech/business jargon protection", "jargon"),
        (EXISTING_SPELLING_CASES, "Existing spelling/confusable regression", "existing"),
    ]:
        results, passed, count = run_eval(cases, label)
        all_results[key] = results
        total_passed += passed
        total_cases += count

    print(f"\n{'=' * 60}")
    print(f"  TOTAL: {total_passed}/{total_cases} passed")
    print(f"{'=' * 60}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)
        print(f"saved -> {args.json}")

    return 0 if total_passed == total_cases else 1


if __name__ == "__main__":
    sys.exit(main())
