// SPDX-License-Identifier: MIT
document.addEventListener("DOMContentLoaded", () => {
  const switcher = document.querySelector(".version-switcher");
  if (!switcher) return;

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && switcher.open) {
      switcher.open = false;
      switcher.querySelector("summary").focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (!switcher.contains(event.target)) switcher.open = false;
  });
  // Plain links remain usable without JavaScript; keep anchors only for matching pages.
  const updateLinks = () => document.querySelectorAll("a[data-version-same-page]").forEach((link) => {
    const target = new URL(link.href);
    target.hash = window.location.hash;
    target.search = window.location.search;
    link.href = target.href;
  });
  updateLinks();
  window.addEventListener("hashchange", updateLinks);
});
