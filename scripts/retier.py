#!/usr/bin/env python3
"""Bulk-remap tier values in the Films sheet.

    python3 scripts/retier.py 0=S 1=A
"""
import sys

import numbers_io as io


def main(argv):
    pairs = []
    for arg in argv:
        if "=" not in arg:
            sys.exit(f"expected FROM=TO, got {arg!r}")
        old, new = arg.split("=", 1)
        pairs.append((old.strip(), new.strip()))
    if not pairs:
        sys.exit("nothing to do")

    doc = io.open_doc()
    table = io.films_table(doc)
    rows = table.rows(values_only=True)

    changed = 0
    for old, new in pairs:
        hits = 0
        for i, row in enumerate(rows):
            if i == 0:
                continue
            tier = row[io.COL_TIER]
            # Tiers arrive as floats when Numbers stored them as numbers.
            if isinstance(tier, float) and tier.is_integer():
                tier = str(int(tier))
            if tier is not None and str(tier) == old:
                table.write(i, io.COL_TIER, new)
                hits += 1
        print(f"{old} -> {new}: {hits} film(s)")
        changed += hits

    if not changed:
        print("no rows matched; nothing written")
        return

    dest = io.save(doc)
    print(f"saved; backup at {dest}")


if __name__ == "__main__":
    main(sys.argv[1:])
