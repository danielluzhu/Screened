const el = (id) => document.getElementById(id);

let toastTimer;
function toast(message, kind = "info") {
  const node = el("toast");
  node.textContent = message;
  node.dataset.kind = kind;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), kind === "error" ? 6000 : 2200);
}

function text(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = value;
  return node;
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

function render(character, data) {
  document.title = `${character.name} — Screened`;
  const main = el("main");
  main.replaceChildren();

  const head = text("div", "film-head");
  if (character.photo) {
    const img = document.createElement("img");
    img.className = "film-poster";
    img.src = `/Screened/characters/${character.photo}`;
    img.alt = character.name;
    head.append(img);
  }

  const heading = text("div", "film-heading");
  heading.append(text("h1", null, character.name));
  if (character.show) heading.append(text("p", "native-big", character.show));
  head.append(heading);
  main.append(head);

  // If the show is in the Shows list, say so — it ties the two tabs together.
  const shows = (data.shows ?? []).map((s) => s.name);
  if (character.show && shows.includes(character.show)) {
    main.append(text("p", "hint", `${character.show} is on your shows list.`));
  }

  // Other characters from the same show.
  const siblings = (data.characters ?? []).filter(
    (c) => c.show && c.show === character.show && c.slug !== character.slug
  );
  if (siblings.length) {
    const box = text("section", "related");
    box.append(text("h2", null, `Others from ${character.show}`));
    const list = document.createElement("ul");
    for (const other of siblings) {
      const li = document.createElement("li");
      const link = text("a", null, other.name);
      link.href = `/Screened/character/${other.slug}`;
      li.append(link);
      list.append(li);
    }
    box.append(list);
    main.append(box);
  }

  // Why they matter — saved into the sheet's own "Why" column.
  const section = text("section", "critique");
  section.append(text("h2", null, "Why they're a favourite"));
  const area = document.createElement("textarea");
  area.id = "why-text";
  area.rows = 10;
  area.placeholder = `What makes ${character.name} stand out? It saves into Favorites.numbers.`;
  area.value = character.why ?? "";
  section.append(area);

  const actions = text("div", "critique-actions");
  const save = text("button", "primary", "Save");
  save.type = "button";
  const status = text("span", "hint", character.why ? "Saved" : "Not written yet");
  actions.append(save, status);
  section.append(actions);
  main.append(section);

  let saved = area.value;
  const commit = async () => {
    const value = area.value.trim();
    if (value === saved.trim()) return;
    save.disabled = true;
    status.textContent = "Saving…";
    try {
      await post("/Screened/api/character/why", { name: character.name, why: value });
      saved = value;
      character.why = value;
      status.textContent = "Saved";
      toast("Saved");
    } catch (err) {
      status.textContent = "Not saved";
      toast(`Couldn't save: ${err.message}`, "error");
    } finally {
      save.disabled = false;
    }
  };
  save.addEventListener("click", commit);
  area.addEventListener("blur", commit);
  area.addEventListener("input", () => {
    status.textContent = area.value.trim() === saved.trim() ? "Saved" : "Unsaved changes";
  });
  window.addEventListener("beforeunload", (e) => {
    if (area.value.trim() !== saved.trim()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

async function init() {
  const slug = decodeURIComponent(location.pathname.replace(/^\/Screened\/character\/?/, "").replace(/\/$/, "")).trim();
  let data;
  try {
    const res = await fetch("/Screened/api/data.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    el("main").replaceChildren(text("p", "empty", `Couldn't load the data (${err.message}).`));
    return;
  }

  const character = (data.characters ?? []).find((c) => c.slug === slug);
  if (!character) {
    const main = el("main");
    main.replaceChildren(text("p", "empty", `No character found for "${slug}".`));
    const back = text("a", "back", "← Back");
    back.href = "/#characters";
    main.append(back);
    return;
  }
  render(character, data);
}

init();
