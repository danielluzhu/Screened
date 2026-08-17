#!/usr/bin/env python3
"""Record which streaming services carry each film and show.

    python3 scripts/streaming.py            # dry run
    python3 scripts/streaming.py --apply    # write streaming.json

Wikidata stores a per-service identifier when a title has a page on that
service (Netflix ID, Crunchyroll series ID, and so on). That is the best signal
available without a paid API, but read it for what it is:

  * it means the title exists on that service, not that it is streaming in your
    country today — rights move constantly and Wikidata lags them;
  * absence is weak evidence: plenty of titles are on a service with nobody
    having added the id.

Each entry keeps the id so the page can link straight to the title where the
service has a predictable URL.

For accurate, region-aware availability you want JustWatch data, which needs a
TMDB API key — see the Readme.
"""
import json
import os
import sys

import autofill
import numbers_io as io
import shows as shows_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "streaming.json")

# Verified property ids — P11460 is Plex, not Crunchyroll, despite the guess
# that a "Crunchyroll ID" would sit near the other streaming properties.
SERVICES = [
    ("Netflix", "P1874", "https://www.netflix.com/title/{}"),
    ("Crunchyroll", "P11330", "https://www.crunchyroll.com/series/{}"),
    ("Prime Video", "P8055", "https://www.amazon.com/dp/{}"),
    ("Disney+", "P7595", "https://www.disneyplus.com/movies/_/{}"),
    ("Disney+", "P7596", "https://www.disneyplus.com/series/_/{}"),
    ("Hulu", "P6466", "https://www.hulu.com/movie/{}"),
    ("Hulu", "P6467", "https://www.hulu.com/series/{}"),
    ("HBO Max", "P8298", "https://play.max.com/video/watch/{}"),
    ("Paramount+", "P13147", "https://www.paramountplus.com/video/{}"),
    ("Apple TV", "P9586", "https://tv.apple.com/movie/{}"),
    ("Plex", "P11460", "https://watch.plex.tv/movie/{}"),
]


def claims_for(qid):
    data = autofill.api({"action": "wbgetentities", "ids": qid, "props": "claims"})
    if not data:
        return {}
    return data.get("entities", {}).get(qid, {}).get("claims", {})


def services_for(qid):
    """[{name, id, url}] for every service that lists this title."""
    claims = claims_for(qid)
    out, seen = [], set()
    for name, prop, template in SERVICES:
        for entry in claims.get(prop, []):
            value = entry.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not isinstance(value, str) or name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "id": value, "url": template.format(value)})
    return out


def main():
    apply = "--apply" in sys.argv
    autofill.load_cache()

    doc = io.open_doc()
    table = io.films_table(doc)
    films = [r for r in table.rows(values_only=True)[1:] if r[io.COL_TITLE]]

    out = {"films": {}, "shows": {}}

    for n, row in enumerate(films, 1):
        title = str(row[io.COL_TITLE]).strip()
        year = io.year_of(row[io.COL_YEAR])
        if n % 25 == 0:
            print(f"  {n}/{len(films)}…", flush=True)
            autofill.save_cache()
        try:
            pick = autofill.pick(autofill.candidates_for(title), year, title)
        except autofill.ApiUnavailable:
            continue
        if not pick:
            continue
        found = services_for(pick["qid"])
        if found:
            out["films"][io.film_key(title, year)] = found
            print(f"  {title[:34]:34} {', '.join(s['name'] for s in found)}", flush=True)

    autofill.save_cache()

    show_table = shows_mod.shows_table(doc)
    for row in show_table.rows(values_only=True)[1:]:
        if not row or not row[0]:
            continue
        name = str(row[0]).strip()
        qid, _ent = shows_mod.series_entity(name)
        if not qid:
            continue
        found = services_for(qid)
        if found:
            out["shows"][name] = found
            print(f"  [show] {name[:28]:28} {', '.join(s['name'] for s in found)}", flush=True)

    autofill.save_cache()
    films_with = len(out["films"])
    shows_with = len(out["shows"])
    print(f"\n{films_with} films and {shows_with} shows have a listed service")

    if not apply:
        print("dry run; nothing written")
        return
    with open(DST, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print(f"wrote {DST}")


if __name__ == "__main__":
    main()
