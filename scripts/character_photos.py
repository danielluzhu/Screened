#!/usr/bin/env python3
"""Find a portrait for each character in the Characters sheet.

    python3 scripts/character_photos.py [--force] [--only NAME]

Wikipedia is a poor source here: most anime characters have no article of their
own, and a loose search returns the *series* article, whose lead image is the
show's poster — the same picture on several characters, presented as a portrait
of each. Fandom wikis run MediaWiki with the same API and do have a page per
character with proper artwork, so those come first.

A page is only accepted when it is a character page on the right wiki: subpages
(/Synopsis, /Image Gallery) are dropped, redirects are followed so short names
like "Bakugo" reach "Katsuki Bakugo", and the page must sit in a Characters
category. Wikipedia is the fallback for live-action or non-anime characters.

Images are copyrighted series artwork, kept locally for a private list — the
same footing as the film posters.

Writes character-photos.json; extract.py folds it into data.json.
"""
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
import posters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "characters")
INDEX = os.path.join(ROOT, "character-photos.json")

# The sheet abbreviates shows; each maps to its Fandom wiki.
WIKIS = {
    "jjk": "jujutsu-kaisen.fandom.com",
    "jujutsu kaisen": "jujutsu-kaisen.fandom.com",
    "bnha": "myheroacademia.fandom.com",
    "mha": "myheroacademia.fandom.com",
    "my hero academia": "myheroacademia.fandom.com",
    "naruto": "naruto.fandom.com",
    "code geass": "codegeass.fandom.com",
    "death note": "deathnote.fandom.com",
    "bleach": "bleach.fandom.com",
    "one punch man": "onepunchman.fandom.com",
    "one-punch man": "onepunchman.fandom.com",
    "aot": "attackontitan.fandom.com",
    "attack on titan": "attackontitan.fandom.com",
    "paranoia agent": "paranoia-agent.fandom.com",
    "parasyte": "parasyte.fandom.com",
}

_last = [0.0]
MIN_GAP = 0.6


def api(host, params):
    url = f"https://{host}/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": autofill.UA})
    for attempt in range(4):
        gap = MIN_GAP - (time.monotonic() - _last[0])
        if gap > 0:
            time.sleep(gap)
        _last[0] = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < 3:
                time.sleep(int(err.headers.get("Retry-After") or 0) or 5 * (attempt + 1))
                continue
            if attempt == 3:
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:  # noqa: BLE001
            if attempt == 3:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def sniff(path):
    """Actual image format from the file's magic bytes."""
    with open(path, "rb") as fh:
        head = fh.read(16)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if head[:2] == b"\xff\xd8":
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return None


def is_character_page(host, title):
    """Fandom files character pages under a Characters category."""
    data = api(host, {"action": "query", "titles": title, "prop": "categories", "cllimit": 60})
    if not data:
        return False
    for page in data.get("query", {}).get("pages", {}).values():
        for cat in page.get("categories", []) or []:
            if "character" in cat.get("title", "").lower():
                return True
    return False


def wiki_page(host, name):
    """Best character page on this wiki, or None."""
    # A short name usually redirects to the full one ("Bakugo" -> "Katsuki Bakugo").
    direct = api(host, {"action": "query", "titles": name, "redirects": 1})
    if direct:
        pages = direct.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid != "-1" and "missing" not in page:
                title = page["title"]
                if is_character_page(host, title):
                    return title

    found = api(host, {"action": "query", "list": "search", "srsearch": name, "srlimit": 10})
    if not found:
        return None
    raw = [h["title"] for h in found.get("query", {}).get("search", [])]
    # Subpages (/Synopsis, /Relationships) aren't the character page, but they
    # do point at it — and rank highly. "Bakugo" ranks Katsuki's subpage first
    # while the top plain hit is his father, so fold subpages to their base
    # page and keep the original order.
    hits = []
    for title in raw:
        base = title.split("/")[0]
        if base not in hits:
            hits.append(base)

    needle = name.strip().lower()
    exact = [h for h in hits if h.strip().lower() == needle]
    worded = [h for h in hits if re.search(rf"(^|\s){re.escape(needle)}(\s|$)", h.lower())]
    for candidate in exact + worded + hits:
        if is_character_page(host, candidate):
            return candidate
    return None


def wiki_image(host, title):
    data = api(
        host,
        {
            "action": "query",
            "titles": title,
            "prop": "pageimages",
            "piprop": "original|thumbnail",
            "pithumbsize": 600,
            "pilicense": "any",
        },
    )
    if not data:
        return None
    for page in data.get("query", {}).get("pages", {}).values():
        original = (page.get("original") or {}).get("source")
        thumb = (page.get("thumbnail") or {}).get("source")
        # Prefer the full-size art; these are portrait renders, not screenshots.
        return original or thumb
    return None


def from_wikipedia(name, show):
    """Fallback for characters without a Fandom wiki."""
    queries = [f"{name} {show} character" if show else f"{name} character", name]
    seen = []
    for query in queries:
        for article in posters.search_articles(query, None, limit=6):
            if article not in seen:
                seen.append(article)

    def names_match(article):
        if posters.title_matches(name, article):
            return True
        bare = re.sub(r"\s*\([^)]*\)\s*$", "", article)
        return bool(re.search(rf"(^|\s){re.escape(name.lower())}(\s|$)", bare.lower()))

    named = [a for a in seen if names_match(a)]
    if not named:
        return None
    for article in named:
        url = posters.thumbnails([article]).get(article)
        if url:
            return url
    return None


def main():
    force = "--force" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    autofill.load_cache()
    os.makedirs(OUT, exist_ok=True)

    table = io.characters_table(io.open_doc())
    rows = [r for r in table.rows(values_only=True)[1:] if r and r[0]]
    print(f"{len(rows)} characters", flush=True)

    index = {}
    if os.path.exists(INDEX):
        with open(INDEX) as fh:
            index = json.load(fh)

    got = skipped = missing = 0
    for row in rows:
        name = str(row[0]).strip()
        show = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        if only and name.lower() != only.lower():
            continue
        if index.get(name) and os.path.exists(os.path.join(OUT, index[name])) and not force:
            skipped += 1
            continue

        url, source = None, None
        host = WIKIS.get(show.lower())
        if host:
            title = wiki_page(host, name)
            if title:
                url = wiki_image(host, title)
                source = f"{host}: {title}"
        if not url:
            url = from_wikipedia(name, show)
            source = "wikipedia" if url else None
            autofill.save_cache()

        if not url:
            print(f"  {name:20} -> no photo found", flush=True)
            missing += 1
            continue

        # Fandom serves WebP whatever the URL says, so name the file after what
        # actually arrived — the server picks its content-type by extension.
        path = urllib.parse.urlparse(url).path
        ext = ".jpg"
        for candidate in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            if candidate in path.lower():
                ext = candidate
                break
        filename = io.slug(name) + ext
        try:
            if posters.download(url, os.path.join(OUT, filename)):
                real = sniff(os.path.join(OUT, filename))
                if real and real != ext:
                    os.replace(os.path.join(OUT, filename), os.path.join(OUT, io.slug(name) + real))
                    filename = io.slug(name) + real
                index[name] = filename
                got += 1
                print(f"  {name:20} -> {source}  [{filename}]", flush=True)
            else:
                missing += 1
        except Exception as err:  # noqa: BLE001
            print(f"  ! {name}: {err}", file=sys.stderr)
            missing += 1

    with open(INDEX, "w") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    autofill.save_cache()
    print(f"\ndownloaded {got}, already had {skipped}, no photo {missing}")


if __name__ == "__main__":
    main()
