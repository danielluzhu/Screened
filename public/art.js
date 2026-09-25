// Artwork loads in two passes: the small copy first so the page fills in at
// once, then the full image over the top of it.
//
// scripts/thumbs.py builds a WebP beside every image at the width its largest
// *list* slot needs, which took the front page from about 17MB of artwork to
// roughly 1MB. But the front page draws films as tiles, and that grid is
// `minmax(190px, 1fr)` — so on the view that matters most the 124px poster
// thumbnail was being stretched to 190px and beyond, further still on a retina
// screen. Fast, and visibly soft.
//
// So the thumbnail becomes the placeholder rather than the final image. It
// paints immediately, and the original is fetched behind it and swapped in.
// The swap is only ever an improvement in quality, never a reflow: both are
// the same artwork at the same aspect ratio.
//
// Two things keep that from undoing the weight saving:
//
//   * an image is only upgraded if the slot it is drawn into can actually show
//     more pixels than the thumbnail has, at this device's pixel ratio. The
//     30px and 52px list rows and most of the avatars never load a second
//     time, so those pages stay exactly as light as they are now;
//   * and nothing below the fold is fetched until it is scrolled towards.
//
// The thumb path is derived from the full URL at runtime rather than written
// as its own literal, so the base path the static build rewrites into these
// strings carries across. An image with no thumbnail yet falls back to the
// original, so a newly added one works before thumbs.py next runs.

// Mirrors SETS in scripts/thumbs.py: the width each set's thumbnails are built
// at. Drifting out of step with that file costs a request that wasn't needed,
// or skips one that was — not a broken image.
const THUMB_WIDTH = { posters: 124, portraits: 176, characters: 480, shows: 600 };

// How far outside the viewport an image starts loading. Generous enough that
// an ordinary scroll arrives to find the full image already there, rather than
// watching each row sharpen as it lands.
const NEAR_VIEWPORT = "600px";

function thumbUrl(url) {
  return url.replace(
    /^(.*)\/([^/]+)\/([^/]+)$/,
    (_, base, dir, file) => `${base}/thumbs/${dir}/${file}.webp`
  );
}

// The directory an image lives in is its set: "/posters/x.jpg" -> "posters".
function setOf(url) {
  const match = url.match(/\/([^/]+)\/[^/]+$/);
  return match ? match[1] : null;
}

function worthUpgrading(img, url) {
  const thumb = THUMB_WIDTH[setOf(url)];
  // A set thumbs.py doesn't build, so the thumbnail request will 404 and the
  // error fallback has this covered; nothing to weigh up.
  if (!thumb) return true;
  const slot = img.clientWidth;
  // Not laid out yet — hidden tab, detached node. Err towards quality; the
  // observer only reaches an element that is on screen anyway.
  if (!slot) return true;
  return slot * (window.devicePixelRatio || 1) > thumb;
}

// Fetch the original, then point the element at it. Assigning src only once
// the preload has finished means the browser already holds a decoded copy, so
// the swap paints in the same frame instead of blanking the slot first.
function upgrade(img, url) {
  if (img.dataset.full !== url) return;
  delete img.dataset.full;
  const full = new Image();
  if (img.fetchPriority) full.fetchPriority = img.fetchPriority;
  full.addEventListener("load", () => {
    img.src = url;
  });
  full.src = url;
}

function settle(img, url) {
  if (img.dataset.full !== url) return;
  if (worthUpgrading(img, url)) upgrade(img, url);
  else delete img.dataset.full;
}

const watcher =
  "IntersectionObserver" in window
    ? new IntersectionObserver(
        (entries, self) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            self.unobserve(entry.target);
            settle(entry.target, entry.target.dataset.full);
          }
        },
        { rootMargin: NEAR_VIEWPORT }
      )
    : null;

// `priority` is for artwork that should reach full quality without waiting to
// be scrolled to — the top tier on the front page. Everything else waits.
function thumbSrc(img, url, { priority = false } = {}) {
  img.src = thumbUrl(url);
  img.dataset.full = url;

  img.addEventListener(
    "error",
    () => {
      // No thumbnail built for this one yet: the original is all there is, and
      // it is already full quality, so there is nothing left to upgrade to.
      if (img.dataset.full) {
        delete img.dataset.full;
        img.src = url;
      }
    },
    { once: true }
  );

  if (priority) {
    img.loading = "eager";
    img.fetchPriority = "high";
  }
  if (priority || !watcher) {
    // Wait a frame so the element is in the document and has been laid out —
    // worthUpgrading needs its width to decide.
    requestAnimationFrame(() => settle(img, url));
    return;
  }
  watcher.observe(img);
}
