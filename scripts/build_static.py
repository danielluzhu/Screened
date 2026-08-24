#!/usr/bin/env python3
"""Build a static, read-only copy of the site into dist/ for GitHub Pages.

The Bun server does three things Pages cannot: it serves data.json at
/api/data, it hands the same HTML shell to every /film/<slug> style URL, and
it shells out to the Python writers to edit Favorites.numbers. Only the first
two can be reproduced statically:

  * /api/data becomes a plain dist/api/data.json file,
  * every slug that exists in data.json gets a real directory with an
    index.html, so Pages answers 200 instead of 404 and no redirect tricks are
    needed,
  * the write endpoints have nowhere to go, so static.js strips the editing
    UI and blocks non-GET fetches.

Pages serves the site from /<repo>/ rather than /, so every absolute path in
the HTML and JS is rewritten to sit under that base.

Output goes to docs/, which is one of the two roots Pages can publish from
directly, so a push to main is the whole deploy.

    python3 scripts/build_static.py [base-path]     # default /Screened
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
OUT = ROOT / "docs"

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BASE_PATH", "/Screened")).rstrip("/")

# Client-resolved routes: the server hands each one a shell and the page reads
# the slug back out of location.pathname.
ROUTES = ("film", "show", "character", "director", "year", "other")
# Directories under public/ that the pages link to with absolute paths.
ASSETS = ("posters", "logos", "characters", "shows", "portraits")
# Pages that are not per-item routes but still need their own directory, as
# (url segment, source file in public/, title). The three views share the front
# page's markup — app.js picks which one to show from the path.
STANDALONE = (
    ("suggestions", "suggestions.html", "What to watch next — Screened"),
    ("directors", "directors.html", "Directors — Screened"),
    ("years", "years.html", "Years — Screened"),
    ("shortlist", "index.html", "Short list — Screened"),
    ("franchises", "index.html", "Franchises — Screened"),
    ("characters", "index.html", "Characters — Screened"),
    ("shows", "index.html", "Shows — Screened"),
)


def rewrite_js(src: str) -> str:
    # The one read endpoint becomes a file. Do this before the general pass so
    # the extensionless /api/data never reaches it.
    src = src.replace('"/api/data"', f'"{BASE}/api/data.json"')

    # Absolute references — "/posters/x.jpg", `/film/${slug}`, "/api/rating".
    names = "|".join(ROUTES + ASSETS + ("api",))
    src = re.sub(
        rf"""(["'`])/({names})(?=[/"'`])""",
        lambda m: f"{m.group(1)}{BASE}/{m.group(2)}",
        src,
    )

    # Slugs are read back off the URL, so the base has to come off first. Pages
    # serves these as directories, hence the trailing slash strip.
    #
    # The base is escaped for a regex literal rather than assumed to start with
    # a slash: at base "/" it is the empty string, and prefixing a backslash to
    # nothing produced /^\\/film/, which matches a literal backslash and left
    # every detail page unable to find its own slug.
    escaped_base = BASE.replace("/", "\\/")
    src = re.sub(
        r'location\.pathname\.replace\(/\^\\/(' + "|".join(ROUTES) + r')\\/\?/, ""\)',
        lambda m: (
            f'location.pathname.replace(/^{escaped_base}\\/{m.group(1)}\\/?/, "")'
            '.replace(/\\/$/, "")'
        ),
        src,
    )

    # Bare "back to the index" links.
    src = re.sub(r'(\.href\s*=\s*)"/"', rf'\1"{BASE}/"', src)
    return src


def rewrite_html(src: str, title: str | None = None) -> str:
    src = re.sub(r'(\b(?:href|src)=")/', rf"\1{BASE}/", src)
    if title:
        src = re.sub(r"<title>.*?</title>", f"<title>{esc(title)}</title>", src, count=1, flags=re.S)
    return src.replace("</body>", f'  <script src="{BASE}/static.js"></script>\n  </body>')


def esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(PUBLIC, OUT)

    # Rewrite everything copied out of public/ in place.
    for path in OUT.rglob("*"):
        if path.suffix == ".js":
            path.write_text(rewrite_js(path.read_text()))
        elif path.suffix == ".html":
            path.write_text(rewrite_html(path.read_text()))

    data = json.loads((ROOT / "data.json").read_text())
    api = OUT / "api"
    api.mkdir()
    shutil.copyfile(ROOT / "data.json", api / "data.json")
    # Fetched only by the /other/ pages; see extract.py.
    other_films = json.loads((ROOT / "other-films.json").read_text())
    shutil.copyfile(ROOT / "other-films.json", api / "other-films.json")

    # One real directory per slug, built from the same shell the server serves.
    shells = {r: (PUBLIC / f"{r}.html").read_text() for r in ROUTES}
    counts = {}
    for route, items, key, title_of in (
        ("film", data["films"], "slug", lambda f: f"{f.get('title', '?')} ({f.get('year') or '—'}) — Screened"),
        ("show", data["shows"], "slug", lambda s: f"{s.get('name', '?')} — Screened"),
        ("character", data["characters"], "slug", lambda c: f"{c.get('name', '?')} — Screened"),
        ("director", data["directors"], "slug", lambda d: f"{d.get('name', '?')} — Screened"),
        ("year", data["years"], "year", lambda y: f"{y.get('year')} in film — Screened"),
        # Not in the list, but each has a page so a filmography can be browsed.
        (
            "other",
            other_films,
            "slug",
            lambda f: f"{f.get('title', '?')} ({f.get('year') or '—'}) — not in the list — Screened",
        ),
    ):
        n = 0
        for item in items:
            slug = str(item.get(key) or "").strip()
            if not slug:
                continue
            page = OUT / route / slug
            page.mkdir(parents=True, exist_ok=True)
            (page / "index.html").write_text(rewrite_html(shells[route], title_of(item)))
            n += 1
        counts[route] = n

    # Plain pages, not slug routes: each gets the same real-directory treatment
    # so /directors and /years answer 200 rather than 404.
    for name, source, page_title in STANDALONE:
        out = OUT / name
        # characters/ and shows/ already exist as image directories; the page
        # sits alongside the artwork rather than replacing it.
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(
            rewrite_html((PUBLIC / source).read_text(), page_title)
        )

    (OUT / "static.js").write_text(STATIC_JS.replace("__BASE__", BASE))
    (OUT / "404.html").write_text(rewrite_html(NOT_FOUND, "Not found — Screened"))
    (OUT / ".nojekyll").write_text("")

    total = sum(counts.values()) + len(STANDALONE) + 1
    print(f"built {total} pages into {OUT.relative_to(ROOT)}/ at base {BASE}/")
    print("  " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 0


STATIC_JS = """\
// The published site is a read-only mirror: no Bun server, no
// Favorites.numbers. The rating control stays exactly as it is — it is how a
// tier is shown, and the scale is worth being able to open and read — but the
// write behind it cannot land here, so it reverts and says why. The add and
// edit forms are hidden instead: those are large, and a form that can only fail
// is worse than no form.
(() => {
  // Hidden, not removed. app.js finishes wiring these up after its data fetch
  // resolves — which is after this script runs — and setUpAddForm() throws on a
  // missing node, killing init() before it ever renders the film list.
  const style = document.createElement("style");
  style.textContent =
    ".add-toggle,.add-form,.edit-title,.edit-details" + "{display:none!important}";
  (document.head ?? document.documentElement).append(style);

  // Say where the missing controls went, once, on any page that had some. The
  // pages re-render after their fetch, so this is idempotent and re-applied.
  const HID =
    ".add-toggle,.add-form,.edit-title,.edit-details," +
    // The add picker stays visible, but its write can't land here either.
    "select.badge.is-add";
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
          JSON.stringify({
            ok: false,
            error: "read-only copy, so the change wasn't saved — make it on the local site",
          }),
          { status: 405, headers: { "content-type": "application/json" } }
        )
      );
    }
    return inner(input, init);
  };
})();
"""

NOT_FOUND = """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Not found — Screened</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>🎬</text></svg>" />
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <header class="masthead">
      <div class="wrap"><h1>Not found</h1></div>
    </header>
    <main class="wrap">
      <p class="empty">That page isn't part of the published site.</p>
      <p><a class="back" href="/">← All films</a></p>
    </main>
  </body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
