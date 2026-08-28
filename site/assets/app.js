/* mORMot2 Daily — theme toggle, category filter, in-edition search.
   No dependencies, no storage beyond the viewer's own theme choice. */

(function () {
  "use strict";

  // ------------------------------------------------------------------ theme
  var root = document.documentElement;
  try {
    var saved = localStorage.getItem("mormot-daily-theme");
    if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);
  } catch (e) { /* private mode: fall back to the OS setting */ }

  var button = document.getElementById("theme");
  if (button) {
    button.addEventListener("click", function () {
      var current = root.getAttribute("data-theme");
      if (!current) {
        current = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      var next = current === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("mormot-daily-theme", next); } catch (e) { /* ignore */ }
    });
  }

  // ------------------------------------------------------- filter + search
  var entries = Array.prototype.slice.call(document.querySelectorAll(".entry"));
  if (!entries.length) return;

  var buttons = Array.prototype.slice.call(document.querySelectorAll(".f"));
  var search = document.getElementById("q");
  var state = { filter: "all", query: "" };

  function apply() {
    entries.forEach(function (entry) {
      var okCat = state.filter === "all" || entry.dataset.category === state.filter;
      var okQuery = !state.query || (entry.dataset.search || "").indexOf(state.query) !== -1;
      entry.classList.toggle("hidden", !(okCat && okQuery));
    });
    document.querySelectorAll(".section").forEach(function (section) {
      var visible = section.querySelectorAll(".entry:not(.hidden)").length;
      section.classList.toggle("hidden", visible === 0);
    });
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      buttons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.filter = btn.dataset.filter;
      apply();
    });
  });

  if (search) {
    var timer = null;
    search.addEventListener("input", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        state.query = search.value.trim().toLowerCase();
        apply();
      }, 120);
    });
    // "/" focuses the search box, Escape clears it.
    document.addEventListener("keydown", function (event) {
      if (event.key === "/" && document.activeElement !== search) {
        event.preventDefault();
        search.focus();
      } else if (event.key === "Escape" && document.activeElement === search) {
        search.value = "";
        state.query = "";
        apply();
        search.blur();
      }
    });
  }
})();
