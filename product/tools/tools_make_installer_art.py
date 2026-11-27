"""Generates the installer's wizard artwork from the brand assets.

Inno Setup ships a stock light-blue box-and-disc bitmap on the welcome page
and a matching one in the top-right corner of every other page. It is the
first thing anyone sees of Comprsly and it looks like generic 2004 shareware,
so both are replaced with the real mark on the app's own dark background.

Inno wants BMP, and accepts a comma-separated list of sizes so it can pick
the right one per display scaling. Run after changing assets/logo.png:

    python tools_make_installer_art.py
"""
import os

from PIL import Image

BG = (14, 14, 17)          # POPUP_BG, the same dark the app's card uses
OUT_DIR = "assets"

# Inno's documented sizes for WizardImageFile, 100% through 250% scaling.
LARGE_SIZES = [(164, 314), (192, 386), (256, 515), (320, 644), (384, 773)]
# ...and for WizardSmallImageFile.
SMALL_SIZES = [(55, 58), (64, 68), (83, 80), (92, 97), (110, 106),
               (119, 123), (138, 140), (150, 161), (164, 161), (192, 192)]


def _mark(size):
    """The teardrop with its own silhouette filled, same asset the badge
    uses, so setup and the running app show an identical mark."""
    src = "assets/badge.png" if os.path.exists("assets/badge.png") else "assets/logo.png"
    return Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS)


def build_large(w, h):
    canvas = Image.new("RGB", (w, h), BG)
    # Mark sized off the panel width and sat above centre, which is where the
    # eye lands first and leaves the lower area clear.
    mark_px = int(w * 0.46)
    mark = _mark(mark_px)
    canvas.paste(mark, ((w - mark_px) // 2, int(h * 0.30) - mark_px // 2), mark)
    return canvas


def build_small(w, h):
    canvas = Image.new("RGB", (w, h), BG)
    mark_px = int(min(w, h) * 0.82)
    mark = _mark(mark_px)
    canvas.paste(mark, ((w - mark_px) // 2, (h - mark_px) // 2), mark)
    return canvas


def main():
    made = []
    for w, h in LARGE_SIZES:
        p = os.path.join(OUT_DIR, f"wizard_large_{w}x{h}.bmp")
        build_large(w, h).save(p)
        made.append(p)
    for w, h in SMALL_SIZES:
        p = os.path.join(OUT_DIR, f"wizard_small_{w}x{h}.bmp")
        build_small(w, h).save(p)
        made.append(p)
    print(f"wrote {len(made)} bitmaps")
    print("  large:", ", ".join(f"{w}x{h}" for w, h in LARGE_SIZES))
    print("  small:", ", ".join(f"{w}x{h}" for w, h in SMALL_SIZES))


if __name__ == "__main__":
    main()
