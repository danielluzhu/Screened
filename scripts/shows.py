#!/usr/bin/env python3
"""Fill in the Shows sheet from Wikidata, and fetch a poster for each show.

    python3 scripts/shows.py            # dry run: report what it would write
    python3 scripts/shows.py --apply    # write it

Fills: full series name, original-language title, years on air, number of
seasons and of episodes, original author, country of origin, genre, and
whether the series is animated or live action.

Matching requires the item to be a television/anime series — searching "Death
Note" otherwise lands on the manga, which has different dates and no seasons.
For adaptations the author comes from the source work (P144 -> P50), so Bleach
credits Tite Kubo rather than the studio.

Wikidata is asked first and Wikipedia's infobox fills in the rest — see
infobox.py, which exists because the gaps are not rare: Bleach has a start
date and no end date, Paranoia Agent no season count, and "Had I Not Seen the
Sun" no Wikidata item at all.

Posters come from the show's Fandom wiki, falling back to Wikipedia.
"""
import json
import os
import re
import sys
import urllib.parse

import autofill
import character_photos as chars
import genres as G
import infobox
import numbers_io as io
import posters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "shows")
INDEX = os.path.join(ROOT, "show-photos.json")

COL_NAME, COL_NATIVE, COL_YEARS, COL_SEASONS, COL_AUTHOR, COL_COUNTRY = range(6)
# Appended after the fact, so rows written before they existed read as blank.
COL_EPISODES, COL_GENRE, COL_FORMAT = 6, 7, 8
HEADERS = {
    COL_NAME: "Show",
    COL_NATIVE: "Original title",
    COL_YEARS: "Years",
    COL_SEASONS: "Seasons",
    COL_AUTHOR: "Author",
    COL_COUNTRY: "Country",
    COL_EPISODES: "Episodes",
    COL_GENRE: "Genre",
    COL_FORMAT: "Format",
}

# Drawn or filmed. Two values, because that is the whole of the distinction
# being drawn — a filter with a long tail of production techniques would be
# worse at the one question it is asked ("is this anime or not?").
ANIMATED, LIVE_ACTION = "Animated", "Live action"

# Instance-of ids that mean the series is drawn. A series whose type is none of
# these is taken as live action rather than left blank: every show here is one
# or the other, and an unset cell reads as "not filled in yet".
ANIMATED_TYPES = {
    "Q63952888",   # anime television series
    "Q117467246",  # anime television series (newer id)
    "Q581714",     # animated series
    "Q11086742",   # animated television series
    "Q202866",     # animated film
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


def quantity(found):
    """A Wikidata quantity claim as a plain whole number string, or None."""
    if found and isinstance(found[0], dict) and "amount" in found[0]:
        return str(int(float(found[0]["amount"].lstrip("+"))))
    return None


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


def genres_of(claims):
    """Canonical genres for a series, folded through the film vocabulary.

    Wikidata labels a series by medium as well as genre ("thriller anime",
    "drama television series"); genres.canonical strips the medium and keeps
    the genre, so a show and a film that share a genre share a filter value.

    An adaptation often carries none of its own, the genre sitting on the
    source work instead — that is where One-Punch Man's Action and Comedy are.
    """
    ids = values(claims, "P136")
    if not ids:
        for source in values(claims, "P144"):
            ids = values(raw_claims(source), "P136")
            if ids:
                break
    if not ids:
        return []
    labels = autofill.labels(sorted(set(ids)))
    return G.canonical_list(labels.get(i, "") for i in ids)


def format_of(entity, claims, found_genres):
    """ANIMATED or LIVE_ACTION, from what the series is an instance of."""
    types = set(entity.get("types", [])) | set(values(claims, "P31"))
    if types & ANIMATED_TYPES:
        return ANIMATED
    if "Anime" in found_genres or "Animation" in found_genres:
        return ANIMATED
    return LIVE_ACTION


def article_for(name):
    """The English Wikipedia article about the series, or None."""
    for article in posters.search_articles(f"{name} television series", None, limit=6):
        if posters.title_matches(name, article):
            return article
    return None


def wiki_details(name):
    """What the article's infobox says, in the same shape as the Wikidata pull.

    Only ever used to fill a field Wikidata left empty — see merge() — so the
    two sources can't fight over a fact they both have.
    """
    article = article_for(name)
    text = infobox.wikitext(article) if article else None
    if not text:
        return {}

    tv = infobox.template(text, "Infobox television")
    # Anime articles split the infobox in two: the title and genre sit in the
    # header, the broadcast run in the video box below it.
    head = infobox.template(text, "Infobox animanga/Header")
    video = infobox.template(text, "Infobox animanga/Video")

    native = infobox.plain(head.get("ja_kanji", ""))
    if not native and tv.get("native_name"):
        # A Chinese-language series nests its titles in {{Infobox Chinese}};
        # the traditional form is the one the sheet carries elsewhere.
        chinese = infobox.template(tv["native_name"], "Infobox Chinese")
        native = infobox.plain(chinese.get("t") or chinese.get("s") or "")
        if not native:
            native = next(iter(infobox.items(tv["native_name"])), None)

    start = infobox.year(tv.get("first_aired") or video.get("first"))
    end = infobox.year(tv.get("last_aired") or video.get("last"))
    labels = infobox.items(tv.get("genre") or head.get("genre") or "")

    return {
        "native": native or None,
        "years": span(start, end),
        "seasons": infobox.count(tv.get("num_seasons")),
        "episodes": infobox.count(tv.get("num_episodes") or video.get("episodes")),
        "country": infobox.plain(tv.get("country", "")) or None,
        "genres": G.canonical_list(labels),
        # The header infobox is only ever used by anime articles, which makes
        # its presence a more reliable tell than any genre label.
        "format": ANIMATED if head else (LIVE_ACTION if tv else None),
        "source": article,
    }


def span(start, end):
    """A run of years as the sheet writes it: "2004", or "2004\u20132012"."""
    if start and end and end != start:
        return f"{start}\u2013{end}"
    return str(start) if start else None


def merge(wikidata, wiki):
    """Wikidata's answer, with Wikipedia filling in whatever it left blank."""
    merged = dict(wikidata)
    for key, value in (wiki or {}).items():
        if key == "source":
            continue
        if not merged.get(key) and value:
            merged[key] = value

    # A start year on its own is not a run. Wikidata has no end date for
    # several of these — Bleach reads as "2004" — and the field isn't blank,
    # so the fill above leaves it that way. Where the article knows when the
    # series finished and the two agree on when it began, take its span.
    span_from_wiki = (wiki or {}).get("years")
    years = str(merged.get("years") or "")
    if span_from_wiki and years and "\u2013" not in years and span_from_wiki.startswith(years):
        merged["years"] = span_from_wiki
    return merged


def series_name(name, article):
    """The article's title, when it is the row's own name better capitalized.

    Only ever the same name — anything else is left alone, since renaming a row
    to a different series would orphan its photo and its characters.
    """
    bare = re.sub(r"\s*\([^)]*\)$", "", article or "").strip()
    return bare if bare.lower() == name.strip().lower() else name


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
            # No Wikidata item — a new or a regional series often has none.
            # The article usually exists regardless, so fall back to it whole
            # rather than leaving the row blank.
            wiki = wiki_details(name)
            if not wiki:
                print(f"  {name:18} -> no series match", flush=True)
                continue
            found[name] = merge(
                {"qid": None, "label": series_name(name, wiki["source"]), "genres": []}, wiki
            )
            print(f"  {name:18} -> wikipedia: {wiki['source']}", flush=True)
            continue
        claims = raw_claims(qid)

        start = [autofill.year_of(t) for t in values(claims, "P580")] or [
            autofill.year_of(t) for t in values(claims, "P571")
        ]
        end = [autofill.year_of(t) for t in values(claims, "P582")]
        start = min([y for y in start if y], default=None)
        # The last of the end dates, not the first: a series with a date per
        # season would otherwise be recorded as finishing after season one.
        end = max([y for y in end if y], default=None)
        years = span(start, end)

        seasons = quantity(values(claims, "P2437"))
        episodes = quantity(values(claims, "P1113"))
        found_genres = genres_of(claims)

        author_ids = author_of(claims)
        country_ids = values(claims, "P495")
        labels = autofill.labels(sorted({*author_ids, *country_ids})) if (author_ids or country_ids) else {}

        native = None
        for entry in values(claims, "P1476"):
            if isinstance(entry, dict) and not (entry.get("language") or "").startswith("en"):
                native = entry.get("text")
                break

        found[name] = merge(
            {
                "qid": qid,
                "label": ent.get("label") or name,
                "native": native,
                "years": years,
                "seasons": seasons,
                "episodes": episodes,
                "author": ", ".join(labels[a] for a in author_ids if a in labels) or None,
                "country": labels.get(country_ids[0]) if country_ids else None,
                "genres": found_genres,
                "format": format_of(ent, claims, found_genres),
            },
            wiki_details(name),
        )
        autofill.save_cache()
        info = found[name]
        print(
            f"  {name:18} -> {info['label']} | {info['years'] or '?'} | "
            f"{info['seasons'] or '?'} seasons | {info['episodes'] or '?'} eps | "
            f"{info['author'] or '?'} | {info['country'] or '?'} | {info['format']} | "
            f"{', '.join(info['genres']) or '?'} | {info['native'] or ''}",
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
        for col, header in HEADERS.items():
            io.ensure_column(tbl, col, header)
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
                (COL_EPISODES, "episodes"),
                (COL_FORMAT, "format"),
            ):
                if info.get(key):
                    tbl.write(i, col, info[key])
            if info.get("genres"):
                tbl.write(i, COL_GENRE, ", ".join(info["genres"]))

    save_index()
    extract.main()
    print(f"\nupdated {len(found)} shows")


if __name__ == "__main__":
    main()
