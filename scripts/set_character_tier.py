#!/usr/bin/env python3
"""Rank a character, into the Characters sheet's Tier column.

Reads JSON on stdin:  {"name": "Toji Fushiguro", "tier": "S"}

Same S–F/? scale the films use, so one legend covers the whole site. Unlike
films, character names are unique in the sheet, so no year is needed to
disambiguate the row.
"""
import json
import sys

import extract
import numbers_io as io


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

    tier = str(payload.get("tier", "")).strip() or "?"
    if tier not in io.TIERS:
        print(json.dumps({"ok": False, "error": f"invalid tier {tier!r}"}))
        return 1

    with io.editing() as (doc, _films):
        table = io.characters_table(doc)
        row = io.find_character_row(table, name)
        if row is None:
            raise NotFound(name)
        io.ensure_column(table, io.COL_CHAR_TIER, "Tier")
        table.write(row, io.COL_CHAR_TIER, tier)

    extract.main()
    print(json.dumps({"ok": True, "name": name, "tier": tier}))
    return 0


class NotFound(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        sys.exit(2)
