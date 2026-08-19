# Screened

A website that tracks my favorite films, shows and characters.
<https://danielluzhu.github.io/Screened/>

Basically a place for me to fanboy or critique.

Two names that deliberately did not change with it: `Favorites.numbers` is the
Numbers document itself — the source of truth, and a file that exists under that
name outside this repo — and the `favorites` systemd unit and tmux session are
running processes on this box. Renaming either is a separate job from renaming
the site, and touches the write path rather than the branding.

## Running

Served by Bun, no dependencies to install:

```sh
bun run server.ts          # http://localhost:3000
bun run dev                # same, with auto-reload on file changes
PORT=8080 bun run start    # different port
```

In tmux, so it survives leaving the terminal:

```sh
tmux new -d -s favorites -c /workspace 'bun run server.ts'
tmux attach -t favorites   # detach with ctrl-b then d
tmux kill-session -t favorites
```

### As a service

`/etc/systemd/system/favorites.service` runs it as `ubuntu` on boot:

```sh
sudo systemctl status favorites
sudo systemctl restart favorites     # after editing server.ts
sudo journalctl -u favorites -f      # logs
```

A system unit rather than `systemctl --user`, because there's no user D-Bus
session on this box. The unit sets `PATH` and `HOME` explicitly — systemd starts
with a bare environment, and both Bun and the `python3` helpers the server
spawns have to be findable. `TimeoutStopSec=30` gives an in-flight rating write
time to finish rewriting the document instead of being killed halfway.

## Published site

A read-only copy is published at <https://danielluzhu.github.io/Screened/> from
the `docs/` folder on `main`. Rebuild it after changing the data, then push:

```sh
python3 scripts/build_static.py     # regenerates docs/
git add -A docs && git commit -m "rebuild site" && git push
```

Pages serves static files only, so the copy differs from the local server in two
ways: `/api/data` becomes `docs/api/data.json`, and every `/film/<slug>` style
route is written out as a real directory with an `index.html` rather than being
resolved per request. Writing to `Favorites.numbers` needs the Python helpers,
which only exist locally, so `docs/static.js` renders the rating dropdowns as
plain badges and hides the add/edit forms. It hides rather than removes them:
`app.js` looks those nodes up by id after its data fetch resolves, and a missing
one throws before the film list ever renders. Edit locally, rebuild, push.

The build takes the base path as its one argument (`/Screened` by default);
pass `/` if the site ever moves to a custom domain.

## Data

`Favorites.numbers` is the source of truth. `scripts/extract.py` reads it and
writes `data.json`, which the server hands to the page at `/api/data`:

```sh
python3 -m pip install --user numbers-parser   # once
python3 scripts/extract.py                     # after editing the Numbers file
```

The server re-reads `data.json` on each request, so a refresh picks up changes
without a restart.

**Country** is normalized: `China`/`Chinese`/`chinese` and friends collapse into
a `region` field used for filtering. The original string is kept and is what the
page shows.

### Cards

Every grid uses one card, `.tile`: the art fills it and the details sit on a
dark scrim across the bottom. The tier badge is pinned to a single character's
width in the corner, because a `<select>` otherwise sizes itself to its widest
option ("Remove").

Two aspect ratios, picked by what the art actually is:

| View | Ratio | Why |
| --- | --- | --- |
| Films, Characters | 2:3 | posters, and portraits are tall far more often than not |
| Shows | 3:2 | art is mostly a banner — 1280×320 up to 9215×2000 |

Show art carries its wordmark low in the frame, right where the scrim lands, so
wide tiles bias the crop upward (`object-position: center 32%`). Wide tiles
also drop to three lines — with four, the scrim grew tall enough to cover the
whole card.

Chips don't go on tiles. Genres and streaming services are filters and detail
pages instead; the film service filter is built from what `streaming.json`
actually found, so a service nothing is on never shows up as a dead option. The
(The Music tab was the one exception, keeping its genres on the card because a
song had no page of its own to read them on.)

The `.film` row card still exists — the film, director and suggestions pages use
it.

The artwork is a link to the item's own page, everywhere it appears: the tiles,
the row cards, the director and year lists, and the backlog. It is the biggest
target on a card and clicking it used to do nothing. The title beside or over
the art already links to the same place, so the wrapper (`.art-link`) is
`aria-hidden` and `tabindex="-1"` — otherwise every card would be read out twice
and take two tab stops to get past. Suggestion cards are the exception: those
films aren't in the list, carry no slug, and have no page to reach.

### Masthead

The wordmark sits under a gold eyebrow and over a short gradient rule, with a
warm glow behind it — light thrown from a projector, which is the one image the
name earns. The glow is anchored to the content column rather than the viewport,
so it stays behind the title instead of drifting to whatever is right of centre
on a wide screen, and it's scoped off `.film-masthead`, where the header is only
a back link.

The tabs lost their folder borders for a single underline indicator, gold on the
active one. Fewer lines competing with the artwork below, and one unambiguous
mark for where you are.

### Theme

Black, always. The `prefers-color-scheme: light` palette is gone: the page is
carried by artwork now, and a light background fought it. Panels step up from
pure black rather than down from grey so cards still separate from the page.
Contrast against `#000` is roughly 18:1 for body text, 8:1 for muted text and
11:1 for the accent, all well past the 4.5:1 floor.

The tile scrim is the one thing that was already theme-independent — light text
on a dark gradient, because a poster can be any colour.

### Editing ratings

Click any tier badge on the Films tab to change a rating. The change is written
back into `Favorites.numbers` itself, so Numbers and the site never disagree.

Because a save rewrites the whole document (~1.4s), the server coalesces rapid
edits into one write and serializes them behind a lock (`.favorites.lock`), which
`scripts/autofill.py` also takes. Every save first copies the current file to
`backups/`, keeping the last 20.

Tiers run `S` (best) through `F`, plus `?` for unrated. The sheet originally used
a numeric scale where `0` was best; `scripts/retier.py` folded those in:

```sh
python3 scripts/retier.py 0=S 1=A     # what was already run
```

### Editing details

**Edit details** on a film's own page opens year, director, country of origin and
genre for editing; saving writes them back into `Favorites.numbers` the same way
ratings do. This is how the films `autofill.py` couldn't resolve (see
`needs-attention.txt`) get filled in.

Director and genre are comma-separated lists — the page splits them apart again.
The genre buttons under that field offer the genres already in use, so the
front-page filter doesn't gain a near-duplicate for every film.

Year is part of a film's identity: posters and streaming links are keyed by
title plus year, so changing it re-keys those indexes and moves the film's page
to a new URL. Changing it to collide with another row of the same title is
refused — that would give two films one page and one poster.

### Posters

```sh
python3 scripts/posters.py            # fetch any that are missing
python3 scripts/posters.py --force    # re-fetch everything
```

Each film is resolved to its Wikidata item, then to its English Wikipedia
article, whose lead image is the poster. Films Wikidata couldn't match get a
second pass that full-text searches Wikipedia; a hit is only accepted if the
article really is a film (checked against Wikidata), the title matches once
punctuation and disambiguators are stripped, and the year is within one of the
recorded year. Search rank alone is not enough — before those checks were added
it matched *Yiyi* to *The Wandering Earth*.

Images land in `public/posters/` with an index in `posters.json`. Films without
one render a dashed placeholder rather than shifting the layout.

Note these are non-free posters that Wikipedia hosts under fair use. A local copy
for a private list is comparable use; check that still holds before putting this
site on a public domain.

### Autofilling year, director, and franchise

```sh
python3 scripts/autofill.py --dry-run   # report what it would fill
python3 scripts/autofill.py             # write it back
```

Looks each film up on Wikidata and fills in missing release years, directors, and
series membership (which drives the Franchises tab). It matches on title plus the
year already recorded, and **leaves anything ambiguous blank** rather than
guessing — unmatched and ambiguous titles are listed at the end of the run for
you to fill in by hand (see *Editing details* above).

### Genres

The Genre column holds exactly 20 values, listed in `scripts/genres.py`. They
came from Wikidata, whose vocabulary is granular enough to give nearly every
film its own label — 105 distinct ones across 188 films, most used once, which
is not a filter anybody can use.

`ALIASES` in that file maps every source label onto the canon. Compounds split
rather than collapse (`Comedy drama` → Comedy + Drama, `Fantasy anime` → Anime +
Fantasy), so consolidating lost nothing. Labels that were never genres in the
first place (`Flashback`, `Independent`, `Screenlife`, `White savior`, `Art`)
are dropped.

`RETIRED` holds the second pass, 30 → 20. The twenty that survive are forms —
you can say how a film of that genre is shaped. The ten that went are a subject
(`Sport`, `Biographical`), a register (`Epic`), a style (`Noir`), a situation
(`Survival`) or a theme (`LGBTQ`): ways of qualifying a drama or a thriller
rather than alternatives to one, which is why they fold without leaving a hole.
The map is applied to `ALIASES` programmatically, so no alias can be left
pointing at a genre that no longer exists.

```sh
python3 scripts/consolidate_genres.py            # show what would change
python3 scripts/consolidate_genres.py --apply    # write it back
```

`autofill.py` and `recommend.py` both fold through `genres.canonical()`, so a
fresh Wikidata pull can't grow the list back past 20, and `set_details.py`
rejects a genre typed on a film's page that isn't in the canon. A new Wikidata
label that no alias covers is reported as UNMAPPED rather than silently
dropped — add it to `ALIASES` and re-run.

Re-running is safe: every canonical genre is an alias of itself, so a second
pass over an already-folded column reports zero changes.

### Character rankings

Characters carry the same S–F/? tier as films, in the Characters sheet's Tier
column. Click the badge on a card to change it; the Characters tab groups by
tier by default and can also sort by name or show.

The badges deliberately don't show the scale's wording the way the film ones do
— "Could not finish" is about a film, not about Levi.

### Music

**The Music tab is gone from the site.** The pipeline behind it is not: the
Music sheet, `/api/music`, `add_song.py`, `set_song_tier.py` and
`music_autofill.py` all still work, and `extract.py` still reads the sheet into
`data.json`. Only the UI was removed, so putting the tab back is markup and a
render function rather than a rebuild. What follows describes that pipeline.

The Music sheet mirrors Films: artist sits where the director does, album where
the franchise does. Country is the artist's; **genre is the album's** — a
single's own genre tags are patchier than the record's. The sheet is created on
first use, so a document without it is fine.

Songs are added with just a title and artist. Album, year, country and genre are
looked up afterwards, detached, the same way a new film waits on its poster:

```sh
python3 scripts/music_autofill.py                 # every song missing fields
python3 scripts/music_autofill.py --only "Rosa"   # one song
python3 scripts/music_autofill.py --dry-run       # look, don't write
```

Only blank cells are filled, so anything typed by hand survives. Candidates are
searched on the title alone — `wbsearchentities` matches labels, so "Bohemian
Rhapsody Queen" matches nothing — and the artist is applied afterwards as a
filter. A named artist that matches no candidate fills nothing rather than
guessing at someone else's song of the same name.

Music genres are left as Wikidata writes them (minus the "… music" suffix).
Unlike films they aren't folded into a canon: there's no listening history yet
to calibrate one against. If they sprawl, `scripts/genres.py` is the pattern to
copy.

### Summaries

Each film page carries 5–10 sentences on what the film is and how it was
received, under a *Summary* heading above your own Notes, split into a **Story**
block and a **Reception** block.

```sh
python3 scripts/summaries.py                  # every film missing one
python3 scripts/summaries.py --film "Parasite" --year 2019
python3 scripts/summaries.py --lead-only      # skip the slow reception pass
python3 scripts/summaries.py --resplit        # re-sort stored text, no network
python3 scripts/summaries.py --dry-run
```

The two halves are decided per sentence by content, not by which section the
sentence came from. A Wikipedia lead habitually closes on scores, takings and
awards, so splitting structurally would leave those sitting in the premise —
`RECEPTION_MARKERS` in `summaries.py` is what sorts them. The opening sentence
is always "X is a YEAR film directed by …", so it stays with the story whatever
else it mentions. Both halves are stored in `summaries.json`, along with
`summary` — the same sentences in their original order, kept for anything
reading the older single field.

`--resplit` re-sorts what is already on disk without fetching anything, so
adjusting the markers costs one offline run rather than 185 Wikipedia requests.
Films whose summary has no reception content at all (14 of them) simply render
the one block.

**The text is Wikipedia's, not invented.** Writing these from a model's own
memory would mean making up box-office figures and review scores for 190-odd
films, most of them not English-language. So each summary is quoted: the lead
section for what the film is, then the *Critical response* section for how it
landed. Every entry in `summaries.json` stores the article and URL it came
from, and the page renders it as a credited quotation — Wikipedia's text is
CC BY-SA 4.0, so keep that attribution visible if this site ever goes public.

The lead is taken from both ends and not the middle: a Wikipedia lead opens with
what the film is and closes with how it landed, while the middle is production
trivia.

Two passes, because the API only batches part of it. `prop=extracts` returns at
most **one** full-text extract per request no matter what `exlimit` says, but
with `exintro` it will return twenty. So pass 1 pulls every lead in about ten
requests — the whole site is populated in under a minute — and pass 2 fetches
reception sections one film at a time, checkpointing every ten. An interrupted
run keeps everything it had.

Films whose article can't be confidently identified are skipped rather than
guessed at, the same rule `posters.py` uses, and listed at the end along with
any summary that came out under five sentences because the article is a stub.

### Directors and Years

`/directors` and `/years` are indexes over the per-item pages that already
existed at `/director/<slug>` and `/year/<year>` — before these there was no way
to reach one except from a film.

They and `/suggestions` carry the front page's masthead verbatim — eyebrow,
wordmark, tagline, glow and tabs — with the current tab marked `is-active` and
`aria-current`. Above the tab row the three render byte-identical to the front
page. The wordmark is a link rather than an `h1` here, since each of these pages
already has its own `h1` in the body.

The four front-page views are tabs of one page, so from these pages they are
links to `/#franchises` and the rest, which the front page reads off the hash on
load.

The detail pages — `/film/<slug>` and the rest — still use `.film-masthead`, a
back link and nothing else.

Directors sort on what you've rated, better tiers first: more `S` films puts a
director ahead however many `A` films the next one has, more `A` breaks that
tie, and so on down the scale. Volume only counts within a tier. Films still
sitting at `?` don't rank at all, so the 57 directors you've watched but never
rated fall below the 99 you have — under the old count-first sort, one `S` film
lost to eight unrated ones. *Most watched* and *A–Z* are still there in the
sort control.

Each card carries a badge per tier with a count, so a director you rate
consistently reads differently from one you rate all over the place, and says
`N rated of M watched` whenever those differ — that first number is what the
order runs on. It also shows how many of their other films aren't in the list
yet.

Years group into decades. A year page exists for anything with box-office
figures, not only years you've watched from, so the index defaults to the 46
years you have watched and can show all 107 — the extra ones muted, because
they're worth reaching but aren't part of the list.

### Director portraits

```sh
python3 scripts/director_photos.py                    # any that are missing
python3 scripts/director_photos.py --only "Ang Lee"
python3 scripts/director_photos.py --force            # re-fetch everything
```

Wikidata carries the portrait directly as `P18`, so this needs none of the
article matching `posters.py` does for films — the director's own item names the
file and Commons serves a thumb. It cannot pick the wrong picture the way a
title search can.

Directors that `directors.py` already resolved have a qid. The rest are searched
for by name and only accepted when the label matches exactly, the item is a
human (`P31=Q5`), and its occupations include directing — otherwise an actor of
the same name would end up as the portrait. Unmatched directors are listed at the
end of the run rather than guessed at.

`wikidata.claim_values` returns only entity ids and timestamps, so it drops `P18`
— a `commonsMedia` value is a plain string. `director_photos.py` reads those
itself rather than widening the shared helper, which `autofill.py` relies on for
that filtering.

Thumbnails are requested at 320px, which covers the 260px cards. Asking for much
more is counterproductive: above roughly 340px Commons stops generating a thumb
for the portraits that are small to begin with and hands back the original, which
took one 35KB portrait to 180KB and the set from 5MB to 27MB.

**Unlike the posters, these are freely licensed** — Commons hosts no fair-use
media. The licence and author come back with the image, are stored in
`director-photos.json`, and are shown under the portrait, because CC BY-SA needs
the credit visible.

### Other films

Every film in a director's Wikidata filmography that isn't in your list gets its
own page at `/other/<slug>` — 1,246 of them — so a filmography is browsable
rather than a flat list of titles. Each page carries the year, its directors
(linked), a Wikidata link, and the rest of that director's work either side of
the line.

**These are not in the list.** They live in `other-films.json`, never in
`films`, and carry no tier, so nothing here reaches the `?` bucket or the Films
tab. The Add button on the page is the only way in, and it stays a deliberate
click; the published copy hides it, since writing needs the Python helpers.

They're keyed by Wikidata id, so a film credited to two of your directors is one
page rather than two — 1,283 filmography entries collapse to 1,246 pages.

`other-films.json` is a separate file rather than a key in `data.json` on
purpose: it is 41KB gzipped and only the `/other/` pages read it. Folding it in
would have put that on every page fetch, a 19% increase on the payload the home
page already pulls.

### What to watch next

`/suggestions` ranks films you haven't seen against your own ratings. Two lists:
films that aren't in the sheet at all, and the unrated films already sitting in
it — a 70-film backlog needs a top as much as anything else does.

Nothing is fetched when the page loads. The candidates are what the other
scripts already wrote:

* the rest of the filmography of every director in the list (`directors.json`)
* the entries you're missing from series you've started (`franchises.json`)
* each year's biggest earners (`box-office.json`)

and the scoring runs inside `extract.py`, so a rating changes the suggestions
the moment it's saved.

Every signal is an *affinity*: the mean tier weight of the films behind it (S is
+3 down to F at -3), damped by `n / (n + 1)` so one film is a hint and five are
a pattern. A candidate scores the sum of the affinities that apply — director
(×2.2), series (×1.6), genres (×1.0, averaged so an eight-genre film isn't eight
times the match), country (×0.8) — and box-office size only ever breaks ties
between films that already fit. Anything without a positive reason is left out
rather than padded out, and no more than two films come from any one series or
director, or one Pokémon run fills the page.

Country matters more than its weight suggests. Without it the box-office pool
answers "you rate Comedy well" with *Mr. Popper's Penguins*; with it, the same
slot goes to *Twilight of the Warriors: Walled In*. Wikidata's full country
names and the sheet's shorthand (`HK`, `Japanese`) fold into the same handful of
regions the Films tab filters by.

Twelve places in the list are reserved for films that got in on nothing but
genre, country and box office — a director already in your list will always
outscore a stranger, and without the reservation the page would only ever offer
you more of what you have already seen.

Co-directors count once: *Infernal Affairs II* is a Lau film and a Mak film, but
you only liked *Infernal Affairs* once.

Genres for a film you haven't seen come from the Wikidata cache the other
scripts fill, which doesn't cover the box-office lists. To widen the pool:

```sh
python3 scripts/recommend.py --refresh   # look up what's missing, then re-extract
python3 scripts/recommend.py             # print the current ranking
```

Both are cached, so it's a one-off per new candidate.

Posters for suggested films come from the same place the list's do:

```sh
python3 scripts/posters.py --suggestions
```

Candidates arrive with a Wikidata QID already attached, so there's no matching
to do — straight to the English Wikipedia article and its lead image. They land
in `public/posters/` with their own index, `suggestion-posters.json`, kept apart
from `posters.json` so removing a film can't delete artwork for one you never
had. Worth rerunning after a batch of ratings, since the ranking will have
moved; anything already downloaded is skipped. Films without one render the same
dashed placeholder the film list uses.

Adding a suggestion claims the poster that's already on disk instead of
re-resolving and re-downloading the identical image.

**Add to list** on a suggestion drops it into the sheet unrated, poster and all,
without retyping it. A director's page carries the same one-click add against
every film of theirs you haven't seen.

### Franchises

```sh
python3 scripts/franchises.py
```

`autofill.py` records which series each watched film belongs to; this walks the
other way, asking Wikidata for *every* film in those series so each franchise
card can list the entries you haven't logged. Series items also collect video
games, novels and soundtracks, so results are filtered to films. Output goes to
`franchises.json`.

Series membership reads both `P179` ("part of the series") and `P8345` ("media
franchise"); films often carry only one of the two. Wikidata frequently has
separate items sharing an English label, so `extract.py` dedupes franchise names
case-insensitively and drops studio catalogues and critics' lists (`list of Pixar
films`, `Studio Ghibli Feature Films`, `BBC's 100 Greatest Films…`), which aren't
franchises.

It uses the Wikidata Action API, which rate-limits hard; the script throttles,
honours `Retry-After`, and caches every lookup in `scripts/.wikidata-cache.json`,
so a rerun resumes cheaply. A full cold run takes roughly an hour.

Two columns are added to the Films sheet on first run: **Director** and
**Franchise**. The pre-existing 5th column is labelled **Notes**, since it holds a
mix of directors and reminders like "Still need to finish".
