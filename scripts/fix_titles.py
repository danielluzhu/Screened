#!/usr/bin/env python3
"""Correct film titles to their canonical spelling, casing and full form.

    python3 scripts/fix_titles.py            # dry run: show what would change
    python3 scripts/fix_titles.py --apply    # write the changes

Two kinds of change are considered safe enough to make automatically:

  tidy    same title, differently written — "Yiyi" -> "Yi Yi", "The God Father"
          -> "The Godfather". The letters match once case and punctuation are
          stripped, so there is no question it is the same film.

  expand  shorthand for a longer official title — "Mugen Train" -> "Demon
          Slayer: Kimetsu no Yaiba - The Movie: Mugen Train". Accepted only
          when the recorded title appears verbatim inside the canonical one and
          Wikidata confirms the target is a film.

Anything else is reported and left alone. Renaming also re-keys posters.json so
artwork follows the film.
"""
import json
import os
import re
import sys

import autofill
import extract
import numbers_io as io
import posters

POSTERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "posters.json")


# Corrections I checked individually. The automatic rules are deliberately
# strict, and these are titles where the right answer is not in doubt but the
# strings are too far apart for a rule to accept safely.
VERIFIED = {
    ("Yiyi", 2000): "Yi Yi",
    ("The God Father", 1972): "The Godfather",
    ("Three Idiots", 2009): "3 Idiots",
    ("Drunken Master 2", 1994): "Drunken Master II",
    ("Dune 2", 2024): "Dune: Part Two",
    ("Havoc of Heaven", None): "Havoc in Heaven",
}


def strip_disambiguator(article):
    """'Mulan (1998 film)' -> 'Mulan'. Only removes film-ish parentheticals."""
    return re.sub(r"\s*\((?:[^)]*\b(?:film|movie|anime)\b[^)]*)\)\s*$", "", article, flags=re.IGNORECASE).strip()


def squash(name):
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def words(name):
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def canonical_for(title, year):
    """Best canonical title for a film, or None. Returns (name, how, year)."""
    # 1. Wikidata already resolves it: its English label is authoritative.
    try:
        pick = autofill.pick(autofill.candidates_for(title), year, title)
    except autofill.ApiUnavailable:
        pick = None
    if pick and pick.get("label"):
        pyears = pick.get("years") or set()
        return pick["label"], "wikidata", (min(pyears) if pyears else None)

    # 2. Otherwise search Wikipedia and confirm the hit is a film.
    hits = posters.search_articles(title, year)
    confirmed = posters.confirm_films(hits)
    for article in hits:
        ent = confirmed.get(article)
        if not ent:
            continue
        if year is not None:
            years = {autofill.year_of(d) for d in ent.get("dates", [])}
            years.discard(None)
            if years and not any(abs(y - year) <= 1 for y in years):
                continue
        name = ent.get("label") or strip_disambiguator(article)
        cyears = {autofill.year_of(d) for d in ent.get("dates", [])}
        cyears.discard(None)
        return name, "search", (min(cyears) if cyears else None)
    return None, None, None


# Words English titles conventionally leave lowercase. Wikidata labels are
# inconsistent here ("Crystal Sky Of Yesterday"), and capitalising them would
# make a correctly written title worse.
MINOR = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of",
         "on", "or", "the", "to", "up", "with", "my", "from", "into", "over"}


def only_minor_word_casing(current, canonical):
    """True when the sole difference is capitalising a minor word."""
    a, b = current.split(), canonical.split()
    if len(a) != len(b):
        return False
    changed = [(x, y) for x, y in zip(a, b) if x != y]
    if not changed:
        return False
    return all(
        x.lower() == y.lower() and x.lower() in MINOR and y[:1].isupper()
        for x, y in changed
    )


def classify(current, canonical, year, canon_year):
    """How confident are we that `canonical` is just a better-written `current`?"""
    if not canonical or canonical == current:
        return None
    if only_minor_word_casing(current, canonical):
        return None  # the recorded title is the better-written one
    if squash(current) == squash(canonical):
        return "tidy"
    # Leading-article and punctuation differences only.
    if posters.title_matches(current, canonical):
        return "tidy"

    # Shorthand: the recorded title is a whole phrase inside the official one.
    cur, can = words(current), words(canonical)
    if re.search(rf"(^|\s){re.escape(cur)}(\s|$)", can):
        # A short phrase inside a longer title proves nothing — "Dragon" sits
        # inside "Red Dragon", a different film. Require either an exact year
        # match or a phrase distinctive enough to stand alone.
        if year is not None and canon_year is not None:
            return "expand" if year == canon_year else "unsure"
        if len(cur) >= 8:
            return "expand"
        return "unsure"
    return "unsure"


def rekey_posters(renames):
    """Move poster index entries onto the new titles."""
    if not os.path.exists(POSTERS) or not renames:
        return
    with open(POSTERS) as fh:
        index = json.load(fh)
    for old, new, year in renames:
        old_key, new_key = io.film_key(old, year), io.film_key(new, year)
        if old_key in index:
            index[new_key] = index.pop(old_key)
    with open(POSTERS, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def main():
    apply = "--apply" in sys.argv
    autofill.load_cache()

    table = io.films_table(io.open_doc())
    films = [r for r in table.rows(values_only=True)[1:] if r[io.COL_TITLE]]
    print(f"{len(films)} films", flush=True)

    tidy, expand, unsure, unmatched = [], [], [], []
    for n, row in enumerate(films, 1):
        title = str(row[io.COL_TITLE]).strip()
        year = io.year_of(row[io.COL_YEAR])
        if n % 25 == 0:
            print(f"  {n}/{len(films)}…", flush=True)
            autofill.save_cache()

        if (title, year) in VERIFIED:
            tidy.append((title, VERIFIED[(title, year)], year, "verified by hand"))
            continue
        canonical, how, canon_year = canonical_for(title, year)
        if not canonical:
            unmatched.append(title)
            continue
        kind = classify(title, canonical, year, canon_year)
        if kind == "tidy":
            tidy.append((title, canonical, year, how))
        elif kind == "expand":
            expand.append((title, canonical, year, how))
        elif kind == "unsure":
            unsure.append((title, canonical, year, how))
    autofill.save_cache()

    def show(label, rows):
        print(f"\n{label} ({len(rows)}):")
        for old, new, year, how in rows:
            print(f"  {old!r} ({year or '?'})  ->  {new!r}   [{how}]")

    show("tidy — casing/spelling", tidy)
    show("expand — shorthand to full title", expand)
    show("UNSURE — left alone, review by hand", unsure)
    print(f"\nno confident match ({len(unmatched)}): {', '.join(unmatched)}")

    changes = tidy + expand
    if not apply:
        print(f"\ndry run; would change {len(changes)} titles. Re-run with --apply")
        return

    if not changes:
        print("\nnothing to change")
        return

    # Two rows must not end up with the same title and year.
    existing = {(str(r[io.COL_TITLE]).strip(), io.year_of(r[io.COL_YEAR])) for r in films}
    safe, collide = [], []
    for old, new, year, how in changes:
        target = (new, year)
        if target in existing and target != (old, year):
            collide.append((old, new, year, how))
        else:
            existing.discard((old, year))
            existing.add(target)
            safe.append((old, new, year, how))
    if collide:
        print(f"\nskipped — would collide with an existing row ({len(collide)}):")
        for old, new, year, _ in collide:
            print(f"  {old!r} ({year or '?'})  ->  {new!r}")
    changes = safe

    with io.editing() as (doc, tbl):
        for old, new, year, _ in changes:
            i = io.find_row(tbl, old, year)
            if i is None:
                continue
            tbl.write(i, io.COL_TITLE, new)
    rekey_posters([(o, n, y) for o, n, y, _ in changes])
    extract.main()
    print(f"\nrenamed {len(changes)} films")


if __name__ == "__main__":
    main()
