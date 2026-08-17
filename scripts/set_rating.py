#!/usr/bin/env python3
"""Apply rating edits to Favorites.numbers, then regenerate data.json.

Reads JSON on stdin so the server can coalesce several rapid edits into one
save (a save rewrites the whole document, so batching matters):

    {"edits": [{"title": "Parasite", "tier": "S"}]}

Writes a JSON result to stdout.
"""
import json
import sys

import extract
import numbers_io as io

VALID = {"S", "A", "B", "C", "D", "E", "F", "?"}


def main():
    try:
        payload = json.load(sys.stdin)
        edits = payload["edits"]
        if not isinstance(edits, list) or not edits:
            raise ValueError("no edits")
    except (json.JSONDecodeError, KeyError, ValueError) as err:
        print(json.dumps({"ok": False, "error": f"bad payload: {err}"}))
        return 1

    for edit in edits:
        tier = str(edit.get("tier", "")).strip() or "?"
        if tier not in VALID:
            print(json.dumps({"ok": False, "error": f"invalid tier {tier!r}"}))
            return 1
        edit["tier"] = tier

    applied, missing = [], []
    try:
        with io.editing() as (doc, table):
            for edit in edits:
                title = str(edit.get("title", "")).strip()
                # Year disambiguates same-title films: without it a rating for
                # Mulan (2020) would land on Mulan (1998).
                year = edit.get("year")
                year = int(year) if isinstance(year, (int, float)) else None
                row = io.find_row(table, title, year) if title else None
                if row is None and year is not None:
                    row = io.find_row(table, title)
                if row is None:
                    missing.append(title)
                    continue
                table.write(row, io.COL_TIER, edit["tier"])
                applied.append({"title": title, "year": year, "tier": edit["tier"]})
            if missing:
                # Bail before saving: an unknown title means a stale page.
                raise LookupError(", ".join(missing))
    except LookupError as err:
        print(json.dumps({"ok": False, "error": f"unknown title(s): {err}"}))
        return 1

    extract.main()
    print(json.dumps({"ok": True, "applied": applied}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
