(function () {
  "use strict";

  // ----- Iframe sizing (Checkpoint 1) -----
  //
  // The plugin renders into a Canvas-injected iframe whose default size is
  // too small for the Exam form. We size the iframe to fit its content
  // (bounded by min/max) and also lift the `min-height` floor on a few
  // parent-document ancestors so Canvas's modal container doesn't
  // collapse the iframe.
  //
  // Why "fit to content" rather than a fixed `80vh`: the form starts
  // short (just RFV + HPI visible until the provider expands sections)
  // and grows as orders / diagnoses are added. A fixed 80vh leaves a
  // large blank area at the bottom of the modal when the form is short.
  // The container CSS sets `.exam-container { height: 100% }`, so it
  // tracks whatever the iframe is sized to.
  //
  // Critical: these inline-style changes MUST be reverted when the user
  // switches away from the Exam tab. Without revert, the Note tab (which
  // re-uses the same parent containers) renders blank because the
  // ancestor min-height pushes its native command UI out of view. We
  // track every node we modify + its original value, then revert on:
  //   (a) the iframe's `pagehide` event (fires when Canvas removes the
  //       iframe from the DOM), and
  //   (b) a visibility poll that catches `display:none` toggles where
  //       pagehide doesn't fire.
  // The poll also re-applies the sizing if Canvas re-shows the iframe.
  // A ResizeObserver on document.body re-syncs the iframe height as the
  // form grows/shrinks (e.g. provider adds an order card).
  var MIN_IFRAME_HEIGHT_PX = 400;   // floor that keeps Canvas's modal from collapsing
  var MAX_IFRAME_HEIGHT_VH = 90;    // ceiling so we don't take over the chart
  var HEIGHT_BUFFER_PX = 16;        // small margin so content isn't pixel-clipped

  var cachedIframe = null;
  var stretchState = { applied: false, snapshots: [] };

  function _targetIframeHeightPx() {
    // document.documentElement.scrollHeight is the natural height of the
    // page content inside the iframe. window.innerHeight is the iframe's
    // own viewport, which is a usable proxy for "how much vertical space
    // do I have" — same-origin context, no cross-frame access needed.
    var contentH = document.documentElement.scrollHeight || 0;
    var viewportH = window.innerHeight || 800;
    var maxH = Math.floor(viewportH * (MAX_IFRAME_HEIGHT_VH / 100));
    return Math.max(MIN_IFRAME_HEIGHT_PX, Math.min(contentH + HEIGHT_BUFFER_PX, maxH));
  }

  function findHostIframe() {
    if (cachedIframe && cachedIframe.contentWindow === window) return cachedIframe;
    try {
      var parentDoc = window.parent && window.parent.document;
      if (!parentDoc) return null;
      var iframes = parentDoc.querySelectorAll("iframe");
      for (var i = 0; i < iframes.length; i++) {
        if (iframes[i].contentWindow === window) {
          cachedIframe = iframes[i];
          return cachedIframe;
        }
      }
    } catch (e) {}
    return null;
  }

  function _snapshot(node, propsArr) {
    var original = {};
    for (var i = 0; i < propsArr.length; i++) original[propsArr[i]] = node.style[propsArr[i]];
    stretchState.snapshots.push({ node: node, properties: propsArr, original: original });
  }

  function applyStretch() {
    var iframe = findHostIframe();
    if (!iframe) return false;
    try {
      if (!stretchState.applied) {
        _snapshot(iframe, ["height", "minHeight", "width"]);
        var node = iframe.parentElement;
        for (var depth = 0; node && depth < 4; depth++) {
          _snapshot(node, ["minHeight"]);
          node = node.parentElement;
        }
        stretchState.applied = true;
      }
      var targetPx = _targetIframeHeightPx();
      var minPx = MIN_IFRAME_HEIGHT_PX + "px";
      iframe.style.height = targetPx + "px";
      iframe.style.minHeight = minPx;
      iframe.style.width = "100%";
      for (var i = 1; i < stretchState.snapshots.length; i++) {
        // i starts at 1 to skip the iframe snapshot (handled above).
        // Ancestors only need a floor that's enough to keep Canvas's
        // modal container from collapsing the iframe — not the full
        // target height (the iframe inline-height handles its own size).
        try { stretchState.snapshots[i].node.style.minHeight = minPx; } catch (e) {}
      }
      return true;
    } catch (e) {
      return false;
    }
  }

  function revertStretch() {
    if (!stretchState.applied) return;
    for (var i = 0; i < stretchState.snapshots.length; i++) {
      var snap = stretchState.snapshots[i];
      try {
        for (var prop in snap.original) {
          if (Object.prototype.hasOwnProperty.call(snap.original, prop)) {
            snap.node.style[prop] = snap.original[prop];
          }
        }
      } catch (e) {}
    }
    stretchState = { applied: false, snapshots: [] };
  }

  function isIframeVisible() {
    try {
      var iframe = findHostIframe();
      if (!iframe) return false;
      // offsetParent is null when display:none is set on the iframe or
      // any ancestor; clientHeight is 0 when the iframe is collapsed.
      return iframe.offsetParent !== null && iframe.clientHeight > 0;
    } catch (e) {
      return false;
    }
  }

  function visibilityTick() {
    if (isIframeVisible()) {
      if (!stretchState.applied) applyStretch();
    } else if (stretchState.applied) {
      revertStretch();
    }
  }

  // Initial stretch attempt: Canvas may not have laid out the iframe yet
  // when this script first runs, so retry briefly via RAF.
  var deadline = (window.performance && performance.now ? performance.now() : Date.now()) + 3000;
  function stretchLoop() {
    applyStretch();
    var now = window.performance && performance.now ? performance.now() : Date.now();
    if (now < deadline) {
      window.requestAnimationFrame ? requestAnimationFrame(stretchLoop) : setTimeout(stretchLoop, 16);
    }
  }
  stretchLoop();

  try {
    if (window.MutationObserver && window.parent && window.parent.document) {
      var observer = new MutationObserver(function () { applyStretch(); });
      observer.observe(window.parent.document.body, {
        attributes: true,
        childList: true,
        subtree: true,
        attributeFilter: ["style", "class"]
      });
      setTimeout(function () { observer.disconnect(); }, 5000);
    }
  } catch (e) {}

  window.addEventListener("load", applyStretch);
  // Revert when Canvas removes our iframe from the DOM. pagehide fires
  // reliably for iframe-as-window lifecycle ends.
  window.addEventListener("pagehide", revertStretch);
  // Poll for the display:none case (Canvas's tab switcher) where
  // pagehide doesn't fire. 250ms is imperceptible and the work is cheap.
  setInterval(visibilityTick, 250);

  // Re-sync iframe height as the form grows/shrinks. Without this the
  // iframe would stay at whatever height it had on initial load and
  // overflow content (e.g. the provider adds an order card → form
  // grows → iframe stays the same → user has to scroll inside the
  // iframe while the parent chart has unused space below).
  try {
    if (window.ResizeObserver && document.body) {
      var contentObserver = new ResizeObserver(function () {
        if (stretchState.applied) applyStretch();
      });
      contentObserver.observe(document.body);
    }
  } catch (e) {}

