#!/usr/bin/env python3
"""Remove a film from the Films sheet, then regenerate data.json.

Reads JSON on stdin:

    {"title": "Zootopia", "year": 2016}

`year` is optional but disambiguates when the sheet holds the same title twice
(it holds two Mulan rows and two Concrete Utopia rows). Prints a JSON result.

The poster file is left in place unless nothing else references it; the index
entry is always dropped so a re-add re-fetches cleanly.
"""
import json
import os
import sys

import extract
import numbers_io as io

POSTERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "posters.json")
SUGGEST_POSTERS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "suggestion-posters.json"
)
POSTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "posters")


def matching_rows(table, title, year):
    """Row indices whose title matches, narrowed by year when one is given."""
    return io.find_rows(table, title, year)


def suggestion_posters():
    """The suggestions page's own poster index; absent until it has been run."""
    try:
        with open(SUGGEST_POSTERS) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def drop_poster(title, year):
    if not os.path.exists(POSTERS):
        return
    with open(POSTERS) as fh:
        index = json.load(fh)
    # Try the year-qualified key first, then the legacy title-only one.
    name = index.pop(io.film_key(title, year), None) or index.pop(title, None)
    if name is None:
        return
    # Another film may share the image (duplicate rows share a slug), and a
    # film added from the suggestions page shares its file with that page's
    # index — removing it here puts it straight back in the suggestions, where
    # a deleted file would show as a broken poster.
    if name not in index.values() and name not in suggestion_posters().values():
        path = os.path.join(POSTER_DIR, name)
        if os.path.exists(path):
            os.remove(path)
    with open(POSTERS, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as err:
        print(json.dumps({"ok": False, "error": f"bad payload: {err}"}))
        return 1

    title = str(payload.get("title", "")).strip()
    if not title:
        print(json.dumps({"ok": False, "error": "title is required"}))
        return 1

    year = payload.get("year")
    if year in (None, ""):
        year = None
    else:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    removed = None
    with io.editing() as (doc, table):
        hits = matching_rows(table, title, year)
        if not hits:
            raise NotFound(title)
        # Remove one row only; duplicates are removed one click at a time.
        row = hits[0]
        values = table.rows(values_only=True)[row]
        removed = {
            "title": str(values[io.COL_TITLE]),
            "year": int(values[io.COL_YEAR]) if isinstance(values[io.COL_YEAR], float) else values[io.COL_YEAR],
            "tier": str(values[io.COL_TIER]) if values[io.COL_TIER] is not None else "?",
        }
        table.delete_row(1, row)
        remaining = len(matching_rows(table, title, year))

    # Same title with a different year is a different film, so the poster goes
    # as soon as no row with this title AND year is left.
    if not remaining:
        drop_poster(title, year)

    extract.main()
    print(json.dumps({"ok": True, "removed": removed, "remaining": remaining}))
    return 0


class NotFound(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        sys.exit(2)
