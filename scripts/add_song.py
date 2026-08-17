#!/usr/bin/env python3
"""Append a song to the Music sheet, then regenerate data.json.

Reads JSON on stdin:

    {"song": "Bohemian Rhapsody", "artist": "Queen", "album": "A Night at the Opera",
     "year": 1975, "country": "United Kingdom", "genre": "Rock",
     "allowDuplicate": false}

Only `song` is required. New songs start unrated ("?"). Album, country, genre
and year are normally left blank here and filled in by music_autofill.py, the
same way a film's poster is fetched as a separate step — so adding stays fast
and can't fail because Wikidata is slow.

The Music sheet is created on first use; documents predating it are fine.
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

    song = clean(payload.get("song"))
    if not song:
        print(json.dumps({"ok": False, "error": "song is required"}))
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

    artist = clean(payload.get("artist"))
    album = clean(payload.get("album"))
    country = clean(payload.get("country"))
    genre = clean(payload.get("genre"))
    tier = clean(payload.get("tier")) or "?"
    if tier not in io.TIERS:
        print(json.dumps({"ok": False, "error": f"invalid tier {tier!r}"}))
        return 1

    with io.editing() as (doc, _films):
        table = io.music_table(doc, create=True)
        # Song titles repeat across artists, and a cover is its own row, so a
        # duplicate is only a duplicate when the artist matches too.
        if not payload.get("allowDuplicate") and io.find_song_row(table, song, artist) is not None:
            raise Duplicate(f"{song} — {artist}" if artist else song)

        row = table.num_rows
        table.add_row(1)
        table.write(row, io.COL_SONG, song)
        if year is not None:
            table.write(row, io.COL_SONG_YEAR, year)
        table.write(row, io.COL_SONG_TIER, tier)
        for value, column in (
            (country, io.COL_SONG_COUNTRY),
            (artist, io.COL_ARTIST),
            (album, io.COL_ALBUM),
            (genre, io.COL_SONG_GENRE),
        ):
            if value:
                table.write(row, column, value)

    extract.main()
    print(
        json.dumps(
            {
                "ok": True,
                "song": {
                    "song": song,
                    "artist": artist,
                    "album": album,
                    "year": year,
                    "country": country,
                    "genre": genre,
                    "tier": tier,
                },
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
