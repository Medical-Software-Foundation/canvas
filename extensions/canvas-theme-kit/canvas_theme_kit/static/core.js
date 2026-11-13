/* Canvas Theme Kit — shared behavior.
 *
 * Ships with the plugin and is versioned in the repository. This file is
 * deliberately NOT admin-editable: admin-authored JavaScript served into
 * patient portal sessions would be a stored-XSS surface by design, where a
 * single compromised staff account becomes script execution on every page.
 * Admins edit CSS and design tokens; behavior ships through code review.
 */
(function (global) {
  "use strict";

  var ThemeKit = {};

  /**
   * Make an embedded Canvas surface grow to fit its content.
   *
   * Note Applications and modals render in an iframe that does not auto-size,
   * so without this the content gets its own scrollbar inside the note instead
   * of the note growing. Canvas opens a MessagePort on INIT_CHANNEL; we post
   * our height on connect and on every resize.
   */
  ThemeKit.autoResize = function autoResize() {
    var port = null;

    function postHeight() {
      if (!port) return;
      port.postMessage({
        type: "RESIZE",
        height: document.body.offsetHeight
      });
    }

    global.addEventListener("message", function (event) {
      if (!event.data || event.data.type !== "INIT_CHANNEL") return;
      port = event.ports && event.ports[0];
      if (!port) return;
      port.start && port.start();
      postHeight();
    });

    if (typeof ResizeObserver === "function") {
      new ResizeObserver(postHeight).observe(document.body);
    } else {
      global.addEventListener("resize", postHeight);
    }
  };

  /**
   * Read a published design token at runtime, e.g. token("color-primary").
   *
   * Reads the computed custom property rather than a copy of the token values,
   * so it always reflects whatever stylesheet actually loaded.
   */
  ThemeKit.token = function token(name) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue("--ctk-" + name)
      .trim();
  };

  global.CanvasThemeKit = ThemeKit;
})(window);
