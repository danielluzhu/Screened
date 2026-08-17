"""Shared helpers for reading and writing Favorites.numbers.

Every save takes a timestamped backup first: numbers-parser rewrites the whole
document, so the original is always recoverable from backups/.

Saving rewrites the entire file, so a read-modify-write from two processes at
once would lose one side's changes. Use the `editing()` context manager, which
holds an exclusive lock across the whole read-modify-write.
"""
import fcntl
import os
import re
import shutil
from contextlib import contextmanager
from datetime import datetime

from numbers_parser import Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "Favorites.numbers")
BACKUPS = os.path.join(ROOT, "backups")

# Films sheet layout. Columns 4 and 5 are added by scripts/add_columns.py.
COL_TITLE, COL_YEAR, COL_TIER, COL_COUNTRY, COL_NOTES, COL_DIRECTOR = range(6)
COL_FRANCHISE, COL_GENRE, COL_NATIVE, COL_CRITIQUE, COL_ANALYSIS = 6, 7, 8, 9, 10

# Characters sheet layout. Tier was appended after the fact, so rows written
# before it exists read as blank and are treated as unrated.
COL_CHAR_NAME, COL_CHAR_SHOW, COL_CHAR_WHY, COL_CHAR_TIER = range(4)

# Music sheet layout, deliberately parallel to Films: artist sits where the
# director does, album where the franchise does. Country is the artist's;
# genre is the album's.
COL_SONG, COL_SONG_YEAR, COL_SONG_TIER, COL_SONG_COUNTRY = range(4)
COL_SONG_NOTES, COL_ARTIST, COL_ALBUM, COL_SONG_GENRE = 4, 5, 6, 7

MUSIC_HEADERS = [
    "Song",
    "Year",
    "Tier",
    "Country",
    "Notes",
    "Artist",
    "Album",
    "Genre",
]

TIERS = ["S", "A", "B", "C", "D", "E", "F", "?"]


def films_table(doc):
    for sheet in doc.sheets:
        if sheet.name == "Films":
            return sheet.tables[0]
    raise KeyError("no Films sheet")


def characters_table(doc):
    for sheet in doc.sheets:
        if sheet.name == "Characters":
            return sheet.tables[0]
    raise KeyError("no Characters sheet")


def music_table(doc, create=False):
    """The Music sheet's table. With create=True, adds the sheet if missing.

    The sheet postdates the rest of the document, so every reader has to cope
    with it not being there; only the writers pass create=True.
    """
    for sheet in doc.sheets:
        if sheet.name == "Music":
            return sheet.tables[0]
    if not create:
        raise KeyError("no Music sheet")
    doc.add_sheet("Music", "Music", num_rows=1, num_cols=len(MUSIC_HEADERS))
    table = doc.sheets[-1].tables[0]
    for column, header in enumerate(MUSIC_HEADERS):
        table.write(0, column, header)
    return table


def find_song_row(table, song, artist=None):
    """Row index for a song, narrowed by artist when given, else None.

    Song titles repeat across artists — and a cover is a different row from the
    original — so anything that writes to a song should pass the artist too.
    """
    needle = str(song).strip().lower()
    artist_needle = str(artist).strip().lower() if artist else None
    for i, values in enumerate(table.rows(values_only=True)):
        if i == 0 or not values[COL_SONG]:
            continue
        if str(values[COL_SONG]).strip().lower() != needle:
            continue
        if artist_needle is not None:
            found = values[COL_ARTIST] if len(values) > COL_ARTIST else None
            if str(found or "").strip().lower() != artist_needle:
                continue
        return i
    return None


def song_key(song, artist=None):
    """Identity for a song across data files: title plus artist."""
    return f"{str(song).strip()}|{str(artist).strip() if artist else ''}"


def find_character_row(table, name):
    """Row index for a character by name, else None."""
    needle = str(name).strip().lower()
    for i, values in enumerate(table.rows(values_only=True)):
        if i == 0 or not values[COL_CHAR_NAME]:
            continue
        if str(values[COL_CHAR_NAME]).strip().lower() == needle:
            return i
    return None


def ensure_column(table, column, header):
    """Widen the table to reach `column` and label it if the header is blank."""
    if table.num_cols <= column:
        table.add_column(column + 1 - table.num_cols)
    if not table.cell(0, column).value:
        table.write(0, column, header)


def open_doc(path=None):
    return Document(path or SRC)


def backup(path=None):
    path = path or SRC
    os.makedirs(BACKUPS, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    dest = os.path.join(BACKUPS, f"Favorites-{stamp}.numbers")
    shutil.copy2(path, dest)
    prune()
    return dest


def prune(keep=20):
    """Keep the most recent backups only; one per edit adds up fast."""
    if not os.path.isdir(BACKUPS):
        return
    files = sorted(
        (f for f in os.listdir(BACKUPS) if f.endswith(".numbers")),
        reverse=True,
    )
    for stale in files[keep:]:
        os.remove(os.path.join(BACKUPS, stale))


def save(doc, path=None):
    """Back up, then write the document atomically via a temp file."""
    path = path or SRC
    dest = backup(path)
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    doc.save(tmp)
    os.replace(tmp, path)
    return dest


LOCK = os.path.join(ROOT, ".favorites.lock")


def slug(title, year=None):
    """URL-safe id for a film's own page. Year keeps same-title films apart."""
    base = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-") or "film"
    return f"{base}-{year}" if year else base


def film_key(title, year=None):
    """Identity for a film across data files: title plus year.

    Title alone is ambiguous (three Mulans), which previously meant all three
    shared one poster and a rating edit hit whichever came first.
    """
    return f"{str(title).strip()}|{year if year is not None else ''}"


@contextmanager
def editing(path=None):
    """Exclusive read-modify-write. Yields (doc, films_table); saves on exit.

    Blocks until any other writer finishes, so edits can't clobber each other.
    Defaults resolve at call time so tests can repoint SRC/LOCK safely.
    """
    path = path or SRC
    with open(LOCK, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            doc = open_doc(path)
            yield doc, films_table(doc)
            save(doc, path)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def year_of(value):
    """The Year cell as an int, or None. Numbers stores them as floats."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value if isinstance(value, int) else None


def find_rows(table, title, year=None):
    """All row indices matching a title, narrowed by year when given.

    Titles are not unique — the sheet holds three Mulan rows (1998, 2000, 2020)
    — so anything that writes to a film must pass the year too.
    """
    needle = title.strip().lower()
    hits = []
    for i, row in enumerate(table.rows(values_only=True)):
        if i == 0 or not row[COL_TITLE]:
            continue
        if str(row[COL_TITLE]).strip().lower() != needle:
            continue
        if year is not None and year_of(row[COL_YEAR]) != year:
            continue
        hits.append(i)
    return hits


def find_row(table, title, year=None):
    """First row matching title (and year, when given), else None."""
    hits = find_rows(table, title, year)
    return hits[0] if hits else None
