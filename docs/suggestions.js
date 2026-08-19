const el = (id) => document.getElementById(id);

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

// Which reason a filter keeps. "All" is the default; the rest answer a
// different question — "what else has this director made", "what's left of a
// series", "what did everyone else watch that year".
const FILTERS = [
  { key: "all", label: "Everything" },
  { key: "director", label: "Directors you like" },
  { key: "franchise", label: "Series you follow" },
  // No "where from" filter: nearly every suggestion matches a region you
  // already watch, so it would narrow nothing. The reason still shows on the
  // card, where it explains a ranking rather than pretending to be a control.
  { key: "popular", label: "Big at the box office" },
];

let toastTimer;
function toast(message, kind = "info") {
  const node = el("toast");
  node.textContent = message;
  node.dataset.kind = kind;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), kind === "error" ? 6000 : 2600);
}

function text(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
}

const slugify = (name) =>
  String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "film";

// Directors with a page of their own — i.e. with a film already in the list.
const KNOWN_DIRECTORS = new Set();

// Adding straight from a suggestion is the whole point of the page, so it uses
// the same endpoint as the Add film form and lands unrated.
async function addFilm(entry, button) {
  button.disabled = true;
  button.textContent = "Adding…";
  try {
    const res = await fetch("/Screened/api/film", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title: entry.title,
        year: entry.year ?? null,
        director: (entry.directors ?? []).join(", ") || null,
        tier: "?",
      }),
    });
    const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
    button.textContent = "✓ In your unrated";
    button.classList.add("is-added");
    toast(`Added ${entry.title} to unrated — looking for a poster…`);
  } catch (err) {
    button.disabled = false;
    button.textContent = "+ Add to unrated";
    toast(`Couldn't add ${entry.title}: ${err.message}`, "error");
  }
}

function reasonList(entry) {
  const ul = text("ul", "reasons");
  for (const reason of entry.reasons ?? []) {
    const li = text("li", `reason reason-${reason.kind}`);
    li.append(text("span", "reason-text", reason.text));
    ul.append(li);
  }
  return ul;
}

function suggestionCard(entry, best) {
  const card = text("article", "suggestion");

  // Poster on the left, everything else in a column beside it. Films with no
  // poster get the same dashed footprint the film list uses, so a row of cards
  // doesn't shift around.
  const art = document.createElement(entry.poster ? "img" : "div");
  art.className = entry.poster ? "sug-poster" : "sug-poster is-blank";
  if (entry.poster) {
    art.src = `/Screened/posters/${entry.poster}`;
    art.alt = `${entry.title} poster`;
    art.loading = "lazy";
    art.decoding = "async";
  } else {
    art.setAttribute("aria-hidden", "true");
  }
  card.append(art);

  const body = text("div", "sug-body");
  const head = text("div", "sug-head");
  const title = text("span", "sug-title", entry.title);
  head.append(title);
  if (entry.year) head.append(text("span", "sug-year", String(entry.year)));
  if (entry.upcoming) head.append(text("span", "chip-soon", "not out yet"));
  body.append(head);

  const who = (entry.directors ?? []).filter(Boolean);
  if (who.length) {
    const line = text("div", "sug-sub");
    who.forEach((name, i) => {
      if (i) line.append(text("span", null, ", "));
      // Only a director with films in the list has a page to link to.
      if (KNOWN_DIRECTORS.has(name)) {
        const link = text("a", "director-link", name);
        link.href = `/Screened/director/${slugify(name)}`;
        line.append(link);
      } else {
        line.append(text("span", null, name));
      }
    });
    body.append(line);
  }

  if ((entry.genres ?? []).length) {
    body.append(text("div", "sug-genres", entry.genres.join(" · ")));
  }

  body.append(reasonList(entry));

  // How strongly it matches, relative to the top suggestion — an absolute
  // number would only look precise, not be it.
  const meter = text("div", "match");
  const fill = text("div", "match-fill");
  fill.style.width = `${Math.max(6, Math.round((entry.score / best) * 100))}%`;
  meter.append(fill);
  meter.title = `Match strength, relative to the strongest suggestion`;
  body.append(meter);

  const actions = text("div", "sug-actions");
  const add = text("button", "add-suggestion", "+ Add to unrated");
  add.type = "button";
  add.title = `Add ${entry.title} to your list unrated — the queue below`;
  add.addEventListener("click", () => addFilm(entry, add));
  actions.append(add);
  if (entry.qid) {
    const look = text("a", "sug-link", "Wikidata ↗");
    look.href = `https://www.wikidata.org/wiki/${entry.qid}`;
    look.target = "_blank";
    look.rel = "noopener noreferrer";
    actions.append(look);
  }
  body.append(actions);
  card.append(body);
  return card;
}


// Artwork that links to the film's own page. The title beside it already links
// to the same place, so this one is hidden from assistive tech and skipped when
// tabbing rather than read out and stopped at twice.
function artLink(art, href) {
  const link = text("a", "art-link");
  link.href = href;
  link.setAttribute("aria-hidden", "true");
  link.tabIndex = -1;
  link.append(art);
  return link;
}

function backlogRow(entry) {
  const li = text("li", "backlog-row");

  if (entry.poster) {
    const img = document.createElement("img");
    img.className = "poster-sm";
    img.src = `/Screened/posters/${entry.poster}`;
    img.alt = "";
    img.loading = "lazy";
    li.append(artLink(img, `/Screened/film/${entry.slug}`));
  } else {
    const blank = text("div", "poster-sm is-blank");
    blank.setAttribute("aria-hidden", "true");
    li.append(artLink(blank, `/Screened/film/${entry.slug}`));
  }

  const body = text("div", "backlog-body");
  const head = text("div", "backlog-head");
  const link = text("a", "ttl", entry.title);
  link.href = `/Screened/film/${entry.slug}`;
  head.append(link);
  if (entry.year) head.append(text("span", "yr", String(entry.year)));
  body.append(head);

  const first = (entry.reasons ?? [])[0];
  body.append(
    text(
      "div",
      first ? "backlog-why" : "backlog-why is-quiet",
      first ? first.text : "Nothing to go on yet — rate more of what you've seen"
    )
  );
  li.append(body);
  return li;
}

function tasteStrip(taste) {
  const box = text("section", "taste");
  const directors = (taste.directors ?? []).slice(0, 6);
  const genres = (taste.genres ?? []).slice(0, 8);
  if (!directors.length && !genres.length) return null;

  box.append(text("h2", null, "What this is based on"));
  if (directors.length) {
    const line = text("div", "taste-row");
    line.append(text("span", "taste-label", "Directors"));
    for (const item of directors) {
      const chip = text("a", "taste-chip", `${item.name} · ${item.count}`);
      chip.href = `/Screened/director/${slugify(item.name)}`;
      chip.title = `${item.count} in your list`;
      line.append(chip);
    }
    box.append(line);
  }
  if (genres.length) {
    const line = text("div", "taste-row");
    line.append(text("span", "taste-label", "Genres"));
    for (const item of genres) {
      line.append(text("span", "taste-chip", `${item.name} · ${item.count}`));
    }
    box.append(line);
  }
  const regions = (taste.regions ?? []).slice(0, 8);
  if (regions.length) {
    const line = text("div", "taste-row");
    line.append(text("span", "taste-label", "Where from"));
    for (const item of regions) {
      line.append(text("span", "taste-chip", `${item.name} · ${item.count}`));
    }
    box.append(line);
  }
  return box;
}

function render(data) {
  for (const director of data.directors ?? []) KNOWN_DIRECTORS.add(director.name);
  const suggestions = data.suggestions ?? {};
  const films = suggestions.films ?? [];
  const backlog = suggestions.unrated ?? [];
  const main = el("main");
  main.replaceChildren();

  main.append(text("h1", "director-name", "What to watch next"));
  main.append(
    text(
      "p",
      "lede",
      films.length
        ? `Ranked from the ${suggestions.rated} films you've rated — who directed them, which ` +
          `series they belong to, where they were made, and which genres you keep rating highly. ` +
          `Adding one puts it in your list unrated, which is the same queue as the unrated ` +
          `films further down.`
        : "Nothing to suggest yet. Rate a few films and this fills itself in."
    )
  );

  const strip = tasteStrip(suggestions.taste ?? {});
  if (strip) main.append(strip);

  if (films.length) {
    const section = text("section", "sug-section");
    const bar = text("div", "sug-filters");
    const count = text("span", "count", "");
    const grid = text("div", "sug-grid");
    const best = films[0].score || 1;

    let active = "all";
    const draw = () => {
      const shown =
        active === "all"
          ? films
          : films.filter((f) => (f.reasons ?? []).some((r) => r.kind === active));
      grid.replaceChildren(...shown.map((f) => suggestionCard(f, best)));
      count.textContent = `${shown.length} film${shown.length === 1 ? "" : "s"}`;
      if (!shown.length) grid.append(text("p", "empty", "Nothing under this heading yet."));
    };

    for (const filter of FILTERS) {
      const button = text("button", "sug-filter", filter.label);
      button.type = "button";
      button.classList.toggle("is-active", filter.key === active);
      button.addEventListener("click", () => {
        active = filter.key;
        for (const other of bar.querySelectorAll(".sug-filter")) {
          other.classList.toggle("is-active", other === button);
        }
        draw();
      });
      bar.append(button);
    }
    bar.append(count);

    section.append(text("h2", null, "New to you"));
    section.append(bar, grid);
    draw();
    main.append(section);
  }

  if (backlog.length) {
    const section = text("section", "sug-section");
    section.append(text("h2", null, "Already on your list, unrated"));
    section.append(
      text(
        "p",
        "hint",
        `${backlog.length} films you've added but not rated, best match first — ` +
          `unrated is the watch-next queue, and anything added above lands here.`
      )
    );
    const ol = text("ol", "backlog");
    for (const entry of backlog) ol.append(backlogRow(entry));
    section.append(ol);
    main.append(section);
  }

  const note = text("p", "hint hint-foot");
  note.append(
    document.createTextNode(
      "Suggestions come from the rest of your directors' filmographies, the series you've " +
        "started, and each year's biggest earners — scored against your own ratings, never " +
        "anyone else's, and never fetched from anywhere at page load. They update as soon " +
        "as you rate something."
    )
  );
  main.append(note);
}

async function init() {
  let data;
  try {
    const res = await fetch("/Screened/api/data.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }
  document.title = "What to watch next — Screened";
  render(data);
}

init();
