#!/usr/bin/env python3
"""Find the official YouTube trailer for each film.

    python3 scripts/trailers.py              # dry run
    python3 scripts/trailers.py --apply      # write trailers.json
    python3 scripts/trailers.py --refresh    # re-pick films already recorded
    python3 scripts/trailers.py --only TITLE # one film, printing every candidate

There is no free trailer database. Wikidata's YouTube video id (P1651) sits on
about one film in seven here and isn't necessarily a trailer when it is there,
and TMDB's /videos endpoint wants an API key this repo doesn't have. So this
reads YouTube's own search results and picks from them.

Picking is the whole job. A search for "<film> official trailer" returns the
distributor's upload alongside reaction videos, fan edits, "ending explained",
and full-movie reuploads, and the top hit is regularly one of those — searching
Ne Zha 2 puts a channel that never distributed it first. So a candidate has to
earn the slot: it must say trailer or teaser, must not say any of the words
that mark a video *about* a trailer, must run for a trailer's length, and must
carry enough of the film's title to be that film rather than its sequel. What
survives is scored, distributor channels above the aggregators that mirror them
unedited, and the best one is confirmed against YouTube's oembed endpoint —
which is also the check that it is embeddable at all, since an upload that
blocks embedding would render as a dead grey box on the film page.

Only the video id is stored. The page loads YouTube's own player, which is how
the studios mean these to be watched, and means no video is copied anywhere.

Scraped HTML is a brittle source: YouTube changes the shape of ytInitialData
every so often, and when it does this prints "no candidates" for everything
rather than writing nonsense. trailers.json is the durable artifact — a rerun
only fills in what's missing unless you pass --refresh.
"""
import collections
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numbers_io as io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "trailers.json")

SEARCH = "https://www.youtube.com/results?search_query={}&sp=EgIQAQ%3D%3D"  # videos only
OEMBED = "https://www.youtube.com/oembed?url={}&format=json"
WATCH = "https://www.youtube.com/watch?v={}"
UA = "Mozilla/5.0 (compatible; screened/1.0; personal film list)"

# Channels that release their own films' trailers. When the distributor is in
# the results it is the answer, so these outrank everything else. Matched as
# substrings of the channel name, which is why "a24" and not "A24 Films" — the
# same studio posts under several names across regions.
STUDIO = (
    "a24", "netflix", "warner bros", "warnerbros", "sony pictures", "universal pictures",
    "paramount pictures", "paramount plus", "walt disney", "disney", "pixar", "marvel",
    "lucasfilm", "20th century", "searchlight", "focus features", "lionsgate", "neon",
    "mubi", "gkids", "well go usa", "shout studios", "ifc films", "magnolia pictures",
    "bleecker street", "sony pictures classics", "studiocanal", "a24films", "apple tv",
    "prime video", "hbo max", "max", "hulu", "crunchyroll", "funimation", "toho",
    "studio ghibli", "ghibli", "cmc pictures", "cj entertainment", "showbox", "next entertainment",
    "plus m entertainment", "aniplex", "sony pictures entertainment", "mgm", "amazon mgm",
    "roadshow", "madman", "altitude films", "vertigo releasing", "curzon", "picturehouse",
    "kino lorber", "janus films", "criterion", "sundance", "annapurna", "blumhouse",
    "legendary", "illumination", "dreamworks", "columbia pictures", "tristar",
    "china lion", "emperor motion pictures", "media asia", "edko films", "applause entertainment",
)

# Aggregators that mirror studio trailers unedited. Second choice: the video is
# the real trailer, just not from the studio's own channel.
AGGREGATOR = (
    "rotten tomatoes", "movieclips", "ign", "kinocheck", "one media", "filmselect",
    "fandango", "joblo", "screen culture", "flixster", "trailer city", "film trailer zone",
    "movie trailers source", "comingsoon", "yahoo movies", "empire magazine",
)

# Words that mark a video *about* a trailer, or a different kind of clip. Any of
# these and the candidate is out regardless of how well it scores otherwise.
JUNK = re.compile(
    r"\b(reaction|reacts?|review|breakdown|explained|explain|recap|ending|"
    r"full movie|fan[\s-]?made|fan[\s-]?trailer|fan[\s-]?edit|concept|parody|spoof|"
    r"honest trailer|honest trailers|\bedit\b|amv|ranking|ranked|top \d+|"
    r"behind the scenes|making of|interview|soundtrack|\bost\b|score|"
    r"deleted scene|first \d+ minutes|bloopers|gag reel|easter eggs|"
    r"everything wrong|\bvs\.?\b|compilation|\bai\b|remake)\b",
    re.IGNORECASE,
)
WANTED = re.compile(r"\b(trailer|teaser)\b", re.IGNORECASE)
OFFICIAL = re.compile(r"\bofficial\b", re.IGNORECASE)

# A trailer runs a minute or two. Teasers dip under 30s; some international
# cuts and "final trailers" run long. Outside this is a clip or the film.
MIN_SECONDS, MAX_SECONDS = 15, 360

STOPWORDS = {"the", "a", "an", "of", "and", "in", "on", "to", "part", "movie", "film"}

# Boilerplate every trailer title carries. Stripped before asking how much of a
# video's title is *not* the film — see precision() for why that question is
# worth asking.
BOILERPLATE = re.compile(
    r"\b(official|officiel|oficial|trailer|trailers|teaser|tráiler|preview|hd|fhd|4k|60fps|uhd|"
    r"full|new|final|original|theatrical|international|domestic|red band|green band|"
    r"restored|remastered|bluray|blu|ray|dvd|vhs|"
    r"in cinemas|in theaters|in theatres|now showing|coming soon|out now|"
    r"english|eng|sub|subs|subtitles|subtitled|dub|dubbed|version|cut|"
    r"movie|film|clip|exclusive|watch|now|available|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)


def fetch(url, timeout=30):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def video_renderers(node):
    """Every videoRenderer in ytInitialData, wherever YouTube has nested it.

    The shelf structure around results changes often; the renderer itself has
    been stable, so walk the whole tree rather than a fixed path into it.
    """
    if isinstance(node, dict):
        if "videoRenderer" in node and isinstance(node["videoRenderer"], dict):
            yield node["videoRenderer"]
        for value in node.values():
            yield from video_renderers(value)
    elif isinstance(node, list):
        for value in node:
            yield from video_renderers(value)


def runs(block):
    if not isinstance(block, dict):
        return ""
    if "simpleText" in block:
        return str(block["simpleText"])
    return "".join(r.get("text", "") for r in block.get("runs", []))


def seconds(text):
    """"1:24" -> 84. None when YouTube gave no duration (a live stream)."""
    if not text:
        return None
    parts = text.strip().split(":")
    if not all(p.isdigit() for p in parts) or not 1 <= len(parts) <= 3:
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def search(title, year):
    """Candidates for one film: [{id, title, channel, seconds}]."""
    terms = f'"{title}" {year} official trailer' if year else f'"{title}" official trailer'
    try:
        html = fetch(SEARCH.format(urllib.parse.quote(terms)))
    except (urllib.error.URLError, OSError) as err:
        print(f"    search failed: {err}", flush=True)
        return []

    match = re.search(r"ytInitialData\s*=\s*(\{.*?\})\s*;\s*</script>", html)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return []

    out, seen = [], set()
    for renderer in video_renderers(data):
        vid = renderer.get("videoId")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(
            {
                "id": vid,
                "title": runs(renderer.get("title", {})),
                "channel": runs(renderer.get("ownerText", {}))
                or runs(renderer.get("longBylineText", {})),
                "seconds": seconds(runs(renderer.get("lengthText", {}))),
            }
        )
    return out


def tokens(title):
    words = re.findall(r"[a-z0-9]+", str(title).lower())
    kept = [w for w in words if w not in STOPWORDS]
    return set(kept or words)


def overlap(film_title, video_title):
    """How much of the film's title the video's title carries, 0..1.

    This is what keeps a sequel's trailer off the original's page: searching
    "Ne Zha" surfaces Ne Zha 2, whose extra token costs it nothing, but the
    reverse — Ne Zha's trailer offered for Ne Zha 2 — is missing a token and
    falls below the floor.
    """
    want = tokens(film_title)
    if not want:
        return 0.0
    have = tokens(video_title)
    return len(want & have) / len(want)


def precision(film_title, video_title, channel):
    """How much of the video's title is the film, 0..1, once boilerplate is out.

    Overlap alone asks only whether the film's words are present, which a
    one-word title answers far too easily: searching Exiled (2006) turned up a
    documentary called "Exiled - The Story Of Skullfades", 100% overlap on the
    single token "exiled". Asking the question the other way — of what is left
    after "official trailer HD 2025" and the channel's own name, how much is
    the film? — is what separates the two, since the documentary's title is
    mostly words the film's title never had.
    """
    rest = BOILERPLATE.sub(" ", video_title)
    rest = re.sub(r"\b(?:19|20)\d{2}\b", " ", rest)
    rest = re.sub(r"#\d+", " ", rest)
    leftover = tokens(rest) - tokens(channel or "")
    if not leftover:
        return 1.0
    return len(tokens(film_title) & leftover) / len(leftover)


# A sequel number, in either of the two ways films write one. Years and trailer
# numbers are stripped before this looks, so only 2..9 and the small romans
# count — which also keeps "96 minutes" and "2046" out of it.
SEQUEL = re.compile(r"\b([2-9]|ii|iii|iv|v|vi|vii|viii|ix)\b", re.IGNORECASE)
ROMAN = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9}
TRAILER_NUMBER = re.compile(r"\b(?:trailer|teaser|part)\s*#?\s*\d+", re.IGNORECASE)


def sequel_numbers(title):
    """{2} for "Ip Man 2" and "Ne Zha II"; empty for "Ip Man"."""
    bare = TRAILER_NUMBER.sub(" ", title)
    bare = re.sub(r"\b(?:19|20)\d{2}\b", " ", bare)
    bare = re.sub(r"#\d+", " ", bare)
    out = set()
    for token in SEQUEL.findall(bare):
        out.add(ROMAN.get(token.lower(), None) or (int(token) if token.isdigit() else None))
    return {n for n in out if n}


def score(film_title, year, candidate, strict_year=False):
    """Rank a candidate, or None if it is disqualified.

    Returns (points, reason) so --only can show why each one placed where it
    did; picking trailers by eye is how the channel lists above got written.
    """
    video_title, channel = candidate["title"], candidate["channel"] or ""
    if not WANTED.search(video_title):
        return None, "no 'trailer' in the title"
    if JUNK.search(video_title):
        return None, "reads as a video about the film, not a trailer"
    length = candidate["seconds"]
    if length is None or not MIN_SECONDS <= length <= MAX_SECONDS:
        return None, f"runs {length}s"

    share = overlap(film_title, video_title)
    if share < 0.6:
        return None, f"title overlap {share:.0%}"

    # Overlap can't tell a film from its sequel: every word of "Ip Man" is in
    # "Ip Man 2". The number is the whole difference, so it has to agree.
    if sequel_numbers(film_title) != sequel_numbers(video_title):
        return None, "sequel number doesn't match"

    exact = precision(film_title, video_title, channel)
    # A one- or two-word title is matched by too much — "Exiled" alone picked up
    # a documentary called "Exiled - The Story Of Skullfades". Longer titles
    # clear 60% overlap only by being the film, so holding them to this as well
    # cost four of them a trailer for no gain.
    if exact < 0.4 and len(tokens(film_title)) <= 2:
        return None, f"short title, and the video's is {1 - exact:.0%} other words"

    points = share * 3 + exact * 2
    reason = [f"overlap {share:.0%}", f"precision {exact:.0%}"]

    low_channel = channel.lower()
    if any(name in low_channel for name in STUDIO):
        points += 6
        reason.append("studio channel")
    elif any(name in low_channel for name in AGGREGATOR):
        points += 3
        reason.append("aggregator")

    if OFFICIAL.search(video_title):
        points += 3
        reason.append("official")
    if re.search(r"\btrailer\b", video_title, re.IGNORECASE):
        points += 1

    # A year in the video's title that isn't the film's is usually a different
    # film with the same name, or a re-release cut.
    years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", video_title)]
    if year and years:
        if any(abs(y - year) <= 1 for y in years):
            points += 1
            reason.append("year matches")
        else:
            # A remake states its own year, and otherwise looks exactly like
            # the original to every test above — which is how the 1978 Enter
            # the Fat Dragon ended up showing the 2020 one. A video that names
            # a year is telling us which film it is; believe it.
            return None, f"names {years[0]}, not {year}"
    elif strict_year:
        # The sheet holds more than one film by this name, so a candidate that
        # never says which year it is cannot be told apart from its namesake —
        # and silently giving both Mulans the same trailer is worse than
        # leaving one blank.
        return None, "title is ambiguous and the video names no year"

    return points, ", ".join(reason)


def confirm(video_id):
    """Ask YouTube for the video's own metadata.

    Doubles as the embeddable check: oembed 401s for a video whose owner has
    turned embedding off, which is exactly the video we must not pick.
    """
    try:
        raw = fetch(OEMBED.format(urllib.parse.quote(WATCH.format(video_id), safe="")), timeout=20)
        return json.loads(raw)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def pick(title, year, verbose=False, strict_year=False):
    """The best trailer for one film, or None."""
    candidates = search(title, year)
    if verbose:
        print(f"  {len(candidates)} results")

    ranked = []
    for candidate in candidates:
        points, reason = score(title, year, candidate, strict_year)
        if verbose:
            mark = f"{points:5.1f}" if points is not None else "   — "
            print(f"    {mark}  {candidate['channel'][:24]:24} {candidate['title'][:56]}")
            print(f"           {reason}")
        if points is not None:
            ranked.append((points, candidate))

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    for points, candidate in ranked[:3]:
        meta = confirm(candidate["id"])
        if not meta:
            if verbose:
                print(f"    {candidate['id']} is not embeddable; trying the next")
            continue
        return {
            "id": candidate["id"],
            # oembed's title and author are YouTube's own, so a renamed video
            # shows its real name rather than whatever search returned.
            "title": meta.get("title") or candidate["title"],
            "channel": meta.get("author_name") or candidate["channel"],
            "seconds": candidate["seconds"],
            "url": WATCH.format(candidate["id"]),
        }
    return None


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


def main():
    argv = sys.argv[1:]
    apply = "--apply" in argv
    refresh = "--refresh" in argv
    only = None
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]

    table = io.films_table(io.open_doc())
    films = [r for r in table.rows(values_only=True)[1:] if r[io.COL_TITLE]]

    # Titles the sheet holds twice (three Mulans, two Legend of Hei). Computed
    # over the whole sheet, not the --only slice, so narrowing to one film
    # doesn't quietly relax the check that keeps it apart from its namesake.
    counts = collections.Counter(str(r[io.COL_TITLE]).strip().lower() for r in films)
    ambiguous = {title for title, n in counts.items() if n > 1}

    found = read(DST, {})
    if refresh:
        found = {}

    if only:
        rows = [r for r in films if str(r[io.COL_TITLE]).strip().lower() == only.lower()]
        if not rows:
            sys.exit(f"no film called {only!r} in the sheet")
        films = rows

    added = 0
    for n, row in enumerate(films, 1):
        title = str(row[io.COL_TITLE]).strip()
        year = io.year_of(row[io.COL_YEAR])
        key = io.film_key(title, year)
        if key in found and not only:
            continue

        if only:
            print(f"{title} ({year})")
        trailer = pick(title, year, verbose=bool(only), strict_year=title.lower() in ambiguous)
        if trailer:
            found[key] = trailer
            added += 1
            print(f"  {title[:32]:32} {trailer['id']}  {trailer['channel'][:26]}", flush=True)
        else:
            print(f"  {title[:32]:32} —", flush=True)

        # Two hundred searches take a few minutes, and a run that dies at film
        # 180 should not throw away the first 179. Saving as we go also means
        # a rerun picks up where this left off.
        if apply and not only and added and n % 20 == 0:
            write(DST, found)

        # One search per film against a page that isn't an API; don't hammer it.
        if n < len(films):
            time.sleep(1.2)

    print(f"\n{added} trailers found; {len(found)} of {len(films)} films have one")

    if not apply:
        print("dry run; nothing written")
        return
    write(DST, found)
    print(f"wrote {DST}")


if __name__ == "__main__":
    main()
