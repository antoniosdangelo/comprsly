Paste this into a new chat to start Comprsly's marketing and promotion track. This is a separate track from product development, don't mix the two chats.

## What Comprsly is

Grammarly for token efficiency. A Windows desktop app that watches whatever text box you're typing in, fixes spelling and grammar, and compresses the whole prompt with a local AI so you send fewer tokens to an LLM. 100% local, zero backend, zero hosting cost.

One line for a stranger: "It's Grammarly, but instead of just fixing your grammar it also shrinks your prompt so you burn fewer tokens and less context window, all running locally on your machine."

## Current state, as of 2026-07-28 (check `Build.md`'s top section before trusting this for anything time-sensitive, it moves fast)

- Windows desktop app: built, working, deployed, now at version 1.0.0. Lead and primary shipped product.
- Website: comprsly.com, live, running on Cloudflare Workers.
- Email: contact@comprsly.com working.
- GitHub repo: github.com/Comprsly/comprsly, MIT licensed, confirmed **private**. Visibility is still Antonio's own open decision, don't assume either way when pitching an "open source" angle.
- **Microsoft Store: submitted, currently In Certification** (Partner Center's own estimate: usually a few hours, up to 3 business days). Store ID `9N8W5HPJ4DHV`. This is no longer "close but blocked", it's actually in Microsoft's review queue — check current status before promoting a specific launch date, it may have passed and gone live, or it may still be pending. No code-signing cost was needed: the Store signs the app automatically and for free on publish.
- Code signing for the *direct-download* .exe/.msix path (separate from the Store) is still unresolved — that download is unsigned and will trigger Windows SmartScreen warnings for anyone who gets it outside the Store. Given the Store submission is already in motion, the likely right sequencing is to point cold-traffic promotion at the Store listing once it's live, rather than a direct download link, until direct-download signing is separately resolved.

## Who it's for

Heavy AI chat users who care about cost and context limits: developers, power users, teams on metered API plans. Not a mass consumer product, a tool for people who already feel the pain of long prompts and token bills.

## Why it's different (the wedge)

Passive token counters exist (7+ of them), they just show a number. Standalone paste-and-compress tools exist too. Nobody found does real-time, inline, "watches you type and offers a shorter version before you send," across any text field on the machine (Chrome, Edge, native apps, Claude and ChatGPT desktop), not just inside a browser tab.

## Monetization stance

Free to start, locked decision. Zero hosting cost removes the usual pressure to charge early. Build usage first, monetize later, same playbook as Antonio's other venture, MCP Finds (an Instagram account, unrelated product, same sequencing philosophy).

## What this chat should actually do

Help figure out marketing and promotion for a bootstrapped, no-budget, developer-facing tool: which channels are worth it (developer communities, Reddit, Product Hunt, Hacker News, X/dev Twitter, YouTube reviewers who cover AI tooling, etc), what the launch sequence should look like, what messaging lands with the specific audience above, and anything else that falls under getting Comprsly in front of the people who'd actually want it.

Before proposing anything concrete, read `Overview.md` in this same folder (`Ventures/Comprsly/Overview.md`) for the full business thesis and competitive research, and skim `Build.md`'s top section for current technical state. Don't assume or invent product details not already established there, ask Antonio if something's unclear rather than guessing.

Known constraint worth weighing into any plan: the unsigned .exe / no Store listing situation above means a cold download link is currently a worse first impression than it will be once the Store listing goes live and starts signing the app for free. That's close (blocked on a package upload and one checkbox click, not new work), so it's a real sequencing question whether to hold hard distribution pushes until the Store listing is live, versus starting to build awareness now and pointing people to the Store once it's ready.

## Antonio's UGC video script idea (noted 2026-07-29, from the build/website-side chat, not yet developed further)

A founder-story UGC ad, structure: relatable problem → reveal/reasoning → CTA.

- **Hook (the problem):** "I was just using Whisper Flow and I kept rambling. Every time I finished rambling I'd take the prompt, paste it into ChatGPT, type 'rewrite,' and use the compressed version, every single time, to save tokens. Yeah, that works, but it takes a lot of time moving between tabs."
- **Turn:** "So I created something."
- **Reasoning:** goes into why Comprsly got built (the tab-switching tax on an already-common manual habit).
- **CTA** at the end.

Real strength worth keeping: the specific, lived-in details ("Whisper Flow," "typed 'rewrite'") are exactly what makes UGC read as authentic rather than scripted, and naming a real dictation tool signals directly to the exact audience who already has this manual habit. If this gets produced, consider showing the tab-switching friction on screen (a quick real screen-recorded copy/paste/switch beat) right before the "so I built this" cut, rather than only narrating it, that's the difference between telling the pain and selling it.

This chat should pick this up and develop it further (shot list, additional hooks/variations, where to post it) rather than the product/build chat.
