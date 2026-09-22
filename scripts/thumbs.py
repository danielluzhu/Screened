#!/usr/bin/env python3
"""Make list-sized thumbnails of every poster.

    python3 scripts/thumbs.py            # only posters with no thumbnail yet
    python3 scripts/thumbs.py --force    # rebuild all of them
    python3 scripts/thumbs.py --prune    # also delete thumbs with no poster

The film list renders posters into a 52px slot (30px on a director or year
page, 62px on the suggestions page) but was loading the full poster to do it —
89KB on average, for something drawn 52px wide. Scrolling the front page
pulled about 17MB of artwork. That is the whole of why the site felt slow; the
JSON it fetches first is a tenth of that and arrives gzipped.

So the lists get their own copy: 124px wide, which covers the widest of those
slots at 2x on a retina screen, in WebP. That lands around 4KB each, and takes
the library from 24MB to under 2MB.

The originals stay exactly as they are. The film page draws its poster at
180px and still loads the real file — downscaling that one would be visible,
and it is one image on a page about one film.

Run this after scripts/posters.py. Pages fall back to the full poster for
anything that has no thumbnail yet, so a new film looks right immediately and
merely costs what it used to until this runs again.
"""
import os
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on the machine
    sys.exit("thumbs.py needs Pillow: python3 -m pip install Pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "public", "posters")
DST = os.path.join(ROOT, "public", "thumbs")

# Widest list slot is 62px (suggestions), doubled for retina.
WIDTH = 124
QUALITY = 80


def thumb_name(poster):
    """poster.jpg -> poster.webp, so the page can derive one from the other."""
    return os.path.splitext(poster)[0] + ".webp"


def build(name, force):
    src = os.path.join(SRC, name)
    dst = os.path.join(DST, thumb_name(name))
    if not force and os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return None

    with Image.open(src) as im:
        # Posters arrive as RGB, RGBA (the PNGs) and the odd palette image;
        # WebP wants one of the first two and the alpha is never meaningful
        # on a poster, so flatten everything to RGB.
        im = im.convert("RGB")
        if im.width > WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
        im.save(dst, "WEBP", quality=QUALITY, method=6)
    return os.path.getsize(dst)


def main():
    force = "--force" in sys.argv
    prune = "--prune" in sys.argv

    if not os.path.isdir(SRC):
        sys.exit(f"no posters at {SRC}")
    os.makedirs(DST, exist_ok=True)

    posters = sorted(
        n for n in os.listdir(SRC) if not n.startswith(".") and os.path.isfile(os.path.join(SRC, n))
    )
    made = skipped = failed = 0
    before = after = 0
    for name in posters:
        try:
            size = build(name, force)
        except (OSError, ValueError) as err:
            failed += 1
            print(f"  {name}: {err}")
            continue
        if size is None:
            skipped += 1
            continue
        made += 1
        before += os.path.getsize(os.path.join(SRC, name))
        after += size

    if prune:
        keep = {thumb_name(n) for n in posters}
        for name in sorted(os.listdir(DST)):
            if name not in keep:
                os.remove(os.path.join(DST, name))
                print(f"  removed {name}")

    total_src = sum(os.path.getsize(os.path.join(SRC, n)) for n in posters)
    total_dst = sum(
        os.path.getsize(os.path.join(DST, n)) for n in os.listdir(DST) if n.endswith(".webp")
    )
    print(f"{made} built, {skipped} already current" + (f", {failed} failed" if failed else ""))
    if made:
        print(f"  those {made}: {before / 1048576:.1f}MB -> {after / 1048576:.2f}MB")
    print(f"  library: {total_src / 1048576:.1f}MB of posters, {total_dst / 1048576:.2f}MB of thumbs")


if __name__ == "__main__":
    main()
