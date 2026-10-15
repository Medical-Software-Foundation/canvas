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
    { k: 'buffers', name: 'Appointment buffers', desc: 'Blocks time before and after appointments, as set on each rule.',
      title: 'Disable appointment buffers', noun: 'buffers',
      body: function (n) { return 'New appointments will no longer receive buffers. ' + n + ' currently on provider calendars.'; },
      choices: [['keep', 'Keep existing buffers until their appointments end'], ['remove', 'Remove existing buffers now']] },
    { k: 'lead_time', name: 'Lead time', desc: 'Blocks booking within each rule\'s minimum lead time.',
      title: 'Disable lead time', noun: 'lead time blocks',
      body: function (n) { return 'Lead time blocks will no longer be created. ' + n + ' currently on provider calendars.'; },
      choices: [['keep', 'Keep existing blocks until they expire'], ['remove', 'Remove existing blocks now']] },
    { k: 'holds', name: 'Same-day and next-day holds', desc: 'Reserves time that opens for booking the day before or the day of.',
      title: 'Disable same-day and next-day holds', noun: 'holds',
      body: function (n) { return 'The Hold rule type will be hidden, and holds will no longer refresh. ' + n + ' currently on provider calendars.'; },
      choices: [['keep', 'Keep existing holds until they end'], ['remove', 'Remove existing holds now']] },
    { k: 'overrides', name: 'Date overrides', desc: 'Changes a provider\'s hours on specific dates, such as holidays or half days.',
      title: 'Disable date overrides', noun: 'upcoming overrides',
      body: function (n) { return 'New date overrides can no longer be added. ' + n + ' change provider hours.'; },
      choices: [['keep', 'Continue applying existing overrides'], ['stop', 'Stop applying existing overrides (those dates revert to regular hours)']] },
    { k: 'provider_timezones', name: 'Provider timezones', desc: 'Allows a provider to work in a timezone other than the practice timezone.',
      title: 'Disable provider timezones', noun: 'providers with their own timezone',
      body: function (n) { return 'All providers will use the practice timezone. Hours for the ' + n + ' will move to the practice timezone.'; },
      choices: [['move', 'Move these providers to the practice timezone']] }
  ];
  var LEVELS = {
    full: { short: 'Full access', loose: 'Editable by admins and by staff outside a group' },
    view: { short: 'View access', loose: 'Editable by admins only' },
    none: { short: 'No access', loose: 'Editable by admins only' }
  };

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
    applyFeatureVisibility();
    drawFeatures();
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

  function askHtml(f) {
    var d = affectedCache[f.k];
    var countText = d ? d.total + ' ' + f.noun + (d.total === 1 ? ' is' : ' are') : 'Some ' + f.noun + ' are';
    if (f.k === 'provider_timezones') countText = d ? plural(d.total, 'provider with their own timezone', 'providers with their own timezone') : f.noun;
    if (f.k === 'overrides') countText = d ? plural(d.total, 'upcoming override', 'upcoming overrides') : 'Upcoming overrides';
    return '<div class="ax-ask" id="set-ask"><div class="ax-cf-title">' + esc(f.title) + '</div><p>' + esc(f.body(countText)) + '</p>' +
      '<div class="opts">' + f.choices.map(function (c, i) {
        return '<label class="ax-check"><input type="radio" name="set-ask" value="' + c[0] + '"' + (i === 0 ? ' checked' : '') + '>' + esc(c[1]) + '</label>';
      }).join('') + '</div>' +
      '<div class="aff" id="set-aff" hidden>' + affectedHtml(f.k) + '</div>' +
      '<div class="acts"><button type="button" class="linkish" id="set-see">View affected items</button><span style="flex:1"></span>' +
      '<button type="button" class="btn" id="set-ask-cancel">Cancel</button><button type="button" class="btn btn-primary" id="set-ask-ok">Disable</button></div></div>';
  }

  function drawFeatures() {
    var el = $('set-features');
    if (!el || !state) return;
    var affOpen = $('set-aff') && !$('set-aff').hidden;
    el.innerHTML = FEATURES.map(function (f) {
      var on = state.features[f.k] !== false;
      return '<label class="ax-switchrow"><span class="ax-sw-text"><b>' + esc(f.name) + '</b><div class="ax-help">' + esc(f.desc) + '</div>' +
        (on ? '' : '<div class="feat-state">Disabled</div>') + '</span>' +
        '<span class="ax-sw"><input type="checkbox" data-k="' + f.k + '"' + (on && asking !== f.k ? ' checked' : '') + ' aria-label="' + esc(f.name) + '"><span class="ax-sw-track"></span></span></label>' +
        (asking === f.k ? askHtml(f) : '');
    }).join('');
    el.querySelectorAll('.ax-sw input').forEach(function (c) { c.addEventListener('change', function () { onSwitch(c); }); });
    if (!asking) return;
    var aff = $('set-aff');
    if (affOpen) aff.hidden = false;
    $('set-see').textContent = aff.hidden ? 'View affected items' : 'Hide affected items';
    $('set-see').onclick = function () { aff.hidden = !aff.hidden; this.textContent = aff.hidden ? 'View affected items' : 'Hide affected items'; };
    aff.querySelectorAll('tr.prow').forEach(function (r) {
      r.addEventListener('click', function () { r.classList.toggle('open'); aff.querySelector('tr.drow[data-i="' + r.dataset.i + '"]').classList.toggle('open'); });
    });
    $('set-ask-cancel').onclick = function () { asking = null; drawFeatures(); };
    $('set-ask-ok').onclick = function () {
      var picked = document.querySelector('#set-ask input[name="set-ask"]:checked');
      changeFeature(asking, false, picked ? picked.value : '');
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
    if (k === 'provider_timezones' || k === 'overrides') { try { loadOverview(); } catch (e) {} }
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

  function drawAccess() {
    if (!state) return;
    var a = state.access;
    var lv = a.default_access;
    var teamSel = $('set-admin-team');
    teamSel.innerHTML = state.teams.map(function (t) { return '<option value="' + esc(t.id) + '"' + (t.id === a.admin_team_id ? ' selected' : '') + '>' + esc(t.name) + '</option>'; }).join('') +
      '<option value=""' + (a.admin_team_id ? '' : ' selected') + '>None</option>';
    $('set-admin-members').innerHTML = (state.admins || []).map(function (m) { return '<span class="tok">' + esc(m.name || m.id) + '</span>'; }).join('');
    $('set-admin-note').textContent = {
      team: 'If no team is selected, admins are read from the allowed-staff-keys plugin secret.',
      secret: 'No admin team selected. ' + plural((state.admins || []).length, 'staff member is', 'staff are') + ' listed in the allowed-staff-keys plugin secret.',
      everyone: 'No admin team selected and the allowed-staff-keys plugin secret is empty, so every staff member is an admin.'
    }[state.admins_from] || '';
    var limited = lv !== 'full' || (a.groups || []).length > 0;
    var summary = plural((state.admins || []).length, 'admin', 'admins') + ' · ' + plural((a.groups || []).length, 'editing group', 'editing groups') + ' · Default access: ' + LEVELS[lv].short;
    if (state.admins_from === 'everyone') summary = 'Every staff member is an admin · ' + plural((a.groups || []).length, 'editing group', 'editing groups') + ' · Default access: ' + LEVELS[lv].short;
    $('set-access-status').innerHTML = limited
      ? '<div class="rs ok"><b>Access control is configured.</b>' + esc(summary) + '</div>'
      : '<div class="rs warn"><b>All staff can edit every provider.</b>' + esc(summary) + '. Create editing groups or change default access to restrict editing.</div>';
    $('set-default-access').value = lv;
    $('set-how-group').textContent = lv === 'full' ? 'Only providers in their group' : 'Providers in their group';
    $('set-how-else').textContent = LEVELS[lv].short;
    $('set-groups-desc').textContent = lv === 'full'
      ? 'Schedulers in a group can edit only that group\'s providers. Staff outside a group can edit all providers.'
      : 'Schedulers in a group can edit that group\'s providers. Staff outside a group receive the default access level.';
  }

  async function saveAccess(body, message) {
    var res = await apiCall('/settings/access', { method: 'PUT', body: JSON.stringify(body) });
    if (!res || res.error) { showMsg((res && res.error) || 'The change was not saved.', 'error'); drawAccess(); return; }
    showMsg(message, 'success');
    await open();
  }
  $('set-admin-team').addEventListener('change', function () { saveAccess({ admin_team_id: this.value }, 'Admin team saved'); });
  $('set-default-access').addEventListener('change', function () { saveAccess({ default_access: this.value }, 'Default access set to ' + LEVELS[this.value].short.toLowerCase()); });

  // ── Editing groups ────────────────────────────────────────────────
  function drawGroups() {
    if (!state) return;
    var groups = state.access.groups || [];
    var grouped = {};
    groups.forEach(function (g) { g.providers.forEach(function (p) { grouped[p] = true; }); });
    var loose = providerList().filter(function (p) { return !grouped[p.id]; });
    var list = $('set-groups');
    list.style.display = groups.length ? '' : 'none';
    list.innerHTML = groups.map(function (g) {
      var open = openGroups[g.id];
      var html = '<div class="grow-row' + (open ? ' open' : '') + '" data-id="' + esc(g.id) + '"><span class="car">▸</span><span class="nm">' + esc(g.name) + '</span>' +
        '<span class="mt">' + plural(g.schedulers.length, 'scheduler', 'schedulers') + ' · ' + plural(g.providers.length, 'provider', 'providers') + '</span>' +
        '<span class="acts"><button type="button" class="lnk-sm" data-edit="' + esc(g.id) + '">Edit</button><button type="button" class="lnk-sm danger" data-del="' + esc(g.id) + '">Delete</button></span></div>' +
        '<div class="gbody' + (open ? ' open' : '') + '"><div class="lb">Schedulers</div><div class="toks" style="margin:0">' +
        (g.schedulers.map(function (id) { return '<span class="tok">' + esc(staffName(id)) + '</span>'; }).join('') || '<span class="note" style="margin:0">None</span>') +
        '</div><div class="lb">Providers</div><div class="toks" style="margin:0">' +
        (g.providers.map(function (id) { return '<span class="tok">' + esc(staffName(id)) + '</span>'; }).join('') || '<span class="note" style="margin:0">None</span>') + '</div></div>';
      if (deletingGroup === g.id) {
        html += '<div class="ax-confirm"><div><div class="ax-cf-title">Delete ' + esc(g.name) + '?</div><p>Schedulers in this group will lose edit access to its providers.</p></div>' +
          '<button type="button" class="btn" data-del-cancel>Cancel</button><button type="button" class="btn btn-danger" data-del-ok="' + esc(g.id) + '">Delete</button></div>';
      }
      return html;
    }).join('');
    var lv = state.access.default_access;
    $('set-groups-loose').textContent = groups.length
      ? (loose.length ? 'Not in a group: ' + loose.map(function (p) { return p.name; }).join(', ') + '. ' + LEVELS[lv].loose + '.' : '')
      : 'No editing groups. Staff who are not admins receive ' + LEVELS[lv].short.toLowerCase() + '.';
    list.querySelectorAll('.grow-row').forEach(function (r) {
      r.addEventListener('click', function (e) { if (e.target.closest('button')) return; openGroups[r.dataset.id] = !openGroups[r.dataset.id]; drawGroups(); });
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
      '<span class="pick-count" data-count="' + key + '"></span></div>' +
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
    document.querySelector('[data-loc="' + key + '"]').addEventListener('change', function () {
      var loc = this.value;
      if (!loc) return;
      var added = 0;
      box.querySelectorAll('label[data-loc-id="' + CSS.escape(loc) + '"] input').forEach(function (i) { if (!i.checked) { i.checked = true; added++; } });
      showMsg('Added ' + plural(added, 'person', 'people') + ' at ' + this.options[this.selectedIndex].text, 'success');
      this.value = '';
      recount();
    });
    document.querySelector('[data-clear="' + key + '"]').addEventListener('click', function () {
      box.querySelectorAll('input:checked').forEach(function (i) { i.checked = false; });
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
      '<label class="ax-lbl" for="set-grp-name">Group name</label><input class="input" id="set-grp-name" placeholder="e.g. Orange County" value="' + esc(g.name) + '" style="max-width:360px">' +
      '<label class="ax-lbl">Schedulers</label>' + pickerHtml('sched', state.staff || [], g.schedulers) +
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

  // ── Providers: timezones note when the feature is off ─────────────
  function drawTzNote() {
    var desc = $('set-tz-desc');
    if (!desc || !state) return;
    desc.textContent = state.features.provider_timezones === false
      ? 'Provider timezones are turned off in Scheduling, so every provider uses the practice timezone.'
      : 'Providers use the practice timezone unless a provider timezone is set.';
  }

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
