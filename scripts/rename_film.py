#!/usr/bin/env python3
"""Rename a film in the Films sheet, then regenerate data.json.

Reads JSON on stdin:

    {"title": "Mugen Train", "year": 2020, "newTitle": "Demon Slayer: …"}

`year` disambiguates same-title films. The poster index is re-keyed so artwork
follows the film; the image file keeps its old name, which is harmless.
"""
import json
import os
import sys

import extract
import numbers_io as io

POSTERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "posters.json")


def rekey_poster(old, new, year):
    if not os.path.exists(POSTERS):
        return
    with open(POSTERS) as fh:
        index = json.load(fh)
    old_key, new_key = io.film_key(old, year), io.film_key(new, year)
    name = index.pop(old_key, None) or index.pop(old, None)
    if name is None:
        return
    index[new_key] = name
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
    new_title = str(payload.get("newTitle", "")).strip()
    if not title or not new_title:
        print(json.dumps({"ok": False, "error": "title and newTitle are required"}))
        return 1
    if new_title == title:
        print(json.dumps({"ok": True, "unchanged": True, "title": title}))
        return 0

    year = payload.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None

    with io.editing() as (doc, table):
        row = io.find_row(table, title, year)
        if row is None:
            raise NotFound(title)
        table.write(row, io.COL_TITLE, new_title)

    rekey_poster(title, new_title, year)
    extract.main()
    print(json.dumps({"ok": True, "from": title, "to": new_title, "year": year}))
    return 0


class NotFound(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        sys.exit(2)
