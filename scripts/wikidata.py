"""The Wikidata HTTP layer: rate limiting, retries, and a JSON-cache helper.

Only the transport lives here. What to ask for and how to interpret it is the
caller's business — autofill.py reads films, music_autofill.py reads songs, and
they keep separate caches because they store different claim sets under the
same QID keys.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.wikidata.org/w/api.php"
UA = "FavoritesSite/1.0 (personal film list)"

_last_call = [0.0]
MIN_GAP = 1.2  # seconds between requests; the API 429s well below its docs


class ApiUnavailable(Exception):
    """A lookup failed outright, so it is never cached as 'no match'."""


def api(params):
    """One API call, rate limited and retried. None when it never succeeded."""
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(6):
        gap = MIN_GAP - (time.monotonic() - _last_call[0])
        if gap > 0:
            time.sleep(gap)
        _last_call[0] = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 429:
                # Honour Retry-After when present, else back off exponentially.
                wait = int(err.headers.get("Retry-After") or 0) or min(60, 5 * 2**attempt)
                print(f"  … rate limited, waiting {wait}s", file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            if attempt == 5:
                print(f"  ! API error: {err}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == 5:
                print(f"  ! API error: {err}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))
    print("  ! giving up after repeated rate limits", file=sys.stderr)
    return None


def claim_values(claims, prop):
    """QIDs or timestamps for one property, dropping snaks with no value."""
    out = []
    for c in claims.get(prop, []):
        val = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(val, dict) and "id" in val:
            out.append(val["id"])
        elif isinstance(val, dict) and "time" in val:
            out.append(val["time"])
    return out


def year_of(stamp):
    """The year out of a Wikidata timestamp like '+1975-11-21T00:00:00Z'."""
    if not stamp or not isinstance(stamp, str):
        return None
    try:
        return int(stamp.lstrip("+")[:4])
    except ValueError:
        return None


def load_cache(path):
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {}


def save_cache(path, cache):
    # Written via a temp file: extract.py reads these caches on every run, and
    # a half-written file would leave a run with no results at all.
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cache, fh)
    os.replace(tmp, path)
