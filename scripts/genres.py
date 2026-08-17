"""The canonical genre vocabulary and the aliases that fold into it.

The Genre column was filled from Wikidata, which is granular to a fault: it
distinguishes "Fantasy anime", "Fantasy anime and manga" and "Dark fantasy",
and it labels films with things that aren't genres at all ("Flashback",
"Independent"). That left 105 distinct labels across 188 films, most used once,
which makes for a filter nobody can use.

Everything now folds into CANON, which is fixed at 20 entries. Compound labels
map to several canonical genres ("Comedy drama" -> Comedy + Drama) rather than
being forced into one, so nothing is lost by consolidating.

autofill.py and recommend.py both route through canonical(), so a fresh
Wikidata pull can't quietly grow the list back past 20. A label that isn't in
ALIASES is dropped, not passed through — see UNMAPPED in consolidate_genres.py
for the report that surfaces those.
"""

CANON = [
    "Action",
    "Adventure",
    "Animation",
    "Anime",
    "Comedy",
    "Coming-of-age",
    "Crime",
    "Drama",
    "Dystopian",
    "Family",
    "Fantasy",
    "Historical",
    "Horror",
    "Martial arts",
    "Musical",
    "Mystery",
    "Romance",
    "Science fiction",
    "Thriller",
    "War",
]

# Retired when the canon went from 30 to 20, and what each folds into.
#
# The twenty that survive are forms — you could describe how a film of that
# genre is shaped. These ten are something else: a subject ("Sport",
# "Biographical"), a register ("Epic"), a style ("Noir"), a situation
# ("Survival"), a theme ("LGBTQ"). Each is a way of qualifying a drama or a
# thriller rather than an alternative to one, which is why they fold without
# leaving a hole — a biopic is still a drama, a spy film is still a thriller.
#
# The fold is applied to ALIASES below rather than written into it by hand, so
# no alias can be left pointing at a genre that no longer exists.
RETIRED = {
    "Biographical": ["Drama"],
    "Epic": ["Historical"],
    "LGBTQ": ["Drama"],
    "Noir": ["Crime", "Thriller"],
    "Slice of life": ["Drama"],
    "Sport": ["Drama"],
    "Spy": ["Thriller"],
    "Superhero": ["Action"],
    "Supernatural": ["Fantasy"],
    "Survival": ["Thriller"],
}

# Source label -> the canonical genres it becomes. An empty list means the
# label is deliberately dropped: it describes a production mode, a narrative
# device or a critical reading, none of which are genres.
ALIASES = {
    # Every canonical name maps to itself — see the loop below, which adds
    # those entries rather than listing them here. Without them the fold is not
    # idempotent: "LGBTQ" and "Noir" are canonical names that no source label
    # spells that way, so a second pass over already-folded data dropped them.
    # --- compounds split into their parts ---------------------------------
    "action comedy": ["Action", "Comedy"],
    "action thriller": ["Action", "Thriller"],
    "buddy cop": ["Crime", "Comedy"],
    "comedy drama": ["Comedy", "Drama"],
    "comedy horror": ["Comedy", "Horror"],
    "crime drama": ["Crime", "Drama"],
    "crime thriller": ["Crime", "Thriller"],
    "erotic thriller": ["Thriller", "Romance"],
    "historical drama": ["Historical", "Drama"],
    "military science fiction": ["Science fiction", "War"],
    "period drama": ["Historical", "Drama"],
    "romantic comedy": ["Romance", "Comedy"],
    "romantic drama": ["Romance", "Drama"],
    "science fiction action": ["Science fiction", "Action"],
    "science fiction comedy": ["Science fiction", "Comedy"],
    "science fiction horror": ["Science fiction", "Horror"],
    "supernatural horror": ["Supernatural", "Horror"],
    "tragicomedy": ["Comedy", "Drama"],
    # --- anime: keep the medium *and* the genre ---------------------------
    "action anime": ["Anime", "Action"],
    "adventure anime": ["Anime", "Adventure"],
    "adventure anime and manga": ["Anime", "Adventure"],
    "drama anime and manga": ["Anime", "Drama"],
    "fantasy anime": ["Anime", "Fantasy"],
    "fantasy anime and manga": ["Anime", "Fantasy"],
    "isekai": ["Anime", "Fantasy"],
    "mystery anime": ["Anime", "Mystery"],
    "science fiction anime": ["Anime", "Science fiction"],
    "supernatural anime": ["Anime", "Supernatural"],
    "thriller anime": ["Anime", "Thriller"],
    # --- narrower labels folded upward ------------------------------------
    "american football": ["Sport"],
    "animated": ["Animation"],
    "anti-war": ["War"],
    "apocalyptic": ["Dystopian"],
    "black comedy": ["Comedy"],
    "bruceploitation": ["Martial arts"],
    "buddy": ["Comedy"],
    "children's": ["Family"],
    "cyberpunk": ["Science fiction"],
    "dark fantasy": ["Fantasy"],
    "detective": ["Mystery"],
    "disaster": ["Survival"],
    "drama fiction": ["Drama"],
    "erotic": ["Romance"],
    "film noir": ["Noir"],
    "gangster": ["Crime"],
    "ghost": ["Supernatural"],
    "hard science fiction": ["Science fiction"],
    "historical play": ["Historical"],
    "kaiju": ["Science fiction"],
    "kung fu": ["Martial arts"],
    "lgbtq-related": ["LGBTQ"],
    "live-action/animated": ["Animation"],
    "magic realist": ["Fantasy"],
    "medical drama": ["Drama"],
    "mockumentary": ["Comedy"],
    "neo-noir": ["Noir"],
    "parody": ["Comedy"],
    "police": ["Crime"],
    "police procedural": ["Crime"],
    "political thriller": ["Thriller"],
    "post-apocalyptic": ["Dystopian"],
    "prison": ["Crime"],
    "psychological thriller": ["Thriller"],
    "samurai": ["Martial arts"],
    "speculative fiction": ["Science fiction"],
    "splatter": ["Horror"],
    "steampunk": ["Science fiction"],
    "suspense": ["Thriller"],
    "techno-horror": ["Horror"],
    "teen": ["Coming-of-age"],
    "time-travel": ["Science fiction"],
    "traditionally animated": ["Animation"],
    "wuxia": ["Martial arts"],
    "zombie": ["Horror"],
    # --- not genres: dropped ----------------------------------------------
    "art": [],
    "flashback": [],
    "independent": [],
    "screenlife": [],
    "white savior": [],
}

def _fold(names):
    """Rewrite retired genres to their replacements, deduped, order kept."""
    out = []
    for name in names:
        for kept in RETIRED.get(name, [name]):
            if kept not in out:
                out.append(kept)
    return out


# Every alias goes through the retirement map, so the compounds above keep
# working: "erotic thriller" was Thriller + Romance and still is, while
# "supernatural horror" quietly becomes Fantasy + Horror.
ALIASES = {label: _fold(names) for label, names in ALIASES.items()}

# The retired names are themselves labels a sheet or a Wikidata pull can hand
# us, so they stay resolvable rather than being reported as unmapped.
for _old, _new in RETIRED.items():
    ALIASES.setdefault(_old.lower(), list(_new))

# A canonical genre is always an alias of itself, so folding an already-folded
# column is a no-op. Explicit entries win, so this can't override a deliberate
# split.
for _name in CANON:
    ALIASES.setdefault(_name.lower(), [_name])

assert len(CANON) == 20, f"CANON must hold 20 genres, has {len(CANON)}"
_UNKNOWN = {g for names in ALIASES.values() for g in names} - set(CANON)
assert not _UNKNOWN, f"ALIASES map to non-canonical genres: {sorted(_UNKNOWN)}"
assert not set(RETIRED) & set(CANON), "a retired genre is still in CANON"

_ORDER = {name: i for i, name in enumerate(CANON)}


def canonical(name):
    """The canonical genres for one source label; [] if it isn't a genre."""
    return ALIASES.get(str(name).strip().lower(), [])


def canonical_list(names):
    """Fold a film's genre labels into the canon, deduped, order preserved."""
    out = []
    for name in names:
        for genre in canonical(name):
            if genre not in out:
                out.append(genre)
    return out


def sort_key(name):
    """Canon order for display; unknown names sort last, alphabetically."""
    return (_ORDER.get(name, len(CANON)), name)
