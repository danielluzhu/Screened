#!/usr/bin/env python3
"""Trim the thin light frame some posters arrive with.

    python3 scripts/trim_posters.py --dry-run     # report, don't write
    python3 scripts/trim_posters.py               # trim them
    python3 scripts/trim_posters.py --dir public/portraits

Wikipedia serves a few posters with a white hairline around the artwork. The
tiles crop to 2:3 with `object-fit: cover`, so a frame on the axis that isn't
cropped survives, and against a black page a two-pixel white line reads as a bar
across the top and bottom of the card.

Only a *frame* is trimmed, never a background. Three rules keep a poster that is
simply light-coloured — Forrest Gump is a feather on white — from being eaten:

  * the edge must be light (mean >= 200) and flat across its whole length,
  * it may be at most 3% of that dimension, which a real frame always is and a
    background never is,
  * flatness is measured between the 5th and 95th percentile of the line, not
    its outright range — JPEG noise puts a clean white line anywhere in 245-255,
    and one stray dark pixel should not save a border from being trimmed.

Run it after posters.py. Needs Pillow: python3 -m pip install --user pillow
"""
import os
import sys

try:
    from PIL import Image
except ImportError:  # noqa: BLE001
    sys.exit("needs Pillow — python3 -m pip install --user pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, "public", "posters")

LIGHT = 200      # mean channel value at or above which an edge counts as light
FLAT = 24        # 5th-95th percentile spread allowed within one edge line
MAX_SHARE = 0.03  # a frame is thin; a background is not


def edge_run(px, w, h, side):
    """How many flat, light lines sit at this edge."""
    horizontal = side in ("top", "bottom")
    length = h if horizontal else w
    limit = int(length * MAX_SHARE)
    order = range(length) if side in ("top", "left") else range(length - 1, -1, -1)

    n = 0
    for k in order:
        if n >= limit:
            break
        if horizontal:
            line = [px[x, k] for x in range(w)]
        else:
            line = [px[k, y] for y in range(h)]
        flat = sorted(v for c in line for v in c)
        if sum(flat) / len(flat) < LIGHT:
            break
        lo = flat[len(flat) // 20]
        hi = flat[-len(flat) // 20 - 1]
        if hi - lo > FLAT:
            break
        n += 1
    return n


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    folder = DEFAULT_DIR
    if "--dir" in args:
        i = args.index("--dir")
        if i + 1 >= len(args):
            sys.exit("--dir needs a path")
        folder = os.path.join(ROOT, args[i + 1])
    if not os.path.isdir(folder):
        sys.exit(f"{folder} is not a directory")

    trimmed, checked = 0, 0
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        try:
            image = Image.open(path)
        except Exception:  # noqa: BLE001
            continue
        checked += 1
        rgb = image.convert("RGB")
        px = rgb.load()
        w, h = rgb.size

        top = edge_run(px, w, h, "top")
        bottom = edge_run(px, w, h, "bottom")
        left = edge_run(px, w, h, "left")
        right = edge_run(px, w, h, "right")
        if not (top or bottom or left or right):
            continue

        box = (left, top, w - right, h - bottom)
        if box[2] - box[0] < w * 0.5 or box[3] - box[1] < h * 0.5:
            print(f"  ! {name} — trim would take half the image, skipped")
            continue

        print(
            f"  {'=' if dry_run else '+'} {name}: {w}x{h} -> "
            f"{box[2] - box[0]}x{box[3] - box[1]}  (t{top} b{bottom} l{left} r{right})"
        )
        trimmed += 1
        if dry_run:
            continue

        out = image.crop(box)
        if image.format == "JPEG":
            out.convert("RGB").save(path, "JPEG", quality=92, subsampling=0, optimize=True)
        elif image.format == "PNG":
            out.save(path, "PNG", optimize=True)
        elif image.format == "WEBP":
            out.save(path, "WEBP", quality=92)
        else:
            out.save(path)

    print(
        f"\n{trimmed} of {checked} image(s) "
        + ("would be trimmed" if dry_run else "trimmed")
        + f" in {os.path.relpath(folder, ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
