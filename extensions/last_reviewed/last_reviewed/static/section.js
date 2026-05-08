// Toggle the "at-bottom" class on .lr-section once the user has scrolled
// to (or past) the section's bottom edge, so the bottom-fade overlay can
// transition out. Walks up from .lr-section to find the nearest
// scrolling ancestor, listens for scroll and resize, and updates state.
(function () {
  function findScrollContainer(el) {
    var parent = el.parentElement;
    while (parent && parent !== document.documentElement) {
      var cs = getComputedStyle(parent);
      var oy = cs.overflowY;
      if ((oy === "auto" || oy === "scroll") && parent.scrollHeight > parent.clientHeight) {
        return parent;
      }
      parent = parent.parentElement;
    }
    return window;
  }

  function init(sectionEl) {
    var scroller = findScrollContainer(sectionEl);

    function update() {
      var rect = sectionEl.getBoundingClientRect();
      var viewportBottom =
        scroller === window ? window.innerHeight : scroller.getBoundingClientRect().bottom;
      // Section "still has more below" when its bottom edge sits below
      // the viewport's bottom edge. Tolerance of 1px to absorb fractional
      // pixel rounding from getBoundingClientRect.
      var hasMoreBelow = rect.bottom - viewportBottom > 1;
      sectionEl.classList.toggle("lr-section--at-bottom", !hasMoreBelow);
    }

    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
    // Re-check after layout settles (e.g., font loading shifts heights).
    requestAnimationFrame(update);
  }

  document.querySelectorAll(".lr-section").forEach(init);
})();
