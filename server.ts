import { file } from "bun";
import { join } from "path";

const ROOT = import.meta.dir;
const PORT = Number(process.env.PORT ?? 3000);
const TIERS = new Set(["S", "A", "B", "C", "D", "E", "F", "?"]);

// data.json is regenerated from Favorites.numbers by scripts/extract.py.
// Read it per request so edits show up on refresh without a restart.
async function loadData() {
  return await file(join(ROOT, "data.json")).json();
}

// --- rating writes -------------------------------------------------------
// Saving rewrites the whole Numbers document (~1.4s), so edits are coalesced
// over a short window and every batch runs strictly one at a time.
// Keyed by title+year: same-title films are different films.
const pending = new Map<string, { title: string; year: number | null; tier: string }>();
let batch: Promise<WriteResult> | null = null;
let chain: Promise<unknown> = Promise.resolve();

type WriteResult = { ok: boolean; error?: string; applied?: unknown[]; backup?: string };
type Edit = { title: string; year: number | null; tier: string };

async function runScript(script: string, payload: unknown): Promise<WriteResult> {
  const proc = Bun.spawn(["python3", script], {
    cwd: join(ROOT, "scripts"),
    stdin: new TextEncoder().encode(JSON.stringify(payload)),
    stdout: "pipe",
    stderr: "pipe",
  });
  const [out, err] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  await proc.exited;
  try {
    // extract.py prints a progress line first; the JSON result is last.
    return JSON.parse(out.trim().split("\n").pop() ?? "");
  } catch {
    return { ok: false, error: err.trim().split("\n").pop() || out.trim() || `${script} failed` };
  }
}

const runWriter = (edits: Edit[]) => runScript("set_rating.py", { edits });

// Posters come from Wikipedia, which rate-limits hard — a fetch can stall for
// a minute. Run it detached so adding a film stays responsive; the page polls
// for the poster to appear.
function fetchPosterInBackground(title: string, year: number | null) {
  const args = ["python3", "posters.py", "--film", title];
  if (year != null) args.push("--year", String(year));
  const proc = Bun.spawn(args, {
    cwd: join(ROOT, "scripts"),
    stdout: "pipe",
    stderr: "pipe",
  });
  // Regenerate data.json once the poster lands so it shows up without a manual step.
  proc.exited.then(async () => {
    const out = await new Response(proc.stdout).text();
    let got = false;
    try {
      got = Boolean(JSON.parse(out.trim().split("\n").pop() ?? "").poster);
    } catch {
      got = false;
    }
    console.log(`poster for ${title}: ${got ? "found" : "none"}`);
    if (got) {
      const re = Bun.spawn(["python3", "extract.py"], { cwd: join(ROOT, "scripts") });
      await re.exited;
    }
  });
}

// Portraits come from Fandom wikis; same treatment as posters.
function fetchPortraitInBackground(name: string) {
  const proc = Bun.spawn(["python3", "character_photos.py", "--only", name], {
    cwd: join(ROOT, "scripts"),
    stdout: "pipe",
    stderr: "pipe",
  });
  proc.exited.then(async () => {
    const out = await new Response(proc.stdout).text();
    console.log(`portrait for ${name}: ${out.includes("no photo found") ? "none" : "found"}`);
    const re = Bun.spawn(["python3", "extract.py"], { cwd: join(ROOT, "scripts") });
    await re.exited;
  });
}

// A new show arrives as a bare name; everything else comes from Wikidata.
// Queue it behind other writes since it edits the same document.
function enrichShowInBackground(name: string) {
  chain = chain.then(async () => {
    const proc = Bun.spawn(["python3", "shows.py", "--only", name, "--apply"], {
      cwd: join(ROOT, "scripts"),
      stdout: "pipe",
      stderr: "pipe",
    });
    const out = await new Response(proc.stdout).text();
    await proc.exited;
    console.log(`show details for ${name}: ${out.includes("no series match") ? "not found" : "filled"}`);
  });
}

// A new song arrives as a title and an artist; album, year, country and the
// album's genre come from Wikidata. Queue it behind other writes since it
// edits the same document.
function enrichSongInBackground(song: string) {
  chain = chain.then(async () => {
    const proc = Bun.spawn(["python3", "music_autofill.py", "--only", song], {
      cwd: join(ROOT, "scripts"),
      stdout: "pipe",
      stderr: "pipe",
    });
    const out = await new Response(proc.stdout).text();
    await proc.exited;
    console.log(`song details for ${song}: ${out.includes("filled in 0") ? "not found" : "filled"}`);
  });
}

function queueEdit(title: string, year: number | null, tier: string): Promise<WriteResult> {
  pending.set(`${title}|${year ?? ""}`, { title, year, tier });
  if (!batch) {
    batch = new Promise<WriteResult>((resolve) => {
      setTimeout(() => {
        const edits = [...pending.values()];
        pending.clear();
        batch = null;
        // Serialize behind any write already in flight.
        chain = chain.then(() => runWriter(edits).then(resolve, (e) => resolve({ ok: false, error: String(e) })));
      }, 250);
    });
  }
  return batch;
}

// --- server --------------------------------------------------------------
const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
};

const server = Bun.serve({
  port: PORT,
  hostname: "0.0.0.0",
  async fetch(req) {
    const url = new URL(req.url);
    let path = decodeURIComponent(url.pathname);

    if (path === "/api/data") {
      return Response.json(await loadData(), { headers: { "cache-control": "no-store" } });
    }

    if (path === "/api/rating") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: { title?: string; tier?: string; year?: unknown };
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      const title = String(body.title ?? "").trim();
      const tier = String(body.tier ?? "").trim();
      if (!title) return Response.json({ ok: false, error: "missing title" }, { status: 400 });
      if (!TIERS.has(tier)) {
        return Response.json({ ok: false, error: `invalid tier "${tier}"` }, { status: 400 });
      }
      const rawYear = body.year;
      const year = typeof rawYear === "number" ? rawYear : null;
      const result = await queueEdit(title, year, tier);
      const status = result.ok ? 200 : result.error?.startsWith("unknown title") ? 404 : 500;
      return Response.json(result, { status });
    }

    if (path === "/api/film") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      const title = String(body.title ?? "").trim();
      if (!title) return Response.json({ ok: false, error: "title is required" }, { status: 400 });

      // Serialize behind rating writes — both rewrite the same document.
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("add_film.py", body)
      ) as Promise<WriteResult>);

      if (!result.ok) {
        const status = (result as { duplicate?: boolean }).duplicate ? 409 : 400;
        return Response.json(result, { status });
      }

      const year = (result as { film?: { year: number | null } }).film?.year ?? null;
      fetchPosterInBackground(title, year);
      return Response.json({ ...result, posterPending: true });
    }

    if (path === "/api/film/critique") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      if (!String(body.title ?? "").trim()) {
        return Response.json({ ok: false, error: "title is required" }, { status: 400 });
      }
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("set_critique.py", body)
      ) as Promise<WriteResult>);
      const status = result.ok ? 200 : result.error?.endsWith("is not in the list") ? 404 : 500;
      return Response.json(result, { status });
    }

    // Year, director, country and genre, edited by hand on the film's page.
    if (path === "/api/film/details") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      if (!String(body.title ?? "").trim()) {
        return Response.json({ ok: false, error: "title is required" }, { status: 400 });
      }
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("set_details.py", body)
      ) as Promise<WriteResult>);
      if (!result.ok) {
        const status = (result as { duplicate?: boolean }).duplicate
          ? 409
          : result.error?.endsWith("is not in the list")
            ? 404
            : 400;
        return Response.json(result, { status });
      }
      return Response.json(result);
    }

    // Every film has its own page at /film/<slug>; the page itself resolves
    // the slug against /api/data.
    if (path === "/film" || path.startsWith("/film/")) {
      return new Response(file(join(ROOT, "public", "film.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    if (path === "/api/show") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      const name = String(body.name ?? "").trim();
      if (!name) return Response.json({ ok: false, error: "name is required" }, { status: 400 });

      const result: WriteResult = await (chain = chain.then(() =>
        runScript("add_show.py", body)
      ) as Promise<WriteResult>);
      if (!result.ok) {
        const status = (result as { duplicate?: boolean }).duplicate ? 409 : 400;
        return Response.json(result, { status });
      }
      enrichShowInBackground(name);
      return Response.json({ ...result, detailsPending: true });
    }

    if (path === "/api/character") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      const name = String(body.name ?? "").trim();
      if (!name) return Response.json({ ok: false, error: "name is required" }, { status: 400 });

      const result: WriteResult = await (chain = chain.then(() =>
        runScript("add_character.py", body)
      ) as Promise<WriteResult>);
      if (!result.ok) {
        const status = (result as { duplicate?: boolean }).duplicate ? 409 : 400;
        return Response.json(result, { status });
      }
      fetchPortraitInBackground(name);
      return Response.json({ ...result, photoPending: true });
    }

    if (path === "/api/music") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      const song = String(body.song ?? "").trim();
      if (!song) return Response.json({ ok: false, error: "song is required" }, { status: 400 });

      const result: WriteResult = await (chain = chain.then(() =>
        runScript("add_song.py", body)
      ) as Promise<WriteResult>);
      if (!result.ok) {
        const status = (result as { duplicate?: boolean }).duplicate ? 409 : 400;
        return Response.json(result, { status });
      }
      enrichSongInBackground(song);
      return Response.json({ ...result, detailsPending: true });
    }

    // Songs use the same S–F/? scale as films.
    if (path === "/api/music/rating") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: { song?: string; artist?: string; tier?: string };
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      const song = String(body.song ?? "").trim();
      const tier = String(body.tier ?? "").trim();
      if (!song) return Response.json({ ok: false, error: "song is required" }, { status: 400 });
      if (!TIERS.has(tier)) {
        return Response.json({ ok: false, error: `invalid tier "${tier}"` }, { status: 400 });
      }
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("set_song_tier.py", { song, artist: body.artist ?? null, tier })
      ) as Promise<WriteResult>);
      const status = result.ok ? 200 : result.error?.endsWith("is not in the list") ? 404 : 500;
      return Response.json(result, { status });
    }

    // Characters use the same S–F/? scale as films, written to the Characters
    // sheet. Names are unique there, so no year is needed to find the row.
    if (path === "/api/character/rating") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: { name?: string; tier?: string };
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      const name = String(body.name ?? "").trim();
      const tier = String(body.tier ?? "").trim();
      if (!name) return Response.json({ ok: false, error: "name is required" }, { status: 400 });
      if (!TIERS.has(tier)) {
        return Response.json({ ok: false, error: `invalid tier "${tier}"` }, { status: 400 });
      }
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("set_character_tier.py", { name, tier })
      ) as Promise<WriteResult>);
      const status = result.ok ? 200 : result.error?.endsWith("is not in the list") ? 404 : 500;
      return Response.json(result, { status });
    }

    if (path === "/api/character/why") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      if (!String(body.name ?? "").trim()) {
        return Response.json({ ok: false, error: "name is required" }, { status: 400 });
      }
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("set_why.py", body)
      ) as Promise<WriteResult>);
      const status = result.ok ? 200 : result.error?.endsWith("is not in the list") ? 404 : 500;
      return Response.json(result, { status });
    }

    // Suggestions are recomputed by extract.py on every write, so this page
    // is just another read of /api/data.
    if (path === "/suggestions") {
      return new Response(file(join(ROOT, "public", "suggestions.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    // Indexes of every director and every year. Checked before the per-item
    // routes below; "/directors" is not "/director" and never falls through.
    if (path === "/directors") {
      return new Response(file(join(ROOT, "public", "directors.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    if (path === "/years") {
      return new Response(file(join(ROOT, "public", "years.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    if (path === "/year" || path.startsWith("/year/")) {
      return new Response(file(join(ROOT, "public", "year.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    if (path === "/show" || path.startsWith("/show/")) {
      return new Response(file(join(ROOT, "public", "show.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    if (path === "/character" || path.startsWith("/character/")) {
      return new Response(file(join(ROOT, "public", "character.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    // Each director gets a page too, resolved client-side from the slug.
    if (path === "/director" || path.startsWith("/director/")) {
      return new Response(file(join(ROOT, "public", "director.html")), {
        headers: { "content-type": MIME[".html"], "cache-control": "no-store" },
      });
    }

    if (path === "/api/film/rename") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      if (!String(body.title ?? "").trim() || !String(body.newTitle ?? "").trim()) {
        return Response.json({ ok: false, error: "title and newTitle are required" }, { status: 400 });
      }
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("rename_film.py", body)
      ) as Promise<WriteResult>);
      const status = result.ok ? 200 : result.error?.endsWith("is not in the list") ? 404 : 500;
      return Response.json(result, { status });
    }

    if (path === "/api/film/remove") {
      if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
      let body: Record<string, unknown>;
      try {
        body = await req.json();
      } catch {
        return Response.json({ ok: false, error: "invalid JSON" }, { status: 400 });
      }
      if (!String(body.title ?? "").trim()) {
        return Response.json({ ok: false, error: "title is required" }, { status: 400 });
      }
      const result: WriteResult = await (chain = chain.then(() =>
        runScript("remove_film.py", body)
      ) as Promise<WriteResult>);
      const status = result.ok ? 200 : result.error?.endsWith("is not in the list") ? 404 : 500;
      return Response.json(result, { status });
    }

    if (path === "/") path = "/index.html";

    // Serve only from public/, and never above it.
    const target = join(ROOT, "public", path);
    if (!target.startsWith(join(ROOT, "public"))) {
      return new Response("forbidden", { status: 403 });
    }

    const asset = file(target);
    if (await asset.exists()) {
      const ext = path.slice(path.lastIndexOf("."));
      return new Response(asset, {
        headers: {
          "content-type": MIME[ext] ?? "application/octet-stream",
          "cache-control": "no-store",
        },
      });
    }

    return new Response("not found", { status: 404 });
  },
});

console.log(`Favorites running at http://localhost:${server.port}`);
