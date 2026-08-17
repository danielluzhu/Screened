#!/usr/bin/env python3
"""Fill in album, year, country and genre for songs on the Music sheet.

    python3 scripts/music_autofill.py                 # every song missing fields
    python3 scripts/music_autofill.py --only "Rosa"   # one song
    python3 scripts/music_autofill.py --dry-run       # look, don't write

Only blank cells are filled, so anything typed by hand is never overwritten.

Where each field comes from:
  album    the song's P361 "part of" / P1433 "published in", when it's an album
  year     the song's P577 publication date, earliest
  country  the performer's P27 country of citizenship, or P495 for a group
  genre    the *album's* P136 genre, falling back to the song's own

The genre is deliberately the album's: that is what the Music tab filters on,
and a single's own genre tags are patchier than the record's.
"""
import json
import os
import re
import sys

import extract
import numbers_io as io
import wikidata as wd

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".wikidata-music-cache.json")

# instance-of values that count as a song rather than an album or an artist
SONG_TYPES = {
    "Q7366",      # song
    "Q134556",    # single
    "Q105543609", # musical work/composition
    "Q2188189",   # musical work
    "Q169930",    # extended play
    "Q4132319",   # promotional single
}

ALBUM_TYPES = {
    "Q482994",   # album
    "Q208569",   # studio album
    "Q209939",   # live album
    "Q222910",   # compilation album
    "Q169930",   # extended play
}

# Wikidata labels its music genres "rock music", "heavy metal music". The
# suffix is noise on a filter where everything is music.
GENRE_NOISE = re.compile(r"\s*\bmusic\b\s*$", re.IGNORECASE)
MAX_GENRES = 4  # albums carry long genre tails; the card shows the head of it

_cache = {}


def tidy_genre(name):
    name = GENRE_NOISE.sub("", str(name)).strip()
    return name[:1].upper() + name[1:] if name else None


def entity(qid):
    """Claims and label for one QID, cached across runs."""
    key = "m-ent:" + qid
    if key in _cache:
        return _cache[key]
    resp = wd.api(
        {"action": "wbgetentities", "ids": qid, "props": "claims|labels", "languages": "en"}
    )
    if resp is None:
        raise wd.ApiUnavailable(qid)
    ent = resp.get("entities", {}).get(qid, {})
    claims = ent.get("claims", {})
    _cache[key] = {
        "label": ent.get("labels", {}).get("en", {}).get("value"),
        "types": wd.claim_values(claims, "P31"),
        "performers": wd.claim_values(claims, "P175"),
        "part_of": wd.claim_values(claims, "P361") + wd.claim_values(claims, "P1433"),
        "genres": wd.claim_values(claims, "P136"),
        "dates": wd.claim_values(claims, "P577"),
        # P27 is for a person, P495 for a band; a song's artist may be either.
        "citizenship": wd.claim_values(claims, "P27"),
        "origin": wd.claim_values(claims, "P495") + wd.claim_values(claims, "P740"),
    }
    return _cache[key]


def label(qid):
    """The English label for a QID, or None when Wikidata has no English one."""
    key = "m-label:" + qid
    if key in _cache:
        return _cache[key]
    resp = wd.api({"action": "wbgetentities", "ids": qid, "props": "labels", "languages": "en"})
    if resp is None:
        raise wd.ApiUnavailable(qid)
    value = (
        resp.get("entities", {}).get(qid, {}).get("labels", {}).get("en", {}).get("value")
    )
    _cache[key] = value
    return value


def search(term):
    """Candidate QIDs for a search term, cached."""
    key = "m-search:" + term.lower()
    if key in _cache:
        return _cache[key]
    resp = wd.api(
        {
            "action": "wbsearchentities",
            "search": term,
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": 20,
        }
    )
    if resp is None:
        raise wd.ApiUnavailable(term)
    ids = list(dict.fromkeys(hit["id"] for hit in resp.get("search", [])))
    _cache[key] = ids
    return ids


def find_song(song, artist):
    """The QID for a song, preferring one whose performer matches the artist.

    Searched on the title alone: wbsearchentities matches labels and aliases,
    so "Bohemian Rhapsody Queen" matches nothing at all. The artist is applied
    afterwards, as a filter over the candidates.
    """
    needle = (artist or "").strip().lower()
    fallback = None
    for qid in search(song)[:10]:
        ent = entity(qid)
        if not set(ent["types"]) & SONG_TYPES:
            continue
        if fallback is None:
            fallback = qid
        if not needle:
            return qid
        for performer in ent["performers"]:
            name = label(performer)
            if name and name.strip().lower() == needle:
                return qid
    # A named artist that never matched means the search found someone else's
    # song of the same name — better to fill nothing than the wrong record.
    return None if needle else fallback


def album_of(ent):
    """The album QID a song belongs to, if any of its 'part of' links is one."""
    for qid in ent["part_of"]:
        if set(entity(qid)["types"]) & ALBUM_TYPES:
            return qid
    return None


def country_of(ent):
    """Where the performer is from: citizenship for a person, origin for a band."""
    for performer in ent["performers"]:
        artist = entity(performer)
        for qid in artist["citizenship"] + artist["origin"]:
            name = label(qid)
            if name:
                return name
    return None


def details(song, artist):
    """Album, year, country and genres for one song. Empty dict if not found."""
    qid = find_song(song, artist)
    if not qid:
        return {}
    ent = entity(qid)

    out = {}
    years = [y for y in (wd.year_of(d) for d in ent["dates"]) if y]
    if years:
        out["year"] = min(years)

    country = country_of(ent)
    if country:
        out["country"] = country

    album_qid = album_of(ent)
    genre_source = ent
    if album_qid:
        album = entity(album_qid)
        if album["label"]:
            out["album"] = album["label"]
        # The album's genre is what the tab filters on; fall back to the
        # single's own tags only when the album carries none.
        if album["genres"]:
            genre_source = album

    names = []
    for qid in genre_source["genres"]:
        name = tidy_genre(label(qid))
        if name and name not in names:
            names.append(name)
    if names:
        out["genres"] = names[:MAX_GENRES]
    return out


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    only = None
    if "--only" in args:
        i = args.index("--only")
        if i + 1 >= len(args):
            sys.exit("--only needs a song title")
        only = args[i + 1].strip().lower()

    global _cache
    _cache = wd.load_cache(CACHE)

    doc = io.open_doc()
    try:
        table = io.music_table(doc)
    except KeyError:
        print("no Music sheet yet — add a song first")
        return 0

    # Read first, write second: the lookups are slow and the editing() lock
    # would be held across all of them otherwise.
    todo = []
    for i, row in enumerate(table.rows(values_only=True)):
        if i == 0 or not row[io.COL_SONG]:
            continue
        cells = list(row) + [None] * 8
        song = str(cells[io.COL_SONG]).strip()
        if only and song.lower() != only:
            continue
        artist = str(cells[io.COL_ARTIST]).strip() if cells[io.COL_ARTIST] else None
        missing = {
            "year": not cells[io.COL_SONG_YEAR],
            "country": not cells[io.COL_SONG_COUNTRY],
            "album": not cells[io.COL_ALBUM],
            "genres": not cells[io.COL_SONG_GENRE],
        }
        if any(missing.values()):
            todo.append((i, song, artist, missing))

    if not todo:
        print("nothing to fill in")
        return 0

    found = {}
    try:
        for _, song, artist, _ in todo:
            print(f"  {song}{f' — {artist}' if artist else ''}", flush=True)
            try:
                found[(song, artist)] = details(song, artist)
            except wd.ApiUnavailable as err:
                print(f"  ! lookup unavailable ({err}); stopping here", file=sys.stderr)
                break
    finally:
        # Keep whatever was resolved, even on an interrupt: the lookups are the
        # slow part and re-running should not start from nothing.
        wd.save_cache(CACHE, _cache)

    filled = 0
    if dry_run:
        for _, song, artist, missing in todo:
            got = {k: v for k, v in found.get((song, artist), {}).items() if missing.get(k)}
            if got:
                filled += 1
                print(f"{song}: {got}")
        print(f"\ndry run — {filled} song(s) would be filled in")
        return 0

    with io.editing() as (doc, _films):
        table = io.music_table(doc, create=True)
        for i, song, artist, missing in todo:
            got = found.get((song, artist))
            if not got:
                continue
            wrote = False
            for key, column, value in (
                ("year", io.COL_SONG_YEAR, got.get("year")),
                ("country", io.COL_SONG_COUNTRY, got.get("country")),
                ("album", io.COL_ALBUM, got.get("album")),
                ("genres", io.COL_SONG_GENRE, ", ".join(got.get("genres", []))),
            ):
                if missing.get(key) and value:
                    table.write(i, column, value)
                    wrote = True
            filled += wrote

    extract.main()
    print(f"filled in {filled} of {len(todo)} song(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
