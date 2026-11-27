# The Mac UI: what carries over, and what does not

Written 2026-11-26 alongside the macOS layer. **None of this has run on a Mac.**

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

Community reports on the macOS path disagree. Some say `-transparent` plus a
`systemTransparent` background works and also drops the window shadow; others
report the window flashing at launch and then disappearing. **That is why it is
isolated behind one function with a fallback instead of sprinkled through the
badge code**, and why it is the first thing to look at on a real Mac.

## Two smaller differences, handled

**Focus.** A window that is both topmost and `overrideredirect` can take key
focus on macOS. For this product that is fatal: the badge appearing must never
interrupt typing. It is marked a non-activating utility panel, which is the
documented way to float without stealing focus.

**Paste.** macOS is Command+V, not Control+V. `platform_mac/input.py` already
sends the right one.

## What needs a human, not a test

1. Does the badge render as a circle, or as a square?
2. Does it steal focus when it appears while you are typing?
3. On a multi display Mac, is the badge where it should be? The Accessibility
   API reports coordinates from the top left of the primary display, which is
   what the shared geometry expects, but a second display above or to the left
   of the primary is exactly where that assumption breaks.
4. Does the review card open near the badge, or somewhere else?

The first is most likely to be wrong. The third is the one that will look
mysterious rather than obviously broken.
