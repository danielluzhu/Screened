#!/usr/bin/env python3
"""Save why a character is a favourite, into the Characters sheet's Why column.

Reads JSON on stdin:  {"name": "Toji Fushiguro", "why": "…"}

An empty value clears the cell.
"""
import json
import sys

import extract
import numbers_io as io

COL_NAME, COL_SHOW, COL_WHY = io.COL_CHAR_NAME, io.COL_CHAR_SHOW, io.COL_CHAR_WHY
MAX = 20000


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

    why = payload.get("why")
    why = "" if why is None else str(why).strip()
    if len(why) > MAX:
        print(json.dumps({"ok": False, "error": f"too long (max {MAX} characters)"}))
        return 1

    with io.editing() as (doc, _films):
        table = io.characters_table(doc)
        row = io.find_character_row(table, name)
        if row is None:
            raise NotFound(name)
        io.ensure_column(table, COL_WHY, "Why")
        table.write(row, COL_WHY, why)

    extract.main()
    print(json.dumps({"ok": True, "name": name, "length": len(why)}))
    return 0


class NotFound(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        sys.exit(2)
