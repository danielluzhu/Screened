#!/usr/bin/env python3
"""Extract Favorites.numbers into data.json for the Bun server.

Run after editing the Numbers file:  python3 scripts/extract.py
Requires: numbers-parser  (python3 -m pip install --user numbers-parser)
"""
import json
import os
import re
import sys
from collections import Counter

from numbers_parser import Document

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recommend  # noqa: E402
from numbers_io import slug as film_slug  # noqa: E402

# Wikidata's "part of the series" (P179) covers studio catalogues and critics'
# lists as well as actual franchises. These aren't franchises, so drop them.
NOT_A_FRANCHISE = re.compile(
    r"^list of|feature films?$|greatest films|\bfilms of\b|\bfilmography\b",
    re.IGNORECASE,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "Favorites.numbers")
DST = os.path.join(ROOT, "data.json")
POSTERS = os.path.join(ROOT, "posters.json")
FRANCHISES = os.path.join(ROOT, "franchises.json")
DIRECTORS = os.path.join(ROOT, "directors.json")
# Written alongside data.json. Kept out of it because only the /other/ pages
# read this, and folding 40KB gzipped into the payload every page fetches to
# serve one page type is a poor trade.
OTHER_FILMS = os.path.join(ROOT, "other-films.json")
# Written by scripts/director_photos.py. Absent until that has run.
DIRECTOR_PHOTOS = os.path.join(ROOT, "director-photos.json")
CHAR_PHOTOS = os.path.join(ROOT, "character-photos.json")
SHOW_PHOTOS = os.path.join(ROOT, "show-photos.json")
STREAMING = os.path.join(ROOT, "streaming.json")
SERVICE_LOGOS = os.path.join(ROOT, "service-logos.json")
SUMMARIES = os.path.join(ROOT, "summaries.json")
BOX_OFFICE = os.path.join(ROOT, "box-office.json")

# The Country column is typed by hand, so the same place shows up several ways.
# Raw values are preserved on each film; this map only drives grouping/filters.
REGIONS = {
    "china": "China",
    "chinese": "China",
    "hk": "Hong Kong",
    "hong kong": "Hong Kong",
    "taiwan": "Taiwan",
    "japanese": "Japan",
    "japanese?": "Japan",
    "japan": "Japan",
    "korea": "Korea",
    "korean": "Korea",
    "south korea": "Korea",
    "american": "USA",
    "usa": "USA",
    "india": "India",
    "indian": "India",
    "french": "France",
    "france": "France",
}

# Display order only. The old numeric tiers (0/1) were folded into S/A by
# scripts/retier.py, but they stay in the list so any stragglers still sort.
TIER_ORDER = ["S", "A", "B", "C", "D", "E", "F", "?", "0", "1"]


def clean(value):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def poster_for(posters, title, year):
    """Posters are keyed by title|year; fall back to a bare title for entries
    written before same-title films were distinguished."""
    y = year if isinstance(year, int) else None
    return posters.get(f"{str(title).strip()}|{y if y is not None else ''}") or posters.get(str(title))


def norm_title(title):
    """Loose title key, so 'Concrete Utopia' and 'Concrete utopia' agree."""
    return re.sub(r"[^a-z0-9]+", "", str(title).lower())


def franchise_names(cell):
    """Split the Franchise cell into distinct, real franchise names.

    Wikidata often has separate items with the same English label (a film series
    and a media franchise both called "Avatar"), so dedupe case-insensitively.
    """
    if not cell:
        return []
    names, seen = [], set()
    for part in str(cell).split(","):
        name = part.strip()
        if not name or NOT_A_FRANCHISE.search(name):
            continue
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(name)
    return names


def main():
    if not os.path.exists(SRC):
        sys.exit(f"missing {SRC}")

    doc = Document(SRC)
    sheets = {s.name: s.tables[0].rows(values_only=True) for s in doc.sheets}

    streaming = {"films": {}, "shows": {}}
    if os.path.exists(STREAMING):
        with open(STREAMING) as fh:
            streaming = json.load(fh)

    service_logos = {}
    if os.path.exists(SERVICE_LOGOS):
        with open(SERVICE_LOGOS) as fh:
            service_logos = json.load(fh)

    # Filled in by scripts/posters.py; absent until that has been run.
    posters = {}
    if os.path.exists(POSTERS):
        with open(POSTERS) as fh:
            posters = json.load(fh)

    # Filled in by scripts/summaries.py. Quoted from Wikipedia, so the source
    # travels with the text — the film page credits it.
    summaries = {}
    if os.path.exists(SUMMARIES):
        with open(SUMMARIES) as fh:
            summaries = json.load(fh)

    films = []
    for row in sheets["Films"][1:]:
        cols = (list(map(clean, row)) + [None] * 11)[:11]
        title, year, tier, country, note, director, franchise, genre, native, critique, analysis = cols
        if not title:
            continue
        films.append(
            {
                "title": str(title),
                "year": year if isinstance(year, int) else None,
                "tier": str(tier) if tier is not None else "?",
                "country": str(country) if country else None,
                "region": REGIONS.get(str(country).lower(), "Unknown") if country else "Unknown",
                "note": str(note) if note else None,
                "director": str(director) if director else None,
                # A film often has several directors; each gets its own page.
                "directors": [d.strip() for d in str(director).split(",") if d.strip()]
                if director
                else [],
                "poster": poster_for(posters, title, year),
                "nativeTitle": str(native) if native else None,
                "critique": str(critique) if critique else None,
                "analysis": str(analysis) if analysis else None,
                # Wikipedia's words, kept separate from critique/analysis, which
                # are the sheet's own. None until summaries.py has run.
                "summary": summaries.get(
                    f"{str(title).strip()}|{year if isinstance(year, int) else ''}"
                ),
                "streaming": streaming["films"].get(
                    f"{str(title).strip()}|{year if isinstance(year, int) else ''}", []
                ),
                # Stable id for the film's own page; made unique below.
                "slug": film_slug(title, year if isinstance(year, int) else None),
                "genres": [g.strip() for g in str(genre).split(",") if g.strip()] if genre else [],
                # A film can belong to more than one series (e.g. Toy Story).
                "franchises": franchise_names(franchise),
            }
        )

    # Duplicate rows (the sheet has two Concrete Utopia entries) would otherwise
    # share a URL. Suffix the later ones so every film has its own page.
    seen_slugs = {}
    for film in films:
        base = film["slug"]
        n = seen_slugs.get(base, 0) + 1
        seen_slugs[base] = n
        if n > 1:
            film["slug"] = f"{base}-{n}"

    char_photos = {}
    if os.path.exists(CHAR_PHOTOS):
        with open(CHAR_PHOTOS) as fh:
            char_photos = json.load(fh)

    characters = []
    for row in sheets["Characters"][1:]:
        name, show, why, tier = (list(map(clean, row)) + [None] * 4)[:4]
        if not name:
            continue
        characters.append(
            {
                "name": str(name),
                "show": str(show) if show else None,
                "why": str(why) if why else None,
                # Same scale as films. Rows predating the Tier column are unrated.
                "tier": str(tier).strip() if tier else "?",
                "photo": char_photos.get(str(name)),
                "slug": film_slug(name),
            }
        )
    seen_chars = {}
    for character in characters:
        base = character["slug"]
        n = seen_chars.get(base, 0) + 1
        seen_chars[base] = n
        if n > 1:
            character["slug"] = f"{base}-{n}"

    show_photos = {}
    if os.path.exists(SHOW_PHOTOS):
        with open(SHOW_PHOTOS) as fh:
            show_photos = json.load(fh)

    shows = []
    for row in sheets["Shows"][1:]:
        cols = (list(map(clean, row)) + [None] * 6)[:6]
        name, native, years, seasons, author, country = cols
        if not name:
            continue
        shows.append(
            {
                "name": str(name),
                "nativeTitle": str(native) if native else None,
                "years": str(years) if years else None,
                "seasons": str(seasons) if seasons else None,
                "author": str(author) if author else None,
                "country": str(country) if country else None,
                "photo": show_photos.get(str(name)),
                "streaming": streaming["shows"].get(str(name), []),
                "slug": film_slug(name),
            }
        )
    seen_shows = {}
    for show in shows:
        base = show["slug"]
        n = seen_shows.get(base, 0) + 1
        seen_shows[base] = n
        if n > 1:
            show["slug"] = f"{base}-{n}"

    # Group by franchise. Series with a single watched film are kept: the point
    # is which of these films belong to something larger, not only where the
    # whole set has been seen.
    by_series = {}
    for film in films:
        for name in film["franchises"]:
            by_series.setdefault(name, []).append(film)

    def sort_key(film):
        return (film["year"] is None, film["year"] or 0, film["title"])

    def entry(film):
        return {
            "title": film["title"],
            "year": film["year"],
            "tier": film["tier"],
            "director": film["director"],
            "poster": film["poster"],
            "slug": film["slug"],
        }

    # Full series membership from Wikidata, written by scripts/franchises.py.
    # Absent until that has been run, in which case "others" is simply empty.
    membership = {}
    if os.path.exists(FRANCHISES):
        with open(FRANCHISES) as fh:
            membership = json.load(fh)

    def others(name, group):
        """Films in this series that aren't in the collection."""
        known = {norm_title(f["title"]) for f in group}
        rest = []
        for member in membership.get(name, {}).get("films", []):
            if member["watched"] or norm_title(member["title"]) in known:
                continue
            rest.append(
                {"title": member["title"], "year": member["year"], "director": member["director"]}
            )
        rest.sort(key=lambda f: (f["year"] is None, f["year"] or 0, f["title"]))
        return rest

    franchises = [
        {
            "name": name,
            "films": sorted((entry(f) for f in group), key=sort_key),
            "others": others(name, group),
        }
        for name, group in by_series.items()
    ]
    franchises.sort(key=lambda f: (-len(f["films"]), -len(f["others"]), f["name"]))

    # Group by director: films watched, plus the rest of their work.
    watched_by_director = {}
    for film in films:
        for name in film["directors"]:
            watched_by_director.setdefault(name, []).append(film)

    filmographies = {}
    if os.path.exists(DIRECTORS):
        with open(DIRECTORS) as fh:
            filmographies = json.load(fh)

    portraits = {}
    if os.path.exists(DIRECTOR_PHOTOS):
        with open(DIRECTOR_PHOTOS) as fh:
            portraits = json.load(fh)

    directors = []
    # Films credited to a director that aren't in the list. Keyed by Wikidata id
    # so one film credited to two directors is one page, not two.
    other_index = {}
    for name, group in watched_by_director.items():
        known = {norm_title(f["title"]) for f in group}
        others = []
        for m in filmographies.get(name, {}).get("films", []):
            if m["watched"] or norm_title(m["title"]) in known:
                continue
            key = m.get("qid") or f"{norm_title(m['title'])}|{m['year'] or ''}"
            record = other_index.setdefault(
                key,
                {"title": m["title"], "year": m["year"], "qid": m.get("qid"), "by": []},
            )
            if name not in record["by"]:
                record["by"].append(name)
            others.append({"title": m["title"], "year": m["year"], "key": key})
        others.sort(key=lambda f: (f["year"] is None, f["year"] or 0, f["title"]))
        shot = portraits.get(name) or {}
        directors.append(
            {
                "name": name,
                "slug": film_slug(name),
                "films": sorted((entry(f) for f in group), key=sort_key),
                "others": others,
                # None until director_photos.py has run. The licence and author
                # travel with it because these are CC-licensed and the credit
                # has to be shown.
                "photo": shot.get("photo"),
                "photoCredit": (
                    {"licence": shot.get("licence"), "author": shot.get("author")}
                    if shot.get("photo")
                    else None
                ),
            }
        )
    directors.sort(key=lambda d: (-len(d["films"]), d["name"]))

    # Each of these gets its own page at /other/<slug>. They are deliberately
    # kept out of `films`, so nothing here lands in the list as unrated — the
    # only way in is the Add button, which stays a deliberate click.
    other_films = []
    seen_other = {}
    for record in other_index.values():
        base = film_slug(record["title"], record["year"])
        n = seen_other.get(base, 0) + 1
        seen_other[base] = n
        record["slug"] = base if n == 1 else f"{base}-{n}"
        record["directors"] = [
            {"name": who, "slug": film_slug(who)} for who in record.pop("by")
        ]
        other_films.append(record)
    other_films.sort(key=lambda f: (f["title"].lower(), f["year"] or 0))

    # Point each director's list at the page that was just built for it.
    slug_of = {key: rec["slug"] for key, rec in other_index.items()}
    for director in directors:
        for other in director["others"]:
            other["slug"] = slug_of[other.pop("key")]

    # A page per year: films watched from it, plus that year's biggest earners.
    box_office = {}
    if os.path.exists(BOX_OFFICE):
        with open(BOX_OFFICE) as fh:
            box_office = json.load(fh)

    watched_by_year = {}
    for film in films:
        if film["year"]:
            watched_by_year.setdefault(film["year"], []).append(film)

    known = {int(y) for y in box_office} | set(watched_by_year)
    first_year = min(known) if known else 1900
    last_year = max(known) if known else 2026
    years = []
    def by_rating(film):
        """Best tier first; unrated last, then alphabetical."""
        tier = film["tier"]
        rank = TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER)
        return (rank, film["title"])

    for year in range(first_year, last_year + 1):
        watched = sorted(watched_by_year.get(year, []), key=by_rating)
        top = box_office.get(str(year), [])
        if not watched and not top:
            continue  # nothing to show; don't advertise an empty page
        seen_titles = {norm_title(f["title"]) for f in watched}
        years.append(
            {
                "year": year,
                "films": [entry(f) for f in watched],
                "top": [
                    {**f, "watched": norm_title(f["title"]) in seen_titles}
                    for f in top
                ],
            }
        )
    years.sort(key=lambda y: -y["year"])

    # Recomputed on every run rather than cached, so a rating changes what the
    # Suggestions page offers as soon as it is saved. Local-only: the candidate
    # pool is what directors.py/franchises.py/box_office.py already wrote.
    suggestions = recommend.build(films)

    # The Music sheet is newer than the rest of the document, so its absence is
    # normal rather than an error — the tab just renders empty.
    music = []
    for row in sheets.get("Music", [])[1:]:
        cols = (list(map(clean, row)) + [None] * 8)[:8]
        song, year, tier, country, note, artist, album, genre = cols
        if not song:
            continue
        music.append(
            {
                "song": str(song),
                "year": year if isinstance(year, int) else None,
                "tier": str(tier) if tier is not None else "?",
                "country": str(country) if country else None,
                "note": str(note) if note else None,
                "artist": str(artist) if artist else None,
                # A track can be credited to several artists; each is filterable.
                "artists": [a.strip() for a in str(artist).split(",") if a.strip()]
                if artist
                else [],
                "album": str(album) if album else None,
                # The album's genres, not the single's.
                "genres": [g.strip() for g in str(genre).split(",") if g.strip()] if genre else [],
                "slug": film_slug(song, year if isinstance(year, int) else None),
            }
        )

    seen_songs = {}
    for song in music:
        base = song["slug"]
        n = seen_songs.get(base, 0) + 1
        seen_songs[base] = n
        if n > 1:
            song["slug"] = f"{base}-{n}"

    def by_count(pick):
        """Facet values, most-used first, so a filter leads with what's useful."""
        tally = Counter(v for entry in music for v in pick(entry))
        return [v for v, _ in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))]

    data = {
        "years": years,
        "suggestions": suggestions,
        "serviceLogos": service_logos,
        "films": films,
        "directors": directors,
        "characters": characters,
        "shows": shows,
        "franchises": franchises,
        "music": music,
        # Facets for the Music tab's filters, each most-used first.
        "musicArtists": by_count(lambda s: s["artists"]),
        "musicAlbums": by_count(lambda s: [s["album"]] if s["album"] else []),
        "musicCountries": by_count(lambda s: [s["country"]] if s["country"] else []),
        "musicGenres": by_count(lambda s: s["genres"]),
        "franchiseFilmCount": sum(1 for f in films if f["franchises"]),
        "tierOrder": TIER_ORDER,
        "regions": sorted({f["region"] for f in films}),
        # Most-used genres first, so the filter leads with the useful ones.
        "genres": [
            g
            for g, _ in sorted(
                Counter(g for f in films for g in f["genres"]).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ],
    }

    with open(DST, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    with open(OTHER_FILMS, "w") as fh:
        json.dump(other_films, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(
        f"wrote {DST}: {len(films)} films, {len(characters)} characters, "
        f"{len(shows)} shows, {len(franchises)} franchises, {len(directors)} directors, "
        f"{len(other_films)} other films, "
        f"{sum(1 for d in directors if d['photo'])} director photos, "
        f"{len(years)} years, {len(music)} songs"
    )


if __name__ == "__main__":
    main()
