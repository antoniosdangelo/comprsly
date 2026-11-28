# The Mac UI: what carries over, and what does not

Written 2026-11-26 alongside the macOS layer. Updated 2026-11-28, when the
badge first drew on a real Mac.

## The good news is most of it

The review card, the settings window, the onboarding screens and the badge are
Tkinter and plain Python. They are not Windows code with Windows styling; they
draw themselves. They should come across as they are.

## The one thing that genuinely breaks

The badge is a circle drawn on a square window. The square is hidden on Windows
with:

```python
win.attributes("-transparentcolor", BRAND_DARK)
```

That colour keys one exact shade to true transparency, so the corners are both
invisible and click through. **That attribute is Windows only.** Tk's own `wm`
documentation lists it under "On Windows", and elsewhere it raises
`bad attribute`.

Shipped unchanged, the Mac badge is **a dark square with a circle painted on
it**, sitting on top of someone's terminal.

`platform_mac/window.py` handles it, with a fallback ladder rather than one
guess, because the macOS replacement is genuinely disputed:

| Result | What the user sees |
|---|---|
| `keyed` | correct: invisible corners, click through |
| `alpha` | acceptable: a faint square, badge still usable |
| `opaque` | wrong: the square is visible, and we say so rather than pretend |

### The ladder has to reach the widgets inside, not just the window

Found on 2026-11-28, from the first CI screenshot. The run reported
`transparency: keyed` and the picture was a dark rectangle with a sliver of
purple in it. **Both were true.** `-transparent` was accepted on the toplevel,
and the Canvas inside it had a solid `-background` and was drawn straight over
the top. A transparent window with an opaque child is an opaque badge.

So `badge_background(mode, key_color)` now says what every widget inside the
badge must paint: `systemTransparent` when the Mac keyed successfully, the key
colour anywhere else. On Windows the key colour **is** the transparency, so the
same function gives the right answer there without a branch at the call site.

### And the badge's own picture is not the same picture on both

`badge_art.flatten_for_colorkey` throws the alpha channel away and paints the
key colour wherever the mark was transparent. That is exactly right for
`-transparentcolor`, which deletes one exact shade, and it is exactly wrong on
a Mac, which composites real alpha and would simply be handed a solid square.
Flattening is a parameter now: Windows asks for it, macOS does not.

## Two smaller differences, handled

**Focus.** A window that is both topmost and `overrideredirect` can take key
focus on macOS. For this product that is fatal: the badge appearing must never
interrupt typing. It is marked a non-activating utility panel, which is the
documented way to float without stealing focus.

**Paste.** macOS is Command+V, not Control+V. `platform_mac/input.py` already
sends the right one.

## The four questions, and who can still answer them

1. **Does the badge render as a circle, or as a square?** *Answered by CI, by
   measurement.* The smoke run screenshots the badge's exact rectangle before
   and after it appears and compares the corners. Unchanged corners mean the
   square really is invisible. A window that claims `keyed` while its corners
   change is a FAILED verdict, not a pass, which is the specific way this went
   wrong the first time.
2. **Does it steal focus when it appears while you are typing?** *Answered by
   CI.* The run reads the frontmost application before and after the badge
   appears and fails if it moved.
3. **On a multi display Mac, is the badge where it should be?** **Still needs
   you.** The runner has one display. The Accessibility API reports coordinates
   from the top left of the primary display, which is what the shared geometry
   expects, and a second display above or to the left of the primary is exactly
   where that assumption breaks. This one will look mysterious rather than
   obviously broken.
4. **Does the review card open near the badge?** **There is no review card on
   macOS yet.** It is `SuggestionPopup` in `main.py`, 1,450 lines wound through
   Win32 focus restore and per-site window measurement, and porting it is its
   own piece of work. `main_mac.py --fix-once` is the half of it that needs no
   window: read the box, run the rules, write the result back. The smoke run
   drives that, so the correction can be seen landing in a real TextEdit window
   even though the panel that would offer it does not exist.

## Sizes are converted, not measured

macOS works in points and Windows in physical pixels. The badge was approved at
58 px on a 144 DPI laptop panel, which is 38.7 points of the same physical
size, so `mac_badge.BADGE_SIZE` is 38 and `BADGE_INSET` is 11 by the same
arithmetic. Both are a conversion of a number Antonio approved on a screen he
was looking at, not a number anyone has seen on a Mac. They are the first thing
to adjust when he does.
