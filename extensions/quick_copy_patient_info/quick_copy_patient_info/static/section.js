// Wire one click listener per .qcpi-section. Clicks on a .qcpi-copy button
// copy its data-copy payload to the clipboard and briefly swap the icon
// to a check mark to confirm the action. Falls back to document.execCommand
// when the Async Clipboard API is unavailable (older embedded browsers).
(function () {
  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error("execCommand copy failed"));
      } catch (err) {
        reject(err);
      }
    });
  }

  function flashCopied(button) {
    button.classList.add("qcpi-copy--copied");
    if (button._qcpiTimer) {
      clearTimeout(button._qcpiTimer);
    }
    button._qcpiTimer = setTimeout(function () {
      button.classList.remove("qcpi-copy--copied");
      button._qcpiTimer = null;
    }, 1200);
  }

  function init(sectionEl) {
    sectionEl.addEventListener("click", function (event) {
      var button = event.target.closest(".qcpi-copy");
      if (!button || !sectionEl.contains(button)) return;
      var payload = button.getAttribute("data-copy") || "";
      if (!payload) return;
      copyToClipboard(payload).then(
        function () { flashCopied(button); },
        function () { /* silently no-op: clipboard not available */ }
      );
    });
  }

  document.querySelectorAll(".qcpi-section").forEach(init);
})();
