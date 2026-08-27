"""Read a Wikipedia infobox as a field dict.

Wikidata is the better source when it has the fact — it is structured, it is
cached, and it doesn't need parsing. It often doesn't have the fact: Bleach
carries a start date and no end date, Paranoia Agent no season count, and
"Had I Not Seen the Sun" has no series item at all. All three are spelled out
in the infobox at the top of the English Wikipedia article, so that is where
shows.py goes when a field comes back empty.

Two families of infobox cover television. Live-action series use
{{Infobox television}}, with num_seasons/num_episodes/first_aired/last_aired.
Anime articles instead use {{Infobox animanga/Header}} for the title and genre
and {{Infobox animanga/Video}} for the broadcast run, so both are read.

Parsing wikitext with a regex doesn't survive contact with these articles —
fields hold nested templates, references and piped links, all of which contain
the "|" that separates one field from the next. The scanner below tracks
template and link depth and splits only at the top.
"""
import re

import posters

WIKI_LINK = re.compile(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]+)\]\]")
REF = re.compile(r"<ref[^>]*?/>|<ref.*?</ref>", re.DOTALL | re.IGNORECASE)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")
# Templates that annotate a value rather than carry one: a footnote, a
# citation, a date qualifier. Dropped whole, contents and all.
NOISE = re.compile(
    r"\{\{\s*(efn|refn|cite[^|}]*|sfn|r|nowrap|small|based on|nihongo foot|"
    r"post-nominals|abbr)\b.*?\}\}",
    re.DOTALL | re.IGNORECASE,
)
# Templates that mean "the value is a list": {{ubl|a|b}}, {{plainlist}}...
LIST_TEMPLATE = re.compile(r"\{\{\s*(ubl|unbulleted list|plainlist|flatlist|hlist)\s*\|?", re.IGNORECASE)
END_LIST = re.compile(r"\{\{\s*endplainlist\s*\}\}", re.IGNORECASE)


def wikitext(article):
    """The raw source of an article, or None if there isn't one."""
    resp = posters.wiki_api(
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": article,
            "redirects": 1,
            "format": "json",
        }
    )
    for page_id, page in (resp or {}).get("query", {}).get("pages", {}).items():
        if page_id == "-1" or "missing" in page:
            continue
        revisions = page.get("revisions") or []
        if revisions:
            return revisions[0].get("slots", {}).get("main", {}).get("*")
    return None


def template(text, name):
    """The named template's fields, as {field: raw value}; {} if it's absent.

    Only the first occurrence is read — an article has one infobox of a kind,
    and the later matches tend to be the navigation box at the foot.
    """
    if not text:
        return {}
    start = re.search(r"\{\{\s*" + re.escape(name) + r"\s*(?=[|\n}])", text, re.IGNORECASE)
    if not start:
        return {}

    fields, key, buf = {}, None, []
    depth, link, i, end = 0, 0, start.start(), len(text)
    while i < end:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            buf.append(pair)
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            if depth == 0:
                break
            buf.append(pair)
            i += 2
            continue
        if pair == "[[":
            link += 1
            buf.append(pair)
            i += 2
            continue
        if pair == "]]":
            link = max(0, link - 1)
            buf.append(pair)
            i += 2
            continue
        # A "|" one level down, outside any link, starts the next field. Inside
        # a nested template or a piped link it is part of the value.
        if text[i] == "|" and depth == 1 and link == 0:
            if key:
                fields[key] = "".join(buf).strip()
            named = re.match(r"\s*([A-Za-z0-9_ -]+?)\s*=", text[i + 1 :])
            key = named.group(1).strip().lower() if named else None
            buf = []
            i += 1 + (named.end() if named else 0)
            continue
        buf.append(text[i])
        i += 1
    if key:
        fields[key] = "".join(buf).strip()
    return fields


def plain(value):
    """A field value as readable text: no markup, references or footnotes."""
    if not value:
        return ""
    text = COMMENT.sub("", value)
    text = REF.sub("", text)
    text = NOISE.sub("", text)
    text = WIKI_LINK.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = TAG.sub(" ", text)
    text = re.sub(r"\{\{|\}\}", " ", text)
    return re.sub(r"\s+", " ", text).strip(" |*\n\t")


def items(value):
    """A field value split into its parts — list templates, bullets, breaks."""
    if not value:
        return []
    text = COMMENT.sub("", value)
    text = REF.sub("", text)
    text = NOISE.sub("", text)
    text = END_LIST.sub("", text)
    text = LIST_TEMPLATE.sub("", text)
    text = BREAK.sub("|", text)
    text = re.sub(r"^\s*\*", "|", text, flags=re.MULTILINE)
    # Links are split on "|" too without this: [[Martial arts film|Martial arts].
    text = WIKI_LINK.sub(lambda m: m.group(1).replace("|", " "), text)
    parts = [plain(part) for part in text.split("|")]
    return [part for part in parts if part]


def year(value):
    """The year in a date field: {{Start date|2004|10|5}}, or prose, or None."""
    if not value:
        return None
    # Comments first: a series still on the air often has its end date written
    # out and commented back out ("present<!--{{End date|2025|12|11}}-->"),
    # which would otherwise read as a run that has finished.
    value = COMMENT.sub("", value)
    stamped = re.search(r"\{\{\s*(?:start|end) date[^}|]*\|\s*(\d{4})", value, re.IGNORECASE)
    if stamped:
        return stamped.group(1)
    loose = re.search(r"\b(1[89]\d{2}|20\d{2})\b", plain(value))
    return loose.group(1) if loose else None


def count(value):
    """The leading whole number in a field like "16{{efn|...}}", or None."""
    if not value:
        return None
    found = re.match(r"\s*(\d+)", plain(value).replace(",", ""))
    return found.group(1) if found else None
