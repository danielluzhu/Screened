#!/usr/bin/env python3
"""Save a short summary of each film and its reception into summaries.json.

    python3 scripts/summaries.py                    # every film missing one
    python3 scripts/summaries.py --film "Parasite" --year 2019
    python3 scripts/summaries.py --force            # refetch ones already saved
    python3 scripts/summaries.py --dry-run          # print, don't write
    python3 scripts/summaries.py --lead-only        # skip the slow reception pass

The text is Wikipedia's, not ours and not invented: the lead section for what
the film is, then its critical response for how it landed. Writing these from a
model's own memory would mean inventing box-office figures and review scores for
189 films, most of them not English-language — so this quotes a source instead
and records the article it came from.

    Wikipedia text is CC BY-SA 4.0. Every summary is stored with the URL it came
    from and the film page renders it as a credited quotation. That is fine for a
    personal list; if this site ever goes public, keep the attribution visible.

Films whose article can't be confidently identified are skipped and listed at
the end rather than guessed at — the same rule posters.py uses.
"""
import json
import os
import re
import sys

import autofill
import extract
import numbers_io as io
import posters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "summaries.json")

# Where the reception paragraph comes from, best first. Wikipedia puts box
# office before critical response under "Reception", and the numbers are the
# less interesting half, so the critical subsection wins when it exists.
RECEPTION_HEADINGS = (
    "Critical response",
    "Critical reception",
    "Critical response and accolades",
    "Reception and legacy",
    "Reception",
    "Release and reception",
)

MAX_SENTENCES = 10
MIN_SENTENCES = 5
# A Wikipedia lead opens with what the film is and closes with how it landed;
# the middle is production trivia (which draft, who was cast when). Take both
# ends and drop the middle.
LEAD_OPENING = 3
LEAD_CLOSING = 2
FROM_RECEPTION = 4
MAX_CHARS = 1600

# Abbreviations that end in a period without ending a sentence. Without these
# the splitter breaks "U.S. Senator" and "Dr. Strangelove" into two sentences.
ABBREVIATIONS = (
    "Mr", "Mrs", "Ms", "Dr", "Prof", "St", "Jr", "Sr", "Rev", "Hon",
    "vs", "etc", "approx", "No", "Vol", "Inc", "Ltd", "Co", "Corp", "Est",
    "U.S", "U.K", "U.N", "e.g", "i.e", "cf", "al", "Ave", "Mt", "Ft",
)
_ABBR = re.compile(r"(?:" + "|".join(re.escape(a) for a in ABBREVIATIONS) + r")\.$")


def sentences(text):
    """Split prose into sentences, keeping abbreviations and decimals intact."""
    out = []
    # A sentence ends at .!? followed by space and something that can start one.
    for part in re.split(r'(?<=[.!?])\s+(?=[A-Z"“‘(\[])', text.strip()):
        if out and _ABBR.search(out[-1]):
            out[-1] += " " + part  # false break: glue it back on
        else:
            out.append(part)
    return [s.strip() for s in out if s.strip()]


def section(text, heading):
    """The prose under one heading, sub-headings stripped, or None."""
    pattern = re.compile(
        r"\n=+ " + re.escape(heading) + r" =+\n(.*?)(?=\n== [^=]|\Z)", re.S
    )
    match = pattern.search(text)
    if not match:
        return None
    body = re.sub(r"\n=+ [^=\n]+ =+\n", "\n", match.group(1))
    return body.strip() or None


def intro_of(text):
    """Everything before the first heading — Wikipedia's lead section."""
    return re.split(r"\n==+ ", text, 1)[0].strip()


# TextExtracts only batches intros: with exintro set, exlimit may go to 20, but
# a full-text extract is capped at one article per request no matter what
# exlimit says. Hence two passes — the leads come in tens, the reception
# sections one at a time.
INTRO_CHUNK = 20


def _pages(resp):
    """{requested title: extract}, following redirects back to what we asked."""
    out = {}
    if not resp:
        return out
    query = resp.get("query") or {}
    for page in (query.get("pages") or {}).values():
        if page.get("extract"):
            out[page["title"]] = page["extract"]
    for hop in list(query.get("redirects") or []) + list(query.get("normalized") or []):
        if hop.get("to") in out:
            out.setdefault(hop["from"], out[hop["to"]])
    return out


def article_intros(articles):
    """{article title: lead section}, twenty articles per request."""
    out = {}
    for i in range(0, len(articles), INTRO_CHUNK):
        chunk = articles[i : i + INTRO_CHUNK]
        out.update(
            _pages(
                posters.wiki_api(
                    {
                        "action": "query",
                        "prop": "extracts",
                        "explaintext": 1,
                        "exintro": 1,
                        "exlimit": len(chunk),
                        "redirects": 1,
                        "titles": "|".join(chunk),
                    }
                )
            )
        )
    return out


def article_text(article):
    """Full plain-text of one article, or None. One article per request."""
    return _pages(
        posters.wiki_api(
            {
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "redirects": 1,
                "titles": article,
            }
        )
    ).get(article)


def lead_sentences(intro):
    """The opening of a lead plus its closing, skipping the middle."""
    all_of = sentences(intro)
    if len(all_of) <= LEAD_OPENING + LEAD_CLOSING:
        return all_of
    return all_of[:LEAD_OPENING] + all_of[-LEAD_CLOSING:]


def compose(text):
    """5–10 sentences: what the film is, then how it was received."""
    lead = lead_sentences(intro_of(text))

    received = []
    for heading in RECEPTION_HEADINGS:
        body = section(text, heading)
        if body:
            received = sentences(body)[:FROM_RECEPTION]
            break

    picked = lead + received
    # Short lead and no reception section: take more of the article's opening
    # rather than return something under the floor.
    if len(picked) < MIN_SENTENCES:
        picked = sentences(intro_of(text))[:MAX_SENTENCES]
    picked = picked[:MAX_SENTENCES]

    summary = " ".join(picked)
    if len(summary) > MAX_CHARS:
        # Trim whole sentences, never mid-word.
        while len(summary) > MAX_CHARS and len(picked) > MIN_SENTENCES:
            picked.pop()
            summary = " ".join(picked)
    return summary, len(picked), bool(received)


def url_for(article):
    return "https://en.wikipedia.org/wiki/" + article.replace(" ", "_")


def films_from_sheet():
    table = io.films_table(io.open_doc())
    out = []
    for i, row in enumerate(table.rows(values_only=True)):
        if i == 0 or not row[io.COL_TITLE]:
            continue
        out.append((str(row[io.COL_TITLE]).strip(), io.year_of(row[io.COL_YEAR])))
    return out


def resolve_articles(films, index):
    """{(title, year): article} — batched, the way posters.py resolves them.

    Wikidata matching comes out of autofill's cache, then one sitelinks call
    covers every film at once. Anything already in summaries.json keeps the
    article it was fetched with, so --force doesn't re-resolve.
    """
    articles, qid_of = {}, {}
    for title, year in films:
        known = (index.get(io.film_key(title, year)) or {}).get("article")
        if known:
            articles[(title, year)] = known
            continue
        try:
            pick = autofill.pick(autofill.candidates_for(title), year, title)
        except autofill.ApiUnavailable:
            continue
        if pick:
            qid_of[(title, year)] = pick["qid"]
    autofill.save_cache()

    if qid_of:
        links = posters.sitelinks(sorted(set(qid_of.values())))
        autofill.save_cache()
        for film, qid in qid_of.items():
            if qid in links:
                articles[film] = links[qid]

    # Whatever Wikidata couldn't place falls back to the slower per-film search,
    # held to the same confidence rules posters.py uses.
    for film in films:
        if film not in articles:
            found = posters.find_article(*film)
            if found:
                articles[film] = found
    return articles


def main():
    args = sys.argv[1:]
    force = "--force" in args
    dry_run = "--dry-run" in args
    lead_only = "--lead-only" in args

    only_title = only_year = None
    if "--film" in args:
        i = args.index("--film")
        if i + 1 >= len(args):
            sys.exit("--film needs a title")
        only_title = args[i + 1].strip()
    if "--year" in args:
        i = args.index("--year")
        if i + 1 >= len(args):
            sys.exit("--year needs a year")
        only_year = int(args[i + 1])

    index = {}
    if os.path.exists(DST):
        with open(DST) as fh:
            index = json.load(fh)

    films = films_from_sheet()
    if only_title:
        needle = only_title.lower()
        films = [
            (t, y)
            for t, y in films
            if t.lower() == needle and (only_year is None or y == only_year)
        ]
        if not films:
            sys.exit(f"{only_title} is not in the sheet")

    todo = [(t, y) for t, y in films if force or io.film_key(t, y) not in index]
    print(f"{len(todo)} of {len(films)} film(s) to fetch")
    if not todo:
        return 0

    autofill.load_cache()
    articles = resolve_articles(todo, index)
    print(f"{len(articles)} of {len(todo)} resolved to an article")

    def save():
        tmp = DST + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(index, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, DST)

    written, skipped, no_reception = 0, [], []
    for title, year in todo:
        if (title, year) not in articles:
            skipped.append(f"{title} ({year})" if year else title)

    def record(title, year, article, summary, count, had_reception):
        index[io.film_key(title, year)] = {
            "summary": summary,
            "sentences": count,
            "reception": had_reception,
            "article": article,
            "url": url_for(article),
            "source": "Wikipedia (CC BY-SA 4.0)",
        }

    pending = [(f, articles[f]) for f in todo if f in articles]

    # Pass 1 — leads, twenty per request. Every film gets a usable summary in
    # about ten calls, so an interrupted run still leaves the site populated.
    print("pass 1: leads")
    intros = article_intros([a for _, a in pending])
    for (title, year), article in pending:
        label = f"{title} ({year})" if year else title
        intro = intros.get(article)
        if not intro:
            skipped.append(label)
            print(f"  ! {label} — no lead section", flush=True)
            continue
        summary, count, _ = compose(intro)
        if not summary:
            skipped.append(label)
            continue
        record(title, year, article, summary, count, False)
        written += 1
    if written and not dry_run:
        save()
    print(f"  {written} lead summaries")

    if lead_only:
        print("--lead-only: stopping before the reception pass")
    else:
        # Pass 2 — reception, one article per request because TextExtracts will
        # not batch full text. Checkpointed every ten so a throttle or an
        # interrupt costs at most ten films' worth of work.
        need = [
            (f, a)
            for f, a in pending
            if not (index.get(io.film_key(*f)) or {}).get("reception")
        ]
        print(f"pass 2: reception for {len(need)} film(s)")
        for n, ((title, year), article) in enumerate(need, 1):
            label = f"{title} ({year})" if year else title
            text = article_text(article)
            if not text:
                print(f"  ! {label} — full text unavailable, keeping the lead", flush=True)
                continue
            summary, count, had_reception = compose(text)
            if not summary:
                continue
            record(title, year, article, summary, count, had_reception)
            if not had_reception:
                no_reception.append(label)
            print(
                f"  + {label} — {count} sentences"
                f"{'' if had_reception else ' (lead only)'}",
                flush=True,
            )
            if dry_run:
                print(f"      {summary[:200]}…")
            if n % 10 == 0:
                if not dry_run:
                    save()
                print(f"  … {n}/{len(need)}", flush=True)
        if not dry_run:
            save()

    if dry_run:
        print(f"\ndry run — {written} summary(ies) would be saved")
        return 0

    if written:
        extract.main()
    print(f"\nsaved {written}; {len(index)} film(s) now have a summary")

    # Under the floor means the article itself is a stub — there is no more
    # text to take. Worth naming rather than quietly shipping two sentences.
    short = sorted(
        (entry["sentences"], key)
        for key, entry in index.items()
        if entry.get("sentences", 0) < MIN_SENTENCES
    )
    if short:
        print(f"\n{len(short)} under {MIN_SENTENCES} sentences (short article):")
        for count, key in short:
            print(f"  {count}  {key.replace('|', ' ')}")
    if no_reception:
        print(f"\n{len(no_reception)} had no reception section (lead only):")
        for label in no_reception[:20]:
            print(f"  {label}")
        if len(no_reception) > 20:
            print(f"  … and {len(no_reception) - 20} more")
    if skipped:
        print(f"\n{len(skipped)} skipped — no confident article match:")
        for label in skipped:
            print(f"  {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
