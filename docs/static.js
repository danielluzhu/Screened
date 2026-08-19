// The published site is a read-only mirror. There is no Bun server and no
// Favorites.numbers behind it, so the editing UI is taken out of reach rather
// than left in place to fail on click.
(() => {
  // Hidden, not removed. app.js finishes wiring these up after its data fetch
  // resolves — which is after this script runs — and setUpAddForm() throws on a
  // missing node, killing init() before it ever renders the film list.
  const style = document.createElement("style");
  style.textContent =
    ".add-toggle,.add-form,.edit-title,.edit-details,.add-suggestion,.add-other" +
    "{display:none!important}";
  (document.head ?? document.documentElement).append(style);

  function neuter() {
    // Ratings render as <select>; swap each for the badge it already looks like.
    document.querySelectorAll("select.badge").forEach((sel) => {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.dataset.tier = sel.value;
      badge.textContent = sel.value;
      if (sel.title) badge.title = sel.title;
      sel.replaceWith(badge);
    });
  }

  // Say where the missing controls went, once, on any page that had some. The
  // pages re-render after their fetch, so this is idempotent and re-applied.
  const HID = ".add-toggle,.add-form,.add-suggestion,.add-other,.edit-title,.edit-details";
  function note() {
    if (document.getElementById("static-note")) return;
    if (!document.querySelector(HID)) return;
    const host = document.getElementById("main");
    if (!host) return;
    const line = document.createElement("p");
    line.id = "static-note";
    line.className = "hint static-note";
    line.textContent =
      "Read-only copy — adding a film and changing a rating happen on the local site, " +
      "which writes them back into the spreadsheet.";
    host.prepend(line);
  }

  const apply = () => {
    neuter();
    note();
  };

  // Content renders after fetch, and re-renders on filter changes.
  new MutationObserver(apply).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  document.addEventListener("DOMContentLoaded", apply);
  apply();

  // Nothing should be able to POST to an endpoint that isn't there.
  const inner = window.fetch;
  window.fetch = (input, init) => {
    const method = String(
      init?.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      return Promise.resolve(
        new Response(
          JSON.stringify({ ok: false, error: "This is a read-only copy of the site." }),
          { status: 405, headers: { "content-type": "application/json" } }
        )
      );
    }
    return inner(input, init);
  };
})();
