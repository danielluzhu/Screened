#!/usr/bin/env python3
"""Rate a song, into the Music sheet's Tier column.

Reads JSON on stdin:  {"song": "Bohemian Rhapsody", "artist": "Queen", "tier": "S"}

`artist` narrows the row — song titles repeat across artists, and a cover is a
different row from the original — so send it whenever the page has it.
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

    song = str(payload.get("song", "")).strip()
    if not song:
        print(json.dumps({"ok": False, "error": "song is required"}))
        return 1

    artist = str(payload.get("artist") or "").strip() or None
    tier = str(payload.get("tier", "")).strip() or "?"
    if tier not in io.TIERS:
        print(json.dumps({"ok": False, "error": f"invalid tier {tier!r}"}))
        return 1

    with io.editing() as (doc, _films):
        try:
            table = io.music_table(doc)
        except KeyError:
            raise NotFound(song)
        row = io.find_song_row(table, song, artist)
        # A stale page may know an artist the sheet no longer has; fall back to
        # the title alone rather than refusing the edit.
        if row is None and artist:
            row = io.find_song_row(table, song)
        if row is None:
            raise NotFound(f"{song} — {artist}" if artist else song)
        io.ensure_column(table, io.COL_SONG_TIER, "Tier")
        table.write(row, io.COL_SONG_TIER, tier)

    extract.main()
    print(json.dumps({"ok": True, "song": song, "artist": artist, "tier": tier}))
    return 0


class NotFound(Exception):
    pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except NotFound as err:
        print(json.dumps({"ok": False, "error": f"{err} is not in the list"}))
        sys.exit(2)
