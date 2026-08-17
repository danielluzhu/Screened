#!/usr/bin/env python3
"""Append a show to the Shows sheet, then regenerate data.json.

Reads JSON on stdin:

    {"name": "Vinland Saga", "allowDuplicate": false}

Only the name is needed — the full series name, original title, years, seasons,
author, country and poster are filled in afterwards by
`scripts/shows.py --only NAME --apply`, which the server runs in the background.
"""
import json
import sys

import extract
import numbers_io as io
import shows

COL_NAME = shows.COL_NAME


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as err:
        print(json.dumps({"ok": False, "error": f"bad payload: {err}"}))
        return 1

    name = str(payload.get("name", "")).strip()
    if not name:
        print(json.dumps({"ok": False, "error": "name is required"}))
        return 1

    with io.editing() as (doc, _films):
        table = shows.shows_table(doc)
        rows = table.rows(values_only=True)

        if not payload.get("allowDuplicate"):
            for i, values in enumerate(rows):
                if i and values[COL_NAME] and str(values[COL_NAME]).strip().lower() == name.lower():
                    raise Duplicate(name)

        # The sheet ends with blank rows; fill one rather than growing the table.
        row = None
        for i, values in enumerate(rows):
            if i and not values[COL_NAME]:
                row = i
                break
        if row is None:
            row = table.num_rows
            table.add_row(1)
        table.write(row, COL_NAME, name)

    extract.main()
    print(json.dumps({"ok": True, "show": {"name": name}}))
    return 0


class Duplicate(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Duplicate as err:
        print(json.dumps({"ok": False, "duplicate": True, "error": f"{err} is already in the list"}))
        sys.exit(2)
