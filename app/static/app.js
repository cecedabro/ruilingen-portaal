// Small extras; every page also works without this file.
"use strict";
document.documentElement.classList.add("js");

// ------------------------------------------------------------ per-page wiring (re-run after a swap)
function init(root) {
  root.querySelectorAll("[data-copy]").forEach(function (btn) {
    if (!navigator.clipboard) return;
    btn.hidden = false;
    btn.addEventListener("click", function () {
      var el = document.getElementById(btn.dataset.copy);
      navigator.clipboard.writeText(el.value !== undefined ? el.value : el.textContent).then(function () {
        btn.textContent = "Gekopieerd ✓";
      });
    });
  });
  // Light/dark switch: flip instantly, remember it in a cookie the server also reads.
  root.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var html = document.documentElement;
      var next = html.dataset.theme === "dark" ? "light" : "dark";
      html.dataset.theme = next;
      var secure = location.protocol === "https:" ? "; secure" : "";
      document.cookie = "theme=" + next + "; max-age=31536000; path=/; samesite=lax" + secure;
      btn.setAttribute("aria-label", next === "dark" ? "Licht thema" : "Donker thema");
    });
  });
  // Filters apply as soon as a choice changes (the "Toon" button is the no-JS fallback).
  root.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    form.addEventListener("change", function () {
      var params = new URLSearchParams(new FormData(form));
      Array.from(params.keys()).forEach(function (k) { if (!params.get(k)) params.delete(k); });
      var q = params.toString();
      go(form.getAttribute("action") + (q ? "?" + q : ""), true);
    });
  });
  // Weggeven / Zoeken: switch in place. The hidden variant's fieldsets are disabled, so the
  // browser neither validates nor submits them.
  root.querySelectorAll("form[data-kind-switch]").forEach(function (form) {
    form.addEventListener("change", function (e) {
      if (e.target.name !== "kind") return;
      form.dataset.kind = e.target.value;
      form.querySelectorAll(".only-offer").forEach(function (f) { f.disabled = e.target.value !== "offer"; });
      form.querySelectorAll(".only-wanted").forEach(function (f) { f.disabled = e.target.value !== "wanted"; });
      history.replaceState(history.state, "", e.target.value === "wanted" ? "/plaatsen?soort=gezocht" : "/plaatsen");
    });
  });
}

document.addEventListener("submit", function (e) {
  var msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});

// ------------------------------------------------------------ instant navigation
// Pages are a few KB. The four tabs are fetched in the background, and following an in-app
// link swaps the page in place instead of reloading it. Forms (POST) still load normally.
var TABS = ["/aangeboden", "/gezocht", "/mijn", "/plaatsen"];
var FRESH_MS = 20000;
var cache = new Map(); // url -> {at, promise}

function fetchPage(url, prefetch) {
  var hit = cache.get(url);
  if (hit && Date.now() - hit.at < FRESH_MS) return hit.promise;
  var promise = fetch(url, {
    credentials: "same-origin",
    headers: prefetch ? { "X-Prefetch": "1" } : {},
  }).then(function (r) {
    if (!r.ok || r.redirected || !(r.headers.get("content-type") || "").includes("text/html")) {
      throw new Error("not swappable");
    }
    return r.text();
  });
  promise.catch(function () { cache.delete(url); });
  cache.set(url, { at: Date.now(), promise: promise });
  return promise;
}

function swap(html, url, push) {
  var doc = new DOMParser().parseFromString(html, "text/html");
  var apply = function () {
    document.title = doc.title;
    document.body.replaceWith(doc.body);
    if (push) history.pushState({}, "", url);
    var hash = url.split("#")[1];
    var target = hash && document.getElementById(hash);
    if (target) target.scrollIntoView(); else window.scrollTo(0, 0);
    init(document);
  };
  // No view transition here: the swap itself takes a few ms, an animation would only add delay.
  apply();
}

function go(url, push) {
  fetchPage(url.split("#")[0], false)
    .then(function (html) { swap(html, url, push); })
    .catch(function () { location.href = url; });
}

function swappable(a) {
  if (!a || a.target || a.hasAttribute("download") || a.dataset.noswap !== undefined) return false;
  var u = new URL(a.href, location.href);
  if (u.origin !== location.origin) return false;
  if (u.pathname === location.pathname && u.search === location.search && u.hash) return false;
  // Only pages that are safe to fetch ahead of time (not /meldingen: opening it marks read).
  return TABS.indexOf(u.pathname) >= 0 || u.pathname === "/account" || u.pathname === "/privacy";
}

document.addEventListener("click", function (e) {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  var a = e.target.closest("a[href]");
  if (!swappable(a)) return;
  e.preventDefault();
  var u = new URL(a.href, location.href);
  go(u.pathname + u.search + u.hash, true);
});

// Start loading the moment a finger touches a link, ~100 ms before the click fires.
document.addEventListener("pointerdown", function (e) {
  var a = e.target.closest("a[href]");
  if (swappable(a)) {
    var u = new URL(a.href, location.href);
    fetchPage(u.pathname + u.search, true);
  }
}, { passive: true });

window.addEventListener("popstate", function () {
  go(location.pathname + location.search + location.hash, false);
});

function prefetchTabs() {
  if (!document.querySelector(".tabbar")) return; // not logged in
  var conn = navigator.connection;
  if (conn && (conn.saveData || /2g/.test(conn.effectiveType || ""))) return;
  TABS.forEach(function (path) {
    if (path !== location.pathname) fetchPage(path, true).catch(function () {});
  });
}

init(document);
if (window.requestIdleCallback) requestIdleCallback(prefetchTabs, { timeout: 1500 });
else setTimeout(prefetchTabs, 300);
