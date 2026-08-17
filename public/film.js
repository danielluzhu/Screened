const el = (id) => document.getElementById(id);

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

let toastTimer;
function toast(message, kind = "info") {
  const node = el("toast");
  node.textContent = message;
  node.dataset.kind = kind;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), kind === "error" ? 6000 : 2200);
}

const slugify = (name) =>
  String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "film";

function text(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
}

function row(label, value) {
  if (value == null || value === "" || (Array.isArray(value) && !value.length)) return null;
  const dt = text("dt", null, label);
  const dd = text("dd", null, Array.isArray(value) ? value.join(", ") : String(value));
  return [dt, dd];
}

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  if (!res.ok || !result.ok) throw new Error(result.error || `HTTP ${res.status}`);
  return result;
}

let LOGOS = {};

function streamingRow(item) {
  const services = item.streaming ?? [];
  if (!services.length) return null;
  const box = text("section", "streaming");
  box.append(text("h2", null, "Where to watch"));
  const list = text("div", "services");
  for (const service of services) {
    const link = text("a", "service");
    link.href = service.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = `Open on ${service.name}`;
    link.dataset.service = service.name;
    const file = (LOGOS ?? {})[service.name];
    if (file) {
      const logo = document.createElement("img");
      logo.className = "service-logo";
      logo.src = `/logos/${file}`;
      logo.alt = "";
      link.append(logo, text("span", "sr-only", service.name));
    } else {
      link.append(text("span", null, service.name));
    }
    list.append(link);
  }
  box.append(list);
  box.append(
    text(
      "p",
      "hint",
      "From Wikidata — the title has a page on these services. Availability varies by country and changes often."
    )
  );
  return box;
}

// Wikipedia's account of the film and how it was received. Quoted, credited,
// and kept clear of Notes and Full analysis below, which are the sheet's own
// words — the two should never be mistaken for each other.
function summaryBox(film) {
  const entry = film.summary;
  if (!entry?.summary) return null;

  const box = text("section", "summary");
  box.append(text("h2", null, "Summary"));
  box.append(text("p", "summary-text", entry.summary));

  const credit = text("p", "summary-credit");
  credit.append(document.createTextNode("From "));
  const link = text("a", null, entry.article || "Wikipedia");
  link.href = entry.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  credit.append(link);
  credit.append(document.createTextNode(" on Wikipedia, CC BY-SA 4.0."));
  box.append(credit);
  return box;
}

function render(film, data) {
  document.title = `${film.title} — Favorites`;
  const main = el("main");
  main.replaceChildren();

  const head = text("div", "film-head");
  if (film.poster) {
    const img = document.createElement("img");
    img.className = "film-poster";
    img.src = `/posters/${film.poster}`;
    img.alt = `${film.title} poster`;
    head.append(img);
  }

  const heading = text("div", "film-heading");
  heading.append(text("h1", null, film.title));
  if (film.nativeTitle) heading.append(text("p", "native-big", film.nativeTitle));

  // Rating is editable here too, so a critique and its score stay together.
  const rating = text("div", "rating-row");
  const select = document.createElement("select");
  select.className = "badge";
  select.dataset.tier = film.tier;
  select.setAttribute("aria-label", `Rating for ${film.title}`);
  for (const t of TIERS) select.append(new Option(t, t, false, t === film.tier));
  const meaning = text("span", "rating-meaning", TIER_MEANING[film.tier] ?? "");
  select.addEventListener("change", async () => {
    const previous = film.tier;
    try {
      await post("/api/rating", { title: film.title, year: film.year, tier: select.value });
      film.tier = select.value;
      select.dataset.tier = select.value;
      meaning.textContent = TIER_MEANING[select.value] ?? "";
      toast(`${film.title} → ${select.value}`);
    } catch (err) {
      select.value = previous;
      toast(`Couldn't save rating: ${err.message}`, "error");
    }
  });
  rating.append(select, meaning);
  heading.append(rating);
  head.append(heading);
  main.append(head);

  const franchiseNames = film.franchises ?? [];
  main.append(facts(film, data));

  const overview = summaryBox(film);
  if (overview) main.append(overview);

  const watch = streamingRow(film);
  if (watch) main.append(watch);

  // Other films in the same franchise, as context for the critique.
  const related = (data.franchises ?? []).filter((f) => franchiseNames.includes(f.name));
  if (related.length) {
    const box = text("section", "related");
    box.append(text("h2", null, "In the same franchise"));
    const list = document.createElement("ul");
    for (const series of related) {
      for (const other of series.films) {
        if (other.slug === film.slug) continue;
        const li = document.createElement("li");
        const link = text("a", null, `${other.title}${other.year ? ` (${other.year})` : ""}`);
        link.href = `/film/${other.slug}`;
        const badge = text("span", "badge", other.tier);
        badge.dataset.tier = other.tier;
        badge.title = TIER_MEANING[other.tier] ?? other.tier;
        li.append(badge, link);
        list.append(li);
      }
    }
    if (list.childElementCount) {
      box.append(list);
      main.append(box);
    }
  }

  // Notes: short and open. Analysis: long, spoilers, folded away.
  const notesBox = editor({
    cls: "critique",
    heading: "Notes",
    rows: 5,
    value: film.critique,
    placeholder: `A line or two on ${film.title} — no spoilers.`,
    field: "critique",
    film,
  });
  main.append(notesBox);

  const details = document.createElement("details");
  details.className = "spoilers";
  const summary = document.createElement("summary");
  summary.append(text("span", "spoiler-label", "Full analysis"));
  summary.append(text("span", "spoiler-warn", "spoilers"));
  if (film.analysis) summary.append(text("span", "spoiler-has", "written"));
  details.append(summary);
  details.append(
    editor({
      cls: "critique inner",
      heading: null,
      rows: 14,
      value: film.analysis,
      placeholder: `The whole argument about ${film.title} — assume the reader has seen it.`,
      field: "analysis",
      film,
    })
  );
  main.append(details);
}

// --- facts, and the form that edits them ---------------------------------
// Year, director, country and genre come from Wikidata via scripts/autofill.py,
// which leaves anything ambiguous blank — so they need to be fixable by hand.

function factsList(film) {
  const dl = text("dl", "film-facts");

  // Year links to that year's page.
  if (film.year) {
    dl.append(text("dt", null, "Year"));
    const dd = document.createElement("dd");
    const link = text("a", "year-link", String(film.year));
    link.href = `/year/${film.year}`;
    dd.append(link);
    dl.append(dd);
  }

  // Directors link to their own pages, so they need real anchors.
  if ((film.directors ?? []).length) {
    dl.append(text("dt", null, film.directors.length > 1 ? "Directors" : "Director"));
    const dd = document.createElement("dd");
    film.directors.forEach((name, i) => {
      if (i) dd.append(text("span", null, ", "));
      const link = text("a", "director-link", name);
      link.href = `/director/${slugify(name)}`;
      dd.append(link);
    });
    dl.append(dd);
  }

  for (const pair of [
    row("Country", film.country),
    row("Genres", film.genres),
    row("Franchise", film.franchises ?? []),
    row("Note", film.note),
  ]) {
    if (pair) dl.append(...pair);
  }
  return dl;
}

function field(label, value, hint, cls = "") {
  const wrap = text("label", `detail-field ${cls}`.trim());
  wrap.append(text("span", "detail-label", label));
  const input = document.createElement("input");
  input.type = "text";
  input.value = value ?? "";
  wrap.append(input);
  if (hint) wrap.append(text("span", "hint", hint));
  return { wrap, input };
}

function detailsForm(film, data, done) {
  const form = document.createElement("form");
  form.className = "details-form";

  const year = field("Year", film.year ?? "", "Blank if unknown", "narrow");
  year.input.type = "number";
  year.input.min = 1880;
  year.input.max = 2100;
  year.input.placeholder = "e.g. 2019";

  const director = field("Director", film.director ?? "", "Comma-separated for co-directors");
  const country = field("Country of origin", film.country ?? "");
  const genre = field("Genre", (film.genres ?? []).join(", "), "Comma-separated");

  // Countries are typed by hand across the sheet, so offer what's already used.
  const list = document.createElement("datalist");
  list.id = "country-options";
  for (const name of [...new Set((data.films ?? []).map((f) => f.country).filter(Boolean))].sort()) {
    list.append(new Option(name, name));
  }
  country.input.setAttribute("list", list.id);
  form.append(list);

  form.append(year.wrap, director.wrap, country.wrap, genre.wrap);

  // Genres drive the filter on the front page, so keep the vocabulary tight by
  // offering the ones already in use; clicking adds or removes one.
  const chips = text("div", "genre-chips");
  const current = () => genre.input.value.split(",").map((g) => g.trim()).filter(Boolean);
  for (const name of (data.genres ?? []).slice(0, 14)) {
    const chip = text("button", "chip", name);
    chip.type = "button";
    const sync = () => chip.classList.toggle("is-on", current().some((g) => g.toLowerCase() === name.toLowerCase()));
    chip.addEventListener("click", () => {
      const kept = current().filter((g) => g.toLowerCase() !== name.toLowerCase());
      genre.input.value = (kept.length === current().length ? [...kept, name] : kept).join(", ");
      genre.input.dispatchEvent(new Event("input"));
    });
    genre.input.addEventListener("input", sync);
    sync();
    chips.append(chip);
  }
  if (chips.childElementCount) genre.wrap.append(chips);

  const actions = text("div", "detail-actions");
  const save = text("button", "primary", "Save");
  save.type = "submit";
  const cancel = text("button", "ghost", "Cancel");
  cancel.type = "button";
  const status = text("span", "hint", "");
  actions.append(save, cancel, status);
  form.append(actions);

  cancel.addEventListener("click", () => done(null));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    // Send only what actually changed, so an untouched field is never rewritten.
    const payload = { title: film.title, year: film.year };
    const nextYear = year.input.value.trim();
    if (nextYear !== String(film.year ?? "")) payload.newYear = nextYear === "" ? null : Number(nextYear);
    if (director.input.value.trim() !== (film.director ?? "")) payload.director = director.input.value.trim();
    if (country.input.value.trim() !== (film.country ?? "")) payload.country = country.input.value.trim();
    if (genre.input.value.trim() !== (film.genres ?? []).join(", ")) payload.genre = genre.input.value.trim();

    if (Object.keys(payload).length === 2) {
      done(null);
      return;
    }

    save.disabled = true;
    cancel.disabled = true;
    status.textContent = "Saving…";
    try {
      const result = await post("/api/film/details", payload);
      toast("Details saved");
      done(result);
    } catch (err) {
      status.textContent = "";
      save.disabled = false;
      cancel.disabled = false;
      toast(`Couldn't save: ${err.message}`, "error");
    }
  });

  return form;
}

function facts(film, data) {
  const section = text("section", "facts");

  const read = () => {
    const dl = factsList(film);
    const edit = text("button", "edit-details", "✎ Edit details");
    edit.type = "button";
    edit.addEventListener("click", () => {
      section.replaceChildren(detailsForm(film, data, finish));
      section.querySelector("input")?.focus();
    });
    section.replaceChildren(
      dl.childElementCount ? dl : text("p", "hint", "Nothing recorded yet."),
      edit
    );
  };

  // A year change moves the film's page, so re-read everything and follow it.
  const finish = async (result) => {
    if (!result) return read();
    try {
      const res = await fetch("/api/data");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const fresh = await res.json();
      LOGOS = fresh.serviceLogos ?? {};
      const updated =
        fresh.films.find((f) => f.title === film.title && f.year === result.year) ??
        fresh.films.find((f) => f.slug === film.slug);
      if (!updated) return read();
      if (updated.slug !== film.slug) history.replaceState({}, "", `/film/${updated.slug}`);
      render(updated, fresh);
    } catch (err) {
      toast(`Saved, but couldn't refresh the page: ${err.message}`, "error");
      read();
    }
  };

  read();
  return section;
}

// One editor, used for both the open notes and the hidden analysis.
function editor({ cls, heading, rows, value, placeholder, field, film }) {
  const section = text("section", cls);
  if (heading) section.append(text("h2", null, heading));

  const area = document.createElement("textarea");
  area.id = `${field}-text`;
  area.rows = rows;
  area.placeholder = placeholder;
  area.value = value ?? "";
  section.append(area);

  const actions = text("div", "critique-actions");
  const save = text("button", "primary", "Save");
  save.type = "button";
  const status = text("span", "hint", value ? "Saved" : "Not written yet");
  actions.append(save, status);
  section.append(actions);

  let saved = area.value;
  const commit = async () => {
    const next = area.value.trim();
    if (next === saved.trim()) return;
    save.disabled = true;
    status.textContent = "Saving…";
    try {
      await post("/api/film/critique", { title: film.title, year: film.year, [field]: next });
      saved = next;
      film[field] = next;
      status.textContent = "Saved";
      toast(field === "analysis" ? "Analysis saved" : "Notes saved");
    } catch (err) {
      status.textContent = "Not saved";
      toast(`Couldn't save: ${err.message}`, "error");
    } finally {
      save.disabled = false;
    }
  };
  save.addEventListener("click", commit);
  // Blur-save so a half-written thought isn't lost on navigation.
  area.addEventListener("blur", commit);
  area.addEventListener("input", () => {
    status.textContent = area.value.trim() === saved.trim() ? "Saved" : "Unsaved changes";
  });
  window.addEventListener("beforeunload", (e) => {
    // The page re-renders after a details edit; ignore the detached editors.
    if (area.isConnected && area.value.trim() !== saved.trim()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  return section;
}

async function init() {
  const slug = decodeURIComponent(location.pathname.replace(/^\/film\/?/, "")).trim();
  let data;
  try {
    const res = await fetch("/api/data");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
    LOGOS = data.serviceLogos ?? {};
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }

  const film = data.films.find((f) => f.slug === slug);
  if (!film) {
    const main = el("main");
    main.replaceChildren(text("p", "empty", `No film found for "${slug}".`));
    const back = text("a", "back", "← Back to all films");
    back.href = "/";
    main.append(back);
    return;
  }
  render(film, data);
}

init();
