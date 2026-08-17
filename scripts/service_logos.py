#!/usr/bin/env python3
"""Download a logo for each streaming service into public/logos/.

    python3 scripts/service_logos.py [--force]

Logos come from each service's Wikidata item (P154), which points at a file on
Commons. Service marks are trademarks; using them to label a link to that
service is ordinary nominative use, the same as any "watch on …" button.

Some Commons files are old revisions of a brand (Crunchyroll's 2006 mark, for
instance). Where the file is unusable the chip falls back to the service name
in its brand colour, which still reads as a service badge rather than a genre.

Writes service-logos.json: service name -> filename.
"""
import json
import os
import sys
import urllib.parse

import autofill
import posters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "logos")
INDEX = os.path.join(ROOT, "service-logos.json")

# The Wikidata item for each service as it appears in streaming.json.
SERVICE_ITEMS = {
    "Netflix": "Q907311",
    "Crunchyroll": "Q1142035",
    "Prime Video": "Q4740856",
    "Disney+": "Q54958752",
    "Hulu": "Q1630304",
    "HBO Max": "Q65359104",
    "Paramount+": "Q27903045",
    "Apple TV": "Q62446736",
    "Plex": "Q7204887",
}


def logo_file(qid):
    data = autofill.api({"action": "wbgetentities", "ids": qid, "props": "claims"})
    if not data:
        return None
    claims = data.get("entities", {}).get(qid, {}).get("claims", {})
    for prop in ("P154", "P8972"):  # logo image, then small logo
        for entry in claims.get(prop, []):
            value = entry.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, str):
                return value
    return None


def main():
    force = "--force" in sys.argv
    autofill.load_cache()
    os.makedirs(OUT, exist_ok=True)

    index = {}
    if os.path.exists(INDEX) and not force:
        with open(INDEX) as fh:
            index = json.load(fh)

    got = missing = 0
    for name, qid in SERVICE_ITEMS.items():
        if index.get(name) and os.path.exists(os.path.join(OUT, index[name])) and not force:
            continue
        filename = logo_file(qid)
        if not filename:
            print(f"  {name:14} no logo on Wikidata")
            missing += 1
            continue
        url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(filename)
        ext = os.path.splitext(filename)[1].lower() or ".svg"
        dest_name = autofill.re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + ext
        try:
            if posters.download(url, os.path.join(OUT, dest_name)):
                index[name] = dest_name
                got += 1
                print(f"  {name:14} {filename}  -> {dest_name}")
            else:
                missing += 1
        except Exception as err:  # noqa: BLE001
            print(f"  ! {name}: {err}", file=sys.stderr)
            missing += 1

    with open(INDEX, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    autofill.save_cache()
    print(f"\ndownloaded {got}, missing {missing}")


if __name__ == "__main__":
    main()
