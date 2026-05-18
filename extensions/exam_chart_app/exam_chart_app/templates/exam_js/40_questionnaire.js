  // ----- Questionnaire chooser + per-system rendering for ROS / PE -----

  function _qSectionConfig(section) {
    if (section === "ros") {
      return {
        chooser: $("ros-chooser"), list: $("ros-questions"),
        narrativeEl: $("ros-narrative"), state: state.ros,
      };
    }
    return {
      chooser: $("pe-chooser"), list: $("pe-questions"),
      narrativeEl: $("pe-narrative"), state: state.pe,
    };
  }

  function renderQuestionnaire(section, detail) {
    var cfg = _qSectionConfig(section);
    cfg.state.responses = {};
    if (!detail || !detail.questions || !detail.questions.length) {
      cfg.list.hidden = true;
      cfg.list.innerHTML = "";
      return;
    }
    cfg.list.innerHTML = detail.questions.map(function (q) {
      var qid = String(q.id);
      var label = '<div class="exam-q-system-label">' + escapeHtml(q.label || "") + '</div>';
      if (q.type === "MULT") {
        // Multi-select pills (one per response option / clinical finding).
        var optionsHtml = (q.options || []).map(function (o) {
          return (
            '<button type="button" class="exam-q-option" ' +
            'data-q="' + escapeHtml(qid) + '" ' +
            'data-value="' + escapeHtml(String(o.value || o.code || "")) + '">' +
            escapeHtml(o.name || o.value || "") +
            '</button>'
          );
        }).join("");
        return (
          '<div class="exam-q-system" data-question-id="' + escapeHtml(qid) + '" data-type="MULT">' +
          label +
          '<div class="exam-q-options">' + optionsHtml + '</div>' +
          '</div>'
        );
      }
      if (q.type === "TXT" || q.type === "SING") {
        // Free-text or single-select rendered as a textarea. For
        // TEXT-type questions, the option's value (if any) is the default
        // narrative — prefill the textarea with it.
        var defaultText = "";
        if (q.options && q.options.length) {
          defaultText = q.options[0].value || q.options[0].name || "";
        }
        return (
          '<div class="exam-q-system" data-question-id="' + escapeHtml(qid) + '" data-type="' + escapeHtml(q.type) + '">' +
          label +
          '<textarea class="exam-q-text" data-q="' + escapeHtml(qid) + '" rows="2">' +
          escapeHtml(defaultText) +
          '</textarea>' +
          '</div>'
        );
      }
      // Unknown question type — render a read-only label.
      return (
        '<div class="exam-q-system" data-question-id="' + escapeHtml(qid) + '">' +
        label +
        '<div class="exam-q-options"><em>Unsupported question type: ' +
        escapeHtml(q.type || "") + '</em></div>' +
        '</div>'
      );
    }).join("");
    cfg.list.hidden = false;

    Array.prototype.forEach.call(
      cfg.list.querySelectorAll(".exam-q-option"),
      function (btn) {
        btn.addEventListener("click", function () {
          var qid = btn.getAttribute("data-q");
          var value = btn.getAttribute("data-value");
          var current = cfg.state.responses[qid] || [];
          var idx = current.indexOf(value);
          if (idx === -1) {
            current.push(value);
            btn.classList.add("is-selected");
          } else {
            current.splice(idx, 1);
            btn.classList.remove("is-selected");
          }
          cfg.state.responses[qid] = current;
        });
      }
    );

    // Seed text-question state with the prefilled default, then capture
    // user edits.
    Array.prototype.forEach.call(
      cfg.list.querySelectorAll(".exam-q-text"),
      function (ta) {
        var qid = ta.getAttribute("data-q");
        if (ta.value && ta.value.trim()) {
          cfg.state.responses[qid] = [ta.value];
        }
        ta.addEventListener("input", function () {
          if (ta.value && ta.value.trim()) {
            cfg.state.responses[qid] = [ta.value];
          } else {
            delete cfg.state.responses[qid];
          }
        });
      }
    );
  }

  function loadQuestionnaireDetail(section, questionnaireId) {
    var cfg = _qSectionConfig(section);
    cfg.state.questionnaire_id = questionnaireId || "";
    if (!questionnaireId) {
      cfg.state.responses = {};
      cfg.list.hidden = true;
      cfg.list.innerHTML = "";
      return Promise.resolve();
    }
    var url = CONFIG.api_base + "/exam/questionnaires/detail?id=" + encodeURIComponent(questionnaireId);
    return fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (detail) {
        if (!detail) return;
        renderQuestionnaire(section, detail);
      })
      .catch(function (err) {
        console.warn("[ExamChartingApp] questionnaire detail fetch failed:", err && err.message);
      });
  }

  function _applyResponsesToRenderedSection(section, savedResponses, savedNarrative) {
    // Paint saved MULT pill selections and TXT textarea values back into
    // the rendered question list, then re-stamp cfg.state.responses to
    // match (renderQuestionnaire reset it on render). Also restore the
    // section narrative textarea.
    var cfg = _qSectionConfig(section);
    if (!savedResponses) savedResponses = {};
    cfg.state.responses = {};
    Object.keys(savedResponses).forEach(function (qid) {
      var values = savedResponses[qid] || [];
      if (!Array.isArray(values)) values = [values];
      cfg.state.responses[qid] = values.slice();
      values.forEach(function (val) {
        var strVal = String(val);
        // MULT: toggle the matching pill.
        var btn = cfg.list.querySelector(
          '.exam-q-option[data-q="' + qid + '"][data-value="' + strVal + '"]'
        );
        if (btn) btn.classList.add("is-selected");
      });
      // TXT: set the textarea value (single-value entries).
      var ta = cfg.list.querySelector('.exam-q-text[data-q="' + qid + '"]');
      if (ta && values.length) ta.value = String(values[0]);
    });
    if (typeof savedNarrative === "string") {
      cfg.state.narrative = savedNarrative;
      var narrativeEl = $(section + "-narrative");
      if (narrativeEl) narrativeEl.value = savedNarrative;
    }
  }

  function populateChooser(section, candidates) {
    var cfg = _qSectionConfig(section);
    cfg.chooser.innerHTML = '<option value="">— None (skip ' + section.toUpperCase() + ') —</option>' +
      candidates.map(function (c) {
        return '<option value="' + escapeHtml(c.id) + '">' + escapeHtml(c.name) + '</option>';
      }).join("");
  }

  function loadQuestionnaireList() {
    return fetch(CONFIG.api_base + "/exam/questionnaires/list", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { ros: [], pe: [] }; })
      .then(function (data) {
        populateChooser("ros", data.ros || []);
        populateChooser("pe", data.pe || []);
      })
      .catch(function (err) {
        console.warn("[ExamChartingApp] questionnaire list fetch failed:", err && err.message);
      });
  }

  $("ros-chooser").addEventListener("change", function (e) {
    loadQuestionnaireDetail("ros", e.target.value);
  });
  $("pe-chooser").addEventListener("change", function (e) {
    loadQuestionnaireDetail("pe", e.target.value);
  });
  $("ros-narrative").addEventListener("input", function (e) {
    state.ros.narrative = e.target.value;
  });
  $("pe-narrative").addEventListener("input", function (e) {
    state.pe.narrative = e.target.value;
  });
  // Capture the chooser-populate promise so _hydrateFromSavedState can
  // wait for it before setting the chooser's selected option and firing
  // loadQuestionnaireDetail with the saved questionnaire_id.
  var _questionnaireListPromise = loadQuestionnaireList();

