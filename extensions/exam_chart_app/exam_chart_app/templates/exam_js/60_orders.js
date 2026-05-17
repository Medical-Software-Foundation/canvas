  // ----- Orders -----

  function _emptyOrder(type) {
    var dxCodes = state.ap.diagnoses.map(function (d) { return d.code; });
    var meId = state.me && state.me.id ? state.me.id : "";
    var meName = state.me ? ((state.me.first_name || "") + " " + (state.me.last_name || "")).trim() : "";
    if (type === "lab") {
      return { type: "lab",
        lab_partner: "", lab_partner_name: "",
        tests: [],
        ordering_provider_key: meId, ordering_provider_name: meName,
        fasting_required: false,
        diagnosis_codes: dxCodes.slice(),
        comment: "" };
    }
    if (type === "imaging") {
      return { type: "imaging",
        image_code: "", priority: "ROUTINE",
        diagnosis_codes: dxCodes.slice(),
        additional_details: "", comment: "",
        ordering_provider_key: meId, ordering_provider_name: meName };
    }
    if (type === "prescribe") {
      return { type: "prescribe",
        fdb_code: "", medication_display: "",
        description_and_quantity: "",
        clinical_quantities: [],
        representative_ndc: "", ncpdp_quantity_qualifier_code: "",
        quantity_description: "",
        sig: "", quantity_to_dispense: "", days_supply: "", refills: "",
        substitutions: "ALLOWED",
        icd10_codes: dxCodes.slice(),
        pharmacy: "",
        prescriber_id: meId, prescriber_name: meName,
        note_to_pharmacist: "" };
    }
    if (type === "refer") {
      return { type: "refer",
        service_provider: {
          first_name: "", last_name: "", specialty: "", practice_name: "",
        },
        clinical_question: "ASSISTANCE_WITH_ONGOING_MANAGEMENT",
        priority: "ROUTINE",
        diagnosis_codes: dxCodes.slice(),
        notes_to_specialist: "", include_visit_note: true };
    }
    if (type === "goal") {
      return { type: "goal",
        goal_statement: "", due_date: "", priority: "MEDIUM", progress: "" };
    }
    if (type === "plan_item") {
      return { type: "plan_item", narrative: "" };
    }
    if (type === "follow_up") {
      return { type: "follow_up",
        requested_date: "", reason_for_visit: "", comment: "" };
    }
    return { type: type };
  }

  function renderDxChooser(order, key) {
    var codes = state.ap.diagnoses.map(function (d) { return d.code; });
    if (!codes.length) {
      return '<div class="exam-help">No diagnoses added — pick one above first.</div>';
    }
    var selected = order[key] || [];
    return '<div class="exam-order-dx-chooser">' +
      codes.map(function (c) {
        var on = selected.indexOf(c) !== -1;
        return '<button type="button" class="exam-order-dx-pill' + (on ? ' is-selected' : '') +
          '" data-code="' + escapeHtml(c) + '" data-key="' + escapeHtml(key) + '">' +
          escapeHtml(c) + '</button>';
      }).join("") + '</div>';
  }

  var ORDER_LABELS = {
    lab: "Lab order", imaging: "Imaging", prescribe: "Prescription", refer: "Referral",
    goal: "Goal", plan_item: "Plan", follow_up: "Follow up",
  };

  function _providerNameField(fieldName) {
    // Map the key field to its display-name companion in the order
    // entry. Both fields live on the same order object; the name is
    // stamped when the user picks from the staff search and is used
    // by _providerDisplayName.
    if (fieldName === "prescriber_id") return "prescriber_name";
    if (fieldName === "ordering_provider_key") return "ordering_provider_name";
    return fieldName + "_name";
  }

  function _providerDisplayName(staffKey, storedName) {
    if (storedName) return storedName;
    if (!staffKey) return "";
    var me = state.me || {};
    if (me.id && me.id === staffKey) {
      var nm = (me.first_name + " " + me.last_name).trim();
      return nm || staffKey;
    }
    return "Provider …" + staffKey.slice(-4);
  }

  function _providerField(staffKey, storedName, idx, fieldName) {
    // Picked: chip with name + × clear.
    if (staffKey) {
      return '<div class="exam-search-picked">' +
        '<span class="exam-search-result-name">' + escapeHtml(_providerDisplayName(staffKey, storedName)) + '</span>' +
        '<button type="button" class="exam-search-picked-clear" data-provider-clear="' + idx + ':' + fieldName + '" aria-label="Clear">×</button>' +
      '</div>';
    }
    // Empty: type-ahead staff search. Picked result is wired in
    // renderOrdersList (data-staff-pick handler).
    return '<div class="exam-search-wrap">' +
      '<input type="text" class="exam-input" data-staff-search="' + idx + ':' + fieldName + '" placeholder="Search staff by name">' +
      '<div class="exam-search-results" data-staff-results="' + idx + ':' + fieldName + '" hidden></div>' +
    '</div>';
  }

  function _orderSummary() {
    // All card types intentionally render an empty header summary. The
    // fields under the header show the picked values; an empty card's
    // "Placeholder? · Placeholder?" summary was noise the user asked to
    // remove (first for Goal/Plan/Follow-up, then Imaging/Referral). Keep
    // it empty universally for consistency.
    return "";
  }

  function _renderLabBody(o, idx) {
    // Lab partner <select> populated from state.lab_partners (preloaded
    // at tab load). Tests show as a type-ahead search input (against
    // /exam/search/lab-tests filtered by the chosen partner), with
    // picked tests rendered as removable pills below.
    var partnerOptions = '<option value="">— Select a lab —</option>' +
      state.lab_partners.map(function (p) {
        var sel = p.id === o.lab_partner ? ' selected' : '';
        return '<option value="' + escapeHtml(p.id) + '"' + sel + '>' +
          escapeHtml(p.name) + '</option>';
      }).join("");
    var pickedTests = (o.tests || []).length ? (
      '<div class="exam-dx-list" style="gap:4px;margin-top:6px">' +
        o.tests.map(function (t, ti) {
          return '<div class="exam-dx-row" data-test-row="' + idx + ':' + ti + '">' +
            '<span class="exam-dx-code">' + escapeHtml(t.order_code || "") + '</span>' +
            '<span class="exam-dx-display">' + escapeHtml(t.order_name || t.order_code || "") + '</span>' +
            '<button type="button" class="exam-dx-remove" data-lab-test-remove="' + idx + ':' + ti + '">×</button>' +
          '</div>';
        }).join("") +
      '</div>'
    ) : "";
    var testSearch = o.lab_partner ? (
      '<div class="exam-search-wrap">' +
        '<input type="text" class="exam-input" data-lab-test-search="' + idx + '" placeholder="Search tests (e.g. metabolic, lipid)">' +
        '<div class="exam-search-results" data-lab-test-results="' + idx + '" hidden></div>' +
      '</div>' + pickedTests
    ) : '<div class="exam-help">Pick a lab partner first to enable test search.</div>';
    return (
      '<div class="exam-order-grid">' +
        '<div class="exam-dx-sublabel">Lab partner<span class="exam-required-asterisk">*</span></div>' +
        '<select class="exam-input" data-order-field="lab_partner_select" data-order-idx="' + idx + '">' + partnerOptions + '</select>' +
        '<div class="exam-dx-sublabel">Tests<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + testSearch + '</div>' +
        '<div class="exam-dx-sublabel">Ordering provider<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + _providerField(o.ordering_provider_key, o.ordering_provider_name, idx, "ordering_provider_key") + '</div>' +
        '<div class="exam-dx-sublabel">Diagnosis codes<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + renderDxChooser(o, "diagnosis_codes") + '</div>' +
        '<div class="exam-dx-sublabel">Fasting required</div>' +
        '<div><input type="checkbox" data-order-field="fasting_required" data-order-idx="' + idx + '"' + (o.fasting_required ? ' checked' : '') + '></div>' +
        '<div class="exam-dx-sublabel">Comment</div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="comment" data-order-idx="' + idx + '">' + escapeHtml(o.comment || "") + '</textarea>' +
      '</div>'
    );
  }

  function _renderImagingBody(o, idx) {
    // Image code: free text. The chart's staged Imaging command UI
    // doesn't render plugin-emitted `image_code` strings (chart-side
    // limitation — confirmed across bare CPT, full description in the
    // chart's own catalog format, and ontologies_http typeahead). The
    // chart's typeahead widget itself is the only path that populates
    // the staged "Image:" row. Captured here for the plugin draft +
    // backend record only.
    // Build the staff option list. If the logged-in user isn't in
    // state.staff (limit=50, sorted by last_name — they could be cut off
    // when there are many staff), inject them at the top so the auto-
    // defaulted ordering_provider_key still matches a real option.
    var staffList = (state.staff || []).slice();
    var me = state.me;
    if (me && me.id) {
      var inList = staffList.some(function (s) { return s.id === me.id; });
      if (!inList) {
        staffList.unshift({
          id: me.id,
          first_name: me.first_name || "",
          last_name: me.last_name || "",
        });
      }
    }
    var staffOptions = '<option value="">— Select an ordering provider —</option>' +
      staffList.map(function (s) {
        var nm = ((s.first_name || "") + " " + (s.last_name || "")).trim();
        var sel = s.id === (o.ordering_provider_key || "") ? ' selected' : '';
        return '<option value="' + escapeHtml(s.id) + '"' + sel + '>' +
          escapeHtml(nm) + '</option>';
      }).join("");
    return (
      '<div class="exam-order-grid">' +
        '<div class="exam-dx-sublabel">Image code</div>' +
        '<div>' +
          '<input type="text" class="exam-input" data-order-field="image_code" data-order-idx="' + idx + '" value="' + escapeHtml(o.image_code) + '" placeholder="e.g. XR Chest 2 views">' +
          '<div class="exam-help" style="margin-top:4px;font-style:italic">Plugin draft only — not sent to the chart. After Finalize, pick the study on the staged Imaging command using the chart\'s CPT typeahead. (Plugin-side value omitted to avoid the chart\'s fuzzy-matcher resolving partial text to an unrelated study.)</div>' +
        '</div>' +
        '<div class="exam-dx-sublabel">Priority</div>' +
        '<select class="exam-input" data-order-field="priority" data-order-idx="' + idx + '">' +
          ['ROUTINE', 'URGENT'].map(function (p) {
            return '<option value="' + p + '"' + (o.priority === p ? ' selected' : '') + '>' + p + '</option>';
          }).join("") +
        '</select>' +
        '<div class="exam-dx-sublabel">Ordering provider<span class="exam-required-asterisk">*</span></div>' +
        '<select class="exam-input" data-imaging-staff-select="' + idx + '">' + staffOptions + '</select>' +
        '<div class="exam-dx-sublabel">Diagnosis codes<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + renderDxChooser(o, "diagnosis_codes") + '</div>' +
        '<div class="exam-dx-sublabel">Additional details</div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="additional_details" data-order-idx="' + idx + '">' + escapeHtml(o.additional_details || "") + '</textarea>' +
        '<div class="exam-dx-sublabel">Comment</div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="comment" data-order-idx="' + idx + '">' + escapeHtml(o.comment || "") + '</textarea>' +
      '</div>'
    );
  }

  function _renderPrescribeBody(o, idx) {
    // When a medication has been picked, replace the search input with
    // the picked chip (medication description + × clear). When no
    // medication is picked, show the search input.
    var medicationField = o.fdb_code ? (
      '<div class="exam-search-picked" data-rx-picked="' + idx + '">' +
        '<span class="exam-search-result-name">' + escapeHtml(o.description_and_quantity || o.medication_display) + '</span>' +
        '<button type="button" class="exam-search-picked-clear" data-rx-clear="' + idx + '" aria-label="Clear">×</button>' +
      '</div>'
    ) : (
      '<div class="exam-search-wrap">' +
        '<input type="text" class="exam-input" data-rx-search="' + idx + '" placeholder="Search medications (FDB)">' +
        '<div class="exam-search-results" data-rx-results="' + idx + '" hidden></div>' +
      '</div>'
    );
    // Dispense-form picker: shown only when a med is picked and has
    // multiple clinical_quantities. With one (or none) we render the
    // chosen description as static text so providers can see what they
    // got auto-defaulted to.
    var dispenseField = "";
    if (o.fdb_code) {
      var cqs = o.clinical_quantities || [];
      if (cqs.length > 1) {
        dispenseField = '<select class="exam-input" data-rx-dispense="' + idx + '">' +
          cqs.map(function (cq) {
            var sel = (cq.representative_ndc === o.representative_ndc &&
                       cq.ncpdp_quantity_qualifier_code === o.ncpdp_quantity_qualifier_code)
                       ? ' selected' : '';
            return '<option value="' + escapeHtml(cq.representative_ndc) + '|' +
              escapeHtml(cq.ncpdp_quantity_qualifier_code) + '"' + sel + '>' +
              escapeHtml(cq.quantity_description || cq.representative_ndc) + '</option>';
          }).join("") +
        '</select>';
      } else {
        dispenseField = '<div class="exam-help">' +
          escapeHtml(o.quantity_description || "—") + '</div>';
      }
    }
    return (
      '<div class="exam-order-grid">' +
        '<div class="exam-dx-sublabel">Medication<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + medicationField + '</div>' +
        (o.fdb_code ? (
          '<div class="exam-dx-sublabel">Dispense form</div>' +
          '<div>' + dispenseField + '</div>'
        ) : "") +
        '<div class="exam-dx-sublabel">Sig<span class="exam-required-asterisk">*</span></div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="sig" data-order-idx="' + idx + '">' + escapeHtml(o.sig || "") + '</textarea>' +
        '<div class="exam-dx-sublabel">Qty to dispense<span class="exam-required-asterisk">*</span></div>' +
        '<input type="number" class="exam-input" data-order-field="quantity_to_dispense" data-order-idx="' + idx + '" value="' + escapeHtml(String(o.quantity_to_dispense || "")) + '">' +
        '<div class="exam-dx-sublabel">Days supply<span class="exam-required-asterisk">*</span></div>' +
        '<input type="number" class="exam-input" data-order-field="days_supply" data-order-idx="' + idx + '" value="' + escapeHtml(String(o.days_supply || "")) + '">' +
        '<div class="exam-dx-sublabel">Refills<span class="exam-required-asterisk">*</span></div>' +
        '<input type="number" class="exam-input" data-order-field="refills" data-order-idx="' + idx + '" value="' + escapeHtml(String((o.refills !== "" && o.refills !== null && o.refills !== undefined) ? o.refills : "")) + '">' +
        '<div class="exam-dx-sublabel">Substitutions</div>' +
        '<select class="exam-input" data-order-field="substitutions" data-order-idx="' + idx + '">' +
          ['ALLOWED', 'NOT_ALLOWED'].map(function (s) {
            return '<option value="' + s + '"' + (o.substitutions === s ? ' selected' : '') + '>' + s + '</option>';
          }).join("") +
        '</select>' +
        '<div class="exam-dx-sublabel">ICD-10 codes<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + renderDxChooser(o, "icd10_codes") + '</div>' +
        '<div class="exam-dx-sublabel">Pharmacy</div>' +
        '<input type="text" class="exam-input" data-order-field="pharmacy" data-order-idx="' + idx + '" value="' + escapeHtml(o.pharmacy || "") + '">' +
        '<div class="exam-dx-sublabel">Prescriber<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + _providerField(o.prescriber_id, o.prescriber_name, idx, "prescriber_id") + '</div>' +
      '</div>'
    );
  }

  function _spOptionLabel(p) {
    var nm = ((p.first_name || "") + " " + (p.last_name || "")).trim();
    var sub = [p.specialty || "", p.practice_name || ""]
      .filter(function (s) { return s; }).join(" · ");
    return sub ? nm + " — " + sub : nm;
  }

  function _renderReferBody(o, idx) {
    var sp = o.service_provider || {};
    var currentId = sp.id || "";
    var providers = state.service_providers || [];
    var spOptions = '<option value="">— Select a specialist —</option>' +
      providers.map(function (p) {
        var sel = p.id === currentId ? ' selected' : '';
        return '<option value="' + escapeHtml(p.id) + '"' + sel + '>' +
          escapeHtml(_spOptionLabel(p)) + '</option>';
      }).join("");
    return (
      '<div class="exam-order-grid">' +
        '<div class="exam-dx-sublabel">Specialist<span class="exam-required-asterisk">*</span></div>' +
        '<select class="exam-input" data-sp-select="' + idx + '">' + spOptions + '</select>' +
        '<div class="exam-dx-sublabel">Clinical question</div>' +
        '<select class="exam-input" data-order-field="clinical_question" data-order-idx="' + idx + '">' +
          ['COGNITIVE_ASSISTANCE', 'ASSISTANCE_WITH_ONGOING_MANAGEMENT', 'SPECIALIZED_INTERVENTION', 'DIAGNOSTIC_UNCERTAINTY'].map(function (q) {
            return '<option value="' + q + '"' + (o.clinical_question === q ? ' selected' : '') + '>' + q.replace(/_/g, " ") + '</option>';
          }).join("") +
        '</select>' +
        '<div class="exam-dx-sublabel">Priority</div>' +
        '<select class="exam-input" data-order-field="priority" data-order-idx="' + idx + '">' +
          ['ROUTINE', 'URGENT'].map(function (p) {
            return '<option value="' + p + '"' + (o.priority === p ? ' selected' : '') + '>' + p + '</option>';
          }).join("") +
        '</select>' +
        '<div class="exam-dx-sublabel">Diagnosis codes<span class="exam-required-asterisk">*</span></div>' +
        '<div>' + renderDxChooser(o, "diagnosis_codes") + '</div>' +
        '<div class="exam-dx-sublabel">Include visit note</div>' +
        '<div><input type="checkbox" data-order-field="include_visit_note" data-order-idx="' + idx + '"' + (o.include_visit_note ? ' checked' : '') + '></div>' +
        '<div class="exam-dx-sublabel">Notes to specialist<span class="exam-required-asterisk">*</span></div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="notes_to_specialist" data-order-idx="' + idx + '">' + escapeHtml(o.notes_to_specialist || "") + '</textarea>' +
      '</div>'
    );
  }

  function _renderGoalBody(o, idx) {
    return (
      '<div class="exam-order-grid">' +
        '<div class="exam-dx-sublabel">Goal statement<span class="exam-required-asterisk">*</span></div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="goal_statement" data-order-idx="' + idx + '">' + escapeHtml(o.goal_statement || "") + '</textarea>' +
        '<div class="exam-dx-sublabel">Due date</div>' +
        '<input type="date" class="exam-input" data-order-field="due_date" data-order-idx="' + idx + '" value="' + escapeHtml(o.due_date || "") + '">' +
        '<div class="exam-dx-sublabel">Priority</div>' +
        '<select class="exam-input" data-order-field="priority" data-order-idx="' + idx + '">' +
          ['LOW', 'MEDIUM', 'HIGH'].map(function (p) {
            return '<option value="' + p + '"' + (o.priority === p ? ' selected' : '') + '>' + p + '</option>';
          }).join("") +
        '</select>' +
        '<div class="exam-dx-sublabel">Progress</div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="progress" data-order-idx="' + idx + '">' + escapeHtml(o.progress || "") + '</textarea>' +
      '</div>'
    );
  }

  function _renderPlanItemBody(o, idx) {
    return (
      '<div class="exam-order-grid">' +
        '<div class="exam-dx-sublabel">Narrative</div>' +
        '<textarea class="exam-textarea" rows="3" data-order-field="narrative" data-order-idx="' + idx + '">' + escapeHtml(o.narrative || "") + '</textarea>' +
      '</div>'
    );
  }

  function _renderFollowUpBody(o, idx) {
    return (
      '<div class="exam-order-grid">' +
        '<div class="exam-dx-sublabel">Requested date</div>' +
        '<input type="date" class="exam-input" data-order-field="requested_date" data-order-idx="' + idx + '" value="' + escapeHtml(o.requested_date || "") + '">' +
        '<div class="exam-dx-sublabel">Reason for visit</div>' +
        '<input type="text" class="exam-input" data-order-field="reason_for_visit" data-order-idx="' + idx + '" value="' + escapeHtml(o.reason_for_visit || "") + '" placeholder="Free-text reason">' +
        '<div class="exam-dx-sublabel">Comment</div>' +
        '<textarea class="exam-textarea" rows="2" data-order-field="comment" data-order-idx="' + idx + '">' + escapeHtml(o.comment || "") + '</textarea>' +
      '</div>'
    );
  }

  function renderOrderCard(o, idx) {
    var body = "";
    if (o.type === "lab")        body = _renderLabBody(o, idx);
    else if (o.type === "imaging")  body = _renderImagingBody(o, idx);
    else if (o.type === "prescribe") body = _renderPrescribeBody(o, idx);
    else if (o.type === "refer")    body = _renderReferBody(o, idx);
    else if (o.type === "goal")     body = _renderGoalBody(o, idx);
    else if (o.type === "plan_item") body = _renderPlanItemBody(o, idx);
    else if (o.type === "follow_up") body = _renderFollowUpBody(o, idx);
    return (
      '<div class="exam-order-card" data-order-idx="' + idx + '">' +
        '<div class="exam-order-card-header">' +
          '<span class="exam-order-card-type">' + escapeHtml(ORDER_LABELS[o.type] || o.type) + '</span>' +
          '<span class="exam-order-card-summary">' + escapeHtml(_orderSummary(o)) + '</span>' +
          '<button type="button" class="exam-dx-remove" data-order-remove="' + idx + '" aria-label="Remove">×</button>' +
        '</div>' +
        '<div class="exam-order-body">' + body + '</div>' +
      '</div>'
    );
  }

  // RxTerms search debounce (per-card; tracked by index in a single map)
  var rxDebounceTimers = {};

  function _renderRxResults(idx, results) {
    var box = document.querySelector('[data-rx-results="' + idx + '"]');
    if (!box) return;
    if (!results || !results.length) {
      box.hidden = true; box.innerHTML = "";
      return;
    }
    box.innerHTML = results.map(function (r, i) {
      var label = r.description_and_quantity || r.display || r.fdb_code;
      return (
        '<button type="button" class="exam-search-result" data-rx-pick="' + idx + '" data-rx-i="' + i + '">' +
        '<span class="exam-search-result-name">' + escapeHtml(label) + '</span>' +
        '</button>'
      );
    }).join("");
    box.hidden = false;
    placeDropdown(box);
    Array.prototype.forEach.call(box.querySelectorAll(".exam-search-result"), function (el, i) {
      el.addEventListener("click", function () {
        var order = state.ap.orders[idx];
        if (!order) return;
        var picked = results[i];
        order.fdb_code = picked.fdb_code || "";
        order.medication_display = picked.display || "";
        order.description_and_quantity = picked.description_and_quantity || "";
        order.clinical_quantities = picked.clinical_quantities || [];
        // Default the dispense form to the first quantity. If the API
        // returned none, leave the NDC/qualifier blank — the backend
        // will simply skip type_to_dispense and the chart's Prescribe UI
        // will still let the provider pick one.
        var first = order.clinical_quantities[0];
        if (first) {
          order.representative_ndc = first.representative_ndc || "";
          order.ncpdp_quantity_qualifier_code = first.ncpdp_quantity_qualifier_code || "";
          order.quantity_description = first.quantity_description || "";
        } else {
          order.representative_ndc = "";
          order.ncpdp_quantity_qualifier_code = "";
          order.quantity_description = "";
        }
        renderOrdersList();
      });
    });
  }

  function _performRxSearch(idx, q) {
    // Hits the plugin's /exam/search/medications endpoint, which proxies
    // ontologies_http /fdb/grouped-medication. Returns FDB GCNs plus the
    // dispense-form (NDC + NCPDP qualifier) the chart's Prescribe UI
    // needs to resolve the medication name and quantity dropdown.
    if (!q || q.length < 2) { _renderRxResults(idx, []); return; }
    var url = CONFIG.api_base + "/exam/search/medications?q=" + encodeURIComponent(q);
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { results: [] }; })
      .then(function (data) {
        var items = (data.results || []).filter(function (it) {
          return it && it.fdb_code && (it.display || it.description_and_quantity);
        });
        _renderRxResults(idx, items);
      })
      .catch(function () { _renderRxResults(idx, []); });
  }

  // The 7 order types render into two separate DOM lists: classic Orders
  // (lab/imaging/prescribe/refer) and Goals/Plans (goal/plan_item/follow_up).
  // All cards still share `state.ap.orders` and `data-order-idx` refers
  // to the absolute index in that array, so every event handler below
  // can find its order entry without caring which list it lives in.
  var GOALS_TYPES = { goal: 1, plan_item: 1, follow_up: 1 };

  function _queryBothLists(selector) {
    var a = $("orders-list");
    var b = $("goals-plans-list");
    var out = [];
    if (a) Array.prototype.push.apply(out, a.querySelectorAll(selector));
    if (b) Array.prototype.push.apply(out, b.querySelectorAll(selector));
    return out;
  }

  function renderOrdersList() {
    var ordersList = $("orders-list");
    var goalsList = $("goals-plans-list");
    var ordersHtml = [];
    var goalsHtml = [];
    state.ap.orders.forEach(function (o, i) {
      var html = renderOrderCard(o, i);
      if (GOALS_TYPES[o.type]) goalsHtml.push(html);
      else ordersHtml.push(html);
    });
    if (ordersList) ordersList.innerHTML = ordersHtml.join("");
    if (goalsList) goalsList.innerHTML = goalsHtml.join("");

    // Remove buttons
    _queryBothLists("[data-order-remove]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var i = parseInt(btn.getAttribute("data-order-remove"), 10);
        if (!isNaN(i)) {
          state.ap.orders.splice(i, 1);
          renderOrdersList();
        }
      });
    });

    // Generic data-order-field inputs (text / textarea / select / checkbox / number)
    _queryBothLists("[data-order-field]").forEach(function (el) {
      var i = parseInt(el.getAttribute("data-order-idx"), 10);
      var path = (el.getAttribute("data-order-field") || "").split(".");
      var isCheckbox = el.type === "checkbox";
      var isNumber = el.type === "number";
      var evt = el.tagName === "SELECT" || isCheckbox ? "change" : "input";
      el.addEventListener(evt, function () {
        if (isNaN(i) || !state.ap.orders[i]) return;
        var node = state.ap.orders[i];
        for (var p = 0; p < path.length - 1; p++) {
          if (!node[path[p]]) node[path[p]] = {};
          node = node[path[p]];
        }
        var key = path[path.length - 1];
        if (key === "tests_csv") {
          state.ap.orders[i].tests = el.value.split(",")
            .map(function (s) { return s.trim(); })
            .filter(function (s) { return s.length > 0; })
            .map(function (s) { return { order_code: s, order_name: s }; });
        } else if (isCheckbox) {
          node[key] = el.checked;
        } else if (isNumber) {
          node[key] = el.value === "" ? "" : parseFloat(el.value);
        } else {
          node[key] = el.value;
        }
      });
    });

    // Diagnosis-code pill toggles
    _queryBothLists(".exam-order-dx-pill").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var card = btn.closest(".exam-order-card");
        if (!card) return;
        var i = parseInt(card.getAttribute("data-order-idx"), 10);
        var order = state.ap.orders[i];
        if (!order) return;
        var key = btn.getAttribute("data-key");
        var code = btn.getAttribute("data-code");
        var current = order[key] || [];
        var pos = current.indexOf(code);
        if (pos === -1) { current.push(code); btn.classList.add("is-selected"); }
        else { current.splice(pos, 1); btn.classList.remove("is-selected"); }
        order[key] = current;
      });
    });

    // Lab-card partner <select>: stores both id and name, then refreshes
    // so the tests-search input becomes interactive.
    _queryBothLists('[data-order-field="lab_partner_select"]').forEach(function (sel) {
      var idx = parseInt(sel.getAttribute("data-order-idx"), 10);
      sel.addEventListener("change", function () {
        var order = state.ap.orders[idx];
        if (!order) return;
        var chosen = state.lab_partners.find(function (p) { return p.id === sel.value; });
        order.lab_partner = sel.value;
        order.lab_partner_name = chosen ? chosen.name : "";
        order.tests = [];
        renderOrdersList();
      });
    });

    // Lab-test search inputs (debounced typeahead, partner-scoped)
    var labTestDebounce = {};
    _queryBothLists("[data-lab-test-search]").forEach(function (input) {
      var idx = parseInt(input.getAttribute("data-lab-test-search"), 10);
      input.addEventListener("input", function (e) {
        var q = e.target.value.trim();
        if (labTestDebounce[idx]) clearTimeout(labTestDebounce[idx]);
        labTestDebounce[idx] = setTimeout(function () {
          var order = state.ap.orders[idx];
          if (!order || !order.lab_partner) return;
          if (!q || q.length < 2) {
            var box0 = document.querySelector('[data-lab-test-results="' + idx + '"]');
            if (box0) { box0.hidden = true; box0.innerHTML = ""; }
            return;
          }
          var url = CONFIG.api_base + "/exam/search/lab-tests?partner_id=" +
            encodeURIComponent(order.lab_partner) + "&q=" + encodeURIComponent(q);
          fetch(url, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : { results: [] }; })
            .then(function (data) {
              var box = document.querySelector('[data-lab-test-results="' + idx + '"]');
              if (!box) return;
              var results = data.results || [];
              if (!results.length) { box.hidden = true; box.innerHTML = ""; return; }
              box.innerHTML = results.map(function (r, i) {
                return '<button type="button" class="exam-search-result" data-lab-test-pick="' + idx + ':' + i + '">' +
                  '<span class="exam-search-result-code">' + escapeHtml(r.order_code) + '</span>' +
                  '<span class="exam-search-result-name">' + escapeHtml(r.order_name) + '</span>' +
                  '</button>';
              }).join("");
              box.hidden = false;
              placeDropdown(box);
              Array.prototype.forEach.call(box.querySelectorAll(".exam-search-result"), function (el, i) {
                el.addEventListener("click", function () {
                  // Avoid duplicates by order_code
                  var dup = order.tests.some(function (t) { return t.order_code === results[i].order_code; });
                  if (!dup) order.tests.push(results[i]);
                  renderOrdersList();
                });
              });
            })
            .catch(function () { /* swallow */ });
        }, 200);
      });
    });
    // Lab-test remove buttons
    _queryBothLists("[data-lab-test-remove]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var parts = (btn.getAttribute("data-lab-test-remove") || "").split(":");
        var i = parseInt(parts[0], 10);
        var ti = parseInt(parts[1], 10);
        if (!isNaN(i) && !isNaN(ti) && state.ap.orders[i]) {
          state.ap.orders[i].tests.splice(ti, 1);
          renderOrdersList();
        }
      });
    });

    // Provider-chip clear buttons (Lab ordering_provider_key / Rx prescriber_id).
    // Clicking × empties the underlying key + name; re-render swaps the chip
    // for a staff-search type-ahead so a different provider can be picked.
    _queryBothLists("[data-provider-clear]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var parts = (btn.getAttribute("data-provider-clear") || "").split(":");
        var i = parseInt(parts[0], 10);
        var fieldName = parts[1];
        if (!isNaN(i) && fieldName && state.ap.orders[i]) {
          state.ap.orders[i][fieldName] = "";
          state.ap.orders[i][_providerNameField(fieldName)] = "";
          renderOrdersList();
        }
      });
    });

    // Staff type-ahead search inputs (revealed when a provider chip is
    // cleared). Hits /exam/search/staff and renders matches as a
    // dropdown; picking a row stamps the staff UUID into the order's
    // key field and the full name into the companion *_name field, then
    // re-renders so the chip reappears.
    var staffDebounce = {};
    _queryBothLists("[data-staff-search]").forEach(function (input) {
      var key = input.getAttribute("data-staff-search") || "";
      input.addEventListener("input", function (e) {
        var q = e.target.value.trim();
        if (staffDebounce[key]) clearTimeout(staffDebounce[key]);
        staffDebounce[key] = setTimeout(function () {
          var box = document.querySelector('[data-staff-results="' + key + '"]');
          if (!box) return;
          if (!q || q.length < 2) { box.hidden = true; box.innerHTML = ""; return; }
          fetch(CONFIG.api_base + "/exam/search/staff?q=" + encodeURIComponent(q),
                { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : { results: [] }; })
            .then(function (data) {
              var results = data.results || [];
              if (!results.length) { box.hidden = true; box.innerHTML = ""; return; }
              box.innerHTML = results.map(function (r, i) {
                var fullName = ((r.first_name || "") + " " + (r.last_name || "")).trim();
                return '<button type="button" class="exam-search-result" data-staff-pick="' + escapeHtml(key) + ':' + i + '">' +
                  '<span class="exam-search-result-name">' + escapeHtml(fullName) + '</span>' +
                  '<span class="exam-search-result-code">' + escapeHtml(r.npi_number || "") + '</span>' +
                  '</button>';
              }).join("");
              box.hidden = false;
              placeDropdown(box);
              Array.prototype.forEach.call(box.querySelectorAll(".exam-search-result"), function (el, i) {
                el.addEventListener("click", function () {
                  var parts = key.split(":");
                  var idx = parseInt(parts[0], 10);
                  var fieldName = parts[1];
                  if (isNaN(idx) || !fieldName || !state.ap.orders[idx]) return;
                  var picked = results[i];
                  var fullName = ((picked.first_name || "") + " " + (picked.last_name || "")).trim();
                  state.ap.orders[idx][fieldName] = picked.id;
                  state.ap.orders[idx][_providerNameField(fieldName)] = fullName;
                  renderOrdersList();
                });
              });
            })
            .catch(function () { box.hidden = true; box.innerHTML = ""; });
        }, 200);
      });
    });

    // Prescribe-card RxTerms search inputs + clear-picked buttons
    _queryBothLists("[data-rx-search]").forEach(function (input) {
      var idx = parseInt(input.getAttribute("data-rx-search"), 10);
      input.addEventListener("input", function (e) {
        var q = e.target.value.trim();
        if (rxDebounceTimers[idx]) clearTimeout(rxDebounceTimers[idx]);
        rxDebounceTimers[idx] = setTimeout(function () { _performRxSearch(idx, q); }, 200);
      });
    });
    _queryBothLists("[data-rx-clear]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(btn.getAttribute("data-rx-clear"), 10);
        var order = state.ap.orders[idx];
        if (!order) return;
        order.fdb_code = "";
        order.medication_display = "";
        order.description_and_quantity = "";
        order.clinical_quantities = [];
        order.representative_ndc = "";
        order.ncpdp_quantity_qualifier_code = "";
        order.quantity_description = "";
        renderOrdersList();
      });
    });

    // Imaging card: ordering-provider <select> from state.staff
    _queryBothLists("[data-imaging-staff-select]").forEach(function (sel) {
      var idx = parseInt(sel.getAttribute("data-imaging-staff-select"), 10);
      sel.addEventListener("change", function () {
        var order = state.ap.orders[idx];
        if (!order) return;
        var chosen = (state.staff || []).find(function (s) { return s.id === sel.value; });
        order.ordering_provider_key = sel.value;
        order.ordering_provider_name = chosen
          ? ((chosen.first_name || "") + " " + (chosen.last_name || "")).trim()
          : "";
      });
    });

    // Refer card: specialist <select> populated from state.service_providers
    // (preloaded at tab load). Picking stamps id + first/last/specialty/
    // practice so the finalize payload has everything ReferCommand needs.
    _queryBothLists("[data-sp-select]").forEach(function (sel) {
      var idx = parseInt(sel.getAttribute("data-sp-select"), 10);
      sel.addEventListener("change", function () {
        var order = state.ap.orders[idx];
        if (!order) return;
        var chosen = (state.service_providers || []).find(function (p) {
          return p.id === sel.value;
        });
        if (chosen) {
          order.service_provider = {
            id: chosen.id,
            first_name: chosen.first_name || "",
            last_name: chosen.last_name || "",
            specialty: chosen.specialty || "",
            practice_name: chosen.practice_name || "",
          };
        } else {
          order.service_provider = {
            first_name: "", last_name: "", specialty: "", practice_name: "",
          };
        }
      });
    });

    // Dispense-form selector (only present when a med has >1 clinical_quantity)
    _queryBothLists("[data-rx-dispense]").forEach(function (sel) {
      var idx = parseInt(sel.getAttribute("data-rx-dispense"), 10);
      sel.addEventListener("change", function () {
        var order = state.ap.orders[idx];
        if (!order) return;
        var parts = (sel.value || "").split("|");
        var ndc = parts[0] || "";
        var qual = parts[1] || "";
        var match = (order.clinical_quantities || []).find(function (cq) {
          return cq.representative_ndc === ndc && cq.ncpdp_quantity_qualifier_code === qual;
        });
        order.representative_ndc = ndc;
        order.ncpdp_quantity_qualifier_code = qual;
        order.quantity_description = match ? (match.quantity_description || "") : "";
      });
    });

    _scheduleSaveDraft();
    updateFinalizeButton();
  }

  // Wire the [+ Add ...] buttons (one-time)
  Array.prototype.forEach.call(document.querySelectorAll(".exam-add-order-btn"), function (btn) {
    btn.addEventListener("click", function () {
      var type = btn.getAttribute("data-order-type");
      state.ap.orders.push(_emptyOrder(type));
      renderOrdersList();
    });
  });

  // Preload the logged-in staff (so freshly-added order cards default
  // their ordering_provider_key / prescriber_id) and the LabPartner list
  // (powers the partner <select> on Lab cards without per-card fetches).
  // Fills in empty ordering_provider / prescriber on existing order cards
  // from state.me. Called from two places: (a) when /exam/me resolves
  // — covers cards added before the fetch landed; (b) when hydrate
  // merges saved orders — covers cards whose saved blob predated this
  // logic, or were saved while state.me was still empty. Both call
  // sites end up running this; idempotent.
  function backfillOrderProviders() {
    var me = state.me;
    if (!me || !me.id) return false;
    var meName = ((me.first_name || "") + " " + (me.last_name || "")).trim();
    var changed = false;
    (state.ap.orders || []).forEach(function (o) {
      if (o.type === "prescribe" && !o.prescriber_id) {
        o.prescriber_id = me.id;
        o.prescriber_name = meName;
        changed = true;
      }
      if ((o.type === "lab" || o.type === "imaging") && !o.ordering_provider_key) {
        o.ordering_provider_key = me.id;
        o.ordering_provider_name = meName;
        changed = true;
      }
    });
    return changed;
  }

  fetch(CONFIG.api_base + "/exam/me", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (me) {
      if (!me || !me.id) return;
      state.me = me;
      if (backfillOrderProviders() && state.ap.orders.length) renderOrdersList();
    })
    .catch(function () { /* swallow */ });

  fetch(CONFIG.api_base + "/exam/search/lab-partners", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : { results: [] }; })
    .then(function (data) {
      state.lab_partners = data.results || [];
      // Re-render any open Lab cards so the new partners populate the select
      var hasLab = state.ap.orders.some(function (o) { return o.type === "lab"; });
      if (hasLab) renderOrdersList();
    })
    .catch(function () { /* swallow */ });

  fetch(CONFIG.api_base + "/exam/search/service-providers?limit=50", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : { results: [] }; })
    .then(function (data) {
      state.service_providers = data.results || [];
      // Re-render any open Refer cards so the specialist <select> populates.
      var hasRefer = state.ap.orders.some(function (o) { return o.type === "refer"; });
      if (hasRefer) renderOrdersList();
    })
    .catch(function () { /* swallow */ });

  fetch(CONFIG.api_base + "/exam/search/staff?limit=50", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : { results: [] }; })
    .then(function (data) {
      state.staff = data.results || [];
      // Re-render any open Imaging cards so the ordering provider <select>
      // populates with the full staff list.
      var hasImaging = state.ap.orders.some(function (o) { return o.type === "imaging"; });
      if (hasImaging) renderOrdersList();
    })
    .catch(function () { /* swallow */ });

  // imaging_codes preload removed: see comment in _renderImagingBody.
  // The chart's staged Imaging command UI doesn't accept plugin-emitted
  // image_code values, so the field is now free-text-with-help.

