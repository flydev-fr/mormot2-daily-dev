/* mORMot2 Daily — theme toggle, table filtering, search and sort.
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

  // ----------------------------------------------------------- language menu
  // The menu is a <details>, so it opens and closes on its own. These two only
  // add what a disclosure does not do by itself: shut when you look elsewhere.
  var langs = document.querySelector("details.langs");
  if (langs) {
    document.addEventListener("click", function (event) {
      if (langs.open && !langs.contains(event.target)) langs.open = false;
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && langs.open) {
        langs.open = false;
        langs.querySelector("summary").focus();
      }
    });
  }

  // ------------------------------------------------------------------ table
  var table = document.getElementById("entries");
  if (!table) return;

  var rows = Array.prototype.slice.call(table.querySelectorAll(".row"));
  if (!rows.length) return;

  var search = document.getElementById("q");
  var fCat = document.getElementById("f-cat");
  var fSev = document.getElementById("f-sev");
  var tAction = document.getElementById("t-action");
  var tReview = document.getElementById("t-review");
  var shown = document.getElementById("shown");
  var noHits = table.querySelector(".no-hits");

  var themeChips = Array.prototype.slice.call(document.querySelectorAll(".theme-chip"));
  var summaries = Array.prototype.slice.call(document.querySelectorAll(".theme-summary"));

  var state = { query: "", cat: "", sev: "", action: false, reviewed: false, theme: null };

  // A row lists the themes it belongs to as comma-separated indices.
  function inTheme(row, idx) {
    if (idx === null) return true;
    var list = (row.dataset.themes || "").split(",");
    return list.indexOf(String(idx)) !== -1;
  }

  function apply() {
    var visible = 0;
    rows.forEach(function (row) {
      var ok =
        (!state.cat || row.dataset.category === state.cat) &&
        (!state.sev || row.dataset.severity === state.sev) &&
        (!state.action || row.dataset.action === "yes") &&
        (!state.reviewed || row.dataset.reviewed === "yes") &&
        inTheme(row, state.theme) &&
        (!state.query || (row.dataset.search || "").indexOf(state.query) !== -1);
      row.classList.toggle("hidden", !ok);
      if (ok) visible++;
    });
    // Zebra striping has to follow what is on screen, not the source order.
    var i = 0;
    rows.forEach(function (row) {
      if (row.classList.contains("hidden")) return;
      row.classList.toggle("odd", i % 2 === 1);
      i++;
    });
    if (shown) shown.textContent = String(visible);
    if (noHits) noHits.classList.toggle("hidden", visible !== 0);
  }

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

  if (fCat) fCat.addEventListener("change", function () { state.cat = fCat.value; apply(); });
  if (fSev) fSev.addEventListener("change", function () { state.sev = fSev.value; apply(); });

  function toggle(el, key) {
    if (!el) return;
    el.addEventListener("click", function () {
      state[key] = !state[key];
      el.setAttribute("aria-pressed", state[key] ? "true" : "false");
      apply();
    });
  }
  toggle(tAction, "action");
  toggle(tReview, "reviewed");

  // Selecting a story filters the table to its commits and reveals its summary.
  // Clicking the active one clears it, so it behaves like a radio you can unset.
  themeChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      var idx = Number(chip.dataset.theme);
      state.theme = state.theme === idx ? null : idx;
      themeChips.forEach(function (c) {
        c.setAttribute("aria-pressed",
          Number(c.dataset.theme) === state.theme ? "true" : "false");
      });
      summaries.forEach(function (sum) {
        sum.classList.toggle("hidden", Number(sum.dataset.theme) !== state.theme);
      });
      apply();
    });
  });

  // ------------------------------------------------------------------- sort
  // Severity ascending is the published order, so a first click on the active
  // column reverses it and a click on the other column takes over as primary.
  var sorters = Array.prototype.slice.call(table.querySelectorAll(".sort"));
  var sort = { key: "rank", dir: 1 };

  function resort() {
    var sorted = rows.slice().sort(function (a, b) {
      var av = Number(a.dataset[sort.key]) || 0;
      var bv = Number(b.dataset[sort.key]) || 0;
      if (av !== bv) return (av - bv) * sort.dir;
      return (Number(a.dataset.rank) || 0) - (Number(b.dataset.rank) || 0);
    });
    var anchor = table.querySelector(".no-hits");
    sorted.forEach(function (row) { table.insertBefore(row, anchor); });
    sorters.forEach(function (s) {
      var active = s.dataset.sort === sort.key;
      s.setAttribute("aria-pressed", active ? "true" : "false");
      s.dataset.dir = active ? (sort.dir === 1 ? "asc" : "desc") : "";
    });
    apply();
  }

  sorters.forEach(function (s) {
    s.addEventListener("click", function () {
      var key = s.dataset.sort;
      if (sort.key === key) {
        sort.dir = -sort.dir;
      } else {
        sort.key = key;
        // Lines is most useful biggest-first; severity most useful worst-first.
        sort.dir = key === "weight" ? -1 : 1;
      }
      resort();
    });
  });

  apply();
})();
