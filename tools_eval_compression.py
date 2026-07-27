"""Measured evaluation of the AI compression stage (real ask 2026-07-22).

This is the "improve the testing part of the AI" tooling. Build.md is
emphatic that this prompt/pipeline must never be changed by reasoning alone:
two of four past prompt rounds made retention WORSE while looking better on
compression percentage. So any change to local_model's SYSTEM_PROMPT,
_clean_output, or token budget must be run through this harness before and
after, and judged on BOTH numbers together:

  - retention:   fraction of each prompt's must-keep items still present in
                 the compressed output. This is the thing that actually
                 matters. A compression that drops the landlord's name, the
                 "$65" threshold, or the "no exclamation marks" constraint is
                 worse than no compression at all.
  - compression: how much shorter the output is (by words). Higher is only
                 good UP TO A POINT. Over-compression is a real failure mode
                 (the user's 2026-07-22 report: "condenses it to a small
                 proportion, doesn't keep characteristics"), so an output
                 that cut >70% is flagged, not celebrated.
  - executed:    a rough flag for the classic small-model failure where the
                 model ANSWERS the prompt instead of compressing it (writes
                 the cover letter, replies "Dear Mr. Patel,"). Heuristic, not
                 perfect, but catches the obvious cases.

Run:  python tools_eval_compression.py
      python tools_eval_compression.py --json results_before.json   (save)

Compare two saved runs:
      python tools_eval_compression.py --compare results_before.json results_after.json
"""
import argparse
import json
import re
import sys
import time

import local_model


# Realistic, messy prompts covering the failure modes Build.md documents:
# dense numbers, named entities, hard constraints, direct "write me X"
# commands (the ones that get executed instead of compressed), a trivially
# short prompt (over-compression bait), and a genuinely multi-part prompt
# (the one _RAMBLE_SPLIT's blank-line clause silently guts).
EVAL_PROMPTS = [
    {
        "name": "email_landlord",
        "text": (
            "Hey so I need to write an email to my landlord Mr. Patel about the "
            "broken heater in apartment 4B, it's been broken since November 12th "
            "and I've already called twice. I want to be firm but still polite, "
            "and mention that I know providing heat is a legal requirement. Keep "
            "it professional."
        ),
        "must_keep": ["patel", "heater", "4b", "november 12", "twice",
                      "firm", "polite", "legal"],
    },
    {
        "name": "product_desc",
        "text": (
            "Can you write me a product description for a stainless steel water "
            "bottle, it should be under 80 words, no exclamation marks, and "
            "highlight that it keeps drinks cold for 24 hours and hot for 12."
        ),
        "must_keep": ["stainless steel", "water bottle", "80 words",
                      "exclamation", "24 hour", "12"],
    },
    {
        "name": "code_debug",
        "text": (
            "I'm getting a KeyError in my Python script when I run it on Python "
            "3.12 but it works fine on 3.9. The error happens in the "
            "parse_config function around line 47 when it tries to read the "
            "'timeout' key. Can you help me figure out why and suggest a fix "
            "that works on both versions?"
        ),
        "must_keep": ["keyerror", "3.12", "3.9", "parse_config", "47",
                      "timeout", "both"],
    },
    {
        "name": "long_ramble",
        "text": (
            "So basically we shipped about 400 orders last month and roughly "
            "70% went to the US and 30% to Canada, and the average order value "
            "was around $39 but shipping cost us like $8 per order which is "
            "eating into margins, and I want to figure out whether we should "
            "raise the free shipping threshold from $50 to maybe $65, can you "
            "analyze the tradeoffs?"
        ),
        "must_keep": ["400", "70%", "30%", "canada", "$39", "$8", "$50",
                      "$65", "shipping"],
    },
    {
        "name": "cover_letter",
        "text": (
            "Help me write a cover letter for a marketing manager position at "
            "Nike. I have 5 years of experience in digital marketing and I led "
            "a campaign that increased engagement by 40%. Make it confident but "
            "not arrogant, about 250 words."
        ),
        "must_keep": ["cover letter", "marketing manager", "nike", "5 years",
                      "digital marketing", "40%", "250 words", "confident"],
    },
    {
        "name": "meeting_notes",
        "text": (
            "ok so from today's standup: John is blocked on the API integration "
            "waiting for the auth token from the security team, Sarah finished "
            "the dashboard redesign and it's ready for review, and we pushed the "
            "launch date from March 3rd to March 17th because of the delays. Can "
            "you turn this into clean meeting notes?"
        ),
        "must_keep": ["john", "api", "auth token", "security team", "sarah",
                      "dashboard", "march 3", "march 17"],
    },
    {
        "name": "recipe_scale",
        "text": (
            "I have a lasagna recipe that serves 4 and uses 1 pound of ground "
            "beef, 2 cups of ricotta, and 12 lasagna noodles. I need to scale "
            "it up to serve 10 people for a dinner party. Can you recalculate "
            "all the ingredient amounts?"
        ),
        "must_keep": ["lasagna", "serves 4", "1 pound", "ground beef",
                      "2 cups", "ricotta", "12", "10"],
    },
    {
        "name": "travel_plan",
        "text": (
            "Planning a 5 day trip to Tokyo in early April with my wife, budget "
            "is around $3000 not including flights, we love food and history but "
            "not big crowds, and we want to do a day trip to Hakone. Can you "
            "suggest an itinerary?"
        ),
        "must_keep": ["5 day", "tokyo", "april", "$3000", "flights", "food",
                      "history", "hakone"],
    },
    {
        "name": "simple_short",
        "text": (
            "can you please please help me fix the grammar in this sentence its "
            "really bad and i dont know whats wrong with it"
        ),
        "must_keep": ["fix", "grammar", "sentence"],
    },
    {
        "name": "multi_part",
        "text": (
            "First, I need you to summarize the attached quarterly report, "
            "focusing on revenue and churn.\n\n"
            "Second, based on that summary, draft three bullet points I can "
            "present to the board about what's working and what isn't."
        ),
        "must_keep": ["summarize", "quarterly report", "revenue", "churn",
                      "three bullet", "board"],
    },
    # --- Rambling-context-then-question collapse (real bug 2026-07-24) ---
    # Antonio's real report: a multi-sentence prompt giving situational
    # context (a meeting, reasons, a busy schedule, a notification overload)
    # and ENDING in a question compressed to ONLY the closing question,
    # discarding every substantive fact that came before it. Reproduced
    # exactly against the shipping model: 82 words -> 12 words, "Weigh pros
    # and cons and recommend based on schedule and long-term goals." The
    # model appears to treat a long lead-in as throat-clearing ramble even
    # when it's the actual subject matter the closing question depends on.
    {
        "name": "context_then_question",
        "text": (
            "Im trying to definately figure out weather or not I should of "
            "went to the meeting yesterday, but their were alot of reasons "
            "not too. First of all, I dont think its a good use of my time "
            "considering how busy I am this week, and also I recieve so "
            "many notifications already that I cant possibly keep up with "
            "everything. In order to make a decision, I think its important "
            "to consider all of the relevant factors before hand, rather "
            "then just going with my gut feeling. Can you help me weigh the "
            "pros and cons and then give me a definitive recommendation on "
            "what I should do, taking into account both my schedule and my "
            "long term goals?"
        ),
        "must_keep": ["meeting", "notifications", "busy", "schedule",
                      "long", "pros and cons"],
        "meaning_note": "The meeting/reasons/busy-week/notifications context "
                        "must survive; must NOT collapse to just the closing "
                        "question with the situation stripped out.",
    },
    # --- Statement-to-request inversion (real bug 2026-07-25) -----------
    # Antonio's real case: a status update ("the vendor said the part won't
    # ship until Thursday") compressed into a REQUEST for that same status
    # ("Update me on the vendor's shipment"), plus a fabricated condition
    # ("if not ready by tomorrow") that was never said, plus the reply
    # deadline and its reason both vanishing. Reproduced deterministically
    # (5/5 identical runs) that the model turns "quick update" into "Update
    # me on...", inverting a STATEMENT into a REQUEST -- a different failure
    # mode from the existing role_boss_link/role_call_order cases below
    # (those are about WHO does WHAT in a request that stays a request; this
    # is a statement becoming a request in the first place).
    {
        "name": "statement_not_request",
        "text": ("Hey, quick update, the vendor said the part we need won't "
                 "ship until next Thursday, which is two days after our "
                 "install date, so we're going to need to either push the "
                 "install or bring in a loaner unit to hold us over. Can you "
                 "let me know by tomorrow morning which way you want to go, "
                 "since I have to tell the customer either way and I'd "
                 "rather not wait until the last minute?"),
        "must_keep": ["vendor", "thursday", "install date", "loaner",
                      "tomorrow morning", "customer"],
        "meaning_note": "This is a STATEMENT telling the reader something "
                        "(the vendor's part is late), not a request for "
                        "status. It must NOT become 'update me on...' or any "
                        "other question asking for what the sender already "
                        "said. The tomorrow-morning reply deadline and the "
                        "reason for it (telling the customer) must survive.",
    },
    # --- Meaning / role preservation (real ask 2026-07-22) --------------
    # These target the worst failure: the model changing WHO DOES WHAT, not
    # just dropping a word. Antonio's real case compressed "send ME the link
    # so I can send it to my boss" into "send link to my boss" (inverted the
    # roles). Substring retention only partly catches this (a directional
    # phrase like "send me" disappears when the roles invert), so ALSO read
    # the printed output by eye for these: did the subject/object/direction
    # survive? "meaning_note" says what to check.
    {
        "name": "role_boss_link",
        "text": ("can you send me the download link so i can forward it to my "
                 "boss before the meeting"),
        "must_keep": ["send me", "forward", "boss", "link", "before"],
        "meaning_note": "YOU receive the link and forward it TO the boss; "
                        "must not become 'send the boss the link'.",
    },
    {
        "name": "role_call_order",
        "text": ("remind me to call John back before he calls me again about "
                 "the invoice"),
        "must_keep": ["remind me", "call john", "before", "invoice"],
        "meaning_note": "You call John BEFORE he calls you; order must hold.",
    },
    {
        "name": "constraint_dont_change",
        "text": ("please tidy up the wording of this report but do not change "
                 "any of the numbers or the conclusion"),
        "must_keep": ["wording", "report", "numbers", "conclusion"],
        "meaning_note": "The 'do NOT change the numbers/conclusion' negation "
                        "must survive, not flip to 'change the numbers'.",
    },
    # --- Bullet-point structure preservation (real ask 2026-07-27) ------
    # Antonio, direct: dictated/typed bullet-point input should compress to
    # bullet-point output, not get flattened into a prose paragraph. This
    # is a STRUCTURE requirement on top of the usual content-retention
    # check -- see bullet_preserved in _words/run_eval below.
    {
        "name": "bullet_week_plan",
        "text": (
            "Can you help me plan my week?\n"
            "- Finish the quarterly report by Friday\n"
            "- Call the vendor about the late shipment\n"
            "- Book flights for the conference in Denver\n"
            "- Follow up with Sarah on the design review"
        ),
        "must_keep": ["quarterly report", "friday", "vendor", "shipment",
                      "flights", "denver", "sarah", "design review"],
        "is_bulleted": True,
        "meaning_note": "Source is a bulleted list; the output should stay "
                        "a bulleted list (or numbered list), not collapse "
                        "into one prose paragraph.",
    },
]


def _words(s):
    return len(re.findall(r"\S+", s or ""))


# Two or more list-item-shaped lines, not just one stray dash, before this
# counts as "the text is actually structured as a list" (real ask
# 2026-07-27: bullet input should compress to bullet output, not prose).
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S")


def _has_bullet_structure(text):
    lines = (text or "").split("\n")
    return sum(1 for ln in lines if _BULLET_LINE_RE.match(ln)) >= 2


def _retention(output, must_keep):
    low = (output or "").lower()
    hits = [k for k in must_keep if k in low]
    missed = [k for k in must_keep if k not in low]
    return len(hits) / len(must_keep), missed


# Heuristic "did it answer instead of compress" detector. The tells: the
# output is LONGER than the input, or it opens like a produced artifact
# ("Dear ", "Subject:", "Here is", "Sure,") rather than a rewritten
# instruction. Rough on purpose; it flags for a human to eyeball.
_EXECUTED_OPENERS = re.compile(
    r"^\s*(dear |subject:|hi |hello |sure[,!]|here('| i)s\b|absolutely[,!]|"
    r"of course[,!]|\* |- |\d+\.\s)", re.IGNORECASE)


def _looks_executed(text, output, allow_bullets=False):
    if not output:
        return False
    if _words(output) > _words(text):
        return True
    if allow_bullets and _EXECUTED_OPENERS.match(output) and _has_bullet_structure(output):
        # A deliberately-bulleted case (see is_bulleted in EVAL_PROMPTS)
        # SHOULD start with "- "/"1. " once the bullet-preservation guard
        # works -- that's success, not the executed-instead-of-compressed
        # failure this heuristic normally catches. Only waived when the
        # output is genuinely list-shaped (2+ item lines), not just any
        # line starting with a dash.
        return False
    return bool(_EXECUTED_OPENERS.match(output))


def run_eval():
    rows = []
    print(f"Running compression eval on {len(EVAL_PROMPTS)} prompts "
          f"(model: {local_model.model_label()})\n")
    for p in EVAL_PROMPTS:
        started = time.time()
        out, err = local_model.rewrite_prompt(p["text"])
        elapsed = time.time() - started
        if err:
            print(f"  {p['name']:16s}  ERROR: {err}")
            rows.append({"name": p["name"], "error": err})
            continue
        src_w, out_w = _words(p["text"]), _words(out)
        comp = 1 - (out_w / src_w) if src_w else 0
        ret, missed = _retention(out, p["must_keep"])
        is_bulleted = p.get("is_bulleted", False)
        executed = _looks_executed(p["text"], out, allow_bullets=is_bulleted)
        over = comp > 0.70
        bullet_preserved = _has_bullet_structure(out) if is_bulleted else None
        rows.append({
            "name": p["name"], "src_words": src_w, "out_words": out_w,
            "compression": round(comp, 3), "retention": round(ret, 3),
            "missed": missed, "executed": executed, "over_compressed": over,
            "bullet_preserved": bullet_preserved,
            "seconds": round(elapsed, 1), "output": out,
        })
        flags = []
        if executed:
            flags.append("EXECUTED?")
        if over:
            flags.append("OVER-COMPRESSED")
        if ret < 0.75:
            flags.append("LOW-RETENTION")
        if is_bulleted and not bullet_preserved:
            flags.append("BULLETS LOST")
        flag_str = ("  <- " + ", ".join(flags)) if flags else ""
        print(f"  {p['name']:16s}  ret {ret:.2f}  comp {comp:+.0%}  "
              f"{src_w:>3d}->{out_w:<3d}w  {elapsed:4.1f}s{flag_str}")
        if missed:
            print(f"                    missed: {', '.join(missed)}")
        # For meaning/role cases, print the output + what to eyeball, since
        # substring retention can't see an inverted role or flipped negation.
        if p.get("meaning_note"):
            print(f"                    OUT: {out}")
            print(f"                    CHECK: {p['meaning_note']}")
    return rows


def summarize(rows):
    ok = [r for r in rows if "error" not in r]
    if not ok:
        print("\nNo successful rewrites.")
        return
    mean_ret = sum(r["retention"] for r in ok) / len(ok)
    mean_comp = sum(r["compression"] for r in ok) / len(ok)
    n_exec = sum(1 for r in ok if r["executed"])
    n_over = sum(1 for r in ok if r["over_compressed"])
    n_lowret = sum(1 for r in ok if r["retention"] < 0.75)
    print("\n" + "=" * 60)
    print(f"  mean retention      {mean_ret:.3f}   (higher is better, aim >0.85)")
    print(f"  mean compression    {mean_comp:+.1%}   (good, but not at retention's cost)")
    print(f"  executed-not-compressed  {n_exec}/{len(ok)}   (want 0)")
    print(f"  over-compressed (>70%)   {n_over}/{len(ok)}")
    print(f"  low-retention (<0.75)    {n_lowret}/{len(ok)}")
    print("=" * 60)


def compare(before_path, after_path):
    with open(before_path) as f:
        before = {r["name"]: r for r in json.load(f)}
    with open(after_path) as f:
        after = {r["name"]: r for r in json.load(f)}
    print(f"{'prompt':16s}  {'retention':>18s}   {'compression':>18s}")
    print("-" * 60)
    for name in before:
        b, a = before.get(name, {}), after.get(name, {})
        br, ar = b.get("retention", 0), a.get("retention", 0)
        bc, ac = b.get("compression", 0), a.get("compression", 0)
        rd = ar - br
        arrow = "  " if abs(rd) < 0.001 else ("UP" if rd > 0 else "DOWN")
        print(f"{name:16s}  {br:.2f} -> {ar:.2f} {arrow:>4s}   "
              f"{bc:+.0%} -> {ac:+.0%}")
    bm = sum(r.get("retention", 0) for r in before.values()) / len(before)
    am = sum(r.get("retention", 0) for r in after.values()) / len(after)
    print("-" * 60)
    print(f"mean retention  {bm:.3f} -> {am:.3f}  ({am - bm:+.3f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="save full results to this path")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="compare two saved result files, no model run")
    args = ap.parse_args()

    if args.compare:
        compare(*args.compare)
        return

    rows = run_eval()
    summarize(rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
        print(f"\nsaved -> {args.json}")


if __name__ == "__main__":
    main()
