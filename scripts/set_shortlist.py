#!/usr/bin/env python3
"""Put a film on the short list, or take it off, then regenerate data.json.

The short list is the films you mean to watch next — a hand-picked subset of
the unrated ones, kept apart from the ranked queue, which is generated. It
lives in Favorites.numbers alongside the rating, because it is a decision you
made rather than something a script worked out.

Reads JSON on stdin, writes JSON to stdout:

    {"title": "Yi Yi", "year": 2000, "on": true}

    python3 scripts/set_shortlist.py --list        # what's on it
"""
import json
import sys

import extract
import numbers_io as io


def shortlisted_films():
    table = io.films_table(io.open_doc())
    rows = table.rows(values_only=True)
    out = []
    for values in rows[1:]:
        if not values or not values[io.COL_TITLE]:
            continue
        cell = values[io.COL_SHORTLIST] if len(values) > io.COL_SHORTLIST else None
        if io.is_shortlisted(cell):
            year = io.year_of(values[io.COL_YEAR])
            out.append({"title": str(values[io.COL_TITLE]).strip(), "year": year})
    return out


def main():
    if "--list" in sys.argv[1:]:
        films = shortlisted_films()
        for film in films:
            print(f"  {film['year'] or '—':>4}  {film['title']}")
        print(f"{len(films)} film(s) on the short list")
        return 0

    try:
        payload = json.load(sys.stdin)
        title = str(payload.get("title", "")).strip()
        if not title:
            raise ValueError("no title")
    except (json.JSONDecodeError, ValueError) as err:
        print(json.dumps({"ok": False, "error": f"bad payload: {err}"}))
        return 1

    year = payload.get("year")
    year = int(year) if isinstance(year, (int, float)) else None
    on = bool(payload.get("on", True))

    try:
        with io.editing() as (doc, table):
            io.ensure_column(table, io.COL_SHORTLIST, io.SHORTLIST_HEADER)
            row = io.find_row(table, title, year)
            if row is None and year is not None:
                row = io.find_row(table, title)
            if row is None:
                raise LookupError(title)
            table.write(row, io.COL_SHORTLIST, io.SHORTLIST_ON if on else "")
    except LookupError as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        return 1

    extract.main()
    print(json.dumps({"ok": True, "title": title, "year": year, "shortlisted": on}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
