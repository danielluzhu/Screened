#!/usr/bin/env python3
"""Fetch the top-grossing films of each year from Wikidata.

    python3 scripts/box_office.py [--from 1900] [--to 2026] [--limit 30]

Box-office values (P2142) are filtered to US dollars. That filter matters:
without it Weathering with You tops 2019 with "14,190,000,000", a yen figure.

Queries run one per decade, not one per year — the SPARQL endpoint hands out
1000-second rate-limit penalties, so 127 requests would take a day and a half.
Results are written after each decade, so an interrupted run resumes.

Coverage thins going back; Wikidata holds few box-office figures for early
films, so those years show a short list or none.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import autofill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "box-office.json")
ENDPOINT = "https://query.wikidata.org/sparql"

QUERY = """
SELECT DISTINCT ?film ?filmLabel ?year ?box WHERE {
  ?film wdt:P31 wd:Q11424 ; wdt:P577 ?date ; p:P2142 ?st .
  BIND(YEAR(?date) AS ?year)
  FILTER(?year >= %d && ?year <= %d)
  ?st psv:P2142 ?v .
  ?v wikibase:quantityAmount ?box ; wikibase:quantityUnit wd:Q4917 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
ORDER BY DESC(?box)
LIMIT 3000
"""


def query_range(first, last):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"format": "json", "query": QUERY % (first, last)})
    req = urllib.request.Request(
        url, headers={"User-Agent": autofill.UA, "Accept": "application/sparql-results+json"}
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.load(resp)["results"]["bindings"]
        except urllib.error.HTTPError as err:
            if err.code == 429:
                wait = int(err.headers.get("Retry-After") or 0) or 60
                print(f"    rate limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            if err.code in (500, 502, 503, 504):
                print(f"    {err.code}, retrying", flush=True)
                time.sleep(15 * (attempt + 1))
                continue
            print(f"    ! {err}", file=sys.stderr)
            return None
        except Exception as err:  # noqa: BLE001
            if attempt == 5:
                print(f"    ! {err}", file=sys.stderr)
                return None
            time.sleep(10 * (attempt + 1))
    return None


def by_year(rows, limit):
    """{year: [top films]}, best USD figure per film, highest first."""
    best = {}
    for row in rows:
        qid = row["film"]["value"].rsplit("/", 1)[-1]
        title = row["filmLabel"]["value"]
        if title == qid:
            continue  # unlabelled item
        try:
            amount = float(row["box"]["value"])
            year = int(row["year"]["value"])
        except (TypeError, ValueError, KeyError):
            continue
        # A film may carry several release dates and several box-office claims;
        # keep the largest figure and the earliest year.
        keep = best.get(qid)
        best[qid] = {
            "qid": qid,
            "title": title,
            "box": max(amount, keep["box"]) if keep else amount,
            "year": min(year, keep["year"]) if keep else year,
        }

    grouped = {}
    for film in best.values():
        grouped.setdefault(film["year"], []).append(film)
    return {
        year: [
            {"qid": f["qid"], "title": f["title"], "box": int(f["box"])}
            for f in sorted(films, key=lambda f: -f["box"])[:limit]
        ]
        for year, films in grouped.items()
    }


def main():
    def arg(name, default):
        return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default

    start, end, limit = arg("--from", 1900), arg("--to", 2026), arg("--limit", 30)
    force = "--force" in sys.argv

    data = {}
    if os.path.exists(DST):
        with open(DST) as fh:
            data = json.load(fh)

    decades = []
    for first in range(start - start % 10, end + 1, 10):
        lo, hi = max(first, start), min(first + 9, end)
        if lo > end:
            break
        if force or any(str(y) not in data for y in range(lo, hi + 1)):
            decades.append((lo, hi))
    # Newest first. The endpoint is slow enough that ordering decides which
    # years are usable today, and nobody browses 1903 before 2019.
    decades.reverse()
    print(f"{len(decades)} decades to fetch, newest first ({start}–{end})", flush=True)

    for lo, hi in decades:
        rows = query_range(lo, hi)
        if rows is None:
            print(f"  {lo}-{hi}: query failed, skipping", flush=True)
            continue
        grouped = by_year(rows, limit)
        for year in range(lo, hi + 1):
            data[str(year)] = grouped.get(year, [])
        with open(DST, "w") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        filled = sum(1 for y in range(lo, hi + 1) if data[str(y)])
        sample = next((grouped[y][0]["title"] for y in sorted(grouped) if grouped[y]), "—")
        print(f"  {lo}-{hi}: {filled} of {hi - lo + 1} years, e.g. {sample[:38]}", flush=True)
        time.sleep(3)

    total = sum(len(v) for v in data.values())
    print(f"\nwrote {DST}: {len(data)} years, {total} films")


if __name__ == "__main__":
    main()
