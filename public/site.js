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

  function start() {
    revealActiveTab();
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
