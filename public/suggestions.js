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
const TIERS = ["S", "A", "B", "C", "D", "E", "F", "?"];

// Single characters with the meaning on each option's tooltip: a <select> is as
// wide as its widest option, and the spelled-out tiers stretch it across a card.
function tierOptions(select, { includeUnrated, verb }) {
  if (includeUnrated) {
    const unrated = new Option("?", "?");
    unrated.title = `${verb} unrated — the watch-later queue`;
    select.append(unrated);
  }
  for (const tier of TIERS) {
    if (tier === "?") continue;
    const option = new Option(tier, tier);
    option.title = `${verb} at ${tier} — ${TIER_MEANING[tier] ?? tier}`;
    select.append(option);
  }
}

function settle(control, tier, message) {
  const badge = text("span", "badge", tier);
  badge.dataset.tier = tier;
  badge.title = TIER_MEANING[tier] ?? tier;
  control.replaceWith(badge);
  toast(message);
}

// Not in the list yet: pick a tier to add it at, or ? for unrated.
function addControl(entry) {
  const select = document.createElement("select");
  select.className = "badge is-add";
  select.title = `Add ${entry.title} to your list`;
  select.setAttribute("aria-label", `Add ${entry.title} to your list`);
  select.append(new Option("+", "", true, true));
  tierOptions(select, { includeUnrated: true, verb: "Add" });
  select.addEventListener("change", async () => {
    const tier = select.value;
    if (!tier) return;
    select.disabled = true;
    try {
      const res = await fetch("/api/film", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title: entry.title,
          year: entry.year ?? null,
          director: (entry.directors ?? []).join(", ") || null,
          tier,
        }),
      });
      const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
      if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
      settle(
        select,
        tier,
        tier === "?"
          ? `Added ${entry.title} to unrated — looking for a poster…`
          : `Added ${entry.title} at ${tier} — looking for a poster…`
      );
    } catch (err) {
      select.disabled = false;
      select.value = "";
      toast(`Couldn't add ${entry.title}: ${err.message}`, "error");
    }
  });
  return select;
}

// Already in the list and unrated: the thing to do is rate it, which is also
// what takes it off this queue.
function rateControl(entry) {
  const select = document.createElement("select");
  select.className = "badge";
  select.dataset.tier = "?";
  select.title = `Rate ${entry.title}`;
  select.setAttribute("aria-label", `Rate ${entry.title}`);
  select.append(new Option("?", "?", true, true));
  tierOptions(select, { includeUnrated: false, verb: "Rate" });
  select.addEventListener("change", async () => {
    const tier = select.value;
    if (tier === "?") return;
    select.disabled = true;
    try {
      const res = await fetch("/api/rating", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: entry.title, year: entry.year ?? null, tier }),
      });
      const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
      if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
      settle(select, tier, `${entry.title} → ${tier}`);
    } catch (err) {
      select.disabled = false;
      select.value = "?";
      toast(`Couldn't rate ${entry.title}: ${err.message}`, "error");
    }
  });
  return select;
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
    art.src = `/posters/${entry.poster}`;
    art.alt = `${entry.title} poster`;
    art.loading = "lazy";
    art.decoding = "async";
  } else {
    art.setAttribute("aria-hidden", "true");
  }
  card.append(art);

  const body = text("div", "sug-body");
  const head = text("div", "sug-head");
  // An unrated film is already in the list, so it has a page; a recommendation
  // does not.
  const title = entry.owned
    ? text("a", "sug-title", entry.title)
    : text("span", "sug-title", entry.title);
  if (entry.owned) title.href = `/film/${entry.slug}`;
  head.append(title);
  if (entry.year) head.append(text("span", "sug-year", String(entry.year)));
  if (entry.upcoming) head.append(text("span", "chip-soon", "not out yet"));
  if (entry.owned) head.append(text("span", "chip-owned", "on your list"));
  body.append(head);

  const who = (entry.directors ?? []).filter(Boolean);
  if (who.length) {
    const line = text("div", "sug-sub");
    who.forEach((name, i) => {
      if (i) line.append(text("span", null, ", "));
      // Only a director with films in the list has a page to link to.
      if (KNOWN_DIRECTORS.has(name)) {
        const link = text("a", "director-link", name);
        link.href = `/director/${slugify(name)}`;
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
  // Already in the list: the thing to do is rate it. Not in the list yet: the
  // thing to do is add it, at a tier or unrated.
  const add = entry.owned ? rateControl(entry) : addControl(entry);
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
      chip.href = `/director/${slugify(item.name)}`;
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
  // Unrated is the watch-later queue, so those films are ranked alongside the
  // recommendations rather than parked below them. Both scores come out of the
  // same pass in extract.py, so they compare directly.
  const queue = [
    ...films.map((f) => ({ ...f, owned: false })),
    ...backlog.map((f) => ({ ...f, owned: true })),
  ].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
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
          `Films already on your list but unrated are ranked in here too: unrated is the ` +
          `watch-later queue.`
        : "Nothing to suggest yet. Rate a few films and this fills itself in."
    )
  );

  const strip = tasteStrip(suggestions.taste ?? {});
  if (strip) main.append(strip);

  if (queue.length) {
    const section = text("section", "sug-section");
    const bar = text("div", "sug-filters");
    const count = text("span", "count", "");
    const grid = text("div", "sug-grid");
    const best = queue[0].score || 1;

    let active = "all";
    let director = "all";
    let genre = "all";

    const draw = () => {
      const shown = queue.filter((f) => {
        if (active !== "all" && !(f.reasons ?? []).some((r) => r.kind === active)) return false;
        if (director !== "all" && !(f.directors ?? []).includes(director)) return false;
        if (genre !== "all" && !(f.genres ?? []).includes(genre)) return false;
        return true;
      });
      grid.replaceChildren(...shown.map((f) => suggestionCard(f, best)));
      const onList = shown.filter((f) => f.owned).length;
      count.textContent =
        (shown.length === queue.length
          ? `${queue.length} film${queue.length === 1 ? "" : "s"}`
          : `${shown.length} of ${queue.length} films`) +
        (onList ? ` · ${onList} already on your list` : "");
      if (!shown.length) {
        grid.append(text("p", "empty", "Nothing matches that combination."));
      }
    };

    // Facets built from the suggestions themselves, most-used first, so the
    // list leads with the ones worth picking and never offers a dead option.
    const facet = (label, pick, onPick) => {
      const tally = new Map();
      for (const film of queue) {
        for (const value of pick(film)) tally.set(value, (tally.get(value) ?? 0) + 1);
      }
      const select = document.createElement("select");
      select.setAttribute("aria-label", `Filter by ${label}`);
      const covered = queue.filter((f) => pick(f).length).length;
      select.append(new Option(`All ${label} (${covered})`, "all"));
      for (const [value, n] of [...tally].sort(
        (a, b) => b[1] - a[1] || a[0].localeCompare(b[0])
      )) {
        select.append(new Option(`${value} (${n})`, value));
      }
      select.addEventListener("change", (event) => {
        onPick(event.target.value);
        draw();
      });
      return select;
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

    bar.append(
      facet("directors", (f) => f.directors ?? [], (v) => (director = v)),
      facet("genres", (f) => f.genres ?? [], (v) => (genre = v))
    );
    bar.append(count);

    section.append(text("h2", null, "The queue"));
    section.append(bar, grid);
    draw();
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
    const res = await fetch("/api/data");
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
