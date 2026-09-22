#!/usr/bin/env python3
"""Record the IMDb, Rotten Tomatoes, and Letterboxd score for each rated film.

    python3 scripts/scores.py                 # dry run
    python3 scripts/scores.py --apply         # write scores.json
    python3 scripts/scores.py --refresh       # re-fetch films already recorded
    python3 scripts/scores.py --only TITLE    # one film, verbosely

Only films with a tier. An unrated row is one I haven't seen, and what the
crowd thought of a film I haven't watched isn't a fact about my list — it's
just noise on a page whose whole point is my own rating. Rerunning after rating
something new picks it up.

Where each number comes from, and why:

  * IMDb publishes title.ratings.tsv.gz, every rating on the site, refreshed
    daily and free for personal use. One 8MB download beats 110 page fetches,
    and it is IMDb's own file rather than a number scraped off a page.
  * Rotten Tomatoes embeds a media-scorecard-json blob holding both the
    Tomatometer (critics) and the Popcornmeter (audience). Both are kept —
    critics and audiences disagree often enough that the gap is the
    interesting part.
  * Letterboxd puts an aggregateRating in its JSON-LD. Its scale is 0.5-5,
    left as-is rather than multiplied to look like IMDb's; a Letterboxd 4.1
    means something different from a 8.2 and shouldn't be dressed up as one.

The three ids all come from Wikidata (P345, P1258, P6127), so no URL is
guessed — Rotten Tomatoes in particular renames slugs (ne_zha_2 now redirects
to ne_zha_ii) and a guessed one would quietly 404.

Only the numbers are stored, never review text. A score is a fact; the reviews
it summarises belong to whoever wrote them.

Scores drift, so every entry carries the date it was read. --refresh re-reads
everything; a plain run only fills in films that have no entry yet.
"""
import datetime
import gzip
import io as _io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import autofill
import numbers_io as io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "scores.json")
# Written by scripts/summaries.py; its article name is the best film id we have.
SUMMARIES = os.path.join(ROOT, "summaries.json")

IMDB_DATASET = "https://datasets.imdbws.com/title.ratings.tsv.gz"
IMDB_URL = "https://www.imdb.com/title/{}/"
RT_URL = "https://www.rottentomatoes.com/{}"
LB_URL = "https://letterboxd.com/film/{}/"

# Wikidata's id for each site.
P_IMDB, P_RT, P_LETTERBOXD = "P345", "P1258", "P6127"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Rotten Tomatoes writes this tag's attributes across several lines, so the
# usual one-line script regex misses it.
SCORECARD = re.compile(
    r'<script\b[^>]*id="media-scorecard-json"[^>]*>\s*(\{.*?\})\s*</script>', re.S
)
LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def fetch(url, timeout=30):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def qids_for_articles(articles):
    """{article title: qid} via each article's Wikidata sitelink.

    summaries.py already worked out which Wikipedia article is this film, and
    that answer is better than matching the title again here: autofill.pick is
    deliberately conservative, so it abstains on a title several films share
    (Hero, Nobody, Ballerina) and lands on the wrong item for La La Land. The
    article is the one that has already been checked, so start from it.

    `normalize` is not passed — Wikidata rejects it for anything but a single
    title, and these go up in batches.
    """
    out = {}
    unique = sorted({a for a in articles if a})
    for start in range(0, len(unique), 40):
        chunk = unique[start : start + 40]
        data = autofill.api(
            {
                "action": "wbgetentities",
                "sites": "enwiki",
                "titles": "|".join(chunk),
                "props": "sitelinks",
                "sitefilter": "enwiki",
            }
        )
        for qid, entity in (data or {}).get("entities", {}).items():
            if not qid.startswith("Q"):
                continue
            title = (entity.get("sitelinks", {}).get("enwiki") or {}).get("title")
            if title:
                out[title] = qid
    return out


def site_ids(qids):
    """{qid: {"imdb": ..., "rt": ..., "letterboxd": ...}} from Wikidata."""
    out = {}
    unique = sorted(set(qids))
    for start in range(0, len(unique), 40):
        chunk = unique[start : start + 40]
        data = autofill.api(
            {"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims"}
        )
        for qid, entity in (data or {}).get("entities", {}).items():
            claims = entity.get("claims", {})
            found = {}
            for key, prop in (("imdb", P_IMDB), ("rt", P_RT), ("letterboxd", P_LETTERBOXD)):
                for claim in claims.get(prop, []):
                    value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if isinstance(value, str) and value.strip():
                        found[key] = value.strip()
                        break
            out[qid] = found
    return out


def imdb_ratings(wanted):
    """{tconst: (score, votes)} for the ids we care about.

    Streams the gzip rather than holding 1.6M rows in memory; we want about a
    hundred of them.
    """
    if not wanted:
        return {}
    print(f"  downloading {IMDB_DATASET}…", flush=True)
    req = urllib.request.Request(IMDB_DATASET, headers={"User-Agent": UA})
    out = {}
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            raw = res.read()
    except (urllib.error.URLError, OSError) as err:
        print(f"  IMDb dataset unavailable ({err}); skipping IMDb scores")
        return {}
    with gzip.open(_io.BytesIO(raw), "rt", encoding="utf-8") as fh:
        next(fh, None)  # tconst / averageRating / numVotes
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3 and parts[0] in wanted:
                try:
                    out[parts[0]] = (float(parts[1]), int(parts[2]))
                except ValueError:
                    continue
    print(f"  {len(out)} of {len(wanted)} films are in IMDb's ratings file")
    return out


def as_int(value):
    try:
        return int(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def rotten_tomatoes(rt_id):
    """(critics, audience) as percentages, either possibly None.

    A film can have one and not the other — an audience score before critics
    have filed, or a critics score with too few audience ratings to publish.
    """
    try:
        html = fetch(RT_URL.format(rt_id.lstrip("/")))
    except (urllib.error.URLError, OSError):
        return None, None
    match = SCORECARD.search(html)
    if not match:
        return None, None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None, None
    critics = as_int((data.get("criticsScore") or {}).get("score"))
    audience = as_int((data.get("audienceScore") or {}).get("score"))
    return critics, audience


def letterboxd(slug):
    """(rating out of 5, number of ratings), or (None, None)."""
    try:
        html = fetch(LB_URL.format(slug))
    except (urllib.error.URLError, OSError):
        return None, None
    for match in LD_JSON.finditer(html):
        raw = match.group(1).replace("/* <![CDATA[ */", "").replace("/* ]]> */", "").strip()
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        rating = data.get("aggregateRating") or {}
        if rating.get("ratingValue") is not None:
            try:
                return float(rating["ratingValue"]), as_int(rating.get("ratingCount"))
            except (TypeError, ValueError):
                return None, None
    return None, None


def read(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write(path, value):
    with open(path, "w") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")


def summarise(entry):
    """One line for the console: the three scores as they'll read on the page."""
    imdb = entry.get("imdb") or {}
    rt = entry.get("rottenTomatoes") or {}
    lb = entry.get("letterboxd") or {}
    parts = [
        f"IMDb {imdb['score']}" if imdb.get("score") is not None else "IMDb —",
        f"RT {rt['critics']}%" if rt.get("critics") is not None else "RT —",
        f"LB {lb['score']}" if lb.get("score") is not None else "LB —",
    ]
    return "  ".join(parts)


def main():
    argv = sys.argv[1:]
    apply = "--apply" in argv
    refresh = "--refresh" in argv
    only = argv[argv.index("--only") + 1] if "--only" in argv else None

    autofill.load_cache()
    table = io.films_table(io.open_doc())
    rows = [r for r in table.rows(values_only=True)[1:] if r[io.COL_TITLE]]

    # Rated films only — see the module docstring.
    films = []
    for row in rows:
        tier = str(row[io.COL_TIER]).strip() if row[io.COL_TIER] is not None else ""
        if not tier or tier == "?":
            continue
        title = str(row[io.COL_TITLE]).strip()
        if only and title.lower() != only.lower():
            continue
        films.append((title, io.year_of(row[io.COL_YEAR])))

    if only and not films:
        sys.exit(f"no rated film called {only!r} in the sheet")

    found = read(DST, {})
    if refresh:
        found = {}

    todo = [(t, y) for t, y in films if only or io.film_key(t, y) not in found]
    print(f"{len(films)} rated films; {len(todo)} to look up")
    if not todo:
        print("nothing to do")
        return

    # Resolve to Wikidata once, so the ids for all three sites come from a
    # single pass rather than one lookup per site. The article summaries.py
    # settled on is the first choice; matching the title again is the fallback
    # for films that have no summary yet.
    summaries = read(SUMMARIES, {})
    article_of = {}
    for title, year in todo:
        article = (summaries.get(io.film_key(title, year)) or {}).get("article")
        if article:
            article_of[(title, year)] = article

    by_article = qids_for_articles(article_of.values())

    qids = {}
    for title, year in todo:
        qid = by_article.get(article_of.get((title, year)))
        if not qid:
            try:
                pick = autofill.pick(autofill.candidates_for(title), year, title)
            except autofill.ApiUnavailable:
                pick = None
            qid = pick["qid"] if pick else None
        if qid:
            qids[(title, year)] = qid
    autofill.save_cache()
    print(f"  {len(qids)} of {len(todo)} matched a Wikidata item")

    ids = site_ids(qids.values())
    imdb_wanted = {ids.get(q, {}).get("imdb") for q in qids.values()}
    ratings = imdb_ratings({t for t in imdb_wanted if t})

    today = datetime.date.today().isoformat()
    added = 0
    for n, (title, year) in enumerate(todo, 1):
        key = io.film_key(title, year)
        qid = qids.get((title, year))
        sites = ids.get(qid, {}) if qid else {}
        entry = {"fetched": today}

        tconst = sites.get("imdb")
        if tconst and tconst in ratings:
            score, votes = ratings[tconst]
            entry["imdb"] = {
                "id": tconst,
                "score": score,
                "votes": votes,
                "url": IMDB_URL.format(tconst),
            }

        if sites.get("rt"):
            critics, audience = rotten_tomatoes(sites["rt"])
            if critics is not None or audience is not None:
                entry["rottenTomatoes"] = {
                    "id": sites["rt"],
                    "critics": critics,
                    "audience": audience,
                    "url": RT_URL.format(sites["rt"].lstrip("/")),
                }

        if sites.get("letterboxd"):
            score, votes = letterboxd(sites["letterboxd"])
            if score is not None:
                entry["letterboxd"] = {
                    "id": sites["letterboxd"],
                    "score": score,
                    "votes": votes,
                    "url": LB_URL.format(sites["letterboxd"]),
                }

        if len(entry) > 1:  # something beyond the date
            found[key] = entry
            added += 1
            print(f"  {title[:30]:30} {summarise(entry)}", flush=True)
        else:
            print(f"  {title[:30]:30} —", flush=True)

        # Saving as we go means a run that dies partway keeps its work, and a
        # rerun resumes rather than starting over.
        if apply and not only and n % 20 == 0:
            write(DST, found)

        if n < len(todo):
            time.sleep(1.0)

    print(f"\n{added} films scored; {len(found)} in {os.path.basename(DST)}")
    if not apply:
        print("dry run; nothing written")
        return
    write(DST, found)
    print(f"wrote {DST}")


if __name__ == "__main__":
    main()
