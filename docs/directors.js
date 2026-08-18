// Every director in the list, as a way in to their own page. The per-director
// pages already exist at /director/<slug>; this is the index that was missing.
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
const state = { query: "", sort: "count" };

// A director's best tier decides where they sort when counts tie — two films
// each says less than what those films were.
function bestRank(director) {
  const order = DATA.tierOrder ?? [];
  let best = order.length;
  for (const film of director.films) {
    const i = order.indexOf(film.tier);
    if (i !== -1 && i < best) best = i;
  }
  return best;
}

function visible() {
  const q = state.query.trim().toLowerCase();
  const list = (DATA.directors ?? []).filter((d) => {
    if (!q) return true;
    return (
      d.name.toLowerCase().includes(q) ||
      d.films.some((f) => f.title.toLowerCase().includes(q))
    );
  });

  if (state.sort === "name") {
    list.sort((a, b) => a.name.localeCompare(b.name));
  } else {
    list.sort(
      (a, b) =>
        b.films.length - a.films.length ||
        bestRank(a) - bestRank(b) ||
        a.name.localeCompare(b.name)
    );
  }
  return list;
}

function card(director) {
  const li = text("li", "dir-card");

  const link = text("a", "dir-name", director.name);
  link.href = `/Screened/director/${director.slug}`;
  li.append(link);

  // One badge per tier they land in, with how many films sit there.
  const counts = new Map();
  for (const film of director.films) {
    counts.set(film.tier, (counts.get(film.tier) ?? 0) + 1);
  }
  const tiers = text("div", "dir-tiers");
  for (const tier of DATA.tierOrder ?? []) {
    const n = counts.get(tier);
    if (!n) continue;
    const badge = text("span", "badge", tier);
    badge.dataset.tier = tier;
    badge.title = `${n} ${n === 1 ? "film" : "films"} — ${TIER_MEANING[tier] ?? tier}`;
    const pair = text("span", "dir-tier");
    pair.append(badge);
    if (n > 1) pair.append(text("span", "dir-tier-n", `×${n}`));
    tiers.append(pair);
  }
  li.append(tiers);

  const titles = director.films
    .slice()
    .sort((a, b) => (a.year ?? 0) - (b.year ?? 0))
    .map((f) => f.title)
    .join(", ");
  li.append(text("p", "dir-films", titles));

  const meta = text("p", "dir-meta");
  const n = director.films.length;
  meta.append(text("span", null, `${n} watched`));
  // What they've made that isn't in the list yet — the reason to open the page.
  if (director.others?.length) {
    meta.append(text("span", "dir-more", `${director.others.length} more to see`));
  }
  li.append(meta);
  return li;
}

function render() {
  const list = visible();
  const total = (DATA.directors ?? []).length;
  el("count").textContent =
    list.length === total ? `${total} directors` : `${list.length} of ${total} directors`;

  const host = el("directors");
  host.replaceChildren();
  if (!list.length) {
    host.append(text("p", "empty", "No director matches that."));
    return;
  }
  const ul = text("ul", "dir-grid");
  for (const director of list) ul.append(card(director));
  host.append(ul);
}

async function init() {
  try {
    const res = await fetch("/Screened/api/data.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }

  const main = el("main");
  main.replaceChildren();
  main.append(text("h1", "director-name", "Directors"));
  main.append(
    text("p", "hint", "Everyone behind a film in the list. Open one for their full filmography.")
  );

  const controls = text("div", "controls");
  const search = document.createElement("input");
  search.id = "dir-search";
  search.type = "search";
  search.placeholder = "Search directors or titles…";
  search.autocomplete = "off";
  search.setAttribute("aria-label", "Search directors");
  search.addEventListener("input", (e) => {
    state.query = e.target.value;
    render();
  });

  const sort = document.createElement("select");
  sort.id = "dir-sort";
  sort.setAttribute("aria-label", "Sort directors");
  sort.append(new Option("Sort: most watched", "count"));
  sort.append(new Option("Sort: A–Z", "name"));
  sort.addEventListener("change", (e) => {
    state.sort = e.target.value;
    render();
  });

  const count = text("span", "count");
  count.id = "count";
  controls.append(search, sort, count);
  main.append(controls);

  const host = text("div");
  host.id = "directors";
  main.append(host);

  render();
}

init();
