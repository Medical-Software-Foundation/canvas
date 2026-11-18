/* Settings tab: Scheduling (feature switches, new rule defaults), Access control (admins, editing
   groups, default access), Providers and Bulk import. Loaded after admin.js and uses its apiCall,
   showMsg, _escHtml, _providers, paAccess, applyFeatureVisibility and renderAccordion.
   Served through render_to_string, so this file must never contain two opening braces in a row. */

(function () {
  'use strict';

  var state = null;          // GET /settings response
  var asking = null;         // feature whose disable question is open
  var affectedCache = {};    // feature -> GET /settings/affected/<feature> response
  var editingGroup = null;   // null, '' (new group) or a group id
  var deletingGroup = null;
  var openGroups = {};
  var defaultsDirty = false;

  var FEATURES = [
    { k: 'facility_rounds', name: 'Facility rounds',
      descHtml: 'Adds the <b>Facility</b> option to Available. Round time shows on the schedule as open time, and visits booked in it get the facility as a label.',
      title: 'Disable facility rounds', noun: 'facility rounds',
      lead: 'The Facility option will be hidden, and new rounds can no longer be added.',
      body: function (n) { return 'The Facility option will be hidden, and new rounds can no longer be added. ' + n + ' saved.'; },
      choices: [['keep', 'Keep existing rounds bookable'], ['remove', 'Remove existing rounds from calendars; the rounds stay saved']] },
    { k: 'facility_blocks', name: 'Facility blocks',
      descHtml: 'Adds the <b>Facility</b> option to Blocked. The block shows on the schedule with the facility’s name, and selecting it lists the facility’s patients.',
      title: 'Disable facility blocks', noun: 'upcoming facility blocks',
      lead: 'The Facility option will be hidden, and new facility blocks can no longer be added.',
      body: function (n) { return 'The Facility option will be hidden, and new facility blocks can no longer be added. ' + n + ' stay on provider calendars.'; },
      choices: [['keep', 'Keep existing facility blocks; they can still be edited or deleted']] },
    { k: 'buffers', name: 'Appointment buffers', desc: 'Blocks time before and after new and rescheduled appointments. Existing appointments are not changed.',
      title: 'Disable appointment buffers', noun: 'buffers',
      lead: 'New appointments will no longer receive buffers.',
      body: function (n) { return 'New appointments will no longer receive buffers. ' + n + ' currently on provider calendars.'; },
      choices: [['keep', 'Keep existing buffers until their appointments end'], ['remove', 'Remove existing buffers now']] },
    { k: 'lead_time', name: 'Lead time', desc: 'Blocks booking within each rule\'s minimum lead time.',
      title: 'Disable lead time', noun: 'lead time blocks',
      lead: 'Lead time blocks will no longer be created.',
      body: function (n) { return 'Lead time blocks will no longer be created. ' + n + ' currently on provider calendars.'; },
      choices: [['keep', 'Keep existing blocks until they expire'], ['remove', 'Remove existing blocks now']] },
    { k: 'holds', name: 'Same-day and next-day holds', desc: 'Reserves time that opens for booking the day before or the day of.',
      title: 'Disable same-day and next-day holds', noun: 'holds',
      lead: 'The Hold rule type will be hidden, and holds will no longer refresh.',
      body: function (n) { return 'The Hold rule type will be hidden, and holds will no longer refresh. ' + n + ' currently on provider calendars.'; },
      choices: [['keep', 'Keep existing holds until they end'], ['remove', 'Remove existing holds now']] },
    { k: 'overrides', name: 'Date overrides', desc: 'Changes a provider\'s hours on specific dates.',
      title: 'Disable date overrides', noun: 'upcoming overrides',
      lead: 'New date overrides can no longer be added.',
      body: function (n) { return 'New date overrides can no longer be added. ' + n + ' change provider hours.'; },
      choices: [['keep', 'Keep honoring overrides already saved'], ['stop', 'Ignore saved overrides; those dates use the weekly schedule again']] },
    { k: 'provider_timezones', name: 'Provider timezones', desc: 'Allows a provider to work in a timezone other than the practice timezone.',
      title: 'Disable provider timezones', noun: 'providers with their own timezone',
      lead: 'All providers will use the practice timezone.',
      body: function (n) { return 'All providers will use the practice timezone. Hours for the ' + n + ' keep the same clock times in the practice timezone.'; },
      choices: [['move', 'Move these providers to the practice timezone']] }
  ];
  var LEVELS = {
    full: { short: 'Full access', hint: 'Edit and view every provider.' },
    view: { short: 'View only', hint: 'View every provider without making changes.' },
    none: { short: 'No access', hint: 'No access to other providers’ availability.' }
  };
  // Names shown per column in an open editing group before "+ N more".
  var NAME_CAP = 8;
  var CHEVRON = '<svg class="row-chevron" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path d="M9 5l7 7-7 7"/></svg>';

  function $(id) { return document.getElementById(id); }
  function esc(t) { return _escHtml(t == null ? '' : String(t)); }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }
  function preloaded() { window.__PRELOADED__ = window.__PRELOADED__ || {}; return window.__PRELOADED__; }

  // ── Section list ──────────────────────────────────────────────────
  function showPage(name) {
    document.querySelectorAll('#set-list .set-row').forEach(function (r) { r.classList.toggle('on', r.dataset.p === name); });
    document.querySelectorAll('.set-page').forEach(function (p) { p.classList.toggle('on', p.id === 'set-p-' + name); });
    try { sessionStorage.setItem('provider_availability:settings-page', name); } catch (e) {}
  }
  document.querySelectorAll('#set-list .set-row').forEach(function (r) {
    r.addEventListener('click', function () { showPage(r.dataset.p); });
  });
  try { var lastPage = sessionStorage.getItem('provider_availability:settings-page'); if (lastPage) showPage(lastPage); } catch (e) {}

  // ── Load ──────────────────────────────────────────────────────────
  async function open() {
    if (!paAccess().is_admin) return;
    var data = await apiCall('/settings');
    if (!data || data.error) { showMsg((data && data.error) || 'Settings could not be loaded.', 'error'); return; }
    state = data;
    affectedCache = {};
    preloaded().features = data.features;
    preloaded().rule_defaults = data.rule_defaults;
    preloaded().facilities = { facilities: data.facilities || [], by_provider: data.provider_facilities || {} };
    applyFeatureVisibility();
    drawFeatures();
    drawProviderFacilities();
    if (!defaultsDirty) drawDefaults();
    drawAccess();
    drawGroups();
    drawTzNote();
  }

  // ── Feature switches ──────────────────────────────────────────────
  function affectedHtml(k) {
    var d = affectedCache[k];
    if (!d) return '<div class="aff-more">Loading…</div>';
    if (!d.total) return '<div class="aff-more">Nothing on calendars right now.</div>';
    var head = function (cols) { return '<tr>' + cols.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr>'; };
    var row = function (cells) { return '<tr>' + cells.map(function (c) { return '<td>' + esc(c) + '</td>'; }).join('') + '</tr>'; };
    if (k === 'provider_timezones') {
      return '<table>' + head(['Provider'].concat(d.columns)) + d.providers.map(function (p) { return row([p.name].concat(p.rows[0] || [])); }).join('') + '</table>';
    }
    var shown = 0;
    var html = '<table>' + head(['Provider', 'Count', '']) + d.providers.map(function (p, i) {
      shown += p.rows.length;
      return '<tr class="prow" data-i="' + i + '"><td>' + esc(p.name) + '</td><td>' + p.count + '</td><td></td></tr>' +
        '<tr class="drow" data-i="' + i + '"><td colspan="3"><table class="det">' + head(d.columns) + p.rows.map(row).join('') +
        (p.rows.length < p.count ? '<tr><td colspan="' + d.columns.length + '">and ' + (p.count - p.rows.length) + ' more</td></tr>' : '') +
        '</table></td></tr>';
    }).join('') + '</table>';
    return html;
  }

  async function loadAffected(k) {
    var d = await apiCall('/settings/affected/' + k);
    affectedCache[k] = (d && !d.error) ? d : { total: 0, providers: [], columns: [] };
    if (asking === k) drawFeatures();
  }

  // A provider's 8:00 AM stays 8:00 AM on the clock and moves to the practice timezone.
  function tzExample(d) {
    var p = d && d.providers && d.providers[0];
    if (!p || !p.rows[0]) return '';
    return ' ' + p.name + ': 8:00 AM ' + p.rows[0][0] + ' becomes 8:00 AM ' + p.rows[0][1] + '.';
  }

  function askHtml(f) {
    var d = affectedCache[f.k];
    var head = '<div class="ax-ask" id="set-ask"><div class="ax-cf-title">' + esc(f.title) + '</div>';
    var acts = function (ready) {
      return '<span style="flex:1"></span><button type="button" class="btn" id="set-ask-cancel">Cancel</button>' +
        '<button type="button" class="btn btn-primary" id="set-ask-ok"' + (ready ? '' : ' disabled') + '>Disable</button></div></div>';
    };
    if (!d) return head + '<p>' + esc(f.lead) + ' Checking calendars\u2026</p><div class="acts">' + acts(false);
    // Nothing on calendars: there is nothing to keep or remove, so no question.
    if (!d.total) return head + '<p>' + esc(f.lead) + ' Nothing on calendars right now.</p><div class="acts">' + acts(true);
    var countText = d.total + ' ' + f.noun + (d.total === 1 ? ' is' : ' are');
    if (f.k === 'provider_timezones') countText = plural(d.total, 'provider with their own timezone', 'providers with their own timezone');
    if (f.k === 'overrides') countText = plural(d.total, 'upcoming override', 'upcoming overrides');
    var body = f.body(countText) + (f.k === 'provider_timezones' ? tzExample(d) : '');
    return head + '<p>' + esc(body) + '</p>' +
      '<div class="opts">' + f.choices.map(function (c, i) {
        return '<label class="ax-check"><input type="radio" name="set-ask" value="' + c[0] + '"' + (i === 0 ? ' checked' : '') + '>' + esc(c[1]) + '</label>';
      }).join('') + '</div>' +
      '<div class="aff" id="set-aff" hidden>' + affectedHtml(f.k) + '</div>' +
      '<div class="acts"><button type="button" class="linkish" id="set-see">View affected items</button>' + acts(true);
  }

  function drawFeatures() {
    var el = $('set-features');
    if (!el || !state) return;
    var affOpen = $('set-aff') && !$('set-aff').hidden;
    el.innerHTML = FEATURES.map(function (f) {
      var on = state.features[f.k] !== false;
      // descHtml is fixed text written here, never data.
      return '<label class="ax-switchrow"><span class="ax-sw-text"><b>' + esc(f.name) + '</b><div class="ax-help">' + (f.descHtml || esc(f.desc)) + '</div>' +
        (on ? '' : '<div class="feat-state">Disabled</div>') + '</span>' +
        '<span class="ax-sw"><input type="checkbox" data-k="' + f.k + '"' + (on && asking !== f.k ? ' checked' : '') + ' aria-label="' + esc(f.name) + '"><span class="ax-sw-track"></span></span></label>' +
        (asking === f.k ? askHtml(f) : '');
    }).join('');
    el.querySelectorAll('.ax-sw input').forEach(function (c) { c.addEventListener('change', function () { onSwitch(c); }); });
    if (!asking) return;
    var aff = $('set-aff');
    if (aff) {
      if (affOpen) aff.hidden = false;
      $('set-see').textContent = aff.hidden ? 'View affected items' : 'Hide affected items';
      $('set-see').onclick = function () { aff.hidden = !aff.hidden; this.textContent = aff.hidden ? 'View affected items' : 'Hide affected items'; };
      aff.querySelectorAll('tr.prow').forEach(function (r) {
        r.addEventListener('click', function () { r.classList.toggle('open'); aff.querySelector('tr.drow[data-i="' + r.dataset.i + '"]').classList.toggle('open'); });
      });
    }
    $('set-ask-cancel').onclick = function () { asking = null; drawFeatures(); };
    $('set-ask-ok').onclick = function () {
      // With nothing on calendars there is no question; the first choice leaves nothing to undo.
      var picked = document.querySelector('#set-ask input[name="set-ask"]:checked');
      var f = FEATURES.find(function (x) { return x.k === asking; });
      changeFeature(asking, false, picked ? picked.value : f.choices[0][0]);
    };
  }

  function onSwitch(c) {
    var k = c.dataset.k;
    if (c.checked) {
      if (asking === k) { asking = null; drawFeatures(); return; }
      changeFeature(k, true, '');
      return;
    }
    asking = k;
    drawFeatures();
    if (!affectedCache[k]) loadAffected(k);
  }

  async function changeFeature(k, on, choice) {
    var f = FEATURES.find(function (x) { return x.k === k; });
    var res = await apiCall('/settings/features', { method: 'PUT', body: JSON.stringify({ feature: k, on: on, choice: choice }) });
    if (!res || res.error) { showMsg((res && res.error) || 'The change was not saved.', 'error'); asking = null; drawFeatures(); return; }
    asking = null;
    if (res.features) { state.features = res.features; preloaded().features = res.features; }
    delete affectedCache[k];
    applyFeatureVisibility();
    drawFeatures();
    drawTzNote();
    showMsg(f.name + (on ? ' enabled' : ' disabled'), 'success');
    if (k === 'facility_rounds' || k === 'facility_blocks') {
      // The facility lists, and the patient counts facility blocks show, depend on these switches.
      var fresh = await apiCall('/settings');
      if (fresh && !fresh.error) preloaded().facilities = { facilities: fresh.facilities || [], by_provider: fresh.provider_facilities || {} };
    }
    if (k === 'provider_timezones' || k === 'overrides' || k === 'facility_rounds' || k === 'facility_blocks') { try { loadOverview(); } catch (e) {} }
    if (k === 'facility_rounds') drawProviderFacilities();
  }

  // ── Provider facilities ───────────────────────────────────────────
  // One facility picker per provider. Suggestions load when a picker first opens,
  // and the provider's facilities save when it closes.
  var suggestions = {};   // provider id -> [{id, name, count}], or 'loading'
  var pfPickers = {};

  function drawProviderFacilities() {
    var on = state && state.features.facility_rounds !== false;
    $('set-providers-sub').textContent = on ? 'Roles, timezones, and facilities' : 'Schedulable roles and timezones';
    $('set-providers-pg-sub').textContent = on
      ? 'Configure which staff can be scheduled, their timezones, and the facilities they round at.'
      : 'Configure which staff can be scheduled and the timezone each provider works in.';
    drawTzNote();
    if (!on) return;
    // Each provider's row in the Timezones and facilities table (admin.js renderSettingsPanel)
    // has a cell for their facilities.
    flushProviderPickers();
    pfPickers = {};
    (_providers || []).forEach(function (p) {
      var pid = String(p.id);
      if (!$('pf-pick-' + pid)) return;
      var picker = FacilityPicker('pf-pick-' + pid, {
        all: function () { return paFacilities().facilities; },
        groups: function () { return pfGroups(pid); },
        onOpen: function () { loadSuggestions(pid); },
        onClose: function (ids) { saveProviderFacilities(pid, ids); }
      });
      picker.setValue(paFacilities().by_provider[pid] || []);
      pfPickers[pid] = picker;
    });
  }

  // Close any open provider facility picker, which saves its picks, before the pickers
  // or their rows are rebuilt. Only these pickers: an open round or block form's
  // Facility picker is left alone.
  function flushProviderPickers() {
    Object.keys(pfPickers).forEach(function (pid) { pfPickers[pid].closeIfOpen(); });
  }
  window.paFlushProviderPickers = flushProviderPickers;

  function pfGroups(pid) {
    var all = paFacilities().facilities;
    var sug = suggestions[pid];
    // Until suggestions arrive, the list is every facility.
    var top = (sug === 'loading' ? [] : sug || []).map(function (f) { return { id: f.id, name: f.name, count: f.patients + (f.patients === 1 ? ' patient' : ' patients') }; });
    var topIds = top.map(function (f) { return String(f.id); });
    var rest = all.filter(function (f) { return topIds.indexOf(String(f.id)) < 0; });
    return top.length ? [['Suggested from patients’ facilities', top], ['All facilities', rest]] : [['All facilities', rest]];
  }

  async function loadSuggestions(pid) {
    if (suggestions[pid]) return;
    suggestions[pid] = 'loading';
    var res = await apiCall('/settings/facility-suggestions/' + encodeURIComponent(pid));
    suggestions[pid] = (res && !res.error && res.suggestions) || [];
    if (pfPickers[pid]) pfPickers[pid].redraw();
  }

  // Each provider's newest save wins: a response that arrives after a later save was sent is ignored.
  var saveSeq = {};

  async function saveProviderFacilities(pid, ids) {
    var seq = (saveSeq[pid] || 0) + 1;
    saveSeq[pid] = seq;
    var res = await apiCall('/settings/provider-facilities', { method: 'PUT', body: JSON.stringify({ provider_id: pid, facility_ids: ids }) });
    if (saveSeq[pid] !== seq) return;
    if (!res || res.error) {
      showMsg((res && res.error) || 'The facilities were not saved.', 'error');
      if (pfPickers[pid]) pfPickers[pid].setValue(paFacilities().by_provider[pid] || []);
      return;
    }
    var byProvider = Object.assign({}, paFacilities().by_provider);
    if (res.facility_ids.length) byProvider[pid] = res.facility_ids; else delete byProvider[pid];
    preloaded().facilities = { facilities: paFacilities().facilities, by_provider: byProvider };
    // The row may have been rebuilt while this saved, showing the list from before; show what
    // saved. If it was reopened since, apply the changes made there on top of what saved.
    var picker = pfPickers[pid];
    if (picker) {
      var opened = picker.openedWith();
      var next = res.facility_ids.slice();
      if (opened) {
        var now = picker.getValue();
        now.forEach(function (id) { if (opened.indexOf(id) < 0 && next.indexOf(id) < 0) next.push(id); });
        next = next.filter(function (id) { return !(opened.indexOf(id) >= 0 && now.indexOf(id) < 0); });
      }
      picker.setValue(next);
    }
    showMsg('Facilities saved', 'success');
  }

  // ── New rule defaults ─────────────────────────────────────────────
  function drawDefaults() {
    if (!state) return;
    document.querySelectorAll('#set-defaults input[data-k]').forEach(function (i) { i.value = state.rule_defaults[i.dataset.k] || 0; });
    setDefaultsStatus('No unsaved changes', '');
    $('def-save').disabled = true;
  }
  function setDefaultsStatus(text, color) { var s = $('def-status'); s.textContent = text; s.style.color = color; }
  document.querySelectorAll('#set-defaults input[data-k]').forEach(function (i) {
    i.addEventListener('input', function () { defaultsDirty = true; _settingsDirty = true; $('def-save').disabled = false; setDefaultsStatus('Unsaved changes', '#9a5b00'); });
  });
  $('def-save').addEventListener('click', async function () {
    var body = {};
    document.querySelectorAll('#set-defaults input[data-k]').forEach(function (i) { body[i.dataset.k] = Number(i.value || 0); });
    var res = await apiCall('/settings/rule-defaults', { method: 'PUT', body: JSON.stringify(body) });
    if (!res || res.error) { setDefaultsStatus((res && res.error) || 'Not saved', '#c62828'); return; }
    state.rule_defaults = res.rule_defaults;
    preloaded().rule_defaults = res.rule_defaults;
    defaultsDirty = false;
    _settingsDirty = false;
    drawDefaults();
    setDefaultsStatus('Saved', '');
    showMsg('Defaults saved', 'success');
  });

  // ── Access control ────────────────────────────────────────────────
  function staffName(id) {
    var s = (state.staff || []).find(function (x) { return x.id === id; });
    return s ? s.name : id.slice(0, 8);
  }
  function providerList() {
    var seen = {};
    var list = (_providers || []).map(function (p) { seen[p.id] = true; return { id: String(p.id), name: p.name }; });
    (state.access.groups || []).forEach(function (g) { g.providers.forEach(function (pid) { if (!seen[pid]) { seen[pid] = true; list.push({ id: pid, name: staffName(pid) }); } }); });
    return list;
  }

  function teamName(id) {
    var t = (state.teams || []).find(function (x) { return x.id === id; });
    return t ? t.name : 'Unknown team';
  }

  function drawAccess() {
    if (!state) return;
    var a = state.access;
    var lv = a.default_access;
    var admins = state.admins || [];
    var secretIds = state.secret_admins || [];
    var everyone = state.admins_from === 'everyone';
    var line = function (label, names) { return '<div class="adm-line"><b>' + label + ':</b> ' + (names.length ? esc(names.join(', ')) : 'None') + '</div>'; };
    $('set-admin-members').innerHTML = everyone ? '' :
      line('Teams', (a.admin_team_ids || []).map(teamName)) + line('People', (a.admin_staff_ids || []).map(staffName));
    var secretNames = secretIds.map(staffName).join(', ');
    $('set-admin-note').textContent = everyone
      ? 'No admins are selected, so every staff member is an admin. Select admins to limit who can change Settings.'
      : state.admins_from === 'secret'
        ? 'No admins are selected. Admins come from the allowed-staff-keys plugin secret: ' + secretNames + '.'
        : (secretIds.length ? 'Always admins through the allowed-staff-keys plugin secret: ' + secretNames + '.' : '');
    var limited = lv !== 'full' || (a.groups || []).length > 0;
    $('set-access-status').innerHTML = limited ? '' :
      '<div class="rs warn"><b>Every staff member can edit every provider.</b>Create an editing group or change default access to limit editing.</div>';
    $('set-default-access').value = lv;
    $('set-default-hint').textContent = LEVELS[lv].hint;
  }

  async function saveAccess(body, message) {
    var res = await apiCall('/settings/access', { method: 'PUT', body: JSON.stringify(body) });
    if (!res || res.error) { showMsg((res && res.error) || 'The change was not saved.', 'error'); drawAccess(); return false; }
    showMsg(message, 'success');
    await open();
    return true;
  }
  $('set-default-access').addEventListener('change', function () {
    $('set-default-hint').textContent = LEVELS[this.value].hint;
    saveAccess({ default_access: this.value }, 'Everyone else set to ' + LEVELS[this.value].short.toLowerCase());
  });

  // Admins: Canvas teams and people, picked together and saved together.
  function openAdminEditor() {
    var a = state.access;
    var teams = (state.teams || []).map(function (t) { return { id: t.id, name: t.name, location_id: '' }; });
    $('set-edit-admins').style.display = 'none';
    $('set-admin-editor').innerHTML = '<div class="gedit"><div class="ax-cf-title" style="margin-bottom:4px">Edit admins</div>' +
      '<label class="ax-lbl">Teams</label><div class="pick" data-pick="admteam">' + teams.map(function (t) {
        return '<label class="ax-check"><input type="checkbox" value="' + esc(t.id) + '"' + ((a.admin_team_ids || []).indexOf(t.id) >= 0 ? ' checked' : '') + '>' + esc(t.name) + '</label>';
      }).join('') + '</div>' +
      '<label class="ax-lbl">People</label>' + pickerHtml('admstaff', state.staff || [], a.admin_staff_ids || []) +
      '<div class="save-row"><span class="status" id="set-adm-status"></span><button type="button" class="btn" id="set-adm-cancel">Cancel</button><button type="button" class="btn btn-primary" id="set-adm-save">Save admins</button></div></div>';
    wirePicker('admstaff');
    $('set-adm-cancel').onclick = closeAdminEditor;
    $('set-adm-save').onclick = async function () {
      var pick = function (key) { return Array.from(document.querySelectorAll('[data-pick="' + key + '"] input:checked')).map(function (i) { return i.value; }); };
      var ok = await saveAccess({ admin_team_ids: pick('admteam'), admin_staff_ids: pick('admstaff') }, 'Admins saved');
      if (ok) closeAdminEditor();
    };
  }
  function closeAdminEditor() { $('set-admin-editor').innerHTML = ''; $('set-edit-admins').style.display = ''; }
  $('set-edit-admins').addEventListener('click', openAdminEditor);

  // ── Editing groups ────────────────────────────────────────────────
  function drawGroups() {
    if (!state) return;
    var groups = state.access.groups || [];
    var grouped = {};
    groups.forEach(function (g) { g.providers.forEach(function (p) { grouped[p] = true; }); });
    var loose = providerList().filter(function (p) { return !grouped[p.id]; });
    var list = $('set-groups');
    list.style.display = groups.length ? '' : 'none';
    // An open group lists schedulers and providers side by side, up to NAME_CAP names each.
    function col(label, ids) {
      var rest = ids.length - NAME_CAP;
      return '<div class="gcol"><div class="lb">' + label + '</div><div class="toks">' +
        (ids.map(function (id, i) { return '<span class="tok"' + (i >= NAME_CAP ? ' hidden' : '') + '>' + esc(staffName(id)) + '</span>'; }).join('') ||
          '<span class="note" style="margin:0">None</span>') +
        (rest > 0 ? '<button type="button" class="gmore">+ ' + rest + ' more</button>' : '') + '</div></div>';
    }
    list.innerHTML = groups.map(function (g) {
      var open = openGroups[g.id];
      var html = '<div class="grow-row' + (open ? ' open' : '') + '" data-id="' + esc(g.id) + '">' + CHEVRON + '<span class="nm">' + esc(g.name) + '</span>' +
        '<span class="mt">' + plural(g.schedulers.length, 'scheduler', 'schedulers') + ' · ' + plural(g.providers.length, 'provider', 'providers') + '</span>' +
        '<span class="acts"><button type="button" class="lnk-sm" data-edit="' + esc(g.id) + '">Edit</button><button type="button" class="lnk-sm danger" data-del="' + esc(g.id) + '">Delete</button></span></div>' +
        '<div class="gbody' + (open ? ' open' : '') + '">' + col('Schedulers', g.schedulers) + col('Providers', g.providers) + '</div>';
      if (deletingGroup === g.id) {
        html += '<div class="ax-confirm"><div><div class="ax-cf-title">Delete ' + esc(g.name) + '?</div><p>Schedulers in this group will lose edit access to its providers.</p></div>' +
          '<button type="button" class="btn" data-del-cancel>Cancel</button><button type="button" class="btn btn-danger" data-del-ok="' + esc(g.id) + '">Delete</button></div>';
      }
      return html;
    }).join('');
    // Who can edit providers outside a group follows Everyone else.
    var lv = state.access.default_access;
    var names = loose.slice(0, 2).map(function (p) { return p.name; }).join(', ') + (loose.length > 2 ? ' + ' + (loose.length - 2) + ' more' : '');
    $('set-groups-loose').textContent = groups.length && loose.length
      ? plural(loose.length, 'provider isn\u2019t', 'providers aren\u2019t') + ' in a group: ' + names + '. ' +
        (lv === 'full'
          ? 'Only admins, the providers themselves, and staff who aren\u2019t in a group can edit them.'
          : 'Only admins and the providers themselves can edit them.')
      : '';
    list.querySelectorAll('.grow-row').forEach(function (r) {
      r.addEventListener('click', function (e) { if (e.target.closest('button')) return; openGroups[r.dataset.id] = !openGroups[r.dataset.id]; drawGroups(); });
    });
    list.querySelectorAll('.gmore').forEach(function (b) {
      b.addEventListener('click', function () { b.parentElement.querySelectorAll('.tok[hidden]').forEach(function (t) { t.hidden = false; }); b.remove(); });
    });
    list.querySelectorAll('[data-edit]').forEach(function (b) { b.addEventListener('click', function () { openEditor(b.dataset.edit); }); });
    list.querySelectorAll('[data-del]').forEach(function (b) { b.addEventListener('click', function () { deletingGroup = b.dataset.del; drawGroups(); }); });
    list.querySelectorAll('[data-del-cancel]').forEach(function (b) { b.addEventListener('click', function () { deletingGroup = null; drawGroups(); }); });
    list.querySelectorAll('[data-del-ok]').forEach(function (b) {
      b.addEventListener('click', async function () {
        var res = await apiCall('/settings/groups/' + encodeURIComponent(b.dataset.delOk), { method: 'DELETE' });
        deletingGroup = null;
        if (!res || res.error) { showMsg((res && res.error) || 'The group was not deleted.', 'error'); drawGroups(); return; }
        showMsg('Group deleted', 'success');
        await open();
      });
    });
  }

  // A picker: search, "Add everyone at <location>", select all / clear, and checkboxes.
  function pickerHtml(key, people, chosen) {
    var locs = state.locations || [];
    return '<div class="pick-tools">' +
      '<input class="input" type="search" placeholder="Search" data-search="' + key + '">' +
      '<select class="input" data-loc="' + key + '"><option value="">Add everyone at…</option>' +
      locs.map(function (l) { return '<option value="' + esc(l.id) + '">' + esc(l.name) + '</option>'; }).join('') + '</select>' +
      '<button type="button" class="lnk-sm" data-clear="' + key + '">Clear</button>' +
      '<span class="pick-count" data-count="' + key + '"></span><span class="pick-added" data-added="' + key + '"></span></div>' +
      '<div class="pick" data-pick="' + key + '">' + people.map(function (p) {
        return '<label class="ax-check" data-name="' + esc(p.name.toLowerCase()) + '" data-loc-id="' + esc(p.location_id || '') + '"><input type="checkbox" value="' + esc(p.id) + '"' +
          (chosen.indexOf(p.id) >= 0 ? ' checked' : '') + '>' + esc(p.name) + '</label>';
      }).join('') + '</div>';
  }

  function wirePicker(key) {
    var box = document.querySelector('[data-pick="' + key + '"]');
    var count = document.querySelector('[data-count="' + key + '"]');
    function recount() { count.textContent = box.querySelectorAll('input:checked').length + ' selected'; }
    box.addEventListener('change', recount);
    document.querySelector('[data-search="' + key + '"]').addEventListener('input', function () {
      var q = this.value.trim().toLowerCase();
      box.querySelectorAll('label').forEach(function (l) { l.style.display = !q || l.dataset.name.indexOf(q) >= 0 ? '' : 'none'; });
    });
    var addedNote = document.querySelector('[data-added="' + key + '"]');
    // A shortcut: selects everyone at the location, notes it, and resets so another location can be added.
    document.querySelector('[data-loc="' + key + '"]').addEventListener('change', function () {
      var loc = this.value;
      if (!loc) return;
      var where = this.options[this.selectedIndex].text;
      var added = 0;
      box.querySelectorAll('label[data-loc-id="' + CSS.escape(loc) + '"] input').forEach(function (i) { if (!i.checked) { i.checked = true; added++; } });
      addedNote.textContent = added ? 'Added ' + plural(added, 'person', 'people') + ' at ' + where : 'Everyone at ' + where + ' is already selected';
      this.value = '';
      recount();
    });
    document.querySelector('[data-clear="' + key + '"]').addEventListener('click', function () {
      box.querySelectorAll('input:checked').forEach(function (i) { i.checked = false; });
      addedNote.textContent = '';
      recount();
    });
    recount();
  }

  function openEditor(id) {
    editingGroup = id || '';
    var g = (state.access.groups || []).find(function (x) { return x.id === id; }) || { name: '', schedulers: [], providers: [] };
    var locById = {};
    (state.staff || []).forEach(function (s) { locById[s.id] = s.location_id; });
    var providers = providerList().map(function (p) { return { id: p.id, name: p.name, location_id: locById[p.id] || '' }; });
    $('set-group-editor').innerHTML = '<div class="gedit"><div class="ax-cf-title" style="margin-bottom:4px">' + (id ? 'Edit editing group' : 'New editing group') + '</div>' +
      '<label class="ax-lbl" for="set-grp-name">Group name</label><input class="input" id="set-grp-name" placeholder="Enter a group name" value="' + esc(g.name) + '" style="max-width:360px">' +
      '<label class="ax-lbl">Schedulers</label><div class="note" style="margin:-2px 0 8px">Staff who can manage the providers below. Providers already manage their own availability.</div>' + pickerHtml('sched', state.staff || [], g.schedulers) +
      '<label class="ax-lbl">Providers</label>' + pickerHtml('prov', providers, g.providers) +
      '<div class="save-row"><span class="status" id="set-grp-status"></span><button type="button" class="btn" id="set-grp-cancel">Cancel</button><button type="button" class="btn btn-primary" id="set-grp-save">Save group</button></div></div>';
    wirePicker('sched');
    wirePicker('prov');
    $('set-grp-name').focus();
    $('set-grp-cancel').onclick = closeEditor;
    $('set-grp-save').onclick = saveGroup;
  }

  function closeEditor() { editingGroup = null; $('set-group-editor').innerHTML = ''; }

  async function saveGroup() {
    var name = $('set-grp-name').value.trim();
    if (!name) { $('set-grp-name').focus(); $('set-grp-status').textContent = 'Group name is required.'; return; }
    var pick = function (key) { return Array.from(document.querySelectorAll('[data-pick="' + key + '"] input:checked')).map(function (i) { return i.value; }); };
    var body = JSON.stringify({ name: name, schedulers: pick('sched'), providers: pick('prov') });
    var res = editingGroup
      ? await apiCall('/settings/groups/' + encodeURIComponent(editingGroup), { method: 'PUT', body: body })
      : await apiCall('/settings/groups', { method: 'POST', body: body });
    if (!res || res.error) { $('set-grp-status').textContent = (res && res.error) || 'Not saved'; $('set-grp-status').style.color = '#c62828'; return; }
    closeEditor();
    showMsg('Group saved', 'success');
    await open();
  }
  $('set-new-group').addEventListener('click', function () { openEditor(''); });

  // ── Providers: the Timezones and facilities heading and note follow the switches ──
  function drawTzNote() {
    var desc = $('set-tz-desc');
    if (!desc || !state) return;
    var rounds = state.features.facility_rounds !== false;
    $('set-pv-title').textContent = rounds ? 'Timezones and facilities' : 'Timezones';
    var tz = state.features.provider_timezones === false
      ? 'Provider timezones are turned off in Scheduling, so every provider uses the practice timezone.'
      : 'Providers use the practice timezone unless one is set.';
    // Fixed text written here, never data.
    desc.innerHTML = esc(tz) + (rounds
      ? ' Their facilities are listed first in the <b>Facility</b> list when adding a round, and suggestions come from the facilities on their patients’ charts.'
      : '');
  }
  window.paDrawProviderFacilities = drawProviderFacilities;

  // ── Bulk import: keep the step header in step with admin.js ───────
  if (typeof bulkShowStep === 'function') {
    var origShowStep = bulkShowStep;
    window.bulkShowStep = function (step) {
      origShowStep(step);
      var order = ['upload', 'preview', 'results'];
      var at = order.indexOf(step);
      document.querySelectorAll('#set-import-steps li').forEach(function (li, i) {
        li.classList.toggle('on', i === at);
        li.classList.toggle('done', i < at);
      });
    };
  }

  window.paSettings = { open: open, showPage: showPage };
  if (typeof _activeTab !== 'undefined' && _activeTab === 'settings') open();
})();
