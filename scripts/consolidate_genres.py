#!/usr/bin/env python3
"""Fold the Genre column in Favorites.numbers into the 30 canonical genres.

Dry run by default — prints the before/after counts and every row that would
change. Pass --apply to write the document and regenerate data.json.

    python3 scripts/consolidate_genres.py            # show what would change
    python3 scripts/consolidate_genres.py --apply    # write it

Labels missing from genres.ALIASES are reported under UNMAPPED and left alone
in a dry run; --apply refuses to run while any are outstanding, so a new
Wikidata label can't be silently dropped from a film.
"""
import sys
from collections import Counter

import extract
import genres as G
import numbers_io as io


def split_cell(value):
    return [part.strip() for part in str(value).split(",") if part.strip()] if value else []


def plan(table):
    """Per-row (index, title, old labels, new labels) for every genre cell."""
    rows = []
    for i, row in enumerate(table.rows(values_only=True)):
        if i == 0 or not row[io.COL_TITLE]:
            continue
        old = split_cell(row[io.COL_GENRE])
        rows.append((i, str(row[io.COL_TITLE]).strip(), old, G.canonical_list(old)))
    return rows


def main():
    apply = "--apply" in sys.argv[1:]
    doc = io.open_doc()
    rows = plan(io.films_table(doc))

    unmapped = Counter(
        label
        for _, _, old, _ in rows
        for label in old
        if not G.canonical(label) and label.strip().lower() not in G.ALIASES
    )
    emptied = [(t, old) for _, t, old, new in rows if old and not new]

    before = {label for _, _, old, _ in rows for label in old}
    after = Counter(g for _, _, _, new in rows for g in new)

    changed = [(i, t, old, new) for i, t, old, new in rows if old != new]
    for _, title, old, new in changed:
        print(f"  {title}\n    - {', '.join(old) or '(none)'}\n    + {', '.join(new) or '(none)'}")

    print(f"\n{len(before)} distinct labels -> {len(after)} canonical genres")
    print(f"{len(changed)} of {len(rows)} films change")
    for genre, n in sorted(after.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:4d}  {genre}")

    if emptied:
        print(f"\n{len(emptied)} film(s) lose every genre (all labels were non-genres):")
        for title, old in emptied:
            print(f"  {title}: {', '.join(old)}")

    if unmapped:
        print(f"\nUNMAPPED — add these to genres.ALIASES ({len(unmapped)}):")
        for label, n in unmapped.most_common():
            print(f"  {n:4d}  {label}")
        if apply:
            sys.exit("refusing to --apply with unmapped labels outstanding")

    if not apply:
        print("\ndry run — pass --apply to write")
        return
    if not changed:
        print("\nnothing to do")
        return

    # Re-read under the lock: the dry-run copy above was read without one.
    with io.editing() as (doc, table):
        for i, _, old, new in plan(table):
            if old != new:
                table.write(i, io.COL_GENRE, ", ".join(new))
    extract.main()
    print(f"\nwrote {len(changed)} rows and regenerated data.json")


if __name__ == "__main__":
    main()
