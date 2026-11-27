#!/usr/bin/env python3
"""Fill in the Original title column for films not made in English.

    python3 scripts/native_titles.py              # dry run, prints each title found
    python3 scripts/native_titles.py --apply      # write them into the sheet

autofill.py only takes a native title from P1476 ("title"), which most Chinese,
Japanese and Korean films on Wikidata don't carry, and most of its cached
entities predate it storing languages at all. So this asks Wikidata again for
each film still missing one: P364 (original language) says which language, and
the film's own label in that language is the title, with P1476 preferred when
it is in the same language.

When an item lists no original language, the sheet's Country stands in for it —
a Hong Kong film without P364 is still a Cantonese-titled film. English among
the languages means no second title, the same rule autofill.py applies.

Chinese titles come in two scripts. Mainland films are written in simplified
characters and Hong Kong and Taiwan films in traditional, so the label lookup
asks for the region's own variant first and falls back to plain "zh".

Matching reuses autofill.py's conservative candidates_for/pick, so a film it
can't place unambiguously is skipped and listed, never guessed. Only empty cells
are written; a title typed by hand is never replaced.
"""
import re
import sys

import autofill as A
import extract
import numbers_io as io
import wikidata as wd

# P364 value -> label language codes to try, in order. Anything not listed is
# looked up through the language item's own Wikimedia code (P424).
LANGUAGE_CODES = {
    "Q7850": ["zh"],  # Chinese
    "Q9192": ["zh"],  # Mandarin
    "Q727694": ["zh"],  # Standard Chinese
    "Q9186": ["zh-hk", "yue", "zh-hant", "zh"],  # Cantonese
    "Q5287": ["ja"],
    "Q9176": ["ko"],
    "Q1568": ["hi"],
    "Q150": ["fr"],
    "Q9217": ["th"],
    "Q5885": ["ta"],
    "Q8097": ["te"],
}

# Stand-ins for P364 when Wikidata has none, from the sheet's Country.
REGION_CODES = {
    "China": ["zh"],
    "Hong Kong": ["zh"],
    "Taiwan": ["zh"],
    "Japan": ["ja"],
    "Korea": ["ko"],
    "India": ["hi"],
    "France": ["fr"],
}

# The sheet's region as a Wikidata country (P495), to tell apart same-titled
# films that autofill.pick leaves ambiguous: Hero (2002) is the Chinese one.
REGION_COUNTRIES = {
    "China": "Q148",
    "Hong Kong": "Q8646",
    "Taiwan": "Q865",
    "Japan": "Q17",
    "Korea": "Q884",
    "India": "Q668",
    "France": "Q142",
}

# Which Chinese script to look for first.
CHINESE_VARIANTS = {
    "Hong Kong": ["zh-hk", "zh-hant", "zh-tw", "zh"],
    "Taiwan": ["zh-tw", "zh-hant", "zh-hk", "zh"],
}
SIMPLIFIED = ["zh-cn", "zh-hans", "zh"]


def fetch(qids):
    """Fresh claims and all labels for each QID, 50 per call."""
    out = {}
    for i in range(0, len(qids), 50):
        chunk = qids[i : i + 50]
        resp = wd.api({"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims|labels"})
        if resp is None:
            raise wd.ApiUnavailable(",".join(chunk[:3]))
        out.update(resp.get("entities", {}))
    return out


def searched(title, region):
    """Candidates from a full-text search limited to films from the sheet's
    country. autofill.search is a label search capped at 20 hits, so a short
    title like Hero (2002) never reaches the Chinese film at all."""
    country = REGION_COUNTRIES.get(region)
    if not country:
        return []
    types = "|".join(f"P31={t}" for t in sorted(A.FILM_TYPES))
    resp = wd.api(
        {
            "action": "query",
            "list": "search",
            "srsearch": f"{title} haswbstatement:{types} haswbstatement:P495={country}",
            "srlimit": 10,
        }
    )
    if resp is None:
        raise wd.ApiUnavailable(title)
    ids = [hit["title"] for hit in resp.get("query", {}).get("search", [])]
    if not ids:
        return []
    out = []
    for qid, ent in fetch(ids).items():
        labels = ent.get("labels", {})
        dates = wd.claim_values(ent.get("claims", {}), "P577")
        out.append(
            {
                "qid": qid,
                "label": (labels.get("en") or {}).get("value"),
                "years": {y for y in (A.year_of(d) for d in dates) if y},
            }
        )
    return out


def by_country(cands, title, year, region):
    """The one candidate from the sheet's country, near its year, if exactly one."""
    country = REGION_COUNTRIES.get(region)
    if not country:
        return None
    # Without a year to check against, only an exact title match will do.
    if year is None:
        pool = [c for c in cands if (c["label"] or "").casefold() == title.casefold()]
    else:
        pool = [c for c in cands if any(abs(y - year) <= 1 for y in c["years"])]
    if not pool:
        return None
    ents = fetch([c["qid"] for c in pool])
    match = [
        c
        for c in pool
        if country in wd.claim_values(ents.get(c["qid"], {}).get("claims", {}), "P495")
    ]
    return match[0] if len(match) == 1 else None


def language_codes(qids):
    """Wikimedia codes (P424) for language items not in LANGUAGE_CODES."""
    unknown = sorted({q for q in qids if q not in LANGUAGE_CODES and q not in A.ENGLISH})
    codes = {}
    for qid, ent in fetch(unknown).items() if unknown else []:
        for claim in ent.get("claims", {}).get("P424", []):
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, str):
                codes[qid] = [value]
                break
    return codes


def native_for(ent, region, codes):
    """The title in the film's own language, or None when English or unknown."""
    claims = ent.get("claims", {})
    langs = [
        c["mainsnak"]["datavalue"]["value"]["id"]
        for c in claims.get("P364", [])
        if c.get("mainsnak", {}).get("datavalue")
    ]
    # The first language is the main one. Plenty of Chinese and Korean films
    # list English further down for a few lines of dialogue; those still get a
    # native title, but a film whose main language is English doesn't.
    if langs and langs[0] in A.ENGLISH:
        return None
    tries = [LANGUAGE_CODES.get(q) or codes.get(q) for q in langs if q not in A.ENGLISH]
    tries = [t for t in tries if t] + [REGION_CODES.get(region)]

    labels = ent.get("labels", {})
    titles = [
        c.get("mainsnak", {}).get("datavalue", {}).get("value", {}) for c in claims.get("P1476", [])
    ]
    for wanted in filter(None, tries):
        if wanted == ["zh"]:
            wanted = CHINESE_VARIANTS.get(region, SIMPLIFIED)
        family = wanted[-1].split("-")[0]
        for value in titles:
            text = tidy(value.get("text"))
            if (value.get("language") or "").split("-")[0] == family and usable(text, family):
                return text
        for code in wanted:
            text = tidy((labels.get(code) or {}).get("value"))
            if usable(text, family):
                return text
    return None


# Languages not written in Latin script: a label in one of these that is plain
# ASCII is the English name copied across, not a native title.
NON_LATIN = {"zh", "yue", "ja", "ko", "hi", "th", "ta", "te", "ru"}


# Wikipedia-style disambiguators that leak into labels: "天涯海角 (1996年電影)".
DISAMBIGUATOR = re.compile(r"\s*[(（][^()（）]*(電影|电影|映画|영화|film)[^()（）]*[)）]\s*$")


def tidy(text):
    return DISAMBIGUATOR.sub("", text or "").strip()


def usable(text, family):
    return bool(text) and not (family in NON_LATIN and text.isascii())


def main():
    apply = "--apply" in sys.argv
    A.load_cache()

    rows = io.films_table(io.open_doc()).rows(values_only=True)
    todo = []
    for row in rows[1:]:
        if not row[io.COL_TITLE] or row[io.COL_NATIVE]:
            continue
        title = str(row[io.COL_TITLE]).strip()
        year = io.year_of(row[io.COL_YEAR])
        country = row[io.COL_COUNTRY]
        region = extract.REGIONS.get(str(country).lower(), "Unknown") if country else "Unknown"
        if region in ("USA", "UK"):
            continue
        todo.append((title, year, region))
    print(f"{len(todo)} films without an original title", flush=True)

    resolved, skipped = {}, []
    for title, year, region in todo:
        try:
            cands = A.candidates_for(title)
            cand = (
                A.pick(cands, year, title)
                or by_country(cands, title, year, region)
                or by_country(searched(title, region), title, year, region)
            )
        except wd.ApiUnavailable:
            skipped.append(f"{title} — lookup failed")
            continue
        if cand is None:
            skipped.append(f"{title} ({year or '?'}) — no unambiguous match")
            continue
        resolved[(title, year)] = (cand["qid"], region)
    A.save_cache()

    ents = fetch(sorted({q for q, _ in resolved.values()}))
    langs = {
        c["mainsnak"]["datavalue"]["value"]["id"]
        for e in ents.values()
        for c in e.get("claims", {}).get("P364", [])
        if c.get("mainsnak", {}).get("datavalue")
    }
    codes = language_codes(langs)

    found = {}
    for (title, year), (qid, region) in resolved.items():
        native = native_for(ents.get(qid, {}), region, codes)
        if native and native.casefold() != title.casefold():
            found[(title, year)] = native
            print(f"  {title} ({year or '?'}) → {native}   [{qid}]")
        elif native is None:
            skipped.append(f"{title} ({year or '?'}) — English or no title in its language [{qid}]")

    print(f"\nfound {len(found)}; skipped {len(skipped)}:")
    for line in skipped:
        print("  -", line)

    if not apply:
        print("\ndry run; nothing written")
        return 0

    written = 0
    with io.editing() as (doc, table):
        for (title, year), native in found.items():
            i = io.find_row(table, title, year)
            if i is None or table.cell(i, io.COL_NATIVE).value:
                continue
            table.write(i, io.COL_NATIVE, native)
            written += 1
    extract.main()
    print(f"\nwrote {written} original titles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
