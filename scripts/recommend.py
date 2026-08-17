#!/usr/bin/env python3
"""Suggest films to watch next, from what's already been rated.

    python3 scripts/recommend.py            # print the current top suggestions
    python3 scripts/recommend.py --refresh  # widen the pool from Wikidata first

`build()` is called by extract.py on every run, so suggestions follow a rating
the moment it is saved. It never touches the network: the candidate pool is what
scripts/directors.py, scripts/franchises.py and scripts/box_office.py have
already written, and genres come from the Wikidata cache those scripts fill.

Two lists come out of it:

  * suggestions — films not in the sheet at all
  * unrated     — films already in the sheet with no tier, ranked the same way,
                  since a 70-film backlog is its own "what do I watch tonight"

Scoring is deliberately simple enough to explain on the page itself. Every
signal is an *affinity*: the mean of the tier weights of the films behind it,
damped by n/(n+1) so one film is a hint and five are a pattern. A candidate's
score is a weighted sum of the affinities that apply to it, and anything without
a positive one is dropped rather than padded out with filler.
"""
import json
import math
import os
import re
import sys
from datetime import date

import genres as G
from numbers_io import film_key  # the one definition of "which film is this"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".wikidata-cache.json")

# S is worth more than A is worth more than B; C down to F is a warning, not a
# shrug — "something missing that does not let me enjoy" should push a director
# down, not leave them where they were.
TIER_WEIGHT = {"S": 3.0, "A": 2.0, "B": 1.0, "C": -0.5, "D": -1.5, "E": -2.0, "F": -3.0}

# How much each signal counts. A director you love is the strongest predictor;
# a genre is the weakest, because "Drama" covers half the list.
W_DIRECTOR, W_FRANCHISE, W_GENRE, W_REGION, W_POPULAR = 2.2, 1.6, 1.0, 0.8, 0.5

# The Country column is shorthand ("HK", "Japanese"); Wikidata spells countries
# out in full. Both are folded to the same names the site groups films by, so a
# candidate's country can be compared with what you already watch.
REGIONS = {
    "china": "China",
    "chinese": "China",
    "people's republic of china": "China",
    "hk": "Hong Kong",
    "hong kong": "Hong Kong",
    "taiwan": "Taiwan",
    "republic of china": "Taiwan",
    "japan": "Japan",
    "japanese": "Japan",
    "korea": "Korea",
    "korean": "Korea",
    "south korea": "Korea",
    "republic of korea": "Korea",
    "north korea": "Korea",
    "usa": "USA",
    "american": "USA",
    "united states": "USA",
    "united states of america": "USA",
    "india": "India",
    "indian": "India",
    "uk": "UK",
    "united kingdom": "UK",
}


def region_of(country):
    if not country:
        return None
    name = str(country).strip().rstrip("?")
    return REGIONS.get(name.casefold(), name)

LIMIT = 80  # suggestions kept; the tail is all noise by then
DISCOVER = 12  # of those, reserved for films by directors you haven't watched

# Mirrors autofill.tidy_genre, which is what wrote the Genre column: Wikidata's
# genres are verbose and repetitive ("thriller film", "drama film").
GENRE_NOISE = re.compile(r"\s*\b(film|movie|cinema)\b\s*$", re.IGNORECASE)


def tidy_genre(name):
    """Wikidata label -> the canonical genres it folds into (possibly none).

    Taste is matched against the sheet's Genre column, which holds only the 30
    canonical genres, so a raw Wikidata label would never match.
    """
    name = GENRE_NOISE.sub("", str(name)).strip()
    return G.canonical(name[:1].upper() + name[1:]) if name else []


def norm_title(title):
    """Loose title key, the same one extract.py dedupes with."""
    return re.sub(r"[^a-z0-9]+", "", str(title).lower())


def affinity(weights):
    """How much a run of ratings says you like something.

    The mean keeps signals comparable no matter how many films are behind them;
    the n/(n+1) damping stops a single S from outranking four steady A's.
    """
    if not weights:
        return 0.0
    n = len(weights)
    return (sum(weights) / n) * (n / (n + 1))


def read(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# --- taste ---------------------------------------------------------------


def profile(films):
    """What the rated films say about directors, genres and franchises."""
    groups = {"directors": {}, "genres": {}, "franchises": {}, "regions": {}}
    for film in films:
        weight = TIER_WEIGHT.get(film.get("tier"))
        if weight is None:  # unrated says nothing either way
            continue
        evidence = {
            "title": film["title"],
            "year": film.get("year"),
            "tier": film["tier"],
            "slug": film.get("slug"),
            "weight": weight,
        }
        for name in film.get("directors") or []:
            groups["directors"].setdefault(name, []).append(evidence)
        for name in film.get("genres") or []:
            groups["genres"].setdefault(name, []).append(evidence)
        for name in film.get("franchises") or []:
            groups["franchises"].setdefault(name, []).append(evidence)
        where = region_of(film.get("country"))
        if where:
            groups["regions"].setdefault(where, []).append(evidence)

    out = {}
    for kind, group in groups.items():
        out[kind] = {
            name: {
                # Best-rated first, so an explanation leads with the strongest
                # thing you can say for it.
                "films": sorted(seen, key=lambda f: (-f["weight"], f["title"])),
                "affinity": affinity([f["weight"] for f in seen]),
            }
            for name, seen in group.items()
        }
    return out


def by_key(taste, kind, name):
    """Case-insensitive lookup; the Genre column is typed by several hands."""
    group = taste[kind]
    hit = group.get(name)
    if hit is not None:
        return hit
    folded = str(name).casefold()
    for other, value in group.items():
        if other.casefold() == folded:
            return value
    return None


# --- candidates ----------------------------------------------------------


def genres_of(qid, cache):
    """Genre labels for a Wikidata film, in the sheet's own vocabulary.

    Labels the cache hasn't resolved yet are skipped rather than shown as a
    QID; `--refresh` fills them in.
    """
    entity = cache.get("ent:" + qid) or {}
    names = []
    for genre in entity.get("genres", []):
        label = cache.get("label:" + genre)
        if not label or label == genre:
            continue
        for tidy in tidy_genre(label):
            if tidy not in names:
                names.append(tidy)
    return names


def regions_of(qid, cache):
    """Where a Wikidata film was made, as the site's region names."""
    entity = cache.get("ent:" + qid) or {}
    names = []
    for country in entity.get("countries", []):
        label = cache.get("label:" + country)
        if not label or label == country:
            continue
        where = region_of(label)
        if where and where not in names:
            names.append(where)
    return names


def collect(films, cache):
    """Every unwatched film worth considering, merged across the three pools."""
    known = {norm_title(f["title"]) for f in films}
    pool = {}

    def add(qid, title, year, source, **extra):
        if norm_title(title) in known:
            return None
        key = qid or f"{norm_title(title)}|{year or ''}"
        entry = pool.setdefault(
            key,
            {
                "qid": qid,
                "title": title,
                "year": year,
                "directors": [],
                "franchises": [],
                "sources": [],
                "box": None,
            },
        )
        if source not in entry["sources"]:
            entry["sources"].append(source)
        if entry["year"] is None:
            entry["year"] = year
        for name in extra.get("directors", []):
            if name and name not in entry["directors"]:
                entry["directors"].append(name)
        for name in extra.get("franchises", []):
            if name and name not in entry["franchises"]:
                entry["franchises"].append(name)
        if extra.get("box") and not entry["box"]:
            entry["box"] = extra["box"]
        return entry

    # The rest of the filmography of everyone in the list.
    for name, record in read(os.path.join(ROOT, "directors.json"), {}).items():
        for member in record.get("films", []):
            if member.get("watched"):
                continue
            add(member.get("qid"), member["title"], member.get("year"), "director", directors=[name])

    # The entries of a series where at least one film is already in the list.
    for name, record in read(os.path.join(ROOT, "franchises.json"), {}).items():
        for member in record.get("films", []):
            if member.get("watched"):
                continue
            add(
                member.get("qid"),
                member["title"],
                member.get("year"),
                "franchise",
                franchises=[name],
                # franchises.json keeps co-directors in one comma-joined cell.
                directors=[d.strip() for d in str(member.get("director") or "").split(",") if d.strip()],
            )

    # The big earners of every year, which is how anything by a director who
    # isn't in the list yet can still surface.
    for year, top in read(os.path.join(ROOT, "box-office.json"), {}).items():
        for member in top:
            add(member.get("qid"), member["title"], int(year), "box office", box=member.get("box"))

    # Directors are QIDs in the cache; the taste profile is keyed by name.
    for entry in pool.values():
        if entry["qid"]:
            entity = cache.get("ent:" + entry["qid"]) or {}
            for qid in entity.get("directors", []):
                name = cache.get("label:" + qid)
                if name and name != qid and name not in entry["directors"]:
                    entry["directors"].append(name)
            entry["genres"] = genres_of(entry["qid"], cache)
            entry["regions"] = regions_of(entry["qid"], cache)
        else:
            entry["genres"] = []
            entry["regions"] = []
    return list(pool.values())


# --- scoring -------------------------------------------------------------


def join(names):
    """"Lau and Mak", "Lau, Mak and Chan" — for reasons meant to be read."""
    names = list(names)
    if len(names) < 2:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"


def cite(films, limit=2):
    """"Hero (A) and To Live (S)" — the evidence behind a reason."""
    names = [f"{f['title']} ({f['tier']})" for f in films[:limit]]
    if len(names) == 2:
        return " and ".join(names)
    return ", ".join(names)


def popularity(box):
    """A blockbuster nudge: 0 below $100M, full weight at $10B."""
    if not box:
        return 0.0
    return max(0.0, min(1.0, (math.log10(box) - 8) / 2))


def score(entry, taste):
    """Score one candidate and say why, or return None if nothing recommends it."""
    total, reasons = 0.0, []

    # Co-directors are one signal, not two: Infernal Affairs II is a Lau film
    # and a Mak film, but you only liked Infernal Affairs once. Take the
    # strongest of them and name the rest alongside it.
    known = [(by_key(taste, "directors", n), n) for n in entry.get("directors", [])]
    known = [(hit, name) for hit, name in known if hit]
    if known:
        best = max(hit["affinity"] for hit, _ in known)
        total += W_DIRECTOR * best
        liked_by = [(hit, name) for hit, name in known if hit["affinity"] > 0]
        if liked_by:
            top = max(liked_by, key=lambda pair: pair[0]["affinity"])[0]
            names = join([name for _, name in liked_by])
            reasons.append(
                {
                    "kind": "director",
                    "name": names,
                    "text": f"You rated {cite(top['films'])} by {names}",
                }
            )

    series = [(by_key(taste, "franchises", n), n) for n in entry.get("franchises", [])]
    series = [(hit, name) for hit, name in series if hit]
    if series:
        hit, name = max(series, key=lambda pair: pair[0]["affinity"])
        total += W_FRANCHISE * hit["affinity"]
        if hit["affinity"] > 0:
            reasons.append(
                {
                    "kind": "franchise",
                    "name": name,
                    "text": f"Part of {name}, where you rated {cite(hit['films'])}",
                }
            )

    # Genres are averaged, not summed: a film tagged with eight of them isn't
    # eight times the match.
    liked, scores = [], []
    for name in entry.get("genres", []):
        hit = by_key(taste, "genres", name)
        if not hit:
            continue
        scores.append(hit["affinity"])
        if hit["affinity"] > 0:
            liked.append((hit["affinity"], name))
    if scores:
        total += W_GENRE * (sum(scores) / len(scores))
    if liked:
        liked.sort(reverse=True)
        names = [name for _, name in liked[:3]]
        reasons.append(
            {
                "kind": "genre",
                "name": ", ".join(names),
                "text": f"{', '.join(names)} — genres you rate well",
            }
        )

    # Where it was made. Weak on its own, but it is what keeps a list this
    # East-Asian from being handed a run of American family comedies because
    # they happen to share the word "Comedy".
    where = [(by_key(taste, "regions", n), n) for n in entry.get("regions", [])]
    where = [(hit, name) for hit, name in where if hit]
    if where:
        hit, name = max(where, key=lambda pair: pair[0]["affinity"])
        total += W_REGION * hit["affinity"]
        if hit["affinity"] > 0:
            reasons.append(
                {
                    "kind": "region",
                    "name": name,
                    "text": f"From {name}, where you've rated {len(hit['films'])} films",
                }
            )

    if not reasons or total <= 0:
        return None

    # Popularity only ever breaks ties between films that already fit; on its
    # own it would just list every blockbuster ever made.
    pop = popularity(entry.get("box"))
    if pop:
        total += W_POPULAR * pop
        reasons.append({"kind": "popular", "name": "", "text": f"One of {entry['year']}'s biggest earners"})

    return {"score": round(total, 3), "reasons": reasons}


PER_GROUP = 2  # suggestions allowed from one series or one director


def rank(entries, taste, limit):
    """Best first, but not eleven Pokémon films.

    One well-liked franchise can fill the whole page — every sequel scores the
    same way. Two per series and per director is enough to make the point; the
    rest are a click away on the franchise and director pages.
    """
    scored = []
    for entry in entries:
        verdict = score(entry, taste)
        if verdict:
            scored.append({**entry, **verdict})
    scored.sort(key=lambda e: (-e["score"], e["title"]))

    kept, used = [], {}
    for entry in scored:
        groups = [("f", n) for n in entry["franchises"]] + [("d", n) for n in entry["directors"]]
        if any(used.get(g, 0) >= PER_GROUP for g in groups):
            continue
        for g in groups:
            used[g] = used.get(g, 0) + 1
        kept.append(entry)
        if len(kept) == limit:
            break
    return kept


# --- output --------------------------------------------------------------


def build(films):
    """Suggestions for data.json. Never raises: a broken pool is not worth
    losing the rest of the site over."""
    empty = {"films": [], "unrated": [], "taste": {"directors": [], "genres": []}, "rated": 0}
    try:
        cache = read(CACHE, {})
        taste = profile(films)
        rated = sum(1 for f in films if f.get("tier") in TIER_WEIGHT)
        if not rated:
            return empty

        this_year = date.today().year
        # Downloaded by scripts/posters.py --suggestions; absent until that has
        # been run, in which case the cards render a placeholder.
        art = read(os.path.join(ROOT, "suggestion-posters.json"), {})
        pool = collect(films, cache)
        best = rank(pool, taste, LIMIT)

        # A director you already like will always outscore a stranger, so the
        # ranking on its own is "more of what you've seen". Keep a slice for
        # films that got here purely on being big that year — the only route in
        # the pool for a director who isn't in the list yet.
        seen = {id(e) for e in best}
        strangers = [
            e
            for e in pool
            if e["sources"] == ["box office"] and popularity(e["box"]) and id(e) not in seen
        ]
        best += rank(strangers, taste, DISCOVER)
        best.sort(key=lambda e: (-e["score"], e["title"]))

        suggestions = []
        for entry in best:
            suggestions.append(
                {
                    "title": entry["title"],
                    "year": entry["year"],
                    "directors": entry["directors"][:3],
                    "franchises": entry["franchises"],
                    "genres": entry["genres"][:4],
                    "regions": entry["regions"],
                    "sources": entry["sources"],
                    "score": entry["score"],
                    "reasons": entry["reasons"],
                    "qid": entry["qid"],
                    "poster": art.get(film_key(entry["title"], entry["year"])),
                    "upcoming": bool(entry["year"] and entry["year"] > this_year),
                }
            )

        # The backlog: films already added but never rated, ranked the same way
        # so the pile has an obvious top.
        backlog = []
        for film in films:
            if film.get("tier") in TIER_WEIGHT:
                continue
            entry = {
                "title": film["title"],
                "year": film.get("year"),
                "directors": film.get("directors") or [],
                "franchises": film.get("franchises") or [],
                "genres": film.get("genres") or [],
                "regions": [region_of(film.get("country"))] if film.get("country") else [],
                "sources": ["your list"],
                "box": None,
            }
            # Unlike the suggestions, nothing is dropped here — it is already
            # on the shelf, so it gets listed even with nothing to go on.
            verdict = score(entry, taste) or {"score": 0.0, "reasons": []}
            backlog.append(
                {
                    **entry,
                    **verdict,
                    "slug": film.get("slug"),
                    "poster": film.get("poster"),
                    "country": film.get("country"),
                }
            )
        backlog.sort(key=lambda e: (-e["score"], e["title"]))

        def summary(kind, least):
            return [
                {"name": name, "affinity": round(v["affinity"], 2), "count": len(v["films"])}
                for name, v in sorted(
                    taste[kind].items(), key=lambda kv: (-kv[1]["affinity"], kv[0])
                )
                if v["affinity"] > 0 and len(v["films"]) >= least
            ]

        return {
            "films": suggestions,
            "unrated": backlog,
            "rated": rated,
            "taste": {
                "directors": summary("directors", 1)[:8],
                "genres": summary("genres", 2)[:10],
                "regions": summary("regions", 1),
            },
        }
    except Exception as err:  # pragma: no cover - suggestions are a nicety
        print(f"  ! suggestions skipped: {err}")
        return empty


# --- widening the pool ---------------------------------------------------


def refresh():
    """Fetch the genre labels and film details the pool is missing.

    Everything is cached, so this is a one-off per new candidate: the box
    office lists ~2000 films the other scripts never looked up, and without
    their genres they can only be recommended by director.
    """
    import autofill  # only needed here; keeps extract.py's imports light

    autofill.load_cache()
    cache = autofill._cache

    films = read(os.path.join(ROOT, "data.json"), {}).get("films", [])
    wanted = [e["qid"] for e in collect(films, cache) if e["qid"]]
    missing = [q for q in dict.fromkeys(wanted) if "ent:" + q not in cache]
    print(f"{len(wanted)} candidates, {len(missing)} to look up")
    try:
        for i in range(0, len(missing), 50):
            autofill.entities(missing[i : i + 50])
            print(f"  … {min(i + 50, len(missing))}/{len(missing)}", flush=True)
            autofill.save_cache()
    except autofill.ApiUnavailable as err:
        print(f"  ! lookup failed ({err}); rerun to resume from the cache")

    # Genres and directors are QIDs; the page needs their names.
    refs = set()
    for key, entity in cache.items():
        if not key.startswith("ent:") or not isinstance(entity, dict):
            continue
        refs.update(entity.get("genres", []))
        refs.update(entity.get("directors", []))
        refs.update(entity.get("countries", []))
    unnamed = sorted(q for q in refs if "label:" + q not in cache)
    print(f"{len(unnamed)} labels to resolve")
    try:
        for i in range(0, len(unnamed), 50):
            autofill.labels(unnamed[i : i + 50])
            autofill.save_cache()
    except autofill.ApiUnavailable as err:
        print(f"  ! label lookup failed ({err}); rerun to resume from the cache")
    autofill.save_cache()


def main():
    if "--refresh" in sys.argv:
        refresh()
        import extract

        extract.main()
        return 0

    films = read(os.path.join(ROOT, "data.json"), {}).get("films", [])
    if not films:
        sys.exit("no data.json — run scripts/extract.py first")
    result = build(films)
    print(f"from {result['rated']} rated films:\n")
    for entry in result["films"][:25]:
        year = entry["year"] or "—"
        print(f"  {entry['score']:5.2f}  {entry['title']} ({year})")
        for reason in entry["reasons"]:
            print(f"         {reason['text']}")
    print(f"\n{len(result['unrated'])} unrated films in your own list, best first:")
    for entry in result["unrated"][:10]:
        print(f"  {entry['score']:5.2f}  {entry['title']} ({entry['year'] or '—'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
