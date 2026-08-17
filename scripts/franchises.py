#!/usr/bin/env python3
"""Fetch the full membership of every franchise the collection touches.

    python3 scripts/franchises.py

The Franchise column records which series each watched film belongs to. This
walks the other way: for each of those series, ask Wikidata for every film in it,
so the site can show which entries are still unwatched.

Writes franchises.json; extract.py folds it into data.json. Reuses autofill's
cache, so films already looked up cost nothing.
"""
import json
import os
import re
import sys

import autofill
import numbers_io as io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "franchises.json")

# Same exclusions extract.py uses: studio catalogues and critics' lists are not
# franchises, and pulling their full membership would be meaningless.
NOT_A_FRANCHISE = re.compile(
    r"^list of|feature films?$|greatest films|\bfilms of\b|\bfilmography\b", re.IGNORECASE
)


def members(series_qid):
    """Every item stating it is part of this series, via either property."""
    found = []
    for prop in ("P179", "P8345"):
        data = autofill.api(
            {
                "action": "query",
                "list": "search",
                "srsearch": f"haswbstatement:{prop}={series_qid}",
                "srlimit": 100,
                "srnamespace": 0,
            }
        )
        if data is None:
            raise autofill.ApiUnavailable(series_qid)
        for hit in data.get("query", {}).get("search", []):
            if hit["title"] not in found:
                found.append(hit["title"])
    return found


def main():
    autofill.load_cache()

    table = io.films_table(io.open_doc())
    rows = table.rows(values_only=True)
    films = [r for r in rows[1:] if r[io.COL_TITLE]]

    # Resolve watched films to QIDs, and collect the series they belong to.
    watched_qids, series_of = set(), {}
    for row in films:
        title = str(row[io.COL_TITLE]).strip()
        year = row[io.COL_YEAR]
        year = int(year) if isinstance(year, float) and year.is_integer() else (year if isinstance(year, int) else None)
        try:
            pick = autofill.pick(autofill.candidates_for(title), year, title)
        except autofill.ApiUnavailable:
            continue
        if not pick:
            continue
        watched_qids.add(pick["qid"])
        for series_qid in pick["series"]:
            series_of.setdefault(series_qid, set()).add(pick["qid"])
    autofill.save_cache()

    names = autofill.labels(sorted(series_of))
    autofill.save_cache()
    wanted = {q: n for q, n in names.items() if not NOT_A_FRANCHISE.search(n)}
    print(f"{len(wanted)} franchises to expand", flush=True)

    out = {}
    for n, (series_qid, name) in enumerate(sorted(wanted.items(), key=lambda kv: kv[1]), 1):
        try:
            qids = members(series_qid)
        except autofill.ApiUnavailable:
            print(f"  ! {name}: lookup failed, skipping", file=sys.stderr)
            continue
        ents = autofill.entities(qids)
        autofill.save_cache()

        # Resolve director names for the unwatched entries.
        director_qids = {
            d for q in qids for d in ents.get(q, {}).get("directors", []) if q not in watched_qids
        }
        dir_names = autofill.labels(sorted(director_qids)) if director_qids else {}

        entries = []
        for qid in qids:
            ent = ents.get(qid) or {}
            if not set(ent.get("types", [])) & autofill.FILM_TYPES:
                continue  # video games, novels and soundtracks also cite the series
            years = {autofill.year_of(d) for d in ent.get("dates", [])}
            years.discard(None)
            entries.append(
                {
                    "qid": qid,
                    "title": ent.get("label") or qid,
                    "year": min(years) if years else None,
                    "director": ", ".join(dir_names[d] for d in ent.get("directors", []) if d in dir_names)
                    or None,
                    "watched": qid in watched_qids,
                }
            )
        entries.sort(key=lambda e: (e["year"] is None, e["year"] or 0, e["title"]))
        out[name] = {"qid": series_qid, "films": entries}
        unwatched = sum(1 for e in entries if not e["watched"])
        print(f"  {n}/{len(wanted)}  {name}: {len(entries)} films, {unwatched} unwatched", flush=True)

    autofill.save_cache()
    with open(DST, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    total = sum(len(v["films"]) for v in out.values())
    print(f"\nwrote {DST}: {len(out)} franchises, {total} films")


if __name__ == "__main__":
    main()
