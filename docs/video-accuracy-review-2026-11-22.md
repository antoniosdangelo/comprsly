# Comprsly product video, accuracy review

**Reviewed:** 2026-11-22 by the Comprsly Builder session, at dev-88's request via Orchestrator.
**Subject:** `Personal Website\frontend\public\demos\comprsly.mp4` (1920x1080, 29.4s) and its source `Personal Website\tools\video\comprsly\video.html`.
**Checked against:** `desktop/main.py` at `APP_VERSION = "1.0.67"`, the running product's own source, not the website and not `brand-spec.md`.

## Verdict

The copy is in excellent shape. Nine strings match the app character for character, including ones that would be easy to get subtly wrong. Every problem below is color or a UI element, not wording.

**One root cause explains most of it.** The brief said to build from `docs/content/brand-spec.md`. That spec documents **comprsly.com**, which is still green and still carries a toast the app does not have. The app went monochrome on 2026-07-26 and the spec never caught up. So the video faithfully reproduces the website's look, and the website does not look like the app. Fix at that level rather than recoloring one value at a time.

## Issues, worst first

### 1. The badge dot is green. At that moment the real app shows yellow.

This one inverts a meaning, so it is the most important.

The badge dot is not a status light, it is a **heat indicator**. `_heat_color(count)` in `main.py` sweeps HSV hue 120 degrees to 0, green to red, driven by how many suggestions are pending, with `BADGE_HEAT_MAX = 6` as fully red.

Green means **count is 0, nothing to fix**. The code comment is explicit that this distinction matters.

The video shows a green dot while 3 fixes are pending. With `count = 3` the real dot is `hue = (120 - 120 * 0.5) / 360`, 60 degrees, HSV(60, 0.85, 0.88), which is **yellow, about `#E0E021`**.

So the video says "all clean" at the exact moment the app says "three things to fix."

`video.html:53`, `.badge .att`, currently `#4FB980`.

### 2. Green `#4FB980` is the website's color, not the app's

Three uses, two wrong, one right idea with the wrong hex.

| Where | Video | Real app |
|---|---|---|
| `.badge .att` (line 53) | `#4FB980` | heat ramp, yellow at 3 fixes, see above |
| `.saved` (line 48) | `#4FB980` | element does not exist, see issue 4 |
| `.check-line` (line 87) | `#4FB980` | **`#2e9e5b`** (`main.py:7604`) |

The check line is genuinely green in the app, just a different green. The other two should not be green at all.

Worth knowing for anything else built from the spec: `ACCENT_GREEN` is now `#6e6b7b` neutral gray, commented "was a savings/success green, now neutral gray to match", and `CORRECTNESS_ACCENT` is `#6e6b7b` with "category color-coding removed". If the category tags (spelling, grammar) are colored in the video, they should be that gray.

### 3. Footer uses a middle dot. The app uses an em dash.

Video, line 185: `100% on your device · nothing you type leaves it`

Real app, `main.py:7291`: `🔒  100% on your device — nothing you type leaves it`

An **em dash**, and a **lock emoji followed by two spaces**. The dormant `webui/reviewcard.html:65` agrees, also an em dash.

Not dev-88's error. `brand-spec.md` states the middle dot is correct and claims it was "corrected 2026-07-28 against a second, clearer real screenshot." Both code paths disagree with the spec. **The spec is wrong and should be fixed**, otherwise this recurs in every asset built from it. I will correct it on a docs branch unless someone has a screenshot that settles it the other way.

### 4. The post apply savings line does not exist in the product

The video ends the flow with `✓ 14 tokens saved, 38% shorter` under the chat box.

There is no such confirmation anywhere in `main.py`. The only `tokens saved` string is `main.py:8591`, the heading on the **Settings History page**, a running total in 28pt, not a per apply toast beside the chat.

It does exist on comprsly.com, which has a `demoShowToast` element reading `✓ N tokens saved`. Same root cause as the colors: the website has it, the app does not.

Either cut it, or relabel the shot as the History page so it is true.

### 5. Wrong separator in the word and token counts

Video: `27 words · 37 tokens` and `17 words · 23 tokens`, middle dot `·` U+00B7.

Real app, `main.py:7986`: `f"{words} words • {tokens} tokens"`, **bullet `•` U+2022**.

Easy to miss because the stat line directly above it genuinely does use a middle dot, `↓ 14 tokens · 38% shorter`, and the video has that one exactly right. The app really does mix the two characters.

### 6. Minor, spacing in the check line

App has two spaces after the tick, `"✓  No grammar or spelling issues found"`. Cosmetic, mentioned only for completeness.

## Verified correct, no action

Character for character against `main.py`:

- `Fix grammar & clarity`
- `Make it concise` (`STEP2_TITLE`)
- `Apply 3 fixes`, matching `f"Apply {n} fix{'es' if n != 1 else ''}"`
- `Dismiss`
- `3 things to clean up · tick the ones to apply`, matching `main.py:7401` including the middle dot
- `✓ No grammar or spelling issues found`
- `Compare both sides. Apply only if nothing important was cut.`
- `↓ 14 tokens · 38% shorter`, matching `main.py:7968` exactly
- `after Step 1`

Also correct: the popup header treatment (bare `mark_dark`, sliders and close, no host app window), the notch badge at bottom right, and the internal math. 37 minus 23 is 14, and 14 of 37 is 37.8 percent, rounding to 38.

Step 1 and Step 2 ordering and labels are right. Note the app draws the step markers as `✓` and `◎` in `ACCENT_VIOLET` (`#1b1a21`, near black), not numbered grey circles as on the website, worth confirming the video did not inherit the website's numbers.

## Recommended order

1. Badge dot to yellow. It is the one that states something false.
2. Drop or relabel the post apply savings line.
3. Check line green to `#2e9e5b`, remove the other two greens.
4. Separator to `•` in the word and token counts.
5. Footer to an em dash with the lock prefix, after the `brand-spec.md` question is settled.

Nothing here needs a re-shoot. It is all values and one deletion.
