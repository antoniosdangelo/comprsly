# Comprsly content brand spec (locked)

Pulled directly from comprsly.com's live computed styles on 2026-07-28, not invented. Same discipline as the MCP Finds brand spec, pick these once, stop re-deciding them per post.

## Colors

| Role | Hex | Source on the real site |
|---|---|---|
| Background | `#FFFFFF` | body background |
| Primary text / headline | `#121212` | h1, body text |
| Secondary text / label | `#6A6A6A` | most-used muted gray across the site (captions, labels) |
| Dark surface (chips, buttons) | `#0B0B0D` | "Download for Windows" button background |
| Divider / hairline | `#E8E8E8` | thin section rules |
| Accent (savings) | `#4FB980` | the real "good news" color on the site, used specifically for token-savings callouts (the terminal demo's stat line, the applied-fix checkmark). This is the one to use for stat highlights. |
| Terminal dark surface | `#0D0D0F` background, `#17171A` header | the site's actual terminal/code-block theme, used when recreating a terminal moment specifically |
| Compression stat (violet) | `#6E6B7B` text, `#FBFAFD` box tint, `#F0EFF4` secondary-button fill | sampled directly from a real app screenshot, 2026-07-28, of the popup's "compare both sides" state. This is a SEPARATE accent from the green above: green is for grammar/checkmark confirmations, this muted slate-violet is specifically for compression stats (the "↓ N tokens · P% shorter" line and the Original/Optimized compare box). Don't unify these two, the real app keeps them visually distinct. |

Correction from the first pass of this spec: initially picked an amber (`#D4A13D`) as the accent, that was wrong, it's a minor one-off UI detail (a small "auto mode on" indicator dot) not the site's real savings-callout color. Green is what the site actually uses twice for "tokens saved," use that.

**The popup's real floating badge (`materials/icons/badge.png`) nests into a concave notch cut from the card's own corner**, confirmed against a real screenshot 2026-07-28, it does not float apart from the card with a gap, and it does not simply overlap the corner either — the card's white edge curves concavely around roughly the top-left of the badge's circle before giving way to whatever's behind it. Built with `mask-image: radial-gradient(circle Rpx at 100% 100%, transparent Rpx, #000 (R+1)px)` on the card element itself (not a plain `border-radius` corner), badge centered at that same `100% 100%` point, sized so its radius matches the mask's notch radius. See `before-after-card.html` for the working implementation. This specific badge state (no green dot) is the one confirmed for the popup corner; the terminal card's badge (with the green attention dot) is a separate, already-confirmed treatment, don't merge the two.

## Typography

System font stack, matching the site exactly: `-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`. On Windows this renders as Segoe UI, the same thing a Windows visitor to comprsly.com already sees, so social graphics and the website look like the same product.

- Headline: weight 600
- Body / labels: weight 400
- Small caps labels ("BEFORE", "AFTER COMPRSLY" style): weight 600, letter-spacing wide, secondary gray

If rendering ever moves off this machine (a Linux render server, for instance), swap to a real embedded webfont at that point rather than trusting system fonts to match across OSes. Not needed yet.

## Layout language

Correction from the first pass: don't invent a generic minimal card layout, recreate the site's own real UI components. Comprsly already has two distinct, recognizable visual moments on the live site, use those directly instead of a new invented look:

1. **The terminal demo** (`terminal-card.html`): dark window chrome, "Windows Terminal" header with the real minus/square/x controls, monospace body (Consolas), a dim "WHAT YOU SAID" line, then the clean instruction sitting inside a **recreation of Claude Code's own real REPL chrome** (a rule-bordered `›` prompt box, plus its live status bar verbatim underneath: "auto mode on (shift+tab to cycle) · ctrl+t to hide tasks · ← 1 agent"), matched against a real screenshot on 2026-07-28, not invented. The real Comprsly badge (`materials/icons/badge.png`, sourced from the actual app's `product/frontend/assets/badge.png`) is pinned to the corner of that prompt box, and Comprsly's own green stat line sits in a separate strip below the real chrome so it never reads as part of Claude Code's own UI. **Because this chrome is Claude-Code-specific real UI text, this template no longer rotates to other coding agents** (the old "Claude Code / Gemini CLI" rotation note is retired, Gemini CLI has its own different interface and would need its own faithful recreation, not this one reused). This is the strongest asset for developer-facing posts.
2. **The suggestion popup, compression state** (`before-after-card.html`): body starts straight into a green "no issues found" checkmark line, numbered step badge, a small plain-text tokens-saved line (not a colored badge), side-by-side Original/Optimized boxes, a black pill "Apply" button, and the signature lock-icon footer line "100% on your device · nothing you type leaves it" (a middle dot, corrected 2026-07-28 against a second, clearer real screenshot, the earlier em-dash note below was wrong). Keep that line verbatim, it's a genuine trust signal, don't paraphrase it.

**Superseded again, 2026-07-28 (later still): the fake host-app window is gone, replaced by the real popup's own actual header.** A real screenshot of the live app confirmed the popup's true top chrome is just the bare dark glyph mark (`materials/icons/mark_dark.png`, sourced from the app's own `product/frontend/assets/mark_dark.png`, transparent, no tile background) at top-left, plus `icon-sliders.png` and `icon-close.png` at top-right, no window title, no host-app name, nothing else. There is no longer any "Claude" or other LLM window shown above the popup in this template, that framing is retired along with its LLM-rotation comment block. Cost of this change: the card no longer demonstrates cross-platform coverage on its own (that job now belongs to other posts, e.g. `platforms-card.html`). Applies to `before-after-card.html` only so far, `checklist-card.html` still has the old host-header + mid-popup-strip pattern pending the same fix.
3. **The suggestion popup, checklist state** (`checklist-card.html`): the earlier moment in the same flow, Step 1 active with real checkbox rows (strikethrough old text, bold corrected text, a right-aligned category tag like "grammar" or "spelling"), an "Apply N fixes" button, and a preview of the still-locked Step 2 below it labeled "after Step 1." Confirmed against real screenshots of the actual running app, not the website, this state doesn't appear on the site's own animated demo.
4. **The weekly savings panel** (`stat-card.html`): a bordered card, small-caps gray label ("Tokens saved this week"), a bold black count, a 7-bar chart (rounded top corners only, black fill, varying height, day-letter labels below each), and a real explanatory caption below a divider. Confirmed against a live full-page capture of the site on 2026-07-28.

**Now fully superseded by the entry above this one.** A minimal Comprsly identity strip (logo + "Comprsly" wordmark, mid-popup, no window controls) briefly replaced the host-header's ambiguity problem, then was itself replaced same-day by the real popup header once a clearer screenshot of the actual app arrived. Kept here only as a record of the sequence, don't rebuild the mid-popup strip.

Verified against real screenshots of the actual desktop app on 2026-07-28, not just the website, the website and the app matched on everything checked except that one punctuation mark in the lock footer.

**Standing lesson from the stat-card rebuild: the live site's content changes within the same session**, sometimes within the same day (confirmed directly, the "tokens saved" component was a big-number-plus-calendar-dots layout earlier in this session and a bar-chart layout later in the same day). Don't trust text extracted from the site earlier in a conversation as still-current, re-check the live site (or a fresh full-page capture) immediately before building or fixing anything that claims to recreate it.

General rules either way:
- Generous whitespace around the recreated component, don't crowd it.
- Shadows are fine here, unlike MCP Finds' flat style, the real site's own cards use a soft drop shadow under window chrome. Match that, don't flatten it.
- Comprsly wordmark bottom-left, same placement logic as MCP Finds' handle placement.

## Voice

Same restraint as the product copy already on the site ("Say everything. Send less.", "Every word has a price now."). Plain, factual, a little dry. No exclamation points, no "amazing/powerful/game-changing." The token math and real demo content do the persuading, the copy doesn't need to oversell it.

## Canvas size

1080x1350 (Instagram 4:5 portrait), same as MCP Finds, for consistency across whichever platform ends up using the asset.

## Rendering

Real Chrome installed on this machine renders these reliably at exact size:

```
cd content && python -m http.server 8743
"C:\Program Files\Google\Chrome\Application\chrome.exe" --headless --disable-gpu --window-size=1080,1350 --default-background-color=FFFFFFFF --screenshot="<output path>.jpg" "http://localhost:8743/templates/<template>.html"
```

**Don't use the claude-in-chrome browser extension's live-tab screenshot for final verification of these templates**, found the hard way: it JPEG-compresses small/light-colored elements (a 22px light-gray icon, specifically) into invisibility even though the underlying HTML/CSS is completely correct. A template can look broken in that tool and be genuinely fine. The headless Chrome command above is the real, trustworthy render, matches what an actual production pipeline would use, and is what MCP Finds' own `render.js` does under the hood (Puppeteer launching real Chrome), just invoked directly here instead of through a Node wrapper.
