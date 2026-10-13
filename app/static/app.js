// Small extras only; every page works without this file.
"use strict";
document.documentElement.classList.add("js");
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
