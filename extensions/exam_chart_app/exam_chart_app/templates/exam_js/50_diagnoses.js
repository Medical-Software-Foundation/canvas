  // ----- Diagnoses: reuse NLM ICD-10 search from RFV -----
  var dxLastQuery = "";

  function renderDxResults(results) {
    var box = $("dx-search-results");
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
      el.addEventListener("click", function () { addDiagnosis(results[i]); });
    });
  }

  function renderDxList() {
    var list = $("dx-list");
    if (!state.ap.diagnoses.length) { list.innerHTML = ""; return; }
    list.innerHTML = state.ap.diagnoses.map(function (d, i) {
      var idx = String(i);
      var isExisting = !!d.existing_condition_id;
      var headerChip = isExisting
        ? '<span class="exam-dx-chip exam-dx-chip--existing">Existing condition</span>'
        : '<span class="exam-dx-chip exam-dx-chip--new">New diagnosis</span>';
      // New-diagnosis cards show Today's Assessment + Background (those
      // fields exist only on DiagnoseCommand). Existing-condition cards
      // skip them — Assess + Plan only.
      var newDxFields = isExisting ? "" : (
        '<div class="exam-dx-sublabel">Today\'s Assessment</div>' +
        '<textarea class="exam-textarea exam-dx-subfield" data-dx-field="today_assessment" data-dx-idx="' + idx + '" rows="2"' +
        ' placeholder="What you assessed today about this diagnosis.">' + escapeHtml(d.today_assessment || "") + '</textarea>' +

        '<div class="exam-dx-sublabel">Background</div>' +
        '<textarea class="exam-textarea exam-dx-subfield" data-dx-field="background" data-dx-idx="' + idx + '" rows="2"' +
        ' placeholder="Optional clinical background for this diagnosis.">' + escapeHtml(d.background || "") + '</textarea>'
      );
      var cardClass = isExisting ? "exam-dx-card exam-dx-card--existing" : "exam-dx-card";
      return (
        '<div class="' + cardClass + '" data-index="' + idx + '">' +
          '<div class="exam-dx-card-header">' +
            '<span class="exam-dx-code">' + escapeHtml(d.code) + '</span>' +
            '<span class="exam-dx-display">' + escapeHtml(d.display) + '</span>' +
            headerChip +
            '<button type="button" class="exam-dx-remove" data-dx-remove="' + idx + '" aria-label="Remove">×</button>' +
          '</div>' +
          '<div class="exam-dx-body">' +
            '<div class="exam-dx-subgrid">' +
              newDxFields +

              '<div class="exam-dx-sublabel">Assessment status</div>' +
              '<div class="exam-dx-subfield">' +
                '<select class="exam-dx-status" data-dx-field="assessment.status" data-dx-idx="' + idx + '">' +
                  ['', 'improved', 'stable', 'deteriorated'].map(function (s) {
                    var selected = (d.assessment && d.assessment.status === s) ? ' selected' : '';
                    var label = s ? (s[0].toUpperCase() + s.slice(1)) : '— None —';
                    return '<option value="' + escapeHtml(s) + '"' + selected + '>' + escapeHtml(label) + '</option>';
                  }).join("") +
                '</select>' +
              '</div>' +

              '<div class="exam-dx-sublabel">Assessment narrative</div>' +
              '<textarea class="exam-textarea exam-dx-subfield" data-dx-field="assessment.narrative" data-dx-idx="' + idx + '" rows="2"' +
              ' placeholder="Optional Assessment narrative for this diagnosis.">' +
              escapeHtml((d.assessment && d.assessment.narrative) || "") + '</textarea>' +

              '<div class="exam-dx-sublabel">Plan narrative</div>' +
              '<textarea class="exam-textarea exam-dx-subfield" data-dx-field="plan.narrative" data-dx-idx="' + idx + '" rows="2"' +
              ' placeholder="Treatment / follow-up plan for this diagnosis.">' +
              escapeHtml((d.plan && d.plan.narrative) || "") + '</textarea>' +
            '</div>' +
          '</div>' +
        '</div>'
      );
    }).join("");

    // Wire remove buttons
    Array.prototype.forEach.call(list.querySelectorAll("[data-dx-remove]"), function (btn) {
      btn.addEventListener("click", function () {
        var i = parseInt(btn.getAttribute("data-dx-remove"), 10);
        if (!isNaN(i)) {
          state.ap.diagnoses.splice(i, 1);
          renderDxList();
        }
      });
    });

    // Wire per-field inputs (text / select). data-dx-field can be a
    // dotted path like "assessment.status".
    function attachFieldHandler(el) {
      var i = parseInt(el.getAttribute("data-dx-idx"), 10);
      var path = (el.getAttribute("data-dx-field") || "").split(".");
      var evt = el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(evt, function () {
        if (isNaN(i) || !state.ap.diagnoses[i]) return;
        var node = state.ap.diagnoses[i];
        for (var p = 0; p < path.length - 1; p++) {
          if (!node[path[p]]) node[path[p]] = {};
          node = node[path[p]];
        }
        node[path[path.length - 1]] = el.value;
      });
    }
    Array.prototype.forEach.call(list.querySelectorAll("[data-dx-field]"), attachFieldHandler);
    _scheduleSaveDraft();
  }

  function _emptyDxFields(extra) {
    var base = {
      existing_condition_id: "",
      today_assessment: "",
      background: "",
      assessment: { status: "", narrative: "" },
      plan: { narrative: "" },
    };
    if (extra) for (var k in extra) base[k] = extra[k];
    return base;
  }

  function _normCode(code) {
    // Canvas stores ICD-10 condition codes without dots (e.g. "K219"),
    // while NLM Clinical Tables returns them with dots ("K21.9"). Strip
    // dots for matching.
    return String(code || "").replace(/\./g, "");
  }

  function addDiagnosis(r) {
    var dup = state.ap.diagnoses.some(function (d) { return d.code === r.code; });
    if (!dup) {
      // If this ICD-10 already exists as an active patient Condition,
      // wire it through as an existing-condition entry so the backend
      // emits AssessCommand(condition_id=...) instead of a new
      // DiagnoseCommand.
      var existing = state.patient_conditions_by_code[_normCode(r.code)];
      var fields = { code: r.code, display: r.display };
      if (existing) {
        fields.existing_condition_id = existing.id;
        // Use the patient's existing display text when available (it may
        // be more specific than the NLM search hit, and matches what
        // the chart shows in the Conditions list).
        if (existing.display) fields.display = existing.display;
      }
      state.ap.diagnoses.push(_emptyDxFields(fields));
      renderDxList();
    }
    $("dx-search-input").value = "";
    $("dx-search-results").hidden = true;
    dxLastQuery = "";
  }

  function loadPatientConditions() {
    if (!CONFIG.patient_id) {
      console.warn("[ExamChartingApp] CONFIG.patient_id is empty; skipping patient-conditions fetch");
      return;
    }
    var url = CONFIG.api_base + "/exam/patient-conditions?patient_id=" +
      encodeURIComponent(CONFIG.patient_id);
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.ok ? r.json() : { conditions: [] };
      })
      .then(function (data) {
        var byCode = {};
        (data.conditions || []).forEach(function (c) {
          if (c.code) byCode[_normCode(c.code)] = c;
        });
        state.patient_conditions_by_code = byCode;
        // Reconcile any diagnoses already in state (e.g. an auto-added
        // RFV that arrived before this fetch returned).
        state.ap.diagnoses.forEach(function (d) {
          if (!d.existing_condition_id) {
            var existing = byCode[_normCode(d.code)];
            if (existing) {
              d.existing_condition_id = existing.id;
              if (existing.display) d.display = existing.display;
            }
          }
        });
        if (state.ap.diagnoses.length) renderDxList();
      })
      .catch(function (err) {
        console.warn("[ExamChartingApp] patient-conditions fetch failed:", err && err.message);
      });
  }
  loadPatientConditions();

  function performDxSearch(q) {
    if (q === dxLastQuery) return;
    dxLastQuery = q;
    if (!q || q.length < 2) { renderDxResults([]); return; }
    var url = ICD10_SEARCH_URL
      + "?sf=code,name&maxList=12&terms=" + encodeURIComponent(q);
    fetch(url)
      .then(function (r) { return r.ok ? r.json() : [0, [], null, []]; })
      .then(function (data) {
        var pairs = (data && data[3]) || [];
        renderDxResults(pairs.map(function (pair) {
          return { code: (pair && pair[0]) || "", display: (pair && pair[1]) || "" };
        }).filter(function (it) { return it.code && it.display; }));
      })
      .catch(function () { renderDxResults([]); });
  }

  var debouncedDxSearch = makeDebouncer(function (q) { performDxSearch(q); }, 200);
  $("dx-search-input").addEventListener("input", function (e) {
    debouncedDxSearch(e.target.value.trim());
  });

