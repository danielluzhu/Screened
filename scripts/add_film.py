#!/usr/bin/env python3
"""Append a film to the Films sheet, then regenerate data.json.

Reads JSON on stdin:

    {"title": "Drive My Car", "year": 2021, "director": "…", "country": "Japan",
     "allowDuplicate": false}

Only `title` is required. New films start unrated ("?"). Prints a JSON result.
Poster fetching is a separate step (scripts/posters.py --film) so this stays
fast and can't fail because Wikipedia is rate-limiting.
"""
import json
import sys

import extract
import numbers_io as io


def clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as err:
        print(json.dumps({"ok": False, "error": f"bad payload: {err}"}))
        return 1

    title = clean(payload.get("title"))
    if not title:
        print(json.dumps({"ok": False, "error": "title is required"}))
        return 1

    year = payload.get("year")
    if year not in (None, ""):
        try:
            year = int(year)
        except (TypeError, ValueError):
            print(json.dumps({"ok": False, "error": f"year must be a number, got {year!r}"}))
            return 1
        if not 1880 <= year <= 2100:
            print(json.dumps({"ok": False, "error": f"year {year} is out of range"}))
            return 1
    else:
        year = None

    director = clean(payload.get("director"))
    country = clean(payload.get("country"))
    tier = clean(payload.get("tier")) or "?"
    if tier not in {"S", "A", "B", "C", "D", "E", "F", "?"}:
        print(json.dumps({"ok": False, "error": f"invalid tier {tier!r}"}))
        return 1

    with io.editing() as (doc, table):
        # Adding the same film twice is easy to do by accident, so make the
        # caller opt in rather than silently creating a duplicate row. Same
        # title with a different year is a different film (Mulan 1998/2020),
        # so only flag it when the year matches too.
        if not payload.get("allowDuplicate") and io.find_row(table, title, year) is not None:
            raise Duplicate(f"{title} ({year})" if year else title)

        row = table.num_rows
        table.add_row(1)
        table.write(row, io.COL_TITLE, title)
        if year is not None:
            table.write(row, io.COL_YEAR, year)
        table.write(row, io.COL_TIER, tier)
        if country:
            table.write(row, io.COL_COUNTRY, country)
        if director:
            table.write(row, io.COL_DIRECTOR, director)

    extract.main()
    print(
        json.dumps(
            {
                "ok": True,
                "film": {"title": title, "year": year, "tier": tier, "country": country, "director": director},
            }
        )
    )
    return 0


class Duplicate(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Duplicate as err:
        print(json.dumps({"ok": False, "duplicate": True, "error": f"{err} is already in the list"}))
        sys.exit(2)
