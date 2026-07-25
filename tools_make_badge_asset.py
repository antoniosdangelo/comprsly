"""Generates assets/badge.png, the floating badge's base mark, from
assets/logo.png. The runtime heat dot (green/amber/red, or none) is
composited on top of THIS at runtime by _make_heat_badge_image in
main.py -- this script only builds the plain mark underneath it.

Real redesign 2026-07-25 (Antonio, direct: "we should make this the
badge instead"): replaced the old teardrop-with-gradient-ring silhouette
with a plain filled circle, matching a reference mockup he generated
separately. logo.png (the source) still carries the OLD teardrop-shaped
outline plus the "C/" glyph, both drawn as strokes on transparent, so
this script no longer just fills the teardrop's own silhouette (that was
the old build()) -- it isolates the glyph by COLOR (glyph = near-white,
equal RGB channels; the old rim = a saturated purple/blue gradient, see
glyph_mask below) and drops the rim entirely, then draws a fresh plain
circle underneath instead of reusing the teardrop's silhouette.

A plain circle is radially symmetric, so the old mirror_for_left_opening
step (flipping the teardrop's directional tail to point the other way
for a left-opening review card, see PersistentBadge.popup_anchor) no
longer applies to anything -- there's no directional tail left to flip.
Removed rather than kept as dead code.

Run this again only if assets/logo.png is ever replaced:
    python tools_make_badge_asset.py
"""
from PIL import Image
import numpy as np

# Deliberately #0e0e11 (the panel's own dark), NOT BRAND_DARK #0b0b0d.
# Real bug caught by rendering this before shipping (2026-07-21): the
# badge window colour-keys BRAND_DARK to true transparency, so filling
# the mark with exactly that colour made the fill vanish. Visually
# identical dark, just not the keyed value.
FILL = (14, 14, 17)

# Supersample factor for a clean anti-aliased circle edge -- drawing the
# circle mask directly at native resolution left a visibly jagged rim
# once composited; rendering at 4x and downsampling with LANCZOS fixes
# that the same way the rest of this asset pipeline already relies on
# LANCZOS resizes elsewhere (see _load_badge_mark_image in main.py).
SUPERSAMPLE = 4

# Circle radius as a fraction of canvas width. Chosen to match the
# reference mockup's proportions (a small margin around the disc, not
# edge-to-edge) -- not derived from logo.png's own geometry, since the
# old teardrop's circular part was a different, larger radius meant to
# leave room for its gradient rim, which this design doesn't have.
RADIUS_FRACTION = 0.465


def _glyph_mask(rgba_arr):
    """Isolates the "C/" glyph from logo.png's alpha channel by COLOR,
    not by shape: the glyph is solid near-white (equal-ish R/G/B, all
    high), while the old teardrop's rim stroke is a saturated purple/
    blue gradient. Same distinguishing test used by the old
    mirror_for_left_opening (see git history), just as the sole
    detection step now rather than a secondary one."""
    r = rgba_arr[..., 0].astype(int)
    g = rgba_arr[..., 1].astype(int)
    b = rgba_arr[..., 2].astype(int)
    a = rgba_arr[..., 3].astype(int)
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    sat = maxc - minc
    return (a > 40) & (sat < 25) & (minc > 120)


def build(src_path="assets/logo.png", out_path="assets/badge.png"):
    logo = Image.open(src_path).convert("RGBA")
    w, h = logo.size
    ss = SUPERSAMPLE
    big = logo.resize((w * ss, h * ss), Image.LANCZOS)
    arr = np.array(big)

    glyph_mask = _glyph_mask(arr)
    ys, xs = np.where(glyph_mask)
    if len(xs) == 0:
        raise RuntimeError(f"no glyph pixels found in {src_path}, check _glyph_mask thresholds")
    glyph_cx, glyph_cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2

    cx, cy = (w * ss) / 2, (h * ss) / 2
    radius = RADIUS_FRACTION * (w * ss)

    # Real bug caught by rendering, not by reading the code (2026-07-25,
    # live feedback: "move the logo a bit more upwards to make it center
    # within the circle"): the glyph's own bounding-box center in
    # logo.png does NOT line up with the square canvas's center -- it
    # was drawn centered within the OLD teardrop's circular part, whose
    # center sits lower than the plain square canvas's center once the
    # tail is discarded. Shift the glyph's alpha (not the circle) onto
    # the canvas center rather than assuming the source is pre-centered.
    shift_x, shift_y = int(round(cx - glyph_cx)), int(round(cy - glyph_cy))
    glyph_alpha_src = np.where(glyph_mask, arr[..., 3], 0).astype(np.float64)
    shifted = np.zeros_like(glyph_alpha_src)
    H, W = shifted.shape
    src_y0, src_y1 = max(0, -shift_y), min(H, H - shift_y)
    src_x0, src_x1 = max(0, -shift_x), min(W, W - shift_x)
    dst_y0, dst_y1 = max(0, shift_y), min(H, H + shift_y)
    dst_x0, dst_x1 = max(0, shift_x), min(W, W + shift_x)
    shifted[dst_y0:dst_y1, dst_x0:dst_x1] = glyph_alpha_src[src_y0:src_y1, src_x0:src_x1]
    glyph_alpha = shifted / 255.0

    yy, xx = np.mgrid[0:H, 0:W]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    # Soft-edged circle: ramps from fully opaque to fully transparent
    # across ~1.5 supersampled px either side of the true radius, which
    # LANCZOS-downsampling then turns into a smooth, non-jagged edge.
    circle_alpha = np.clip((radius - dist) / 1.5 + 0.5, 0, 1)

    out = np.zeros((H, W, 4), dtype=np.float64)
    out[..., 0], out[..., 1], out[..., 2] = FILL
    out[..., 3] = circle_alpha * 255
    for c in range(3):
        out[..., c] = out[..., c] * (1 - glyph_alpha) + 255 * glyph_alpha
    out[..., 3] = np.maximum(out[..., 3], glyph_alpha * 255)

    result = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")
    result = result.resize((w, h), Image.LANCZOS)
    result.save(out_path)
    print(f"wrote {out_path} {result.size}")


if __name__ == "__main__":
    build()
