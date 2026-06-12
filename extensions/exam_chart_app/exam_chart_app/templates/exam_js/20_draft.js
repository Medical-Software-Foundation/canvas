  // ----- Draft state persistence (Checkpoint 8) -----
  // While the provider edits the form we POST the full state blob to
  // /exam/state debounced 800ms. On tab open we GET the same blob and
  // hydrate `state` so re-opening a note shows what they had typed.
  var _saveTimer = null;
  var _hydrating = true;  // suppress saves until the initial fetch lands

  function _buildSavePayload() {
    // Strip volatile fields that are reloaded from the server each
    // session (me, lab_partners, patient_conditions_by_code). Keep
    // the rest of the form state.
    return {
      rfv: state.rfv,
      hpi: state.hpi,
      ros: state.ros,
      pe: state.pe,
      ap: state.ap,
    };
  }

  function _showSaveErrorBanner(message) {
    var banner = $("save-error-banner");
    if (!banner) return;
    banner.textContent = message;
    banner.hidden = false;
  }

  function _clearSaveErrorBanner() {
    var banner = $("save-error-banner");
    if (!banner) return;
    banner.hidden = true;
    banner.textContent = "";
  }

  function _scheduleSaveDraft() {
    if (_hydrating || !CONFIG.note_uuid) return;
    if (_saveTimer) clearTimeout(_saveTimer);
    _saveTimer = setTimeout(function () {
      _saveTimer = null;
      fetch(CONFIG.api_base + "/exam/state/save", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          note_uuid: CONFIG.note_uuid,
          state: _buildSavePayload(),
        }),
      }).then(function (r) {
        // fetch() resolves on any HTTP status — 4xx/5xx don't reject.
        // Check r.ok explicitly so the backend's 413 (DraftTooLargeError),
        // 400 (malformed body / bad note_uuid), and 500 (upstream failure)
        // paths actually reach the provider instead of being silently
        // dropped, which would let them keep editing while saves are
        // being rejected.
        if (r.ok) {
          _clearSaveErrorBanner();
          return;
        }
        var fallback = "Could not save draft (HTTP " + r.status +
          "). Please retry.";
        return r.json().then(
          function (body) {
            var msg = (body && body.errors && body.errors[0] &&
              body.errors[0].message) || fallback;
            _showSaveErrorBanner(msg);
            console.warn(
              "[ExamChartingApp] draft save HTTP " + r.status + ": " + msg
            );
          },
          function () {
            // Non-JSON error body — surface the status code at least.
            _showSaveErrorBanner(fallback);
            console.warn(
              "[ExamChartingApp] draft save HTTP " + r.status + " (non-JSON body)"
            );
          }
        );
      }).catch(function (err) {
        // Only triggers on network failures (DNS, offline, CORS, abort).
        // 4xx/5xx flow through the .then branch above. Still surface so
        // the provider knows their edits aren't reaching the server.
        _showSaveErrorBanner(
          "Could not save draft (network error). Please retry."
        );
        console.warn("[ExamChartingApp] draft save failed:", err);
      });
    }, 800);
  }

  var BANNER_TEXT = {
    finalized:
      "This exam has been finalized. The values below are a record of what " +
      "you entered — edit the commands in the note to make further changes.",
    orphan_commands:
      "This note has commands attached, but the plugin draft was cleared " +
      "(typically from a delete/undelete cycle). Further edits go through " +
      "the chart's command UI.",
  };

  function _showBanner(kind, scrollIntoView) {
    var banner = $("finalized-banner");
    if (!banner) return;
    banner.textContent = BANNER_TEXT[kind] || "";
    // Orphan-commands is a louder warning (chart shows data the form
    // can't represent); finalized is informational. Different palette.
    banner.classList.toggle("exam-finalized-banner--alert", kind === "orphan_commands");
    banner.hidden = false;
    if (scrollIntoView) {
      try { banner.scrollIntoView({ behavior: "smooth", block: "start" }); }
      catch (e) { banner.scrollIntoView(); }
    }
  }

  function _applyFinalizedUI(scrollBannerIntoView) {
    _showBanner("finalized", scrollBannerIntoView);
    updateFinalizeButton();
    _lockFormForFinalized();
  }

  function _lockFormForFinalized() {
    // After Finalize, the chart's commands are the source of truth.
    // The form must stop accepting edits so the provider isn't misled
    // into thinking they're amending the finalized exam (which they
    // can't — those edits would only land in the plugin's draft state
    // and never reach the chart).
    //
    // Disable every interactive control inside .exam-container and add
    // a class for visual feedback. The banner stays clickable; the
    // Finalize button is already disabled by updateFinalizeButton.
    var container = document.querySelector(".exam-container");
    if (!container) return;
    container.classList.add("exam-container--finalized");
    var selectors = "input, textarea, select, button";
    Array.prototype.forEach.call(
      container.querySelectorAll(selectors),
      function (el) {
        // Skip the banner's own controls if any (defensive — the
        // finalized banner has no inputs today, but future banner
        // content should remain interactive).
        if (el.closest("#finalized-banner")) return;
        el.disabled = true;
      }
    );
  }

  function _rehydrateQuestionnaireSection(section, savedSection) {
    // Re-paint a ROS / PE section from the saved blob.
    //
    // IMPORTANT: capture savedResponses/savedNarrative into local refs
    // BEFORE calling loadQuestionnaireDetail. That function ultimately
    // calls renderQuestionnaire, which sets `cfg.state.responses = {}`
    // and seeds TXT defaults — and since savedSection IS state.<section>
    // (same object reference after the shallow-merge in
    // _hydrateFromSavedState), reading savedSection.responses AFTER the
    // render would see the wiped/defaulted dict, not the saved one.
    // Local-var capture pins the original dict so we can re-stamp it.
    if (!savedSection || !savedSection.questionnaire_id) {
      var narrativeEl = $(section + "-narrative");
      if (narrativeEl && savedSection && typeof savedSection.narrative === "string") {
        narrativeEl.value = savedSection.narrative;
      }
      return Promise.resolve();
    }
    var savedQuestionnaireId = savedSection.questionnaire_id;
    var savedResponses = savedSection.responses;
    var savedNarrative = savedSection.narrative;
    return _questionnaireListPromise.then(function () {
      var chooser = $(section + "-chooser");
      if (chooser) chooser.value = savedQuestionnaireId;
      return loadQuestionnaireDetail(section, savedQuestionnaireId);
    }).then(function () {
      _applyResponsesToRenderedSection(section, savedResponses, savedNarrative);
    });
  }

  function _hydrateFromSavedState() {
    if (!CONFIG.note_uuid) {
      _hydrating = false;
      return;
    }
    var url = CONFIG.api_base + "/exam/state?note_uuid=" +
      encodeURIComponent(CONFIG.note_uuid);
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.ok ? r.json() : {
          state: {}, finalized: false, has_chart_commands: false,
        };
      })
      .then(function (data) {
        var saved = (data && data.state) || {};
        var draftIsEmpty = !saved || !Object.keys(saved).length;
        if (saved.rfv) state.rfv = saved.rfv;
        if (saved.hpi) state.hpi = saved.hpi;
        if (saved.ros) state.ros = saved.ros;
        if (saved.pe)  state.pe = saved.pe;
        if (saved.ap)  state.ap = saved.ap;
        // Saved orders may be missing ordering_provider/prescriber if
        // they were created before /exam/me resolved. Re-apply the
        // backfill from state.me (which is populated by an independent
        // fetch — may have landed already, or may still be in flight;
        // in the latter case the /exam/me .then will re-run this fn).
        backfillOrderProviders();
        if (data && data.finalized) {
          _finalized = true;
          _applyFinalizedUI();
        } else if (draftIsEmpty && data && data.has_chart_commands) {
          // No draft was ever saved (or it was wiped by note-lifecycle
          // cleanup), but the chart already has commands attached. The
          // form can't reconstruct them — warn the provider so they
          // know to edit via the chart's command UI.
          _showBanner("orphan_commands", false);
        }
        // Dx + Orders cards re-render from state.
        try { renderDxList(); } catch (e) { /* not yet defined */ }
        try { renderOrdersList(); } catch (e) { /* same */ }
        // HPI + RFV-comment textareas.
        var hpiInput = $("hpi-narrative");
        if (hpiInput && state.hpi && state.hpi.narrative) {
          hpiInput.value = state.hpi.narrative;
        }
        var rfvInput = $("rfv-comment");
        if (rfvInput && state.rfv && state.rfv.comment) {
          rfvInput.value = state.rfv.comment;
        }
        // RFV picked chip — repaint if a coding was saved.
        if (state.rfv && state.rfv.coding) {
          _showRfvPickedChip(state.rfv.coding);
        }
        // ROS / PE — chain on the list-populate promise so the chooser
        // <option> exists before we set .value, then fetch the questions
        // and stamp the saved responses back onto the rendered toggles.
        return Promise.all([
          _rehydrateQuestionnaireSection("ros", saved.ros),
          _rehydrateQuestionnaireSection("pe", saved.pe),
        ]);
      })
      .catch(function (err) {
        console.warn("[ExamChartingApp] hydrate failed:", err);
      })
      .finally(function () {
        _hydrating = false;
        updateFinalizeButton();
      });
  }

  // Global edit listeners — most form mutations come through `input` /
  // `change` events on a control. The rendered card lists already wire
  // their own handlers that mutate state; this just kicks the debounce
  // afterwards. Click-only mutations (pick-result, dx pill toggle, etc.)
  // call _scheduleSaveDraft() explicitly via the render-list hooks.
  function _afterEdit() {
    _scheduleSaveDraft();
    updateFinalizeButton();
  }
  document.addEventListener("input", _afterEdit);
  document.addEventListener("change", _afterEdit);

