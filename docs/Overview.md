# Comprsly

**Status (refreshed 2026-11-27):** Live product, version **1.1.1**, published in the Microsoft Store (verified 2026-11-27 with the `msstore` CLI: `ComprslyStore-1.1.1.msix`, Published, no pending submission). The repo is public, MIT licensed and product only, at `C:\Dev\Claude Code\Projects\Comprsly\comprsly`; the website moved to the private `comprsly-website` repo. A macOS version is built and in testing, not released. Everything below this line is the original business thesis and may be stale on specifics: the live technical state is `README.md` and `docs/Build.md`'s CURRENT STATE block. Original July status line follows for history: submitted to the Microsoft Store (v1.0.1.0 package, In Certification as of 2026-07-28) — website at [comprsly.com](https://comprsly.com), name settled as **Comprsly** (renamed from Compresly/Token Saver earlier in development)
**Started:** 2026-07-20 · **Last updated:** 2026-07-28 (status line only — see `Build.md` for everything since 2026-07-21, this file's own thesis content below is otherwise unchanged and may be stale on specifics)
**One-liner:** Grammarly for token efficiency. Watches whatever text box you're typing in, fixes spelling and grammar, and compresses the whole prompt with a local AI so you send fewer tokens. 100% local, zero backend.

> **Technical state, build commands, and all hard-won engineering findings live in `Build.md`.** That file is written to be sufficient context on its own for resuming work. This file is the business thesis.

---

## Where the product actually landed

The original thesis was a Chrome extension. The **Windows desktop app is now the lead product**, because it works everywhere the user types (Chrome, Edge, native apps, Claude and ChatGPT desktop) rather than only in a browser tab.

The engine also evolved past the original "flag known filler phrases" idea into a two-stage design:

1. **Rules** fix spelling, grammar and wordiness instantly (a custom rules engine, no model needed, always on).
2. **A local AI** (Qwen2.5-1.5B-Instruct, int4, fully offline — switched from an earlier Phi-3-mini plan for a much smaller memory footprint) then compresses the corrected prompt.

They cooperate rather than gate each other. Rules hand clean text to the AI; the AI does the compression rules can't. As of the Microsoft Store submission (v1.0.0, 2026-07-28), the model ships bundled inside the app package itself — no separate first-run download, unlike earlier builds.

**Delivery mechanisms (stale as of 2026-07-21, kept for history — see `Build.md` for the real current state):**

| Mechanism | State |
|---|---|
| Windows desktop app | **Lead and, as of 2026-07-28, only actively-shipped product.** Live on comprsly.com, submitted to the Microsoft Store |
| Chrome extension | Not confirmed still active as a separate distribution channel — check `Build.md` before assuming this line is current |
| Terminal PTY wrapper | Superseded — terminal support (Windows Terminal/PowerShell) is now built directly into the same desktop app, not a separate wrapper, per `Build.md` §10s onward |

---

## The six questions

- **Is this worth building?** Yes, verified against real competitors before starting. Passive token counters exist (7+). A standalone paste-and-compress tool exists. Nobody found does the real-time, inline, watches-you-type version.
- **Who would use it?** Heavy AI chat users who care about cost and context limits: developers, power users, teams on metered plans.
- **What problem does it solve?** People burn tokens, money and context window on verbose prompts without noticing, and only find out afterwards, if ever.
- **Can it be a business?** Realistic as free first (zero hosting cost removes the usual pressure). Monetization deferred until real usage exists.
- **Smallest version that creates value?** Shipped: catch typos and wordiness in any text box, compress on demand, show tokens saved.
- **How does it scale?** No backend. Distribution via installer and the Chrome Web Store.

---

## Competitive landscape

Verified 2026-07-20 via live checks, not assumed:

| Competitor | What it does | Gap |
|---|---|---|
| Claude Token Counter, AI Token Counter, etc. | Passive display, just a number | No suggestions, no compression |
| Kunal Ganglani's AI Prompt Compressor | Real compression | Standalone paste-and-click, not inline |
| Compressly | Looked like a direct competitor in search results | **Checked directly: expired domain for sale. Not a real product.** Lesson: verify by visiting the site, not trusting search snippets |
| LLMLingua-2 (Microsoft research) | The compression technique | A research project, not a consumer tool |

**The wedge:** real-time, inline, "watches what you're typing and offers a shorter version before you send" does not exist yet.

---

## Monetization

**Free to start (locked).** Zero hosting cost removes the usual reason to charge early. Build usage first, monetize later, same playbook as MCP Finds.

---

## Risks & open questions

- **Biggest assumption:** that inline real-time suggestions beat existing passive counters and paste-tools for users. Not user-tested yet.
- **Resolved 2026-07-21:** the memory constraint (peak 3.93 GB measured, mostly Phi-3-mini's 1.6 GB KV cache from having no grouped-query attention). Decision made: switch to Qwen2.5-1.5B-Instruct int4, which matches Phi-3 on instruction following at 40% of the size and cuts KV cache 13.7x. Code is in, one ~1 GB download away. See Build.md §5.
- **The bigger thing that audit found:** the AI stage wasn't doing prompt compression at all. On 6 of 10 test prompts it executed the user's prompt instead of shortening it. That was a prompt-design bug, now fixed with a real compression system prompt plus fencing the user's text as data. Worth more to the product than the model swap.
- **Privacy vs quality tension:** staying 100% local caps rewrite quality versus a cloud API. The local-only promise is currently locked, and is also the main differentiator.
- **Market risk:** fast-moving space, obvious gaps get filled quickly. Move fast.
- **Strategic question:** whether to go cross-platform ("anywhere device"). Recommended sequence if pursued: extract one shared rules core, then browser extension, then web app, then a mobile keyboard, which is the real unlock and how Grammarly does mobile.

---

## Verdict

**Pursue.** Verified as more open than every other idea evaluated the same session. Technically proven end to end: it reads real text fields across Chrome, Edge and native apps, fixes real errors, and compresses prompts locally. The remaining blocker is hardware headroom for the AI stage, not feasibility.
