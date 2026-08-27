const el = (id) => document.getElementById(id);

let DATA = { films: [], characters: [], shows: [], tierOrder: [], regions: [] };

const state = { query: "", region: "all", genre: "all", service: "all", sort: "tier" };

// Characters have their own sort; "tier" is the ranked view.
const charState = { sort: "tier" };

// Shows aren't tiered, so they filter rather than sort. Region and genre reuse
// the film vocabularies; format is the one thing only a show is asked.
const showState = { region: "all", genre: "all", format: "all" };

function text(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
}

const TIERS = ["S", "A", "B", "C", "D", "E", "F", "?"];

// Mirrors numbers_io.slug so links match the slugs extract.py emits.
const slugify = (name) =>
  String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "film";

const TIER_MEANING = {
  S: "Evangelize",
  A: "Great film",
  B: "Good",
  C: "Something missing that does not let me enjoy",
  D: "Would advise against watching without disclaimer",
  E: "Could not finish",
  F: "Waste of time",
  "?": "Unrated",
};

let toastTimer;
function toast(message, kind = "info") {
  const node = el("toast");
  node.textContent = message;
  node.dataset.kind = kind;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), kind === "error" ? 6000 : 2200);
}

async function saveRating(film, tier, select) {
  const previous = film.tier;
  film.tier = tier;
  select.dataset.tier = tier;
  select.classList.add("is-saving");
  select.disabled = true;
  try {
    const res = await fetch("/api/rating", {
      method: "POST",
      headers: { "content-type": "application/json" },
      // Year included so the write hits the right row when titles repeat.
      body: JSON.stringify({ title: film.title, year: film.year, tier }),
    });
    const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
    select.classList.add("is-saved");
    setTimeout(() => select.classList.remove("is-saved"), 900);
    toast(`${film.title} → ${tier}`);
    // Under tier grouping the card now belongs elsewhere; regroup so the
    // headings stay honest.
    if (state.sort === "tier") renderFilms();
  } catch (err) {
    // Put the old value back so the page never disagrees with the file.
    film.tier = previous;
    select.value = previous;
    select.dataset.tier = previous;
    toast(`Couldn't save ${film.title}: ${err.message}`, "error");
  } finally {
    select.classList.remove("is-saving");
    select.disabled = false;
  }
}

const REMOVE = "__remove__";

async function removeFilm(film, select) {
  const label = film.year ? `${film.title} (${film.year})` : film.title;
  if (!confirm(`Remove ${label} from your list? This edits Favorites.numbers.`)) {
    select.value = film.tier; // put the dropdown back
    return;
  }
  select.disabled = true;
  try {
    const res = await fetch("/api/film/remove", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: film.title, year: film.year }),
    });
    const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
    await reload();
    toast(`Removed ${film.title}`);
  } catch (err) {
    select.value = film.tier;
    select.disabled = false;
    toast(`Couldn't remove ${film.title}: ${err.message}`, "error");
  }
}

// The S–F/? control, shared by film and character cards. Callers attach their
// own change handler. `meanings` is off for characters: the scale's wording is
// written about films, and "Could not finish" says nothing about a character.
function tierBadgeSelect(tier, label, { meanings = true } = {}) {
  const select = document.createElement("select");
  select.className = "badge";
  select.dataset.tier = tier;
  select.title = meanings ? `${label} — ${TIER_MEANING[tier] ?? tier}` : label;
  select.setAttribute("aria-label", `Rating for ${label}`);
  // Keep any legacy value that isn't in the current scale selectable.
  const options = TIERS.includes(tier) ? TIERS : [...TIERS, tier];
  for (const t of options) {
    const option = new Option(t, t, false, t === tier);
    // Spelled out in the menu; the closed select still shows just the letter.
    if (meanings && TIER_MEANING[t]) option.title = TIER_MEANING[t];
    select.append(option);
  }
  return select;
}

// The short list is a decision rather than a rating, so it gets its own mark:
// on the tile opposite the tier, filled when the film is on it.
function shortlistToggle(film) {
  const button = text("button", "pin", "★");
  button.type = "button";
  const paint = () => {
    button.classList.toggle("is-on", Boolean(film.shortlisted));
    button.title = film.shortlisted
      ? `${film.title} is on your short list — click to take it off`
      : `Put ${film.title} on your short list`;
    button.setAttribute("aria-pressed", String(Boolean(film.shortlisted)));
    button.setAttribute("aria-label", button.title);
  };
  paint();

  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const next = !film.shortlisted;
    button.disabled = true;
    try {
      const res = await fetch("/api/film/shortlist", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: film.title, year: film.year, on: next }),
      });
      const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
      if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
      film.shortlisted = next;
      paint();
      toast(next ? `${film.title} → short list` : `${film.title} off the short list`);
      // The short list view is a filter over the same films, so it has to
      // lose the card that just left it.
      if (currentView() === "shortlist") renderShortlist();
    } catch (err) {
      toast(`Couldn't update ${film.title}: ${err.message}`, "error");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function tierSelect(film) {
  const label = film.year ? `${film.title} (${film.year})` : film.title;
  const select = tierBadgeSelect(film.tier, label);

  // Removal lives in the same control, separated so it can't be hit by accident
  // while scrolling through the tiers.
  const group = document.createElement("optgroup");
  group.label = "—";
  group.append(new Option("Remove", REMOVE));
  select.append(group);

  select.addEventListener("change", () => {
    if (select.value === REMOVE) removeFilm(film, select);
    else saveRating(film, select.value, select);
  });
  return select;
}

// Compact service chips for the list view; the detail pages carry the caveat.
function serviceLink(service, label, cls) {
  const link = text("a", cls);
  link.href = service.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.title = `Open ${label} on ${service.name}`;
  link.dataset.service = service.name;

  const file = (DATA.serviceLogos ?? {})[service.name];
  if (file) {
    const logo = document.createElement("img");
    logo.className = "service-logo";
    logo.src = `/logos/${file}`;
    // The wordmark carries the name, so it would be read out twice.
    logo.alt = "";
    logo.loading = "lazy";
    link.append(logo);
    const sr = text("span", "sr-only", service.name);
    link.append(sr);
  } else {
    link.append(text("span", null, service.name));
  }
  return link;
}

function streamingChips(item, limit = 4) {
  const services = item.streaming ?? [];
  if (!services.length) return null;
  const wrap = text("div", "services-sm");
  for (const service of services.slice(0, limit)) {
    wrap.append(serviceLink(service, item.title ?? item.name, "service-sm"));
  }
  if (services.length > limit) {
    wrap.append(text("span", "service-more", `+${services.length - limit}`));
  }
  return wrap;
}


// Artwork that links to the item's own page. The title beside or over the art
// already links to the same place, so this one is hidden from assistive tech
// and skipped when tabbing rather than read out and stopped at twice.
function artLink(art, href) {
  const link = text("a", "art-link");
  link.href = href;
  link.setAttribute("aria-hidden", "true");
  link.tabIndex = -1;
  link.append(art);
  return link;
}

function poster(film, cls = "poster", href = null) {
  if (!film.poster) {
    // Keep the same footprint so rows stay aligned without an image.
    const blank = text("div", `${cls} is-blank`);
    blank.setAttribute("aria-hidden", "true");
    return href ? artLink(blank, href) : blank;
  }
  const img = document.createElement("img");
  img.className = cls;
  img.src = `/posters/${film.poster}`;
  img.alt = `${film.title} poster`;
  img.loading = "lazy";
  img.decoding = "async";
  return href ? artLink(img, href) : img;
}

async function renameFilm(film, newTitle, titleEl) {
  const previous = film.title;
  try {
    const res = await fetch("/api/film/rename", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: film.title, year: film.year, newTitle }),
    });
    const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
    film.title = newTitle;
    await reload();
    toast(`Renamed to ${newTitle}`);
  } catch (err) {
    film.title = previous;
    titleEl.textContent = previous;
    toast(`Couldn't rename ${previous}: ${err.message}`, "error");
  }
}

function titleField(film) {
  const wrap = text("div", "title");
  // The title links to the film's own page; the pencil edits it in place.
  const label = text("a", "title-text", film.title);
  label.href = `/film/${film.slug}`;
  const edit = text("button", "edit-title", "✎");
  edit.type = "button";
  edit.title = `Rename ${film.title}`;
  edit.setAttribute("aria-label", `Rename ${film.title}`);

  edit.addEventListener("click", () => {
    const input = document.createElement("input");
    input.className = "title-input";
    input.value = film.title;
    input.setAttribute("aria-label", "Film title");

    const commit = (save) => {
      const next = input.value.trim();
      wrap.replaceChildren(label, edit);
      if (save && next && next !== film.title) renameFilm(film, next, label);
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") commit(true);
      if (e.key === "Escape") commit(false);
    });
    input.addEventListener("blur", () => commit(true));

    wrap.replaceChildren(input);
    input.focus();
    input.select();
  });

  wrap.append(label, edit);
  return wrap;
}

// The card every grid uses: the art fills the tile and the details sit on a
// scrim across the bottom of it. Chips (genres, streaming services) belong in
// the filters and on the detail pages, not drawn over artwork.
//
// `wide` picks the aspect ratio, which follows what the art actually is: film
// posters and character portraits are tall, show banners are wide.
function tile({ art, badge, pin = null, title, lines = [], wide = false, href = null }) {
  const card = text("article", wide ? "tile is-wide" : "tile");

  let node;
  if (art) {
    const img = document.createElement("img");
    img.className = "tile-art";
    img.src = art;
    // Decorative: the title is right there in the overlay, so announcing the
    // artwork as well would just repeat it.
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    node = img;
  } else {
    const blank = text("div", "tile-art is-blank");
    blank.setAttribute("aria-hidden", "true");
    node = blank;
  }
  // The art is the biggest target on the card; clicking it used to do nothing.
  card.append(href ? artLink(node, href) : node);

  if (badge) card.append(badge);
  if (pin) card.append(pin);

  const overlay = text("div", "tile-overlay");
  overlay.append(title);
  for (const line of lines) if (line) overlay.append(line);
  card.append(overlay);
  return card;
}

function filmCard(film) {
  // Show the raw country string, not the normalized region. Directors are
  // links to their own page; a film can credit several.
  const meta = text("div", "meta");
  if (film.year) {
    const yearLink = text("a", "year-link", String(film.year));
    yearLink.href = `/year/${film.year}`;
    yearLink.title = `Everything from ${film.year}`;
    meta.append(yearLink);
  }
  if (film.country) {
    if (meta.childElementCount) meta.append(text("span", null, " · "));
    meta.append(text("span", null, film.country));
  }
  for (const name of film.directors ?? []) {
    if (meta.childElementCount) meta.append(text("span", null, " · "));
    const link = text("a", "director-link", name);
    link.href = `/director/${slugify(name)}`;
    meta.append(link);
  }

  return tile({
    href: `/film/${film.slug}`,
    art: film.poster ? `/posters/${film.poster}` : null,
    badge: tierSelect(film),
    pin: shortlistToggle(film),
    title: titleField(film),
    lines: [
      // Original-language title for films not made in English.
      film.nativeTitle ? text("div", "native", film.nativeTitle) : null,
      meta.childElementCount ? meta : null,
    ],
  });
}

function tierRank(tier) {
  const i = DATA.tierOrder.indexOf(tier);
  return i === -1 ? DATA.tierOrder.length : i;
}

function visibleFilms() {
  const q = state.query.trim().toLowerCase();
  return DATA.films.filter((f) => {
    if (state.region !== "all" && f.region !== state.region) return false;
    if (state.genre !== "all" && !(f.genres ?? []).includes(state.genre)) return false;
    if (
      state.service !== "all" &&
      !(f.streaming ?? []).some((s) => s.name === state.service)
    ) {
      return false;
    }
    if (!q) return true;
    return (
      f.title.toLowerCase().includes(q) ||
      (f.country ?? "").toLowerCase().includes(q) ||
      (f.director ?? "").toLowerCase().includes(q) ||
      (f.note ?? "").toLowerCase().includes(q) ||
      (f.genres ?? []).some((g) => g.toLowerCase().includes(q)) ||
      (f.franchises ?? []).some((s) => s.toLowerCase().includes(q))
    );
  });
}

function renderFilms() {
  const host = el("films");
  host.replaceChildren();

  const films = visibleFilms();
  el("count").textContent = `${films.length} of ${DATA.films.length} films`;

  if (!films.length) {
    host.append(text("p", "empty", "Nothing matches that."));
    return;
  }

  if (state.sort === "tier") {
    const groups = new Map();
    for (const f of films) {
      if (!groups.has(f.tier)) groups.set(f.tier, []);
      groups.get(f.tier).push(f);
    }
    const tiers = [...groups.keys()].sort((a, b) => tierRank(a) - tierRank(b));
    for (const tier of tiers) {
      const section = text("section", "tier-group");
      const head = text("h2", "tier-head");
      const badge = text("span", "badge", tier);
      badge.dataset.tier = tier;
      const inTier = groups.get(tier).length;
      head.append(
        badge,
        text("span", null, tier === "?" ? "unrated" : `tier ${tier}`),
        TIER_MEANING[tier] && tier !== "?"
          ? text("span", "tier-meaning", `— ${TIER_MEANING[tier]}`)
          : text("span", null, ""),
        text("span", "tier-count", `${inTier} ${inTier === 1 ? "film" : "films"}`)
      );
      section.append(head);

      const grid = text("div", "grid is-tiles");
      const sorted = groups.get(tier).sort((a, b) => a.title.localeCompare(b.title));
      for (const f of sorted) grid.append(filmCard(f));
      section.append(grid);
      host.append(section);
    }
    return;
  }

  const sorted = [...films];
  if (state.sort === "title") sorted.sort((a, b) => a.title.localeCompare(b.title));
  // Films with no year sink to the bottom of either year sort.
  if (state.sort === "year-desc") sorted.sort((a, b) => (b.year ?? -Infinity) - (a.year ?? -Infinity));
  if (state.sort === "year-asc") sorted.sort((a, b) => (a.year ?? Infinity) - (b.year ?? Infinity));

  const grid = text("div", "grid is-tiles");
  for (const f of sorted) grid.append(filmCard(f));
  host.append(grid);
}

// The short list, in the order the films sit in the sheet. Unrated first,
// because that's what the list is for; anything rated has been watched and is
// only still here because it hasn't been taken off.
function renderShortlist() {
  const host = el("shortlist");
  host.replaceChildren();

  const picked = DATA.films.filter((f) => f.shortlisted);
  const waiting = picked.filter((f) => f.tier === "?");
  const seen = picked.filter((f) => f.tier !== "?");
  el("shortlist-count").textContent = picked.length
    ? `${picked.length} film${picked.length === 1 ? "" : "s"}` +
      (seen.length ? ` · ${seen.length} now rated` : "")
    : "";

  if (!picked.length) {
    host.append(
      text(
        "p",
        "empty",
        "Nothing on the short list yet — hit the ★ on a film to put it here."
      )
    );
    return;
  }

  const section = (label, films, hint) => {
    if (!films.length) return;
    const box = text("section", "tier-group");
    const head = text("h2", "tier-head");
    head.append(text("span", null, label));
    head.append(text("span", "tier-count", `${films.length}`));
    box.append(head);
    if (hint) box.append(text("p", "hint", hint));
    const grid = text("div", "grid is-tiles");
    for (const film of films) grid.append(filmCard(film));
    box.append(grid);
    host.append(box);
  };

  section("To watch", waiting, null);
  section("Watched since", seen, "Rated now — take them off with the ★.");
}

function renderFranchises() {
  const host = el("franchises");
  host.replaceChildren();

  const list = DATA.franchises ?? [];
  // franchiseFilmCount counts films once even when they sit in several series.
  const films = DATA.franchiseFilmCount ?? 0;
  const rest = list.reduce((n, f) => n + (f.others ?? []).length, 0);
  el("franchise-lede").textContent = list.length
    ? `${films} of your films belong to a larger series — ${list.length} in all, ` +
      `with ${rest} further entries you haven't logged. ` +
      `Membership comes from Wikidata, so films it couldn't match are missing.`
    : "";

  if (!list.length) {
    host.append(
      text("p", "empty", "No franchises yet — run scripts/autofill.py to pull series data.")
    );
    return;
  }

  const row = (film) => {
    const li = document.createElement("li");
    const badge = text("span", "badge", film.tier);
    badge.dataset.tier = film.tier;
    badge.title = TIER_MEANING[film.tier] ?? film.tier;
    const link = text("a", "ttl", film.title);
    link.href = `/film/${film.slug}`;
    li.append(
      poster(film, "poster-sm", `/film/${film.slug}`),
      badge,
      text("span", "yr", film.year ?? "—"),
      link
    );
    if (film.director) li.append(text("span", "dir", film.director));
    return li;
  };

  // Films in the series that aren't in the collection: no rating, no poster.
  const otherRow = (film) => {
    const li = text("li", "other");
    li.append(text("span", "yr", film.year ?? "—"), text("span", "ttl", film.title));
    if (film.director) li.append(text("span", "dir", film.director));
    return li;
  };

  for (const series of list) {
    const box = text("div", "franchise");
    const seen = series.films.length;
    const head = text("h3", null, series.name);
    head.append(
      text("span", "n", `  ${seen} watched${series.others.length ? ` of ${seen + series.others.length}` : ""}`)
    );
    box.append(head);

    const ol = document.createElement("ol");
    for (const film of series.films) ol.append(row(film));
    box.append(ol);

    // The rest of the series folds away at the bottom of the card. <details>
    // gives us open/close and keyboard support for free.
    if (series.others.length) {
      const details = document.createElement("details");
      details.className = "others";
      const summary = document.createElement("summary");
      const n = series.others.length;
      summary.textContent = `${n} more in this franchise you haven't logged`;
      details.append(summary);
      const rest = document.createElement("ol");
      for (const film of series.others) rest.append(otherRow(film));
      details.append(rest);
      box.append(details);
    }

    host.append(box);
  }
}

async function saveCharacterRating(character, tier, select) {
  const previous = character.tier;
  character.tier = tier;
  select.dataset.tier = tier;
  select.classList.add("is-saving");
  select.disabled = true;
  try {
    const res = await fetch("/api/character/rating", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: character.name, tier }),
    });
    const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
    select.classList.add("is-saved");
    setTimeout(() => select.classList.remove("is-saved"), 900);
    toast(`${character.name} → ${tier}`);
    // The card belongs to a different tier row now; regroup so the headings
    // stay honest.
    if (charState.sort === "tier") renderCharacters();
  } catch (err) {
    // Put the old value back so the page never disagrees with the file.
    character.tier = previous;
    select.value = previous;
    select.dataset.tier = previous;
    toast(`Couldn't save ${character.name}: ${err.message}`, "error");
  } finally {
    select.classList.remove("is-saving");
    select.disabled = false;
  }
}

function characterTierSelect(character) {
  const select = tierBadgeSelect(character.tier ?? "?", character.name, { meanings: false });
  select.addEventListener("change", () =>
    saveCharacterRating(character, select.value, select)
  );
  return select;
}

function characterCard(character) {
  const title = text("div", "title");
  const link = text("a", "title-text", character.name);
  link.href = `/character/${character.slug}`;
  title.append(link);

  // Portraits are tall far more often than not, so they take the same 2:3 tile
  // the posters do; the handful of landscape ones crop to centre, which is
  // where a character's face tends to be anyway.
  return tile({
    href: `/character/${character.slug}`,
    art: character.photo ? `/characters/${character.photo}` : null,
    badge: characterTierSelect(character),
    title,
    lines: [
      character.show ? text("div", "meta", character.show) : null,
      character.why ? text("div", "note", character.why) : null,
    ],
  });
}

async function awaitPortrait(name, tries = 15) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    const fresh = await (await fetch("/api/data")).json();
    const character = fresh.characters.find((c) => c.name === name);
    if (character?.photo) {
      DATA = fresh;
      renderCharacters();
      toast(`Portrait found for ${name}`);
      return;
    }
  }
}

function setupCharacterForm() {
  const form = el("char-form");
  const toggle = el("char-toggle");

  const show = (open) => {
    form.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "− Add character" : "+ Add character";
    if (open) form.elements.name.focus();
  };

  toggle.addEventListener("click", () => show(form.hidden));
  el("char-cancel").addEventListener("click", () => {
    form.reset();
    show(false);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    const data = Object.fromEntries(new FormData(form));
    const name = String(data.name ?? "").trim();
    if (!name) return;

    const send = (allowDuplicate) =>
      fetch("/api/character", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name,
          show: String(data.show ?? "").trim() || null,
          why: String(data.why ?? "").trim() || null,
          allowDuplicate,
        }),
      }).then(async (res) => [res, await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))]);

    submit.disabled = true;
    submit.textContent = "Adding…";
    try {
      let [res, result] = await send(false);
      if (res.status === 409) {
        if (!confirm(`"${name}" is already in your characters. Add again anyway?`)) return;
        [res, result] = await send(true);
      }
      if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
      form.reset();
      show(false);
      DATA = await (await fetch("/api/data")).json();
      renderCharacters();
      toast(`Added ${name} — looking for a portrait…`);
      awaitPortrait(name);
    } catch (err) {
      toast(`Couldn't add ${name}: ${err.message}`, "error");
    } finally {
      submit.disabled = false;
      submit.textContent = "Add character";
    }
  });
}

function renderCharacters() {
  const host = el("characters");
  host.replaceChildren();
  const count = el("char-count");
  if (count) {
    const n = DATA.characters.length;
    count.textContent = `${n} character${n === 1 ? "" : "s"}`;
  }
  if (!DATA.characters.length) {
    host.append(text("p", "empty", "No characters yet."));
    return;
  }

  // Ranked view: one row per tier, best first, same grouping the films use.
  if (charState.sort === "tier") {
    // `host` is the .grid itself for the flat sorts; tier rows bring their own
    // grids, so it has to stop being one.
    host.className = "";
    const groups = new Map();
    for (const c of DATA.characters) {
      const tier = c.tier ?? "?";
      if (!groups.has(tier)) groups.set(tier, []);
      groups.get(tier).push(c);
    }
    const tiers = [...groups.keys()].sort((a, b) => tierRank(a) - tierRank(b));
    for (const tier of tiers) {
      const section = text("section", "tier-group");
      const head = text("h2", "tier-head");
      const badge = text("span", "badge", tier);
      badge.dataset.tier = tier;
      const inTier = groups.get(tier).length;
      head.append(
        badge,
        text("span", null, tier === "?" ? "unranked" : `tier ${tier}`),
        text("span", "tier-count", `${inTier} character${inTier === 1 ? "" : "s"}`)
      );
      section.append(head);

      const grid = text("div", "grid is-tiles");
      const sorted = [...groups.get(tier)].sort((a, b) => a.name.localeCompare(b.name));
      for (const c of sorted) grid.append(characterCard(c));
      section.append(grid);
      host.append(section);
    }
    return;
  }

  host.className = "grid is-tiles";
  const sorted = [...DATA.characters];
  if (charState.sort === "name") sorted.sort((a, b) => a.name.localeCompare(b.name));
  if (charState.sort === "show") {
    sorted.sort(
      (a, b) =>
        (a.show ?? "").localeCompare(b.show ?? "") || a.name.localeCompare(b.name)
    );
  }
  for (const c of sorted) host.append(characterCard(c));
}

function showCard(show) {
  const title = text("div", "title");
  const link = text("a", "title-text", show.name);
  link.href = `/show/${show.slug}`;
  title.append(link);

  const bits = [
    show.years,
    show.seasons ? `${show.seasons} season${show.seasons === "1" ? "" : "s"}` : null,
    show.episodes ? `${show.episodes} ep${show.episodes === "1" ? "" : "s"}` : null,
    show.country,
  ].filter(Boolean);

  // Wide tiles: most show art is a banner (1280×320 up to 9215×2000), which a
  // 2:3 tile would crop down to a sliver. The few portrait posters crop
  // instead, which loses much less.
  //
  // Three lines, not four: the scrim grows with its content, and author plus
  // streaming chips left the artwork with nothing visible. Both are on the
  // show's own page.
  return tile({
    wide: true,
    href: `/show/${show.slug}`,
    art: show.photo ? `/shows/${show.photo}` : null,
    title,
    lines: [
      show.nativeTitle ? text("div", "native", show.nativeTitle) : null,
      bits.length ? text("div", "meta", bits.join(" · ")) : null,
    ],
  });
}

// Details arrive after the row is added, so watch for them rather than making
// the user reload. Wikidata is slow under rate limiting; give up quietly.
async function awaitShowDetails(name, tries = 20) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    const fresh = await (await fetch("/api/data")).json();
    // The name itself may be corrected ("Parasyte" -> "Parasyte: The Maxim").
    const show =
      fresh.shows.find((s) => s.name === name) ??
      fresh.shows.find((s) => s.name.toLowerCase().includes(name.toLowerCase()));
    if (show && (show.photo || show.years)) {
      DATA = fresh;
      renderShows();
      toast(`Filled in ${show.name}`);
      return;
    }
  }
}

function setupShowForm() {
  const form = el("show-form");
  const toggle = el("show-toggle");

  const show = (open) => {
    form.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "− Add show" : "+ Add show";
    if (open) form.elements.name.focus();
  };

  toggle.addEventListener("click", () => show(form.hidden));
  el("show-cancel").addEventListener("click", () => {
    form.reset();
    show(false);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    const name = String(new FormData(form).get("name") ?? "").trim();
    if (!name) return;

    const send = (allowDuplicate) =>
      fetch("/api/show", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, allowDuplicate }),
      }).then(async (res) => [res, await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))]);

    submit.disabled = true;
    submit.textContent = "Adding…";
    try {
      let [res, result] = await send(false);
      if (res.status === 409) {
        if (!confirm(`"${name}" is already in your shows. Add again anyway?`)) return;
        [res, result] = await send(true);
      }
      if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
      form.reset();
      show(false);
      DATA = await (await fetch("/api/data")).json();
      renderShows();
      toast(`Added ${name} — looking up details…`);
      awaitShowDetails(name);
    } catch (err) {
      toast(`Couldn't add ${name}: ${err.message}`, "error");
    } finally {
      submit.disabled = false;
      submit.textContent = "Add show";
    }
  });
}

// The three filters over the Shows page. Only values some show actually has
// are offered — thirteen shows against nine regions and twenty genres would
// otherwise be mostly dead options — and each carries its count, so the size
// of a category is visible before you pick it.
function setupShowFilters(countBy) {
  const regionCounts = countBy(DATA.shows, (s) => (s.region ? [s.region] : []));
  const genreCounts = countBy(DATA.shows, (s) => s.genres ?? []);
  const formatCounts = countBy(DATA.shows, (s) => (s.format ? [s.format] : []));
  const byCount = (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]);

  const fill = (id, all, entries, onPick) => {
    const select = el(id);
    if (!select) return;
    select.append(new Option(all, "all"));
    for (const [value, n] of entries) select.append(new Option(`${value} (${n})`, value));
    select.addEventListener("change", (event) => {
      onPick(event.target.value);
      renderShows();
    });
  };

  fill(
    "show-region",
    `All regions (${DATA.shows.length})`,
    [...regionCounts].sort(byCount),
    (value) => (showState.region = value)
  );
  fill(
    "show-genre",
    `All genres (${DATA.shows.filter((s) => (s.genres ?? []).length).length})`,
    // In the shared order, so the list reads the same here as on the films
    // page; only the counts beside each genre are the shows' own.
    (DATA.genres ?? []).filter((g) => genreCounts.has(g)).map((g) => [g, genreCounts.get(g)]),
    (value) => (showState.genre = value)
  );
  fill(
    "show-format",
    `Animated and live action (${[...formatCounts.values()].reduce((a, b) => a + b, 0)})`,
    (DATA.showFormats ?? []).filter((f) => formatCounts.has(f)).map((f) => [f, formatCounts.get(f)]),
    (value) => (showState.format = value)
  );
}

function visibleShows() {
  return DATA.shows.filter((s) => {
    if (showState.region !== "all" && s.region !== showState.region) return false;
    if (showState.genre !== "all" && !(s.genres ?? []).includes(showState.genre)) return false;
    if (showState.format !== "all" && s.format !== showState.format) return false;
    return true;
  });
}

function renderShows() {
  const host = el("shows");
  host.replaceChildren();

  const shows = visibleShows();
  const count = el("show-count");
  if (count) {
    const all = DATA.shows.length;
    count.textContent =
      shows.length === all
        ? `${all} show${all === 1 ? "" : "s"}`
        : `${shows.length} of ${all} shows`;
  }
  if (!shows.length) {
    host.className = "";
    // Told apart, because an empty grid means two different things: nothing
    // added yet, or nothing left after filtering.
    host.append(text("p", "empty", DATA.shows.length ? "Nothing matches that." : "No shows yet."));
    return;
  }
  host.className = "grid is-tiles-wide";
  for (const s of shows) host.append(showCard(s));
}

async function reload() {
  const res = await fetch("/api/data");
  DATA = await res.json();
  renderFilms();
  renderShortlist();
  renderFranchises();
}

// The poster is fetched after the film is added, so watch for it to appear
// rather than making the user reload. Wikipedia's rate limits mean this can
// take a while; give up quietly and let the next refresh pick it up.
async function awaitPoster(title, year, tries = 20) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    const res = await fetch("/api/data");
    const fresh = await res.json();
    const film = fresh.films.find(
      (f) => f.title === title && (year == null || f.year === year)
    );
    if (film?.poster) {
      DATA = fresh;
      renderFilms();
      renderFranchises();
      toast(`Poster found for ${title}`);
      return;
    }
  }
}

function setupAddForm() {
  const form = el("add-form");
  const toggle = el("add-toggle");

  const show = (open) => {
    form.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "− Add film" : "+ Add film";
    if (open) form.elements.title.focus();
  };

  toggle.addEventListener("click", () => show(form.hidden));
  el("add-cancel").addEventListener("click", () => {
    form.reset();
    show(false);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]");
    const data = Object.fromEntries(new FormData(form));
    const title = String(data.title ?? "").trim();
    if (!title) return;

    const send = async (allowDuplicate) => {
      const res = await fetch("/api/film", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title,
          year: String(data.year ?? "").trim() || null,
          director: String(data.director ?? "").trim() || null,
          country: String(data.country ?? "").trim() || null,
          tier: String(data.tier ?? "?").trim() || "?",
          allowDuplicate,
        }),
      });
      return [res, await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))];
    };

    submit.disabled = true;
    submit.textContent = "Adding…";
    try {
      let [res, result] = await send(false);
      if (res.status === 409) {
        // Already present — the sheet has real duplicates, so ask rather than assume.
        if (!confirm(`"${title}" is already in your list. Add it again anyway?`)) return;
        [res, result] = await send(true);
      }
      if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);

      form.reset();
      show(false);
      await reload();
      toast(`Added ${title} — looking for a poster…`);
      awaitPoster(title, result.film?.year ?? null);
    } catch (err) {
      toast(`Couldn't add ${title}: ${err.message}`, "error");
    } finally {
      submit.disabled = false;
      submit.textContent = "Add film";
    }
  });
}

const VIEWS = ["films", "shortlist", "franchises", "characters", "shows"];

// Each of these is its own URL — /franchises, /characters, /shows — served the
// same HTML, with the view picked here. Matching on the end of the path rather
// than the whole of it keeps this working under the /Screened base the
// published copy is served from, with no rewriting.
function currentView() {
  const path = location.pathname.replace(/\/$/, "");
  for (const name of VIEWS) {
    if (path.endsWith(`/${name}`)) return name;
  }
  // Links from before these were pages.
  const hash = location.hash.slice(1);
  return VIEWS.includes(hash) ? hash : "films";
}

function setView(view) {
  for (const tab of el("tabs").children) {
    tab.classList.toggle("is-active", tab.dataset.view === view);
    if (tab.dataset.view === view) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  for (const name of VIEWS) {
    el(`view-${name}`).hidden = name !== view;
  }
}

function fail(message) {
  el("main").replaceChildren(text("p", "empty", message));
}

// A render that throws would otherwise leave a silently blank page — which is
// exactly what happened when data.json predated the genres field.
function safely(label, fn) {
  try {
    fn();
  } catch (err) {
    console.error(`${label} failed`, err);
    toast(`Couldn't render ${label}: ${err.message}. Try re-running scripts/extract.py.`, "error");
  }
}

async function init() {
  let res;
  try {
    res = await fetch("/api/data");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    fail(`Couldn't load the data (${err.message}). Is the server still running?`);
    return;
  }

  // Counts in the filter labels, so the size of each category is visible
  // before you pick it.
  const countBy = (rows, pick) => {
    const tally = new Map();
    for (const row of rows) {
      for (const value of pick(row)) tally.set(value, (tally.get(value) ?? 0) + 1);
    }
    return tally;
  };
  const regionCounts = countBy(DATA.films, (f) => (f.region ? [f.region] : []));
  const genreCounts = countBy(DATA.films, (f) => f.genres ?? []);

  // Both vocabularies are shared with the Shows page, so each option is only
  // offered where a film actually carries it — otherwise a region or a genre
  // that only a show has would sit here reading "(0)".
  const region = el("region");
  region.append(new Option(`All regions (${DATA.films.length})`, "all"));
  for (const r of DATA.regions) {
    if (regionCounts.has(r)) region.append(new Option(`${r} (${regionCounts.get(r)})`, r));
  }

  const genre = el("genre");
  const anyGenre = DATA.films.filter((f) => (f.genres ?? []).length).length;
  genre.append(new Option(`All genres (${anyGenre})`, "all"));
  for (const g of DATA.genres ?? []) {
    if (genreCounts.has(g)) genre.append(new Option(`${g} (${genreCounts.get(g)})`, g));
  }
  genre.addEventListener("change", (e) => {
    state.genre = e.target.value;
    renderFilms();
  });

  // Services come from what streaming.json actually found, not from the logo
  // list, so a service nothing is on never appears as a dead option.
  const serviceCounts = countBy(DATA.films, (f) => [
    ...new Set((f.streaming ?? []).map((s) => s.name)),
  ]);
  const service = el("service");
  const anyService = DATA.films.filter((f) => (f.streaming ?? []).length).length;
  service.append(new Option(`All services (${anyService})`, "all"));
  for (const [name, n] of [...serviceCounts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
    service.append(new Option(`${name} (${n})`, name));
  }
  service.addEventListener("change", (e) => {
    state.service = e.target.value;
    renderFilms();
  });

  el("search").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderFilms();
  });
  region.addEventListener("change", (e) => {
    state.region = e.target.value;
    renderFilms();
  });
  el("sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    renderFilms();
  });
  el("char-sort").addEventListener("change", (e) => {
    charState.sort = e.target.value;
    renderCharacters();
  });

  setupShowFilters(countBy);
  setupAddForm();
  setupCharacterForm();
  setupShowForm();
  safely("films", renderFilms);
  safely("shortlist", renderShortlist);
  safely("franchises", renderFranchises);
  safely("characters", renderCharacters);
  safely("shows", renderShows);

  setView(currentView());
}

init();
