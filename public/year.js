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

function text(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
}

const money = (n) =>
  n >= 1e9 ? `$${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `$${Math.round(n / 1e6)}M` : `$${n.toLocaleString()}`;

function watchedRow(film) {
  const li = document.createElement("li");
  if (film.poster) {
    const img = document.createElement("img");
    img.className = "poster-sm";
    img.src = `/posters/${film.poster}`;
    img.alt = "";
    img.loading = "lazy";
    li.append(img);
  } else {
    const blank = text("div", "poster-sm is-blank");
    blank.setAttribute("aria-hidden", "true");
    li.append(blank);
  }
  const badge = text("span", "badge", film.tier);
  badge.dataset.tier = film.tier;
  badge.title = TIER_MEANING[film.tier] ?? film.tier;
  const link = text("a", "ttl", film.title);
  link.href = `/film/${film.slug}`;
  li.append(badge, link);
  if (film.director) li.append(text("span", "dir", film.director));
  return li;
}

function grossRow(film, rank) {
  const li = text("li", film.watched ? "gross is-watched" : "gross");
  li.append(text("span", "rank", `${rank}.`));
  li.append(text("span", "ttl", film.title));
  li.append(text("span", "box", money(film.box)));
  if (film.watched) {
    const seen = text("span", "seen", "watched");
    seen.title = "This one is in your list";
    li.append(seen);
  }
  return li;
}

function render(entry, data) {
  document.title = `${entry.year} — Favorites`;
  const main = el("main");
  main.replaceChildren();

  main.append(text("h1", "director-name", String(entry.year)));

  // Neighbouring years that have a page, so you can walk through them.
  const years = (data.years ?? []).map((y) => y.year).sort((a, b) => a - b);
  const i = years.indexOf(entry.year);
  const nav = text("p", "year-nav");
  if (i > 0) {
    const prev = text("a", null, `← ${years[i - 1]}`);
    prev.href = `/year/${years[i - 1]}`;
    nav.append(prev);
  }
  if (i >= 0 && i < years.length - 1) {
    const next = text("a", null, `${years[i + 1]} →`);
    next.href = `/year/${years[i + 1]}`;
    nav.append(next);
  }
  main.append(nav);

  const watched = text("section", "director-section");
  watched.append(text("h2", null, `Films you've watched from ${entry.year}`));
  if (entry.films.length) {
    const ol = document.createElement("ol");
    for (const film of entry.films) ol.append(watchedRow(film));
    watched.append(ol);
  } else {
    watched.append(text("p", "hint", `Nothing from ${entry.year} in your list yet.`));
  }
  main.append(watched);

  const top = text("section", "director-section");
  top.append(text("h2", null, `Biggest earners of ${entry.year}`));
  if (entry.top.length) {
    top.append(
      text(
        "p",
        "hint",
        `Worldwide box office, from Wikidata. ${entry.top.filter((f) => f.watched).length} of these are in your list.`
      )
    );
    const ol = document.createElement("ol");
    entry.top.forEach((film, n) => ol.append(grossRow(film, n + 1)));
    top.append(ol);
  } else {
    top.append(
      text("p", "hint", `No box-office figures recorded for ${entry.year}.`)
    );
  }
  main.append(top);
}

async function init() {
  const raw = decodeURIComponent(location.pathname.replace(/^\/year\/?/, "")).trim();
  const year = Number.parseInt(raw, 10);
  let data;
  try {
    const res = await fetch("/api/data");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }

  const entry = (data.years ?? []).find((y) => y.year === year);
  if (!entry) {
    const main = el("main");
    main.replaceChildren(
      text("p", "empty", Number.isNaN(year) ? `"${raw}" is not a year.` : `Nothing recorded for ${year}.`)
    );
    const back = text("a", "back", "← Back to all films");
    back.href = "/";
    main.append(back);
    return;
  }
  render(entry, data);
}

init();
