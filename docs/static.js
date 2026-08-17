// The published site is a read-only mirror. There is no Bun server and no
// Favorites.numbers behind it, so the editing UI is stripped out rather than
// left in place to fail on click.
(() => {
  const GONE = ".add-toggle,.add-form,.edit-title,.edit-details,.add-suggestion,.add-other";

  function neuter() {
    document.querySelectorAll(GONE).forEach((n) => n.remove());
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

  // Content renders after fetch, and re-renders on filter changes.
  new MutationObserver(neuter).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  document.addEventListener("DOMContentLoaded", neuter);
  neuter();

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
