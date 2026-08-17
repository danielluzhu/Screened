#!/usr/bin/env python3
"""Download a poster for each film into public/posters/.

    python3 scripts/posters.py [--force]

Resolves each film to its Wikidata item (reusing autofill's cache and matching,
so this is mostly offline), follows the English Wikipedia sitelink, and takes
that article's lead image — for a film article that is the poster.

Posters are non-free images used editorially by Wikipedia. Keeping a local copy
for a personal, private film list is the same kind of use; don't redeploy this
site publicly without checking that's still true for you.

Writes posters.json mapping film title -> filename, which extract.py folds into
data.json. Images are stored locally rather than hotlinked, per Wikimedia's
request that their servers not be used as a CDN.
"""
import difflib
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
OUT = os.path.join(ROOT, "public", "posters")
INDEX = os.path.join(ROOT, "posters.json")
# Posters for films that aren't in the sheet — the suggestions page. Kept out of
# posters.json so remove_film.py can't delete artwork for a film you never had,
# and so "which films do I own" stays one file.
SUGGEST_INDEX = os.path.join(ROOT, "suggestion-posters.json")
DATA = os.path.join(ROOT, "data.json")
WIKI = "https://en.wikipedia.org/w/api.php"
THUMB = 500


def slug(title, year=None):
    s = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-") or "film"
    # Year in the filename keeps same-title films apart (three Mulans).
    return f"{s}-{year}" if year else s


_last = [0.0]
MIN_GAP = 1.2


def wiki_api(params):
    url = WIKI + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": autofill.UA})
    for attempt in range(6):
        gap = MIN_GAP - (time.monotonic() - _last[0])
        if gap > 0:
            time.sleep(gap)
        _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < 5:
                wait = int(err.headers.get("Retry-After") or 0) or min(60, 5 * 2**attempt)
                time.sleep(wait)
                continue
            if attempt == 5:
                print(f"  ! wiki API: {err}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
        except Exception as err:  # noqa: BLE001 - any failure is retryable here
            if attempt == 5:
                print(f"  ! wiki API: {err}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
    return None


def sitelinks(qids):
    """QID -> English Wikipedia article title."""
    out = {}
    todo = [q for q in qids if "site:" + q not in autofill._cache]
    for i in range(0, len(todo), 50):
        chunk = todo[i : i + 50]
        data = autofill.api(
            {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "sitelinks",
                "sitefilter": "enwiki",
            }
        )
        if data is None:
            raise autofill.ApiUnavailable("sitelinks")
        for qid in chunk:
            link = data.get("entities", {}).get(qid, {}).get("sitelinks", {}).get("enwiki", {})
            autofill._cache["site:" + qid] = link.get("title")
    for q in qids:
        title = autofill._cache.get("site:" + q)
        if title:
            out[q] = title
    return out


def thumbnails(titles):
    """Wikipedia article title -> lead image URL (posters are non-free, so
    pilicense=any is required; the default only returns freely licensed files)."""
    out = {}
    for i in range(0, len(titles), 40):
        chunk = titles[i : i + 40]
        data = wiki_api(
            {
                "action": "query",
                "titles": "|".join(chunk),
                "prop": "pageimages",
                "piprop": "thumbnail",
                "pithumbsize": THUMB,
                "pilicense": "any",
            }
        )
        if not data:
            continue
        pages = data.get("query", {}).get("pages", {})
        # Follow any redirects the API resolved for us.
        norm = {n["from"]: n["to"] for n in data.get("query", {}).get("normalized", [])}
        for page in pages.values():
            src = page.get("thumbnail", {}).get("source")
            if src:
                out[page["title"]] = src
        for src_title, dest in norm.items():
            if dest in out:
                out[src_title] = out[dest]
    return out


def search_articles(title, year, limit=6):
    """Full-text search Wikipedia for a film article. Used for the films
    Wikidata's label lookup couldn't match (spelling variants, alternate
    titles), so it needs to actually search rather than resolve a known id."""
    terms = f"{title} film"
    if year:
        terms += f" {year}"
    data = wiki_api({"action": "query", "list": "search", "srsearch": terms, "srlimit": limit})
    if not data:
        return []
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def normalize(name, drop_article=False):
    """Strip disambiguators and punctuation so 'Kiki Delivery Service' and
    "Kiki's Delivery Service (film)" compare equal."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    if drop_article:
        name = re.sub(r"^(the|a|an)\s+", "", name.strip(), flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def title_matches(film_title, article):
    """Is this article plausibly the same film? Search results are loose — they
    will return an unrelated film of a similar-sounding name — so require a
    close title match rather than trusting rank.

    Deliberately does NOT accept mere containment: that let "Dragon" match
    "Red Dragon". Only a leading article may differ.
    """
    a, b = normalize(film_title), normalize(article)
    if not a or not b:
        return False
    if a == b:
        return True
    if normalize(film_title, True) == normalize(article, True):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def confirm_films(articles):
    """Keep only articles whose Wikidata item is actually a film.

    A text search will happily return the novel, the soundtrack, or an unrelated
    article of the same name; taking their lead image would put the wrong poster
    on the card.
    """
    if not articles:
        return {}
    qid_of = {}
    for i in range(0, len(articles), 40):
        chunk = articles[i : i + 40]
        data = wiki_api(
            {"action": "query", "titles": "|".join(chunk), "prop": "pageprops", "ppprop": "wikibase_item"}
        )
        if not data:
            continue
        for page in data.get("query", {}).get("pages", {}).values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                qid_of[page["title"]] = qid
    ents = autofill.entities(sorted(set(qid_of.values())))
    return {
        article: ents[qid]
        for article, qid in qid_of.items()
        if qid in ents and set(ents[qid].get("types", [])) & autofill.FILM_TYPES
    }


def download(url, dest):
    """Fetch one image, retrying through the 429s Wikimedia hands out freely."""
    req = urllib.request.Request(url, headers={"User-Agent": autofill.UA})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            break
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < 5:
                wait = int(err.headers.get("Retry-After") or 0) or min(60, 5 * 2**attempt)
                print(f"    … rate limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception:  # noqa: BLE001
            if attempt == 5:
                raise
            time.sleep(2 * (attempt + 1))
    else:
        return False
    if len(data) < 500:
        return False
    with open(dest, "wb") as fh:
        fh.write(data)
    return True


def load_index():
    if os.path.exists(INDEX):
        with open(INDEX) as fh:
            return json.load(fh)
    return {}


def save_index(index):
    save_json(INDEX, index)


def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, value):
    # Via a temp file: a --suggestions run and a --film run can be in flight at
    # once, and a half-written index reads as no index at all.
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def poster_name(title, year, url):
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    return slug(title, year) + ext


def fetch_suggestions(force=False):
    """Posters for the films on the suggestions page.

    These already carry a Wikidata QID from the candidate pool, so there is no
    matching to do — straight to the sitelink and the article's lead image. The
    ranking shifts as ratings change, so this is worth rerunning now and then;
    everything already downloaded is skipped.
    """
    autofill.load_cache()
    os.makedirs(OUT, exist_ok=True)

    entries = load_json(DATA, {}).get("suggestions", {}).get("films", [])
    if not entries:
        print("no suggestions in data.json — run scripts/extract.py first")
        return
    index = load_json(SUGGEST_INDEX, {})
    owned = load_json(INDEX, {})

    wanted = {}  # film key -> (title, year, qid)
    for entry in entries:
        if not entry.get("qid"):
            continue
        key = io.film_key(entry["title"], entry.get("year"))
        # A film already in the sheet has its own poster; never fetch it twice.
        if key in owned:
            continue
        have = index.get(key)
        if have and os.path.exists(os.path.join(OUT, have)) and not force:
            continue
        wanted[key] = (entry["title"], entry.get("year"), entry["qid"])

    print(f"{len(entries)} suggestions, {len(wanted)} without a poster")
    if not wanted:
        return

    links = sitelinks(sorted({qid for _, _, qid in wanted.values()}))
    autofill.save_cache()
    print(f"{len(links)} have an English Wikipedia article")

    articles = {key: links[qid] for key, (_, _, qid) in wanted.items() if qid in links}
    thumbs = thumbnails(sorted(set(articles.values())))
    print(f"{len(thumbs)} articles have a lead image")

    got = failed = 0
    for key, article in sorted(articles.items()):
        url = thumbs.get(article)
        if not url:
            continue
        title, year, _ = wanted[key]
        name = poster_name(title, year, url)
        try:
            if download(url, os.path.join(OUT, name)):
                index[key] = name
                got += 1
                save_json(SUGGEST_INDEX, index)
                time.sleep(1.0)  # be a polite guest on Wikimedia's servers
            else:
                failed += 1
        except Exception as err:  # noqa: BLE001
            print(f"  ! {title}: {err}", file=sys.stderr)
            failed += 1

    save_json(SUGGEST_INDEX, index)
    print(f"downloaded {got}, failed {failed}; {len(index)} suggestions have a poster")


def adopt_suggestion_poster(title, year, index):
    """Reuse a poster already fetched for the suggestions page.

    Adding a film from that page would otherwise re-resolve and re-download the
    identical image; the file is right there, so just claim it.
    """
    key = io.film_key(title, year)
    name = load_json(SUGGEST_INDEX, {}).get(key)
    if not name or not os.path.exists(os.path.join(OUT, name)):
        return None
    index[key] = name
    save_index(index)
    return name


def find_article(title, year):
    """Best Wikipedia article for one film, or None if nothing is confident.

    Tries the Wikidata item first, then falls back to searching — same rules as
    the batch run, so a newly added film is held to the same standard.
    """
    try:
        pick = autofill.pick(autofill.candidates_for(title), year, title)
    except autofill.ApiUnavailable:
        pick = None
    if pick:
        article = sitelinks([pick["qid"]]).get(pick["qid"])
        if article:
            return article

    hits = search_articles(title, year)
    confirmed = confirm_films(hits)
    for article in hits:
        ent = confirmed.get(article)
        if not ent or not title_matches(title, article):
            continue
        if year is not None:
            years = {autofill.year_of(d) for d in ent.get("dates", [])}
            years.discard(None)
            if years and not any(abs(y - year) <= 1 for y in years):
                continue
        return article
    return None


def fetch_one(title, year=None, force=False):
    """Download the poster for a single film. Returns the filename or None."""
    autofill.load_cache()
    os.makedirs(OUT, exist_ok=True)
    index = load_index()
    key = io.film_key(title, year)

    if index.get(key) and os.path.exists(os.path.join(OUT, index[key])) and not force:
        return index[key]

    if not force:
        adopted = adopt_suggestion_poster(title, year, index)
        if adopted:
            return adopted

    article = find_article(title, year)
    autofill.save_cache()
    if not article:
        return None

    url = thumbnails([article]).get(article)
    if not url:
        return None

    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        ext = ".jpg"
    name = slug(title, year) + ext
    if not download(url, os.path.join(OUT, name)):
        return None

    index[key] = name
    save_index(index)
    return name


def main():
    # The suggestions page: films that aren't in the sheet at all.
    if "--suggestions" in sys.argv:
        fetch_suggestions(force="--force" in sys.argv)
        return

    # Single-film mode, used by the server when a film is added.
    if "--film" in sys.argv:
        i = sys.argv.index("--film")
        title = sys.argv[i + 1]
        year = None
        if "--year" in sys.argv:
            try:
                year = int(sys.argv[sys.argv.index("--year") + 1])
            except (ValueError, IndexError):
                year = None
        name = fetch_one(title, year, force="--force" in sys.argv)
        print(json.dumps({"ok": bool(name), "title": title, "poster": name}))
        return

    force = "--force" in sys.argv
    autofill.load_cache()
    os.makedirs(OUT, exist_ok=True)

    table = io.films_table(io.open_doc())
    rows = table.rows(values_only=True)
    films = [r for r in rows[1:] if r[io.COL_TITLE]]
    print(f"{len(films)} films")

    # Resolve each film to a QID using the cached matcher — no new lookups for
    # anything autofill already saw.
    # Keyed by (title, year): same-title films are different films and must not
    # share a poster.
    qid_of, unmatched, film_of = {}, [], {}
    for row in films:
        title = str(row[io.COL_TITLE]).strip()
        year = io.year_of(row[io.COL_YEAR])
        key = io.film_key(title, year)
        film_of[key] = (title, year)
        try:
            cands = autofill.candidates_for(title)
        except autofill.ApiUnavailable:
            unmatched.append(key)
            continue
        pick = autofill.pick(cands, year, title)
        if pick:
            qid_of[key] = pick["qid"]
        else:
            unmatched.append(key)
    autofill.save_cache()
    print(f"resolved {len(qid_of)} to Wikidata")

    links = sitelinks(sorted(set(qid_of.values())))
    autofill.save_cache()
    print(f"{len(links)} have an English Wikipedia article")

    wanted = {k: links[q] for k, q in qid_of.items() if q in links}
    thumbs = thumbnails(sorted(set(wanted.values())))
    print(f"{len(thumbs)} articles have a lead image")

    index = {}
    if os.path.exists(INDEX) and not force:
        with open(INDEX) as fh:
            index = json.load(fh)

    def fetch_all(mapping, thumbs, index):
        """Download a poster per {film key: article} pair. Returns counts."""
        got = skipped = failed = 0
        for key, article in sorted(mapping.items()):
            url = thumbs.get(article)
            if not url:
                continue
            title, year = film_of[key]
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower() or ".jpg"
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                ext = ".jpg"
            name = slug(title, year) + ext
            dest = os.path.join(OUT, name)
            if index.get(key) == name and os.path.exists(dest) and not force:
                skipped += 1
                continue
            try:
                if download(url, dest):
                    index[key] = name
                    got += 1
                    time.sleep(1.0)  # be a polite guest on Wikimedia's servers
                else:
                    failed += 1
            except Exception as err:  # noqa: BLE001
                print(f"  ! {title}: {err}", file=sys.stderr)
                failed += 1
        return got, skipped, failed

    got, skipped, failed = fetch_all(wanted, thumbs, index)

    # Second pass: search for anything still missing.
    still = [r for r in films if io.film_key(str(r[io.COL_TITLE]).strip(), io.year_of(r[io.COL_YEAR])) not in index]
    if still:
        print(f"\nsearching for {len(still)} films with no poster yet…", flush=True)
        found = {}
        for row in still:
            title = str(row[io.COL_TITLE]).strip()
            year = io.year_of(row[io.COL_YEAR])
            key = io.film_key(title, year)
            hits = search_articles(title, year)
            confirmed = confirm_films(hits)
            # Search rank alone is not evidence: require the article title to
            # match, and the year too when the sheet records one.
            pick = None
            for article in hits:
                ent = confirmed.get(article)
                if not ent or not title_matches(title, article):
                    continue
                if year is not None:
                    years = {autofill.year_of(d) for d in ent.get("dates", [])}
                    years.discard(None)
                    if years and not any(abs(y - year) <= 1 for y in years):
                        continue
                pick = article
                break
            if pick:
                found[key] = pick
                print(f"  {title} ({year or '?'})  ->  {pick}", flush=True)
            else:
                print(f"  {title} ({year or '?'})  ->  (no confident match)", flush=True)
        autofill.save_cache()
        if found:
            more = thumbnails(sorted(set(found.values())))
            g2, s2, f2 = fetch_all(found, more, index)
            got, skipped, failed = got + g2, skipped + s2, failed + f2

    with open(INDEX, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")

    missing = [
        f"{str(r[io.COL_TITLE]).strip()} ({io.year_of(r[io.COL_YEAR]) or '?'})"
        for r in films
        if io.film_key(str(r[io.COL_TITLE]).strip(), io.year_of(r[io.COL_YEAR])) not in index
    ]
    print(f"\ndownloaded {got}, already had {skipped}, failed {failed}")
    print(f"{len(index)} of {len(films)} films have a poster")
    print(f"\nno poster ({len(missing)}):")
    for t in missing:
        print("  -", t)


if __name__ == "__main__":
    main()
