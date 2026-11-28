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

### The macOS keying is dead, and it was measured dead

Settled on 2026-11-28, on macOS 26.7.2, by forcing all three rungs in one CI
run and photographing each.

`wm attributes -transparent 1` plus a `systemTransparent` background draws
**nothing at all**. Tk reported the window mapped and viewable at exactly the
right 38x38 rectangle, and the screen was byte identical before and after.
The same run forced `alpha` and `opaque` and both drew the real badge in
exactly the right place with the real artwork, which is what rules out
position, geometry, the asset and the heat ring and leaves only the keying.
This is the vanishing this page has warned about since it was written.

So the macOS badge asks AppKit instead: `setOpaque_(False)` with a clear
background colour and no shadow, on the Tk toplevel's own NSWindow. `keyed`
now means the Windows colour key and nothing else.

**Two corrections to that, both from the run after it.** The NSWindow was
looked up by title, and an overrideredirect window on Aqua is a borderless
NSWindow that `wm title` does not reach, so the lookup never matched once and
every AppKit call below it reported success while doing nothing. It is found
by what is on screen now: the Tk root is permanently withdrawn, so a single
visible window IS the badge, and where there is more than one the frame
decides, converted from Tk's top left origin to AppKit's bottom left.

And the clearing cannot be asked for before the window is mapped, because Tk
does not create the NSWindow until then. It is an upgrade rather than a rung:
the window is built on `alpha`, which definitely draws, and improved
afterwards. A badge that is mapped and ugly beats one that is perfect and
invisible.

### And then Tk would not draw into it either

The run after that one got the whole window right and still drew nothing:

| What AppKit reported | |
|---|---|
| `visible=True` | the window is on screen |
| `frame=38x38+686+296` | exactly where the shared geometry put it |
| `opaque=False`, `alpha=1.00` | genuinely clear, not merely faint |
| `key=False` | and not taking the caret |

Byte identical before and after, all the same. **A Tk Label on a
`systemTransparent` background renders nothing on Aqua.** That is also what
killed the original `-transparent` route, so the window took the blame twice
for something the content was doing.

So Tk stops painting the mark on macOS. An `NSImageView` holding the real
PNG, alpha intact, goes in as a subview of the content view Tk already owns.
Tk keeps geometry, mapping and teardown; AppKit supplies the pixels. The
image is the same one Windows draws and is never flattened, so the edges stay
soft rather than keyed to one exact shade.

The image view swallows mouse events, which costs nothing while there is no
review card for the badge to open. Give it a `hitTest_` that returns nothing,
or forward the click, when there is one.

`alpha` and `opaque` are kept below it, and they look nearly identical: the
0.92 whole-window alpha is barely distinguishable from solid. Either is a
dark square with the mark on it, which is usable and wrong, and exactly what
the ladder promises you get when the rung above fails.

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

### Tk makes this a regular application, whatever Info.plist says

Found on 2026-11-28, from the first CI screenshot of the real badge. The menu
bar reads **Comprsly, File, Edit, Window, Help** and there is a Dock icon.
Those are Tk's own default Aqua menus, not ours, and `LSUIElement` really is
`true` in the built bundle's `Info.plist`, which was confirmed by reading it.
**Tk sets the activation policy back to regular when it starts.**

A regular application activates when it shows a window, so the badge appearing
took the caret from TextEdit. That is fatal twice over: it interrupts typing,
which is the one thing the badge must never do, and the watch loop then reads
Comprsly's own focused element instead of the text box it is meant to badge,
so the badge can never appear again either. One cause, both failures.

`become_accessory_app()` sets `NSApplicationActivationPolicyAccessory` after
the Tk root exists, since creating the root is what sets the policy it is
undoing.

## Two smaller differences, handled

**Focus.** A window that is both topmost and `overrideredirect` can take key
focus on macOS. For this product that is fatal: the badge appearing must never
interrupt typing. It is marked a non-activating utility panel, which is the
documented way to float without stealing focus.

**Paste.** macOS is Command+V, not Control+V. `platform_mac/input.py` already
sends the right one.

## The four questions, and who can still answer them

1. **Does the badge render as a circle, or as a square?** *Being answered by
   CI, by measurement.* The first run of the real badge drew **nothing at
   all**: the rectangle it belongs in was byte identical before and after,
   while the app reported `transparency: keyed` and a window it believed was
   on screen. That is the vanishing this page has warned about since it was
   written. The smoke run now measures all three rungs of the ladder in one
   go and reports which is visible, rather than another round of picking one.
   *Previously answered by measurement:* The smoke run screenshots the badge's exact rectangle before
   and after it appears and compares the corners. Unchanged corners mean the
   square really is invisible. A window that claims `keyed` while its corners
   change is a FAILED verdict, not a pass, which is the specific way this went
   wrong the first time.
2. **Does it steal focus when it appears while you are typing?** *Answered by
   CI, and it did.* The run reads the frontmost application before and after
   the badge appears and fails if it moved.

   Two separate causes, found in that order. Tk made the app a regular
   application, fixed by the accessory policy above. Then, with the menu bar
   correctly still reading TextEdit, **the badge window itself became the key
   window**: TextEdit's title bar went grey the moment the badge appeared, and
   the Accessibility API then correctly reported Comprsly as the focused
   application, so the watch loop read Comprsly's own focused element instead
   of the text box it was badging.

   **It was the `-transparent` window doing it.** Abandoning the macOS colour
   key fixed focus on its own: the run that replaced it passes in all three
   rungs. The AppKit undo written for this, `orderOut_` to hand key status
   back and `orderFrontRegardless` to show the badge without asking to be
   key, has never actually executed, because the window lookup it depends on
   was broken at the time. It is kept because the clearing may bring the
   problem back, and the run will say so rather than us assuming either way.
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
