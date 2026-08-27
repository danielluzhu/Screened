const el = (id) => document.getElementById(id);

function text(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
}

function row(label, value) {
  if (value == null || value === "") return null;
  return [text("dt", null, label), text("dd", null, String(value))];
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

function render(show, data) {
  document.title = `${show.name} — Screened`;
  const main = el("main");
  main.replaceChildren();

  const head = text("div", "film-head");
  if (show.photo) {
    const img = document.createElement("img");
    img.className = "film-poster";
    img.src = `/shows/${show.photo}`;
    img.alt = show.name;
    head.append(img);
  }

  const heading = text("div", "film-heading");
  heading.append(text("h1", null, show.name));
  if (show.nativeTitle) heading.append(text("p", "native-big", show.nativeTitle));
  head.append(heading);
  main.append(head);

  const dl = text("dl", "film-facts");
  const seasons = show.seasons
    ? `${show.seasons} season${show.seasons === "1" ? "" : "s"}`
    : null;
  const episodes = show.episodes
    ? `${show.episodes} episode${show.episodes === "1" ? "" : "s"}`
    : null;
  for (const pair of [
    row("Years", show.years),
    row("Seasons", seasons),
    row("Episodes", episodes),
    row("Format", show.format),
    row("Author", show.author),
    row("Country", show.country),
    row("Genres", (show.genres ?? []).join(", ")),
  ]) {
    if (pair) dl.append(...pair);
  }
  if (dl.childElementCount) main.append(dl);

  const watch = streamingRow(show);
  if (watch) main.append(watch);

  // Characters you've logged from this show, linking to their pages.
  const cast = (data.characters ?? []).filter((c) => c.show === show.name);
  if (cast.length) {
    const box = text("section", "related");
    box.append(text("h2", null, `Your favourite characters from ${show.name}`));
    const list = document.createElement("ul");
    for (const character of cast) {
      const li = document.createElement("li");
      if (character.photo) {
        const img = document.createElement("img");
        img.className = "poster-sm";
        img.src = `/characters/${character.photo}`;
        img.alt = "";
        img.loading = "lazy";
        li.append(artLink(img, `/character/${character.slug}`));
      }
      const link = text("a", null, character.name);
      link.href = `/character/${character.slug}`;
      li.append(link);
      list.append(li);
    }
    box.append(list);
    main.append(box);
  } else {
    main.append(
      text("p", "hint", `No characters from ${show.name} on your characters list yet.`)
    );
  }
}

async function init() {
  const slug = decodeURIComponent(location.pathname.replace(/^\/show\/?/, "")).trim();
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

  const show = (data.shows ?? []).find((s) => s.slug === slug);
  if (!show) {
    const main = el("main");
    main.replaceChildren(text("p", "empty", `No show found for "${slug}".`));
    const back = text("a", "back", "← Back");
    back.href = "/#shows";
    main.append(back);
    return;
  }
  render(show, data);
}

init();
