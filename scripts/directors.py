#!/usr/bin/env python3
"""Fetch each director's full filmography from Wikidata.

    python3 scripts/directors.py

The Director column records who made each watched film; this walks the other
way, asking Wikidata for everything those people directed, so a director's page
can list the rest of their work below the films already rated.

Writes directors.json; extract.py folds it into data.json. Reuses autofill's
cache, so films already looked up cost nothing.
"""
import json
import os
import sys

import autofill
import numbers_io as io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "directors.json")


def filmography(qid):
    """Every item stating this person directed it."""
    data = autofill.api(
        {
            "action": "query",
            "list": "search",
            "srsearch": f"haswbstatement:P57={qid}",
            "srlimit": 200,
            "srnamespace": 0,
        }
    )
    if data is None:
        raise autofill.ApiUnavailable(qid)
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def main():
    autofill.load_cache()

    table = io.films_table(io.open_doc())
    rows = table.rows(values_only=True)
    films = [r for r in rows[1:] if r[io.COL_TITLE]]

    # Map each watched film to its Wikidata id, and collect director ids.
    watched_qids, director_qids = set(), {}
    for row in films:
        title = str(row[io.COL_TITLE]).strip()
        year = io.year_of(row[io.COL_YEAR])
        try:
            pick = autofill.pick(autofill.candidates_for(title), year, title)
        except autofill.ApiUnavailable:
            continue
        if not pick:
            continue
        watched_qids.add(pick["qid"])
        for qid in pick.get("directors", []):
            director_qids.setdefault(qid, set()).add(pick["qid"])
    autofill.save_cache()

    names = autofill.labels(sorted(director_qids))
    autofill.save_cache()
    print(f"{len(director_qids)} directors to expand", flush=True)

    out = {}
    for n, (qid, name) in enumerate(sorted(names.items(), key=lambda kv: kv[1]), 1):
        try:
            film_qids = filmography(qid)
        except autofill.ApiUnavailable:
            print(f"  ! {name}: lookup failed, skipping", file=sys.stderr)
            continue
        try:
            ents = autofill.entities(film_qids)
        except autofill.ApiUnavailable:
            print(f"  ! {name}: entity lookup failed, skipping", file=sys.stderr)
            continue
        autofill.save_cache()

        entries = []
        for film_qid in film_qids:
            ent = ents.get(film_qid) or {}
            # A person's items include awards and articles about them, not only films.
            if not set(ent.get("types", [])) & autofill.FILM_TYPES:
                continue
            years = {autofill.year_of(d) for d in ent.get("dates", [])}
            years.discard(None)
            entries.append(
                {
                    "qid": film_qid,
                    "title": ent.get("label") or film_qid,
                    "year": min(years) if years else None,
                    "watched": film_qid in watched_qids,
                }
            )
        entries.sort(key=lambda e: (e["year"] is None, e["year"] or 0, e["title"]))
        out[name] = {"qid": qid, "films": entries}
        unwatched = sum(1 for e in entries if not e["watched"])
        print(f"  {n}/{len(names)}  {name}: {len(entries)} films, {unwatched} unwatched", flush=True)

    autofill.save_cache()
    with open(DST, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print(f"\nwrote {DST}: {len(out)} directors")


if __name__ == "__main__":
    main()
