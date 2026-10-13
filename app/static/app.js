// Small extras only; every page works without this file.
"use strict";
document.documentElement.classList.add("js");
// Light/dark switch: flip instantly and remember it in a cookie the server also reads.
document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
  btn.addEventListener("click", function (e) {
    e.preventDefault();
    var root = document.documentElement;
    var next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    var secure = location.protocol === "https:" ? "; secure" : "";
    document.cookie = "theme=" + next + "; max-age=31536000; path=/; samesite=lax" + secure;
    btn.setAttribute("aria-label", next === "dark" ? "Licht thema" : "Donker thema");
  });
});
document.querySelectorAll("[data-copy]").forEach(function (btn) {
  if (!navigator.clipboard) return;
  btn.hidden = false;
  btn.addEventListener("click", function () {
    var el = document.getElementById(btn.dataset.copy);
    navigator.clipboard.writeText(el.value !== undefined ? el.value : el.textContent).then(function () {
      btn.textContent = "Gekopieerd ✓";
    });
  });
});
document.addEventListener("submit", function (e) {
  var msg = e.target.dataset.confirm;
  if (msg && !window.confirm(msg)) e.preventDefault();
});
// Filters apply as soon as a choice changes (the "Toon" button is the no-JS fallback).
document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
  form.addEventListener("change", function () {
    // Leave out empty fields so the URL stays readable.
    Array.prototype.forEach.call(form.elements, function (el) { el.disabled = el.name && !el.value; });
    form.submit();
  });
});
