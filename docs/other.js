// A film credited to one of your directors that isn't in your list. It has a
// page so the filmography is browsable, but it is not part of the list and
// carries no tier — the Add button is the only thing that moves it in.
const el = (id) => document.getElementById(id);

function text(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
}

function toast(message, kind) {
  const box = el("toast");
  if (!box) return;
  box.textContent = message;
  box.className = kind === "error" ? "toast is-error" : "toast";
  box.hidden = false;
  setTimeout(() => {
    box.hidden = true;
  }, 2600);
}

const TIERS = ["S", "A", "B", "C", "D", "E", "F", "?"];

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

// Same write the director page uses, and the same choice of tier: nothing is
// added until one is picked.
async function addFilm(film, tier, control) {
  control.disabled = true;
  try {
    const res = await fetch("/Screened/api/film", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title: film.title,
        year: film.year,
        director: (film.directors ?? []).map((d) => d.name).join(", "),
        tier,
      }),
    });
    const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
    if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
    const badge = text("span", "badge", tier);
    badge.dataset.tier = tier;
    badge.title = tier === "?" ? "Unrated" : TIER_MEANING[tier] ?? tier;
    control.replaceWith(badge);
    toast(
      tier === "?" ? `${film.title} added, unrated` : `${film.title} added at ${tier}`
    );
  } catch (err) {
    control.disabled = false;
    control.value = "";
    toast(`Couldn't add ${film.title}: ${err.message}`, "error");
  }
}

// Not in the list, so this picks the tier to add it at. Unrated first: it is the
// usual answer, and it is the watch-next queue.
function addControl(film) {
  const select = document.createElement("select");
  select.className = "badge is-add";
  select.title = `Add ${film.title} to your list`;
  select.setAttribute("aria-label", `Add ${film.title} to your list`);
  // Single characters, with the meaning on each option's tooltip. A <select>
  // takes the width of its widest option, and a row of "C — Something missing
  // that does not let me enjoy" stretched the control across the page.
  select.append(new Option("+", "", true, true));
  const unrated = new Option("?", "?");
  unrated.title = "Add unrated — the watch-next queue";
  select.append(unrated);
  for (const tier of TIERS) {
    if (tier === "?") continue;
    const option = new Option(tier, tier);
    option.title = `Add at ${tier} — ${TIER_MEANING[tier] ?? tier}`;
    select.append(option);
  }
  select.addEventListener("change", () => {
    if (select.value) addFilm(film, select.value, select);
  });
  return select;
}

function render(film, data) {
  document.title = `${film.title} — Screened`;
  const main = el("main");
  main.replaceChildren();

  const head = text("div", "film-head");
  const body = text("div", "film-body");

  const heading = text("div", "film-heading");
  heading.append(text("h1", "title-text", film.title));
  body.append(heading);

  const facts = text("dl", "film-facts");
  const fact = (label, value) => {
    if (!value) return;
    facts.append(text("dt", null, label));
    const dd = document.createElement("dd");
    if (value instanceof Node) dd.append(value);
    else dd.textContent = value;
    facts.append(dd);
  };

  fact("Year", film.year ? String(film.year) : null);

  if ((film.directors ?? []).length) {
    const wrap = document.createElement("span");
    film.directors.forEach((d, i) => {
      if (i) wrap.append(document.createTextNode(", "));
      const link = text("a", "director-link", d.name);
      link.href = `/Screened/director/${d.slug}`;
      wrap.append(link);
    });
    fact(film.directors.length > 1 ? "Directors" : "Director", wrap);
  }

  if (film.qid) {
    const link = text("a", "sug-link", `${film.qid} ↗`);
    link.href = `https://www.wikidata.org/wiki/${film.qid}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    fact("Wikidata", link);
  }

  body.append(facts);
  head.append(body);
  main.append(head);

  const note = text("section", "summary");
  note.append(text("h2", null, "Not in your list"));
  note.append(
    text(
      "p",
      "summary-text",
      "This one came from the director's filmography on Wikidata, not from " +
        "Favorites.numbers. It has no rating because it isn't in the list — adding " +
        "it puts it there as unrated."
    )
  );
  // Sits with the explanation, since picking a tier is what puts it in the list.
  const row = text("div", "rating-row");
  row.append(addControl(film));
  row.append(text("span", "rating-meaning", "Pick a tier to add it — or ? for unrated"));
  note.append(row);
  main.append(note);

  // The rest of that director's work, so a filmography can be walked through.
  for (const who of film.directors ?? []) {
    const director = (data.directors ?? []).find((d) => d.slug === who.slug);
    if (!director) continue;
    const box = text("section", "related");
    box.append(text("h2", null, `More from ${director.name}`));

    const seen = director.films.slice(0, 8);
    if (seen.length) {
      box.append(text("p", "hint", "In your list:"));
      const ul = document.createElement("ul");
      for (const f of seen) {
        const li = document.createElement("li");
        const badge = text("span", "badge", f.tier);
        badge.dataset.tier = f.tier;
        const link = text("a", "ttl", f.title);
        link.href = `/Screened/film/${f.slug}`;
        li.append(badge, text("span", "yr", f.year ?? "—"), link);
        ul.append(li);
      }
      box.append(ul);
    }

    const rest = (director.others ?? []).filter((o) => o.slug !== film.slug).slice(0, 12);
    if (rest.length) {
      box.append(text("p", "hint", "Not in your list:"));
      const ul = document.createElement("ul");
      for (const o of rest) {
        const li = document.createElement("li");
        const link = text("a", "ttl", o.title);
        link.href = `/Screened/other/${o.slug}`;
        li.append(text("span", "yr", o.year ?? "—"), link);
        ul.append(li);
      }
      box.append(ul);
    }

    const back = text("a", "back", `← ${director.name}'s full filmography`);
    back.href = `/Screened/director/${director.slug}`;
    box.append(back);
    main.append(box);
  }
}

async function init() {
  // build_static.py rewrites this for the published copy, base path and all.
  const slug = decodeURIComponent(location.pathname.replace(/^\/Screened\/other\/?/, "").replace(/\/$/, "")).trim();
  // Two fetches: the list itself, and the filmography entries that aren't in
  // it. They're separate files so every other page skips the second.
  let data, otherFilms;
  try {
    const [a, b] = await Promise.all([fetch("/Screened/api/data.json"), fetch("/Screened/api/other-films.json")]);
    if (!a.ok) throw new Error(`HTTP ${a.status}`);
    if (!b.ok) throw new Error(`HTTP ${b.status}`);
    [data, otherFilms] = await Promise.all([a.json(), b.json()]);
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }

  const film = otherFilms.find((f) => f.slug === slug);
  if (!film) {
    const main = el("main");
    main.replaceChildren(text("p", "empty", `No film found for "${slug}".`));
    const back = text("a", "back", "← Back to all films");
    back.href = "/Screened/";
    main.append(back);
    return;
  }
  render(film, data);
}

init();
