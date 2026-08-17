#!/usr/bin/env python3
"""Fill in the Shows sheet from Wikidata, and fetch a poster for each show.

    python3 scripts/shows.py            # dry run: report what it would write
    python3 scripts/shows.py --apply    # write it

Fills: full series name, original-language title, years on air, number of
seasons, original author, and country of origin.

Matching requires the item to be a television/anime series — searching "Death
Note" otherwise lands on the manga, which has different dates and no seasons.
For adaptations the author comes from the source work (P144 -> P50), so Bleach
credits Tite Kubo rather than the studio.

Posters come from the show's Fandom wiki, falling back to Wikipedia.
"""
import json
import os
import sys
import urllib.parse

import autofill
import character_photos as chars
import numbers_io as io
import posters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "shows")
INDEX = os.path.join(ROOT, "show-photos.json")

COL_NAME, COL_NATIVE, COL_YEARS, COL_SEASONS, COL_AUTHOR, COL_COUNTRY = range(6)
HEADERS = {
    COL_NAME: "Show",
    COL_NATIVE: "Original title",
    COL_YEARS: "Years",
    COL_SEASONS: "Seasons",
    COL_AUTHOR: "Author",
    COL_COUNTRY: "Country",
}

# Items that count as a series. Without this, "Death Note" resolves to the manga.
SERIES_TYPES = {
    "Q5398426",    # television series
    "Q63952888",   # anime television series
    "Q581714",     # animated series
    "Q117467246",  # anime television series (newer id)
    "Q1259759",    # miniseries
    "Q15416",      # television programme
    "Q21191270",   # television series season
    "Q3464665",    # television series (general)
}


def shows_table(doc):
    for sheet in doc.sheets:
        if sheet.name == "Shows":
            return sheet.tables[0]
    raise KeyError("no Shows sheet")


def series_entity(name):
    """Wikidata id + claims for the series called `name`, or None."""
    ids = autofill.search(name)
    if not ids:
        return None, None
    ents = autofill.entities(ids)
    candidates = [
        (qid, ent)
        for qid, ent in ents.items()
        if ent and set(ent.get("types", [])) & SERIES_TYPES
    ]
    if not candidates:
        return None, None
    exact = [
        (qid, ent)
        for qid, ent in candidates
        if (ent.get("label") or "").strip().lower() == name.strip().lower()
    ]
    return (exact or candidates)[0]


def raw_claims(qid):
    """Claims we don't cache: seasons, dates, author, source work."""
    data = autofill.api(
        {"action": "wbgetentities", "ids": qid, "props": "claims", "languages": "en"}
    )
    if not data:
        return {}
    return data.get("entities", {}).get(qid, {}).get("claims", {})


def values(claims, prop):
    out = []
    for entry in claims.get(prop, []):
        val = entry.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(val, dict) and "id" in val:
            out.append(val["id"])
        elif isinstance(val, dict) and "time" in val:
            out.append(val["time"])
        elif isinstance(val, dict) and "text" in val:
            out.append(val)
        elif val is not None:
            out.append(val)
    return out


def author_of(claims):
    """Original creator. For adaptations that's the author of the source work."""
    direct = values(claims, "P50")
    if direct:
        return direct
    for source in values(claims, "P144"):
        source_claims = raw_claims(source)
        found = values(source_claims, "P50") or values(source_claims, "P170")
        if found:
            return found
    return values(claims, "P170") or values(claims, "P58")


def photo_for(name):
    """Series artwork, from the show's own wiki where there is one."""
    host = chars.WIKIS.get(name.lower())
    if host:
        page = chars.api(host, {"action": "query", "titles": name, "redirects": 1})
        title = None
        if page:
            for pid, entry in page.get("query", {}).get("pages", {}).items():
                if pid != "-1" and "missing" not in entry:
                    title = entry["title"]
        # "Naruto" redirects to the character Naruto Uzumaki on that wiki; a
        # character portrait is the wrong image for a series card.
        if title and not chars.is_character_page(host, title):
            url = chars.wiki_image(host, title)
            if url:
                return url, f"{host}: {title}"

    for article in posters.search_articles(f"{name} television series", None, limit=5):
        if not posters.title_matches(name, article):
            continue
        url = posters.thumbnails([article]).get(article)
        if url:
            return url, f"wikipedia: {article}"
    return None, None


def main():
    apply = "--apply" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    autofill.load_cache()
    os.makedirs(OUT, exist_ok=True)

    table = shows_table(io.open_doc())
    names = [str(r[0]).strip() for r in table.rows(values_only=True)[1:] if r and r[0]]
    if only:
        names = [n for n in names if n.lower() == only.lower()]
    print(f"{len(names)} shows", flush=True)

    index = {}
    if os.path.exists(INDEX):
        with open(INDEX) as fh:
            index = json.load(fh)

    found = {}
    for name in names:
        qid, ent = series_entity(name)
        if not qid:
            print(f"  {name:18} -> no series match", flush=True)
            continue
        claims = raw_claims(qid)

        start = [autofill.year_of(t) for t in values(claims, "P580")] or [
            autofill.year_of(t) for t in values(claims, "P571")
        ]
        end = [autofill.year_of(t) for t in values(claims, "P582")]
        start = min([y for y in start if y], default=None)
        end = min([y for y in end if y], default=None)
        if start and end and end != start:
            years = f"{start}–{end}"
        elif start:
            years = str(start)
        else:
            years = None

        seasons = values(claims, "P2437")
        seasons = str(int(float(seasons[0]["amount"].lstrip("+")))) if seasons and isinstance(seasons[0], dict) and "amount" in seasons[0] else None

        author_ids = author_of(claims)
        country_ids = values(claims, "P495")
        labels = autofill.labels(sorted({*author_ids, *country_ids})) if (author_ids or country_ids) else {}

        native = None
        for entry in values(claims, "P1476"):
            if isinstance(entry, dict) and not (entry.get("language") or "").startswith("en"):
                native = entry.get("text")
                break

        found[name] = {
            "qid": qid,
            "label": ent.get("label") or name,
            "native": native,
            "years": years,
            "seasons": seasons,
            "author": ", ".join(labels[a] for a in author_ids if a in labels) or None,
            "country": labels.get(country_ids[0]) if country_ids else None,
        }
        autofill.save_cache()
        info = found[name]
        print(
            f"  {name:18} -> {info['label']} | {info['years'] or '?'} | "
            f"{info['seasons'] or '?'} seasons | {info['author'] or '?'} | {info['country'] or '?'}"
            f" | {info['native'] or ''}",
            flush=True,
        )

        if name not in index or "--force" in sys.argv:
            url, source = photo_for(name)
            if url:
                path = urllib.parse.urlparse(url).path
                ext = next((e for e in (".png", ".jpg", ".jpeg", ".gif", ".webp") if e in path.lower()), ".jpg")
                filename = io.slug(name) + ext
                try:
                    if posters.download(url, os.path.join(OUT, filename)):
                        real = chars.sniff(os.path.join(OUT, filename))
                        if real and real != ext:
                            os.replace(os.path.join(OUT, filename), os.path.join(OUT, io.slug(name) + real))
                            filename = io.slug(name) + real
                        index[name] = filename
                        print(f"      photo: {source} [{filename}]", flush=True)
                except Exception as err:  # noqa: BLE001
                    print(f"      ! photo: {err}", file=sys.stderr)
            else:
                print("      photo: none found", flush=True)

    def save_index():
        with open(INDEX, "w") as fh:
            json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")

    save_index()
    autofill.save_cache()

    if not apply:
        print("\ndry run; nothing written to the sheet")
        return

    import extract

    with io.editing() as (doc, _films):
        tbl = shows_table(doc)
        if tbl.num_cols <= COL_COUNTRY:
            tbl.add_column(COL_COUNTRY + 1 - tbl.num_cols)
        for col, header in HEADERS.items():
            if not tbl.cell(0, col).value:
                tbl.write(0, col, header)
        for i, values_row in enumerate(tbl.rows(values_only=True)):
            if i == 0 or not values_row[COL_NAME]:
                continue
            info = found.get(str(values_row[COL_NAME]).strip())
            if not info:
                continue
            # Renaming the show would orphan its photo key.
            if info["label"] != str(values_row[COL_NAME]).strip():
                old = str(values_row[COL_NAME]).strip()
                if old in index:
                    index[info["label"]] = index.pop(old)
            tbl.write(i, COL_NAME, info["label"])
            for col, key in (
                (COL_NATIVE, "native"),
                (COL_YEARS, "years"),
                (COL_SEASONS, "seasons"),
                (COL_AUTHOR, "author"),
                (COL_COUNTRY, "country"),
            ):
                if info[key]:
                    tbl.write(i, col, info[key])

    save_index()
    extract.main()
    print(f"\nupdated {len(found)} shows")


if __name__ == "__main__":
    main()
