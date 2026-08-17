#!/usr/bin/env python3
"""Fill in release year, director, and franchise for each film from Wikidata.

    python3 scripts/autofill.py [--dry-run]

Uses the Wikidata Action API rather than the SPARQL endpoint, which rate-limits
to 1 request/minute during WDQS outages.

Matching is deliberately conservative: a film is only filled in when exactly one
candidate matches the title, or when one candidate's release year matches the
year already recorded. Anything ambiguous is left blank and listed at the end.
Results are cached in scripts/.wikidata-cache.json so reruns are cheap.
"""
import os
import re
import sys
import time

import genres as G
import numbers_io as io
import wikidata as wd

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".wikidata-cache.json")

# instance-of values that count as a film
FILM_TYPES = {
    "Q11424",     # film
    "Q202866",    # animated film
    "Q24862",     # short film
    "Q29168811",  # animated feature film
    "Q506240",    # television film
    "Q20650540",  # anime film
    "Q1054574",   # romantic comedy film
    "Q226730",    # silent film
    "Q842256",    # documentary film
    "Q17517379",  # anime feature film
    "Q130232",    # drama film
    "Q157443",    # comedy film
    "Q1361932",   # comedy-drama
    "Q188473",    # action film
    "Q471839",    # science fiction film
    "Q200092",    # horror film
    "Q959790",    # crime film
    "Q319221",    # adventure film
    "Q52207310",  # animated feature
    "Q93204",     # documentary
}

HEADERS = {io.COL_NOTES: "Notes", io.COL_DIRECTOR: "Director"}
COL_FRANCHISE = io.COL_FRANCHISE
COL_GENRE = io.COL_GENRE
COL_NATIVE = io.COL_NATIVE
HEADERS[COL_FRANCHISE] = "Franchise"
HEADERS[COL_GENRE] = "Genre"
HEADERS[COL_NATIVE] = "Original title"
HEADERS[io.COL_CRITIQUE] = "Critique"
LAST_COL = io.COL_CRITIQUE

# Wikidata genres are verbose and repetitive ("thriller film", "drama film").
# Trim the boilerplate and keep the list short enough to read on a card.
GENRE_NOISE = re.compile(r"\s*\b(film|movie|cinema)\b\s*$", re.IGNORECASE)
MAX_GENRES = 8  # effectively "all of them"; a handful of films list many


# Films whose original language is English don't need a second title.
ENGLISH = {"Q1860", "Q7976"}


def native_title(cand):
    """The film's title in its own language, when that isn't English."""
    if set(cand.get("languages", [])) & ENGLISH:
        return None
    entries = cand.get("titles") or []
    for entry in entries:
        lang = (entry.get("lang") or "").lower()
        if lang.startswith("en"):
            continue
        text = (entry.get("text") or "").strip()
        if text:
            return text
    return None


def tidy_genre(name):
    """Wikidata label -> the canonical genres it folds into (possibly none).

    Wikidata's vocabulary is granular enough to produce a distinct label per
    film; folding here is what keeps the Genre column at 30 values.
    """
    name = GENRE_NOISE.sub("", name).strip()
    return G.canonical(name[:1].upper() + name[1:]) if name else []

_cache = {}


# The transport (rate limiting, retries, cache files) is shared with
# music_autofill.py; the caches stay separate because the two store different
# claim sets under the same QID keys.
#
# API and UA are re-exported because posters.py, character_photos.py and
# box_office.py call Wikipedia and Fandom directly and take their User-Agent
# from here.
ApiUnavailable = wd.ApiUnavailable
api = wd.api
API = wd.API
UA = wd.UA


def load_cache():
    global _cache
    _cache = wd.load_cache(CACHE)


def save_cache():
    wd.save_cache(CACHE, _cache)


def search(title):
    """Candidate QIDs for a title, from label and alias search."""
    key = "search:" + title.lower()
    if key in _cache:
        return _cache[key]
    resp = api(
        {
            "action": "wbsearchentities",
            "search": title,
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": 20,
        }
    )
    if resp is None:
        raise ApiUnavailable(title)
    ids = []
    for hit in resp.get("search", []):
        if hit["id"] not in ids:
            ids.append(hit["id"])
    _cache[key] = ids
    return ids


def entities(qids):
    """Fetch claims+labels for QIDs, 50 at a time, cached."""
    want = [q for q in qids if "ent:" + q not in _cache]
    for i in range(0, len(want), 50):
        chunk = want[i : i + 50]
        resp = api(
            {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "claims|labels",
                "languages": "en",
            }
        )
        if resp is None:
            raise ApiUnavailable(",".join(chunk[:3]))
        data = resp.get("entities", {})
        for qid in chunk:
            ent = data.get(qid, {})
            claims = ent.get("claims", {})

            def values(prop):
                out = []
                for c in claims.get(prop, []):
                    val = c.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if isinstance(val, dict) and "id" in val:
                        out.append(val["id"])
                    elif isinstance(val, dict) and "time" in val:
                        out.append(val["time"])
                return out

            def monolingual(prop):
                """P1476 title values carry their own language tag."""
                out = []
                for c in claims.get(prop, []):
                    val = c.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if isinstance(val, dict) and "text" in val:
                        out.append({"lang": val.get("language"), "text": val["text"]})
                return out

            # P179 is "part of the series"; many films instead carry P8345
            # "media franchise" (the Apes reboots, for one), so take both.
            _cache["ent:" + qid] = {
                "label": ent.get("labels", {}).get("en", {}).get("value"),
                "types": values("P31"),
                "directors": values("P57"),
                "series": list(dict.fromkeys(values("P179") + values("P8345"))),
                "genres": values("P136"),
                "countries": values("P495"),
                "languages": values("P364"),
                "titles": monolingual("P1476"),
                "dates": values("P577"),
            }
        time.sleep(0.2)
    return {q: _cache.get("ent:" + q, {}) for q in qids}


def labels(qids):
    """Resolve QIDs to English labels."""
    missing = [q for q in qids if "label:" + q not in _cache]
    for i in range(0, len(missing), 50):
        chunk = missing[i : i + 50]
        resp = api(
            {"action": "wbgetentities", "ids": "|".join(chunk), "props": "labels", "languages": "en"}
        )
        if resp is None:
            raise ApiUnavailable(",".join(chunk[:3]))
        data = resp.get("entities", {})
        for qid in chunk:
            _cache["label:" + qid] = (
                data.get(qid, {}).get("labels", {}).get("en", {}).get("value") or qid
            )
        time.sleep(0.2)
    return {q: _cache.get("label:" + q, q) for q in qids}


def year_of(stamp):
    # Wikidata times look like "+2019-05-21T00:00:00Z"
    try:
        return int(str(stamp)[1:5])
    except (ValueError, IndexError):
        return None


def candidates_for(title):
    ents = entities(search(title))
    out = []
    for qid, ent in ents.items():
        if not ent or not set(ent.get("types", [])) & FILM_TYPES:
            continue
        years = {y for y in (year_of(d) for d in ent.get("dates", [])) if y}
        out.append(
            {
                "qid": qid,
                "label": ent.get("label"),
                "directors": ent.get("directors", []),
                "series": ent.get("series", []),
                "genres": ent.get("genres", []),
                "countries": ent.get("countries", []),
                "languages": ent.get("languages", []),
                "titles": ent.get("titles", []),
                "years": years,
            }
        )
    return out


def pick(cands, year, title):
    if not cands:
        return None
    # Prefer an exact label match when the search returned near-misses.
    exact = [c for c in cands if (c["label"] or "").strip().lower() == title.strip().lower()]
    pool = exact or cands
    if year is not None:
        near = [c for c in pool if any(abs(y - year) <= 1 for y in c["years"])]
        if len(near) == 1:
            return near[0]
        if len(near) > 1:
            return None
        # Nothing matches the recorded year. A lone candidate used to be
        # accepted anyway, which matched Uprising (2024) to Uprising (2001).
        # Only accept one that has no release year to contradict the sheet.
        if len(pool) == 1 and not pool[0]["years"]:
            return pool[0]
        return None
    return pool[0] if len(pool) == 1 else None


def main():
    dry = "--dry-run" in sys.argv
    load_cache()

    # Network lookups happen against a throwaway read so the write lock is only
    # held for the final save, not the many minutes of API calls.
    doc = io.open_doc()
    table = io.films_table(doc)

    # add_column's first argument is a COUNT, not a column index.
    if table.num_cols <= LAST_COL:
        table.add_column(LAST_COL + 1 - table.num_cols)
    for col, name in HEADERS.items():
        if not table.cell(0, col).value:
            table.write(0, col, name)

    rows = table.rows(values_only=True)
    films = [(i, r) for i, r in enumerate(rows) if i > 0 and r[io.COL_TITLE]]
    print(f"{len(films)} films", flush=True)

    resolved, unmatched, ambiguous, failed = {}, [], [], []
    for n, (i, row) in enumerate(films, 1):
        title = str(row[io.COL_TITLE]).strip()
        year = row[io.COL_YEAR]
        year = int(year) if isinstance(year, float) and year.is_integer() else (year if isinstance(year, int) else None)
        if n % 20 == 0:
            print(f"  {n}/{len(films)}…", flush=True)
            save_cache()

        try:
            cands = candidates_for(title)
        except ApiUnavailable:
            # Lookup never completed — not the same as "Wikidata has nothing".
            failed.append(title)
            continue
        if not cands:
            unmatched.append(title)
            continue
        cand = pick(cands, year, title)
        if cand is None:
            ambiguous.append(f"{title} ({year or '?'}) — {len(cands)} candidates")
            continue
        # Keyed by (title, year), not row index: rows can be added or removed
        # while the lookups run, and same-title films are different films.
        resolved[(title, year)] = cand
    save_cache()

    # Resolve director/series QIDs to names in bulk.
    refs = {
        q
        for c in resolved.values()
        for q in c["directors"] + c["series"] + c.get("genres", []) + c.get("countries", [])
    }
    try:
        names = labels(sorted(refs))
    except ApiUnavailable:
        save_cache()
        sys.exit("label lookup failed; rerun to resume from cache")
    save_cache()

    def apply(table, rows):
        """Write resolved values; returns per-field counts."""
        years = directors = series = genres = countries = natives = 0
        for (title, year), cand in resolved.items():
            i = io.find_row(table, title, year)
            if i is None:
                continue  # removed while we were looking things up
            row = rows[i]
            if row[io.COL_YEAR] is None and cand["years"]:
                table.write(i, io.COL_YEAR, min(cand["years"]))
                years += 1
            if cand["directors"] and not row[io.COL_DIRECTOR]:
                table.write(i, io.COL_DIRECTOR, ", ".join(names[q] for q in cand["directors"]))
                directors += 1
            if cand["series"]:
                table.write(i, COL_FRANCHISE, ", ".join(names[q] for q in cand["series"]))
                series += 1
            tidy = []
            for q in cand.get("genres", []):
                for name in tidy_genre(names.get(q, "")):
                    if name not in tidy:
                        tidy.append(name)
            if tidy:
                tidy.sort(key=G.sort_key)
                table.write(i, COL_GENRE, ", ".join(tidy[:MAX_GENRES]))
                genres += 1

            # Main country of origin: Wikidata lists co-productions, and the
            # first claim is the primary one.
            if cand.get("countries") and not row[io.COL_COUNTRY]:
                table.write(i, io.COL_COUNTRY, names.get(cand["countries"][0], ""))
                countries += 1

            # Original-language title, for films not made in English.
            native = native_title(cand)
            if native and not row[COL_NATIVE]:
                table.write(i, COL_NATIVE, native)
                natives += 1
        return years, directors, series, genres, countries, natives

    filled_year, filled_dir, filled_series, filled_genre, filled_country, filled_native = apply(table, rows)

    print(f"\nmatched {len(resolved)} of {len(films)}")
    print(
        f"filled: {filled_year} years, {filled_dir} directors, {filled_series} franchises, "
        f"{filled_genre} genres, {filled_country} countries, {filled_native} original titles"
    )
    print(f"\nno match ({len(unmatched)}):")
    for t in unmatched:
        print("  -", t)
    print(f"\nambiguous, left blank ({len(ambiguous)}):")
    for t in ambiguous:
        print("  -", t)
    if failed:
        print(f"\nlookup failed, rerun to retry ({len(failed)}):")
        for t in failed:
            print("  -", t)

    if dry:
        print("\ndry run; nothing written")
        return

    # Re-read under the lock and reapply, so any rating edits made while the
    # lookups were running are preserved.
    with io.editing() as (fresh_doc, fresh_table):
        if fresh_table.num_cols <= LAST_COL:
            fresh_table.add_column(LAST_COL + 1 - fresh_table.num_cols)
        for col, name in HEADERS.items():
            if not fresh_table.cell(0, col).value:
                fresh_table.write(0, col, name)
        apply(fresh_table, fresh_table.rows(values_only=True))
    print("\nsaved")


if __name__ == "__main__":
    main()
