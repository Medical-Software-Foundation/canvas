  // ----- RFV search -----
  var debounceTimer = null;
  var lastQuery = "";

  function debounce(fn, ms) {
    return function () {
      var args = arguments;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  function placeDropdown(box) {
    // Flip the absolutely-positioned dropdown above its input when there
    // isn't enough room below in the scrollable container. Without this,
    // dropdowns opened near the bottom of the form get clipped — the
    // exam-container has overflow-y:auto, and the embedded iframe has a
    // hard bottom edge that hides anything past it.
    var input = box.previousElementSibling;
    var wrap = box.parentElement;
    if (!input || !wrap) return;
    var inputRect = input.getBoundingClientRect();
    var maxHeight = 220; // matches .exam-search-results max-height
    var viewportBottom = (window.innerHeight || document.documentElement.clientHeight);
    var roomBelow = viewportBottom - inputRect.bottom;
    if (roomBelow < maxHeight && inputRect.top > maxHeight) {
      // Flip above.
      box.style.top = "auto";
      box.style.bottom = "100%";
      box.style.borderTop = "1px solid #ccc";
      box.style.borderBottom = "none";
      box.style.borderRadius = "4px 4px 0 0";
      box.style.boxShadow = "0 -2px 6px rgba(0,0,0,0.08)";
    } else {
      // Default below.
      box.style.top = "";
      box.style.bottom = "";
      box.style.borderTop = "";
      box.style.borderBottom = "";
      box.style.borderRadius = "";
      box.style.boxShadow = "";
    }
  }

  function renderResults(results) {
    var box = $("rfv-search-results");
    if (!results || !results.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.innerHTML = results.map(function (r, i) {
      return (
        '<button type="button" class="exam-search-result" data-index="' + i + '">' +
        '<span class="exam-search-result-code">' + escapeHtml(r.code) + '</span>' +
        '<span class="exam-search-result-name">' + escapeHtml(r.display) + '</span>' +
        '</button>'
      );
    }).join("");
    box.hidden = false;
    placeDropdown(box);
    Array.prototype.forEach.call(box.querySelectorAll(".exam-search-result"), function (el, i) {
      el.addEventListener("click", function () { pickResult(results[i]); });
    });
  }

  function _showRfvPickedChip(coding) {
    // Render the green "picked" chip from a coding object. Extracted so
    // _hydrateFromSavedState can repaint the chip on refresh without
    // re-running the side effects of pickResult (template fetch,
    // addDiagnosis) — those side-effects already happened the first time
    // and their results are in the saved state.
    if (!coding) return;
    $("rfv-search-input").value = "";
    $("rfv-search-results").hidden = true;
    var picked = $("rfv-search-picked");
    picked.innerHTML =
      '<span class="exam-search-result-code">' + escapeHtml(coding.code || "") + '</span>' +
      '<span class="exam-search-result-name">' + escapeHtml(coding.display || "") + '</span>' +
      '<button type="button" class="exam-search-picked-clear" id="rfv-clear" aria-label="Clear">×</button>';
    picked.hidden = false;
    $("rfv-clear").addEventListener("click", clearPick);
  }

  function pickResult(r) {
    state.rfv.coding = { code: r.code, system: r.system, display: r.display };
    _showRfvPickedChip(state.rfv.coding);
    fetchTemplateAndPrefill(r.code);
    // Pull the RFV down as the first diagnosis in the A&P section so the
    // provider doesn't have to re-pick it there. Idempotent — duplicates
    // by code are skipped by addDiagnosis.
    addDiagnosis({ code: r.code, display: r.display });
    updateFinalizeButton();
  }

  function clearPick() {
    state.rfv.coding = null;
    $("rfv-search-picked").hidden = true;
    $("rfv-search-picked").innerHTML = "";
    updateFinalizeButton();
  }

  function fetchTemplateAndPrefill(code) {
    var url = CONFIG.api_base + "/exam/templates?code=" + encodeURIComponent(code || "");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { hpi: "" }; })
      .then(function (data) {
        if (!data || !data.hpi) return;
        var ta = $("hpi-narrative");
        if (!state.hpi.user_edited) {
          ta.value = data.hpi;
          state.hpi.narrative = data.hpi;
          $("status-hpi").textContent = "Prefilled from template.";
        } else {
          $("status-hpi").textContent = "Template available — click to apply.";
        }
      })
      .catch(function () { /* template fetch is best-effort */ });
  }

  var ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm";

  function performSearch(q) {
    if (q === lastQuery) return;
    lastQuery = q;
    if (!q || q.length < 2) {
      renderResults([]);
      return;
    }
    // ICD-10-CM search endpoint — defaults to NLM Clinical Tables (no
    // auth, cross-origin GET). Response shape: [count, [codes,...],
    // extras_or_null, [[code, name], ...]]. The intake plugin uses the
    // same endpoint. Override via the `icd10-search-url` plugin secret.
    var url = ICD10_SEARCH_URL
      + "?sf=code,name&maxList=12&terms=" + encodeURIComponent(q);
    fetch(url)
      .then(function (r) { return r.ok ? r.json() : [0, [], null, []]; })
      .then(function (data) {
        var pairs = (data && data[3]) || [];
        var items = pairs.map(function (pair) {
          return {
            code: (pair && pair[0]) || "",
            system: ICD10_SYSTEM,
            display: (pair && pair[1]) || (pair && pair[0]) || "",
          };
        }).filter(function (it) { return it.code && it.display; });
        renderResults(items);
      })
      .catch(function (err) {
        console.warn("[ExamChartingApp] ICD-10 search failed:", err && err.message);
        renderResults([]);
      });
  }

  var debouncedSearch = debounce(function (q) { performSearch(q); }, 200);

  // ----- Wire up inputs -----
  $("rfv-search-input").addEventListener("input", function (e) {
    debouncedSearch(e.target.value.trim());
  });
  $("rfv-comment").addEventListener("input", function (e) {
    state.rfv.comment = e.target.value;
    updateFinalizeButton();
  });
  $("hpi-narrative").addEventListener("input", function (e) {
    state.hpi.narrative = e.target.value;
    state.hpi.user_edited = true;
  });

