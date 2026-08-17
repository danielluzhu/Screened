#!/usr/bin/env python3
"""Save a film's notes and full analysis into the Films sheet.

Reads JSON on stdin:

    {"title": "Parasite", "year": 2019, "critique": "…", "analysis": "…"}

`critique` is the short, spoiler-free note shown openly on the film's page;
`analysis` is the long-form write-up kept behind a spoiler toggle. Either may be
sent alone. An empty string clears that cell. `year` disambiguates same-title
films.
"""
import json
import sys

import extract
import numbers_io as io

MAX = 20000  # a Numbers cell will hold far more, but this is a sanity bound


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

    fields = {}
    for key, column in (("critique", io.COL_CRITIQUE), ("analysis", io.COL_ANALYSIS)):
        if key not in payload:
            continue
        value = payload[key]
        value = "" if value is None else str(value).strip()
        if len(value) > MAX:
            print(json.dumps({"ok": False, "error": f"{key} is too long (max {MAX} characters)"}))
            return 1
        fields[column] = value
    if not fields:
        print(json.dumps({"ok": False, "error": "nothing to save"}))
        return 1

    year = payload.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None

    with io.editing() as (doc, table):
        row = io.find_row(table, title, year)
        if row is None:
            raise NotFound(title)
        # Widen the sheet if the notes columns aren't there yet.
        if table.num_cols <= io.COL_ANALYSIS:
            table.add_column(io.COL_ANALYSIS + 1 - table.num_cols)
        for column, header in ((io.COL_CRITIQUE, "Notes"), (io.COL_ANALYSIS, "Full analysis")):
            if not table.cell(0, column).value:
                table.write(0, column, header)
        for column, value in fields.items():
            table.write(row, column, value)

    extract.main()
    print(json.dumps({"ok": True, "title": title, "year": year, "saved": list(payload.keys() & {"critique", "analysis"})}))
    return 0


class NotFound(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        sys.exit(2)
