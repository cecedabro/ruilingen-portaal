// Small extras only; every page works without this file.
"use strict";
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
