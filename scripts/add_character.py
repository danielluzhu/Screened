#!/usr/bin/env python3
"""Append a character to the Characters sheet, then regenerate data.json.

Reads JSON on stdin:

    {"name": "Gojo Satoru", "show": "JJK", "why": "…", "allowDuplicate": false}

Only `name` is required. The portrait is fetched separately
(scripts/character_photos.py --only NAME) so this stays fast.
"""
import json
import sys

import extract
import numbers_io as io

COL_NAME, COL_SHOW, COL_WHY = 0, 1, 2


def find(table, name):
    needle = name.strip().lower()
    for i, values in enumerate(table.rows(values_only=True)):
        if i == 0 or not values[COL_NAME]:
            continue
        if str(values[COL_NAME]).strip().lower() == needle:
            return i
    return None


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

    name = clean(payload.get("name"))
    if not name:
        print(json.dumps({"ok": False, "error": "name is required"}))
        return 1
    show = clean(payload.get("show"))
    why = clean(payload.get("why"))

    with io.editing() as (doc, _films):
        table = io.characters_table(doc)
        if not payload.get("allowDuplicate") and find(table, name) is not None:
            raise Duplicate(name)

        # The sheet has trailing blank rows; reuse one rather than growing.
        row = None
        for i, values in enumerate(table.rows(values_only=True)):
            if i and not values[COL_NAME]:
                row = i
                break
        if row is None:
            row = table.num_rows
            table.add_row(1)

        if table.num_cols <= COL_WHY:
            table.add_column(COL_WHY + 1 - table.num_cols)
        table.write(row, COL_NAME, name)
        if show:
            table.write(row, COL_SHOW, show)
        if why:
            table.write(row, COL_WHY, why)

    extract.main()
    print(json.dumps({"ok": True, "character": {"name": name, "show": show, "why": why}}))
    return 0


class Duplicate(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Duplicate as err:
        print(json.dumps({"ok": False, "duplicate": True, "error": f"{err} is already in the list"}))
        sys.exit(2)
