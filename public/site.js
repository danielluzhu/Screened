// Behaviour every page shares. Loaded before each page's own script, so keep
// it in a closure like art.js — the pages share one global scope.
(function () {
  // On a phone the tabs are one row that scrolls sideways, so the active tab
  // can start off-screen: "What to watch next" is the last of eight. Bring it
  // into view on load, and again when the front page switches views in place.
  function revealActiveTab() {
    const tabs = document.querySelector(".tabs");
    const active = tabs?.querySelector(".tab.is-active");
    if (!tabs || !active || tabs.scrollWidth <= tabs.clientWidth) return;
    const left = active.offsetLeft - (tabs.clientWidth - active.offsetWidth) / 2;
    tabs.scrollTo({ left: Math.max(0, left) });
  }

  // Which sides have more tabs past the edge, for the CSS fade: fading the
  // right edge once the row is scrolled to its end would dim the last tab.
  function markEdges(tabs) {
    const max = tabs.scrollWidth - tabs.clientWidth;
    tabs.classList.toggle("more-left", tabs.scrollLeft > 1);
    tabs.classList.toggle("more-right", tabs.scrollLeft < max - 1);
  }

  // On a phone a filter row — search plus three or four dropdowns — wraps into
  // three rows above the content. Any row with two or more dropdowns gets a
  // "Filters" button instead, which opens them as a panel and counts how many
  // are set. The dropdowns are moved, not copied, so the page's own listeners
  // and lookups by id keep working. On wider screens the panel is
  // display: contents and the row lays out exactly as before.
  const FILTER_ROWS = ".controls, .sug-filters";

  function enhanceFilters(row) {
    if (row.dataset.filters) return;
    const selects = [...row.querySelectorAll(":scope > select")];
    if (selects.length < 2) return;
    row.dataset.filters = "on";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "filter-toggle";
    button.setAttribute("aria-expanded", "false");
    const label = document.createElement("span");
    label.textContent = "Filters";
    const count = document.createElement("span");
    count.className = "filter-count";
    button.append(label, count);

    const panel = document.createElement("div");
    panel.className = "filter-panel";
    selects[0].before(button);
    button.after(panel);
    panel.append(...selects);

    // Sort isn't a filter: changing it hides nothing, so it isn't counted.
    const filters = selects.filter((s) => !/^sort/i.test(s.getAttribute("aria-label") || ""));
    const refresh = () => {
      const set = filters.filter((s) => s.selectedIndex > 0).length;
      count.textContent = set ? String(set) : "";
      button.classList.toggle("has-active", set > 0);
    };
    panel.addEventListener("change", refresh);
    refresh();

    button.addEventListener("click", () => {
      const open = row.classList.toggle("filters-open");
      button.setAttribute("aria-expanded", String(open));
    });
  }

  function start() {
    revealActiveTab();
    document.querySelectorAll(FILTER_ROWS).forEach(enhanceFilters);
    // Several pages build their filter rows after their data arrives.
    new MutationObserver(() => {
      document.querySelectorAll(FILTER_ROWS).forEach(enhanceFilters);
    }).observe(document.body, { childList: true, subtree: true });
    const tabs = document.querySelector(".tabs");
    if (tabs) {
      markEdges(tabs);
      tabs.addEventListener("scroll", () => markEdges(tabs), { passive: true });
      window.addEventListener("resize", () => markEdges(tabs));
      // Only a tab's own class changing means the view switched; the row's
      // edge classes changing is just the user scrolling it.
      new MutationObserver((changes) => {
        if (changes.some((change) => change.target !== tabs)) revealActiveTab();
      }).observe(tabs, {
        subtree: true,
        attributeFilter: ["class"],
      });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
