  // ----- Finalize -----
  $("finalize-btn").addEventListener("click", function () {
    var btn = $("finalize-btn");
    var msg = $("finalize-status");
    btn.disabled = true;
    msg.textContent = "Finalizing…";
    msg.className = "exam-finalize-status exam-finalize-status--committing";

    // Cancel any debounced save still pending from recent keystrokes.
    // Otherwise the save POST races finalize's state transition and
    // the backend 409-guard rejects it post-finalize, surfacing a
    // red save-error banner alongside the legitimate yellow finalized
    // banner. _scheduleSaveDraft also gates on `_finalized` once the
    // transition completes, but cancelling here closes the race
    // window between click + 200-response.
    _cancelPendingSave();

    var payload = {
      note_uuid: CONFIG.note_uuid,
      rfv: state.rfv,
      hpi: { narrative: state.hpi.narrative },
      ros: {
        questionnaire_id: state.ros.questionnaire_id,
        responses: state.ros.responses,
        narrative: state.ros.narrative,
      },
      pe: {
        questionnaire_id: state.pe.questionnaire_id,
        responses: state.pe.responses,
        narrative: state.pe.narrative,
      },
      ap: {
        diagnoses: state.ap.diagnoses,
        orders: state.ap.orders,
      },
    };

    fetch(CONFIG.api_base + "/exam/finalize", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        // Parse via r.text() + try-catch rather than r.json() directly:
        // a non-JSON error body (e.g. an empty-body 500 from an
        // un-caught upstream exception) would otherwise reject the
        // promise, route control to .catch, and surface as a misleading
        // "Network error: Unexpected token..." message. Falling back
        // to a synthesized error body keeps the response-status path
        // the same regardless of whether the server sent JSON.
        return r.text().then(function (text) {
          var body;
          try {
            body = text ? JSON.parse(text) : {};
          } catch (e) {
            body = { errors: [{ message: "HTTP " + r.status + ": " + (text || "no response body") }] };
          }
          return { ok: r.ok, body: body };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          msg.textContent = (res.body.errors && res.body.errors[0]
            ? res.body.errors[0].message : "Finalize failed.");
          msg.className = "exam-finalize-status exam-finalize-status--error";
          btn.disabled = false;
          return;
        }
        var ef = res.body.effects || {};
        var parts = [];
        if (ef.rfv) parts.push("RFV");
        if (ef.hpi) parts.push("HPI");
        if (ef.ros) parts.push("ROS");
        if (ef.pe)  parts.push("PE");
        if (ef.diagnose_count) parts.push("Diagnose×" + ef.diagnose_count);
        if (ef.assess_count)   parts.push("Assess×" + ef.assess_count);
        if (ef.plan_count)     parts.push("Plan×" + ef.plan_count);
        if (ef.lab_count)      parts.push("Lab×" + ef.lab_count);
        if (ef.imaging_count)  parts.push("Imaging×" + ef.imaging_count);
        if (ef.prescribe_count) parts.push("Rx×" + ef.prescribe_count);
        if (ef.refer_count)    parts.push("Refer×" + ef.refer_count);
        if (ef.goal_count)        parts.push("Goal×" + ef.goal_count);
        if (ef.plan_item_count)   parts.push("PlanItem×" + ef.plan_item_count);
        if (ef.follow_up_count)   parts.push("FollowUp×" + ef.follow_up_count);
        msg.textContent = "Finalized. " + parts.join(" + ") + " emitted.";
        msg.className = "exam-finalize-status exam-finalize-status--committed";
        // Backend has marked the draft finalized; mirror that locally
        // so any later in-tab interactions (or the very next save tick)
        // see the same flag the next reload will fetch.
        _finalized = true;
        _applyFinalizedUI(true);
      })
      .catch(function (err) {
        msg.textContent = "Network error: " + (err && err.message);
        msg.className = "exam-finalize-status exam-finalize-status--error";
        btn.disabled = false;
      });
  });

  updateFinalizeButton();
  _hydrateFromSavedState();
})();
