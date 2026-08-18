#!/usr/bin/env python3
"""Find a portrait for each director and save it under public/portraits/.

    python3 scripts/director_photos.py [--force] [--only NAME] [--dry-run]

Wikidata carries the portrait directly as P18, so this needs no article
matching: the director's own item names the file, and Commons serves a thumb of
it. That is a far shorter path than posters.py has to take for films, and it
cannot pick the wrong picture the way a title search can.

Directors already resolved by directors.py have a qid. The rest are searched for
by name and only accepted when the label matches exactly, the item is a human,
and its occupations include directing — the same "leave it blank rather than
guess" rule autofill.py uses.

Unlike the posters, these are freely licensed: Commons hosts no fair-use media.
The licence and author come back with the image and are stored beside it, and
the pages show them, since CC BY-SA needs the credit visible.

Writes director-photos.json; extract.py folds it into data.json.
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import posters
import wikidata as wd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "portraits")
INDEX = os.path.join(ROOT, "director-photos.json")
DATA = os.path.join(ROOT, "data.json")
DIRECTORS = os.path.join(ROOT, "directors.json")

COMMONS = "https://commons.wikimedia.org/w/api.php"
# The cards are ~260px wide, so 320 covers them with room to spare. Above ~340
# Commons stops generating a thumb and hands back the original for the portraits
# that are small to begin with — 35KB a head becomes 180KB, 5MB becomes 27MB.
THUMB_WIDTH = 320

HUMAN = "Q5"
# Occupations that count as directing, so a search hit for an actor of the same
# name is not accepted as the director.
DIRECTING = {
    "Q2526255",  # film director
    "Q3455803",  # director
    "Q5322166",  # television director
    "Q715301",   # animator
    "Q1053574",  # executive producer — often the only credit on older items
}
# wbgetentities takes fifty ids per call.
CHUNK = 50


def media_values(claims, prop):
    """Filenames for a commonsMedia property.

    wikidata.claim_values only yields entity ids and timestamps, so it drops
    these — P18 is a plain string. Left alone rather than widened, since
    autofill.py depends on that filtering.
    """
    out = []
    for claim in claims.get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    return out


def sniff(path):
    """Actual image format from the file's magic bytes, not from the URL."""
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


def strip_tags(value):
    """Commons returns the author as a fragment of HTML."""
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip() or None


def commons(params):
    """One Commons API call, sharing posters.py's retry and rate limiting."""
    url = COMMONS + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": wd.UA})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < 5:
                wait = int(err.headers.get("Retry-After") or 0) or min(60, 5 * 2**attempt)
                print(f"    … rate limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            if attempt == 5:
                return None
        except Exception:  # noqa: BLE001
            if attempt == 5:
                return None
    return None


def portraits_for(qids):
    """{qid: P18 filename} for as many of these items as have one."""
    found = {}
    for i in range(0, len(qids), CHUNK):
        chunk = qids[i : i + CHUNK]
        data = wd.api(
            {"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims"}
        )
        for qid, ent in ((data or {}).get("entities") or {}).items():
            files = media_values(ent.get("claims") or {}, "P18")
            if files:
                found[qid] = files[0]
    return found


def resolve(name):
    """Wikidata id for a director not already resolved, or None if unsure."""
    hits = wd.api(
        {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "type": "item",
            "limit": 8,
        }
    )
    ids = [
        h["id"]
        for h in (hits or {}).get("search", [])
        # An exact label is the whole guard against picking a different person.
        if (h.get("label") or "").strip().lower() == name.strip().lower()
    ]
    if not ids:
        return None
    data = wd.api({"action": "wbgetentities", "ids": "|".join(ids[:CHUNK]), "props": "claims"})
    for qid in ids:
        claims = ((data or {}).get("entities") or {}).get(qid, {}).get("claims") or {}
        if HUMAN not in wd.claim_values(claims, "P31"):
            continue
        if not set(wd.claim_values(claims, "P106")) & DIRECTING:
            continue
        return qid
    return None


def image_info(filename):
    """Thumb url, licence and author for one Commons file."""
    data = commons(
        {
            "action": "query",
            "titles": f"File:{filename}",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": THUMB_WIDTH,
        }
    )
    for page in ((data or {}).get("query") or {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("thumburl"):
            continue
        meta = info.get("extmetadata") or {}
        strip = lambda key: (meta.get(key) or {}).get("value")  # noqa: E731
        return {
            "url": info["thumburl"],
            "licence": strip("LicenseShortName"),
            "author": strip_tags(strip("Artist")),
            "file": filename,
        }
    return None


def main():
    args = sys.argv[1:]
    force = "--force" in args
    dry_run = "--dry-run" in args
    only = None
    if "--only" in args:
        i = args.index("--only")
        if i + 1 >= len(args):
            sys.exit("--only needs a name")
        only = args[i + 1].strip().lower()

    if not os.path.exists(DATA):
        sys.exit("no data.json — run scripts/extract.py first")
    with open(DATA) as fh:
        directors = json.load(fh)["directors"]
    if only:
        directors = [d for d in directors if d["name"].lower() == only]
        if not directors:
            sys.exit(f"{only} is not a director in the list")

    known = {}
    if os.path.exists(DIRECTORS):
        with open(DIRECTORS) as fh:
            known = {name: v.get("qid") for name, v in json.load(fh).items()}

    index = {}
    if os.path.exists(INDEX):
        with open(INDEX) as fh:
            index = json.load(fh)

    todo = [d for d in directors if force or d["name"] not in index]
    print(f"{len(todo)} of {len(directors)} director(s) to fetch")
    if not todo:
        return 0

    # Resolve any that directors.py never got a qid for.
    qid_of, unresolved = {}, []
    for director in todo:
        qid = known.get(director["name"])
        if not qid:
            qid = resolve(director["name"])
        if qid:
            qid_of[director["name"]] = qid
        else:
            unresolved.append(director["name"])
    print(f"{len(qid_of)} resolved to a Wikidata item")

    files = portraits_for(sorted(set(qid_of.values())))
    print(f"{len(files)} of those have a portrait on Wikidata")

    os.makedirs(OUT, exist_ok=True)

    def save():
        tmp = INDEX + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, INDEX)

    written, no_image = 0, []
    for n, director in enumerate(todo, 1):
        name = director["name"]
        qid = qid_of.get(name)
        filename = files.get(qid) if qid else None
        if not filename:
            no_image.append(name)
            continue

        info = image_info(filename)
        if not info:
            no_image.append(name)
            print(f"  ! {name} — Commons gave no thumb for {filename}", flush=True)
            continue

        if dry_run:
            print(f"  = {name} — would save {filename} ({info['licence']})", flush=True)
            continue

        # Extension comes from the bytes, not the URL, same as the posters.
        stem = os.path.join(OUT, director["slug"])
        tmp = stem + ".tmp"
        try:
            if not posters.download(info["url"], tmp):
                no_image.append(name)
                continue
        except Exception as err:  # noqa: BLE001
            print(f"  ! {name} — download failed: {err}", flush=True)
            no_image.append(name)
            continue
        ext = sniff(tmp)
        if not ext:
            os.remove(tmp)
            no_image.append(name)
            print(f"  ! {name} — not an image we recognise", flush=True)
            continue
        dest = stem + ext
        os.replace(tmp, dest)

        index[name] = {
            "photo": os.path.basename(dest),
            "licence": info["licence"],
            "author": info["author"],
            "file": info["file"],
            "qid": qid,
        }
        written += 1
        print(f"  + {name} — {os.path.basename(dest)} ({info['licence']})", flush=True)
        if written % 10 == 0:
            save()

    if not dry_run:
        save()

    print(f"\n{written} portrait(s) saved to {os.path.relpath(OUT, ROOT)}")
    if no_image:
        print(f"{len(no_image)} with no portrait on Wikidata:")
        for name in no_image[:15]:
            print(f"  - {name}")
        if len(no_image) > 15:
            print(f"  … and {len(no_image) - 15} more")
    if unresolved:
        print(f"{len(unresolved)} could not be matched to a Wikidata item confidently:")
        for name in unresolved[:10]:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
