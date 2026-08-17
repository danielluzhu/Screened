#!/usr/bin/env python3
"""Edit a film's year, director, country and genre, then regenerate data.json.

Reads JSON on stdin:

    {"title": "Parasite", "year": 2019,
     "newYear": 2019, "director": "Bong Joon-ho", "country": "Korea",
     "genre": "Comedy drama, Thriller"}

`title` plus `year` locate the row (same-title films are different films); any
of `newYear`, `director`, `country` and `genre` may be sent alone, and an empty
value clears that cell. `director` and `genre` are comma-separated lists — the
page splits them back apart — so they are normalized to "a, b, c" here.

Year is part of a film's identity: posters and streaming links are keyed by
title|year, so those indexes are re-keyed when it changes, and a change that
would collide with another row of the same title is refused.
"""
import json
import os
import sys

import extract
import genres as G
import numbers_io as io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTERS = os.path.join(ROOT, "posters.json")
STREAMING = os.path.join(ROOT, "streaming.json")

MAX = 500  # these are short list cells, not prose


def as_list(value):
    """Normalize a comma-separated cell: drop blanks, collapse whitespace."""
    return ", ".join(part.strip() for part in str(value).split(",") if part.strip())


def rekey_posters(title, old_year, new_year):
    if not os.path.exists(POSTERS):
        return
    with open(POSTERS) as fh:
        index = json.load(fh)
    old_key, new_key = io.film_key(title, old_year), io.film_key(title, new_year)
    # Entries written before same-title films were distinguished are bare titles.
    name = index.pop(old_key, None) or index.pop(title, None)
    if name is None:
        return
    index[new_key] = name
    with open(POSTERS, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def rekey_streaming(title, old_year, new_year):
    if not os.path.exists(STREAMING):
        return
    with open(STREAMING) as fh:
        index = json.load(fh)
    films = index.get("films", {})
    services = films.pop(io.film_key(title, old_year), None)
    if services is None:
        return
    films[io.film_key(title, new_year)] = services
    with open(STREAMING, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def parse_year(value):
    """A year cell as an int, or None to clear it. Raises Invalid on junk."""
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise Invalid(f"year must be a number, got {value!r}")
    if not 1880 <= year <= 2100:
        raise Invalid(f"year {year} is out of range")
    return year


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

    try:
        year = parse_year(payload.get("year"))
    except Invalid:
        year = None  # the locator year is a hint; a bad one just widens the match

    # Text fields: only what was sent gets written, so a form can save one field.
    fields = {}
    for key, column, listish in (
        ("director", io.COL_DIRECTOR, True),
        ("country", io.COL_COUNTRY, False),
        ("genre", io.COL_GENRE, True),
    ):
        if key not in payload:
            continue
        value = payload[key]
        value = "" if value is None else str(value).strip()
        if len(value) > MAX:
            print(json.dumps({"ok": False, "error": f"{key} is too long (max {MAX} characters)"}))
            return 1
        if key == "genre" and value:
            # The Genre column holds only the 30 canonical genres, so the
            # filter stays usable. Aliases fold silently; anything else is a
            # typo worth surfacing rather than quietly dropping.
            labels = [p.strip() for p in value.split(",") if p.strip()]
            unknown = [l for l in labels if not G.canonical(l) and l.lower() not in G.ALIASES]
            if unknown:
                print(json.dumps({
                    "ok": False,
                    "error": f"unknown genre(s): {', '.join(unknown)}",
                    "allowed": G.CANON,
                }))
                return 1
            fields[column] = ", ".join(sorted(G.canonical_list(labels), key=G.sort_key))
            continue
        fields[column] = as_list(value) if listish else value

    changed_year = "newYear" in payload
    new_year = year
    if changed_year:
        try:
            new_year = parse_year(payload["newYear"])
        except Invalid as err:
            print(json.dumps({"ok": False, "error": str(err)}))
            return 1
        changed_year = new_year != year

    if not fields and not changed_year:
        print(json.dumps({"ok": False, "error": "nothing to save"}))
        return 1

    with io.editing() as (doc, table):
        row = io.find_row(table, title, year)
        if row is None:
            raise NotFound(title)
        if changed_year:
            # Two rows for the same title and year would share a page and a
            # poster, so refuse rather than create the collision.
            clash = [i for i in io.find_rows(table, title, new_year) if i != row]
            if clash:
                raise Duplicate(f"{title} ({new_year})" if new_year else title)
        # Widen the sheet if the genre column isn't there yet.
        if table.num_cols <= io.COL_GENRE:
            table.add_column(io.COL_GENRE + 1 - table.num_cols)
        for column, header in (
            (io.COL_COUNTRY, "Country"),
            (io.COL_DIRECTOR, "Director"),
            (io.COL_GENRE, "Genre"),
        ):
            if not table.cell(0, column).value:
                table.write(0, column, header)
        for column, value in fields.items():
            table.write(row, column, value)
        if changed_year:
            table.write(row, io.COL_YEAR, new_year if new_year is not None else "")

    if changed_year:
        rekey_posters(title, year, new_year)
        rekey_streaming(title, year, new_year)

    extract.main()
    print(
        json.dumps(
            {
                "ok": True,
                "title": title,
                "year": new_year,
                "saved": sorted(payload.keys() & {"newYear", "director", "country", "genre"}),
            }
        )
    )
    return 0


class Invalid(Exception):
    pass


class NotFound(Exception):
    pass


class Duplicate(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        sys.exit(2)
    except Duplicate as err:
        print(json.dumps({"ok": False, "duplicate": True, "error": f"{err} is already in the list"}))
        sys.exit(2)
