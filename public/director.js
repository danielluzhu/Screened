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


// Artwork that links to the item's own page. The title beside it already links
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

function watchedRow(film) {
  const li = document.createElement("li");

  if (film.poster) {
    const img = document.createElement("img");
    img.className = "poster-sm";
    img.src = `/posters/${film.poster}`;
    img.alt = "";
    img.loading = "lazy";
    li.append(artLink(img, `/film/${film.slug}`));
  } else {
    const blank = text("div", "poster-sm is-blank");
    blank.setAttribute("aria-hidden", "true");
    li.append(artLink(blank, `/film/${film.slug}`));
  }

  const badge = text("span", "badge", film.tier);
  badge.dataset.tier = film.tier;
  badge.title = TIER_MEANING[film.tier] ?? film.tier;

  const link = text("a", "ttl", film.title);
  link.href = `/film/${film.slug}`;

  li.append(badge, text("span", "yr", film.year ?? "—"), link);
  return li;
}

let toastTimer;
function toast(message, kind = "info") {
  const node = el("toast");
  node.textContent = message;
  node.dataset.kind = kind;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), kind === "error" ? 6000 : 2600);
}

// Their other films are the obvious thing to want on your list, so each one
// can be added from here. It lands unrated, with this director filled in.
async function addFilm(film, director, button) {
  button.disabled = true;
  button.textContent = "Adding…";
  try {
    const res = await fetch("/api/film", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ title: film.title, year: film.year ?? null, director, tier: "?" }),
    });
    const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
    button.textContent = "✓ Added";
    button.classList.add("is-added");
    toast(`Added ${film.title} — looking for a poster…`);
  } catch (err) {
    button.disabled = false;
    button.textContent = "+ Add";
    toast(`Couldn't add ${film.title}: ${err.message}`, "error");
  }
}

function otherRow(film, director) {
  const li = text("li", "other");
  const add = text("button", "add-other", "+ Add");
  add.type = "button";
  add.title = `Add ${film.title} to your list, unrated`;
  add.setAttribute("aria-label", `Add ${film.title} to your list`);
  add.addEventListener("click", () => addFilm(film, director, add));
  li.append(text("span", "yr", film.year ?? "—"), text("span", "ttl", film.title), add);
  return li;
}

function render(director) {
  document.title = `${director.name} — Favorites`;
  const main = el("main");
  main.replaceChildren();

  main.append(text("h1", "director-name", director.name));

  const seen = director.films.length;
  const rated = director.films.filter((f) => f.tier && f.tier !== "?").length;
  main.append(
    text(
      "p",
      "lede",
      `${seen} ${seen === 1 ? "film" : "films"} in your list` +
        (rated < seen ? ` (${rated} rated)` : "") +
        (director.others.length ? ` · ${director.others.length} more they directed` : "")
    )
  );

  const watched = text("section", "director-section");
  watched.append(text("h2", null, "Films you've watched"));
  const list = document.createElement("ol");
  for (const film of director.films) list.append(watchedRow(film));
  watched.append(list);
  main.append(watched);

  if (director.others.length) {
    const rest = text("section", "director-section");
    rest.append(text("h2", null, "Their other films"));
    rest.append(
      text(
        "p",
        "hint",
        "From Wikidata — everything else credited to them, newest last. Add moves one " +
          "into your list as unrated."
      )
    );
    const ol = document.createElement("ol");
    for (const film of director.others) ol.append(otherRow(film, director.name));
    rest.append(ol);
    main.append(rest);
  } else {
    main.append(
      text(
        "p",
        "hint",
        "No other films found for them yet — run scripts/directors.py to pull their filmography."
      )
    );
  }
}

async function init() {
  const slug = decodeURIComponent(location.pathname.replace(/^\/director\/?/, "")).trim();
  let data;
  try {
    const res = await fetch("/api/data");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }

  const director = (data.directors ?? []).find((d) => d.slug === slug);
  if (!director) {
    const main = el("main");
    main.replaceChildren(text("p", "empty", `No director found for "${slug}".`));
    const back = text("a", "back", "← Back to all films");
    back.href = "/";
    main.append(back);
    return;
  }
  render(director);
}

init();
