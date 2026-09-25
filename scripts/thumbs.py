#!/usr/bin/env python3
"""Make display-sized copies of every image the pages draw small.

    python3 scripts/thumbs.py                    # anything not built yet
    python3 scripts/thumbs.py --force            # rebuild all of them
    python3 scripts/thumbs.py --prune            # drop thumbs with no original
    python3 scripts/thumbs.py posters portraits  # only these sets

Every set here was being loaded at full size and drawn at a fraction of it.
Posters are the worst of it — 89KB of artwork average, rendered into a 52px
slot, about 17MB to scroll the front page — but the same is true of the
director avatars (330px stored, 44px drawn) and the character art (968px
median, one of them 2001px, drawn into a 240px tile).

So each set gets a WebP copy at the size its largest small use actually needs,
doubled for retina:

    posters     124px   62px suggestion card, the widest of the *row* slots
    portraits   176px   88px avatar on a director's own page
    characters  480px   240px tile in the characters grid
    shows       600px   300px tile, which is the wide grid

Posters are the exception, and deliberately so. The film grid draws them as
tiles at `minmax(190px, 1fr)`, so 124px does not cover that slot and was never
going to — sized this way it is a *placeholder*, not the final image. public/
art.js paints it immediately and then swaps the original in behind it, only for
the slots where the extra pixels would actually show. Widening it here would
slow the first paint to save a request the page is already making lazily.

The other three sets do cover their largest slot, so art.js leaves them alone
and they are still loaded exactly once.

Originals stay untouched and are what art.js upgrades to, and what the fallback
loads. Keeping them matters twice over: they are the source these are rebuilt
from, and a newly added image works before this has run again.

An image smaller than its target is copied across rather than blown up.

posters.py runs this for its own set, and build_static.py runs the lot before
publishing, so the deployed site always has current thumbnails whichever image
script last ran.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
THUMBS = os.path.join(PUBLIC, "thumbs")

# set -> width in px. Twice the largest slot the pages draw it into, except
# posters, where it is the placeholder width art.js upgrades away from.
SETS = {
    "posters": 124,
    "portraits": 176,
    "characters": 480,
    "shows": 600,
}

QUALITY = 80


def thumb_name(original):
    """poster.jpg -> poster.jpg.webp, so a page can derive one from the other.

    The extension is kept rather than replaced: public/shows holds both a
    naruto.png and a naruto.webp, and swapping the extension collapsed them
    onto one thumbnail whose source depended on directory order.
    """
    return original + ".webp"


def _build(src, dst, width):
    from PIL import Image

    with Image.open(src) as im:
        # Originals arrive as RGB, RGBA (the PNGs), and the odd palette image.
        # WebP wants one of the first two, and alpha is never meaningful on a
        # poster or a portrait, so flatten everything.
        im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        im.save(dst, "WEBP", quality=QUALITY, method=6)


def refresh(name, force=False, prune=False, quiet=False):
    """Build the thumbnails for one set. Returns (built, skipped, failed).

    Importable so posters.py and build_static.py can keep the thumbnails
    current without shelling out. Missing Pillow is reported, not raised: the
    pages fall back to the original image, so a machine without it still
    builds a working site, just a heavier one.
    """
    try:
        import PIL  # noqa: F401
    except ImportError:
        if not quiet:
            print("  thumbs: Pillow not installed, skipping (pages use full images)")
        return 0, 0, 0

    src_dir = os.path.join(PUBLIC, name)
    if not os.path.isdir(src_dir):
        return 0, 0, 0
    dst_dir = os.path.join(THUMBS, name)
    os.makedirs(dst_dir, exist_ok=True)
    width = SETS[name]

    originals = sorted(
        n
        for n in os.listdir(src_dir)
        if not n.startswith(".") and os.path.isfile(os.path.join(src_dir, n))
    )
    built = skipped = failed = 0
    before = after = 0
    for original in originals:
        src = os.path.join(src_dir, original)
        dst = os.path.join(dst_dir, thumb_name(original))
        if not force and os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            skipped += 1
            continue
        try:
            _build(src, dst, width)
        except (OSError, ValueError) as err:
            # A file Pillow can't read is better left to the fallback than
            # left as a half-written thumb.
            if os.path.exists(dst):
                os.remove(dst)
            failed += 1
            if not quiet:
                print(f"  {name}/{original}: {err}")
            continue
        built += 1
        before += os.path.getsize(src)
        after += os.path.getsize(dst)

    if prune:
        keep = {thumb_name(n) for n in originals}
        for stale in sorted(os.listdir(dst_dir)):
            if stale not in keep:
                os.remove(os.path.join(dst_dir, stale))
                if not quiet:
                    print(f"  removed {name}/{stale}")

    if not quiet:
        total_src = sum(os.path.getsize(os.path.join(src_dir, n)) for n in originals)
        total_dst = sum(
            os.path.getsize(os.path.join(dst_dir, n)) for n in os.listdir(dst_dir)
        )
        note = f", {failed} failed" if failed else ""
        print(
            f"  {name:11} {built:4} built, {skipped:4} current{note}"
            f"   {total_src / 1048576:5.2f}MB -> {total_dst / 1048576:5.2f}MB"
        )
    return built, skipped, failed


def refresh_all(force=False, prune=False, quiet=False, names=None):
    total = [0, 0, 0]
    for name in names or SETS:
        for i, n in enumerate(refresh(name, force, prune, quiet)):
            total[i] += n
    return tuple(total)


def main():
    argv = sys.argv[1:]
    force = "--force" in argv
    prune = "--prune" in argv
    names = [a for a in argv if not a.startswith("-")]
    for name in names:
        if name not in SETS:
            sys.exit(f"unknown set {name!r}; try {', '.join(SETS)}")

    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("thumbs.py needs Pillow: python3 -m pip install Pillow")

    built, skipped, failed = refresh_all(force, prune, names=names or None)
    print(f"\n{built} built, {skipped} already current" + (f", {failed} failed" if failed else ""))


if __name__ == "__main__":
    main()
