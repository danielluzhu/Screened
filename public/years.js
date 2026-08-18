// Every year with a film in the list, grouped by decade. The per-year pages
// already exist at /year/<year>; this is the index that was missing.
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

let DATA = null;
const state = { order: "desc", scope: "watched" };

// The best tier reached in a year, used to colour the chip. A year is more
// interesting for the one film you loved than for how many you watched.
function bestTier(entry) {
  const order = DATA.tierOrder ?? [];
  let best = null;
  let rank = order.length;
  for (const film of entry.films) {
    const i = order.indexOf(film.tier);
    if (i !== -1 && i < rank) {
      rank = i;
      best = film.tier;
    }
  }
  return best;
}

function chip(entry) {
  const link = text("a", "year-chip");
  link.href = `/year/${entry.year}`;
  if (!entry.films.length) link.classList.add("is-empty");

  const best = bestTier(entry);
  if (best) {
    const badge = text("span", "badge", best);
    badge.dataset.tier = best;
    badge.title = `Best that year — ${TIER_MEANING[best] ?? best}`;
    link.append(badge);
  }

  link.append(text("span", "year-chip-y", String(entry.year)));
  const n = entry.films.length;
  link.append(
    text(
      "span",
      "year-chip-n",
      n ? `${n} ${n === 1 ? "film" : "films"}` : `${(entry.top ?? []).length} charted`
    )
  );
  link.title = entry.films
    .slice()
    .sort((a, b) => a.title.localeCompare(b.title))
    .map((f) => f.title)
    .join(", ");
  return link;
}

function render() {
  // A year page exists for anything with box-office figures, not just years
  // you've watched from — so the index can show either set.
  const all = DATA.years ?? [];
  const years = state.scope === "all" ? all : all.filter((y) => (y.films ?? []).length);
  const host = el("years");
  host.replaceChildren();

  const films = years.reduce((n, y) => n + (y.films ?? []).length, 0);
  el("count").textContent =
    state.scope === "all"
      ? `${years.length} years, ${films} films`
      : `${years.length} of ${all.length} years, ${films} films`;

  if (!years.length) {
    host.append(text("p", "empty", "No years recorded yet."));
    return;
  }

  // Group into decades, then order the decades and the years inside them the
  // same way, so the whole page reads in one direction.
  const decades = new Map();
  for (const entry of years) {
    const decade = Math.floor(entry.year / 10) * 10;
    if (!decades.has(decade)) decades.set(decade, []);
    decades.get(decade).push(entry);
  }

  const dir = state.order === "asc" ? 1 : -1;
  const keys = [...decades.keys()].sort((a, b) => (a - b) * dir);
  for (const decade of keys) {
    const section = text("section", "decade");
    const head = text("h2", "decade-head");
    head.append(text("span", null, `${decade}s`));
    const inDecade = decades.get(decade);
    const films = inDecade.reduce((n, y) => n + y.films.length, 0);
    head.append(text("span", "tier-count", `${films} ${films === 1 ? "film" : "films"}`));
    section.append(head);

    const row = text("div", "year-chips");
    for (const entry of inDecade.slice().sort((a, b) => (a.year - b.year) * dir)) {
      row.append(chip(entry));
    }
    section.append(row);
    host.append(section);
  }
}

async function init() {
  try {
    const res = await fetch("/api/data");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }

  const main = el("main");
  main.replaceChildren();
  main.append(text("h1", "director-name", "Years"));
  main.append(
    text("p", "hint", "Every year you've watched something from. Open one for that year's films and its biggest earners.")
  );

  const controls = text("div", "controls");
  const order = document.createElement("select");
  order.id = "year-order";
  order.setAttribute("aria-label", "Order years");
  order.append(new Option("Newest first", "desc"));
  order.append(new Option("Oldest first", "asc"));
  order.addEventListener("change", (e) => {
    state.order = e.target.value;
    render();
  });

  const scope = document.createElement("select");
  scope.id = "year-scope";
  scope.setAttribute("aria-label", "Which years to show");
  scope.append(new Option("Years I've watched from", "watched"));
  scope.append(new Option("Every year with data", "all"));
  scope.addEventListener("change", (e) => {
    state.scope = e.target.value;
    render();
  });

  const count = text("span", "count");
  count.id = "count";
  controls.append(order, scope, count);
  main.append(controls);

  const host = text("div");
  host.id = "years";
  main.append(host);

  render();
}

init();
