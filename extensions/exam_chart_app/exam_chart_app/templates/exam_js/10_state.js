  // ----- Checkpoint 2: section state + behavior -----
  var CONFIG = (function () {
    var el = document.getElementById("exam-config");
    if (!el) return { note_uuid: "", api_base: "/plugin-io/api/exam_chart_app" };
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (e) {
      console.warn("[ExamChartingApp] could not parse exam-config:", e);
      return { note_uuid: "", api_base: "/plugin-io/api/exam_chart_app" };
    }
  })();

  // Default ICD-10-CM search endpoint: the NLM Clinical Tables public
  // service (no auth, cross-origin GET). Production deployments behind
  // strict egress / CSP can override via the `icd10-search-url` plugin
  // secret, which flows through the server-side `exam_config` payload.
  var ICD10_SEARCH_URL = CONFIG.icd10_search_url ||
    "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search";

  var state = {
    rfv: { coding: null, comment: "" },
    hpi: { narrative: "", user_edited: false },
    // For ROS/PE: responses is {question_id: [option_value, ...]} (list, multi-select)
    ros: { questionnaire_id: "", responses: {}, narrative: "" },
    pe:  { questionnaire_id: "", responses: {}, narrative: "" },
    ap: {
      // [{code, display, existing_condition_id, today_assessment,
      //   background, assessment: {status, narrative}, plan: {narrative}},
      //  ...]  existing_condition_id is set when the picked code matches
      //  a patient.conditions row → backend switches to AssessCommand.
      diagnoses: [],
      // [{type: "lab" | "imaging" | "prescribe" | "refer", ...type-specific fields}]
      orders: [],
    },
    // Lookup: {ICD-10 code: existing-condition row} — populated at tab
    // load via /exam/patient-conditions. addDiagnosis() consults this to
    // mark entries that should emit Assess instead of Diagnose.
    patient_conditions_by_code: {},
    // Logged-in staff (id + first/last name). Populated at tab load via
    // /exam/me. Used to default ordering_provider_key / prescriber_id on
    // freshly-added order cards.
    me: { id: "", first_name: "", last_name: "" },
    // LabPartner rows pre-loaded once at tab load; powers the partner
    // <select> on Lab order cards. Tests are searched on-demand once
    // the partner is chosen.
    lab_partners: [],
    // ServiceProvider rows pre-loaded once at tab load; powers the
    // specialist <select> on Refer order cards.
    service_providers: [],
    // Active Staff rows pre-loaded once at tab load; powers the
    // Ordering provider <select> on Imaging cards.
    staff: [],
    // Bundled imaging-codes catalog (CPT-coded studies); pre-loaded once
    // at tab load to power the Image code <select> on Imaging cards.
    imaging_codes: [],
  };

  function $(id) { return document.getElementById(id); }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c];
    });
  }

  // Per-instance debouncer. Each call closes over its own timer rather
  // than sharing module-level state, so multiple debounced functions
  // can coexist in this bundle without timer-aliasing bugs.
  function makeDebouncer(fn, ms) {
    var timer = null;
    return function () {
      var args = arguments;
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, ms);
    };
  }

  // Re-edit-on-reopen flag. Set when the saved state is hydrated with
  // finalized=true, or when Finalize completes successfully. Disables
  // the Finalize button and surfaces the read-only banner. The saved
  // state is still loaded so the form shows what the provider entered.
  var _finalized = false;

  function _missingRequired() {
    // Per-card required-field gate. Mirrors the backend's _missing_required
    // checks so the provider sees the problem before clicking Finalize
    // and the button stays disabled until everything resolves.
    var missing = [];
    (state.ap.orders || []).forEach(function (o, i) {
      var label = "#" + (i + 1);
      if (o.type === "lab") {
        if (!(o.lab_partner || "").trim()) missing.push("Lab " + label + ": pick a lab partner");
        if (!Array.isArray(o.tests) || !o.tests.length) missing.push("Lab " + label + ": add at least one test");
        if (!(o.ordering_provider_key || "").trim()) missing.push("Lab " + label + ": needs an ordering provider");
        if (!Array.isArray(o.diagnosis_codes) || !o.diagnosis_codes.length) missing.push("Lab " + label + ": needs a diagnosis code");
      }
      if (o.type === "imaging") {
        // image_code intentionally not gated — chart-side limitation
        // means the provider re-picks it on the staged command anyway.
        if (!(o.ordering_provider_key || "").trim()) missing.push("Imaging " + label + ": needs an ordering provider");
        if (!Array.isArray(o.diagnosis_codes) || !o.diagnosis_codes.length) missing.push("Imaging " + label + ": needs a diagnosis code");
      }
      if (o.type === "prescribe") {
        if (!(o.fdb_code || "").trim()) missing.push("Rx " + label + ": pick a medication");
        if (!(o.sig || "").trim()) missing.push("Rx " + label + ": needs a sig");
        if (!(o.prescriber_id || "").trim()) missing.push("Rx " + label + ": needs a prescriber");
        if (!Array.isArray(o.icd10_codes) || !o.icd10_codes.length) missing.push("Rx " + label + ": needs an ICD-10 code");
        // Numeric fields: blank when "" / null; 0 is valid (esp. refills).
        if (o.quantity_to_dispense === "" || o.quantity_to_dispense === null || o.quantity_to_dispense === undefined) {
          missing.push("Rx " + label + ": needs quantity to dispense");
        }
        if (o.days_supply === "" || o.days_supply === null || o.days_supply === undefined) {
          missing.push("Rx " + label + ": needs days supply");
        }
        if (o.refills === "" || o.refills === null || o.refills === undefined) {
          missing.push("Rx " + label + ": needs refills (0 is OK)");
        }
      }
      if (o.type === "refer") {
        var sp = o.service_provider || {};
        if (!(sp.first_name || sp.last_name)) missing.push("Refer " + label + ": pick a specialist");
        if (!(o.notes_to_specialist || "").trim()) missing.push("Refer " + label + ": needs notes to specialist");
        if (!Array.isArray(o.diagnosis_codes) || !o.diagnosis_codes.length) missing.push("Refer " + label + ": needs a diagnosis code");
      }
      if (o.type === "goal" && !(o.goal_statement || "").trim()) {
        missing.push("Goal " + label + ": needs a goal statement");
      }
    });
    return missing;
  }

  function updateFinalizeButton() {
    var btn = $("finalize-btn");
    var msg = $("finalize-status");
    if (_finalized) {
      btn.disabled = true;
      if (!msg.classList.contains("exam-finalize-status--committed")) {
        msg.textContent = "Already finalized — edits go through the chart's commands.";
        msg.className = "exam-finalize-status";
      }
      return;
    }
    var hasRfv = !!state.rfv.coding || state.rfv.comment.trim().length > 0;
    if (!hasRfv) {
      btn.disabled = true;
      msg.textContent = "Pick or type a Reason for Visit to enable Finalize.";
      msg.className = "exam-finalize-status";
      return;
    }
    var missing = _missingRequired();
    if (missing.length) {
      btn.disabled = true;
      msg.textContent = missing.join(" · ");
      msg.className = "exam-finalize-status exam-finalize-status--error";
      return;
    }
    btn.disabled = false;
    msg.textContent = "Ready to finalize.";
    msg.className = "exam-finalize-status";
  }

