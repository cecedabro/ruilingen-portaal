// Progressive enhancement only: everything works without this file.
"use strict";
function wireCopyButtons(root) {
  root.querySelectorAll("[data-copy]").forEach(function (btn) {
    if (!navigator.clipboard || btn.dataset.wired) return;
    btn.dataset.wired = "1";
    btn.hidden = false;
    btn.addEventListener("click", function () {
      var text = document.getElementById(btn.dataset.copy).value;
      navigator.clipboard.writeText(text).then(
        function () { btn.textContent = "Gekopieerd ✓"; },
        function () {
          var range = document.createRange();
          range.selectNodeContents(document.getElementById(btn.dataset.select));
          var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
          btn.textContent = "Geselecteerd, kopieer met Cmd/Ctrl+C";
        });
    });
  });
}
document.addEventListener("DOMContentLoaded", function () { wireCopyButtons(document); });
document.addEventListener("htmx:load", function (e) { wireCopyButtons(e.target); });
