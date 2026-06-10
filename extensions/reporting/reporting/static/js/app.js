/* =========================================================
   Reporting SPA — Vanilla JS, no build step, no frameworks
   Named top-level functions for each concern.
   ========================================================= */

/* ===== Globals ===== */
var _datasets = null;        // cached GET /datasets result
var _editContext = null;     // { id, version } when editing a saved report
var _previewTimer = null;    // debounce handle
var _fieldOptionsCache = {}; // "<dataset>::<field>" -> [{value,label}] (live options)
var _libraryTab = 'reports'; // 'reports' | 'dashboards'
var _dashEditContext = null; // { id, version } when editing a saved dashboard
var _reportDefCache = {};    // report_id -> report object (for dashboard tile lazy loads)
var _dashPreviewTimer = null; // debounce handle for dashboard editor preview

/* ===== Utilities ===== */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function api(path, options) {
  var base = window.API_BASE;
  return fetch(base + path, options).then(function (r) {
    // Read as text first so an empty or non-JSON body (e.g. a 500 with no payload)
    // never throws "Unexpected end of JSON input".
    return r.text().then(function (text) {
      var body = {};
      if (text) {
        try { body = JSON.parse(text); } catch (e) { body = { error: text }; }
      } else if (!r.ok) {
        body = { error: 'Server error (HTTP ' + r.status + ')' };
      }
      return { status: r.status, ok: r.ok, body: body };
    });
  });
}

function categoryTagClass(cat) {
  var map = {
    operations: 'tag-operations',
    financial:  'tag-financial',
    clinical:   'tag-clinical',
    patients:   'tag-patients',
  };
  return map[(cat || '').toLowerCase()] || 'tag-other';
}

function formatNumber(val) {
  if (val === null || val === undefined) return '—';
  var n = Number(val);
  if (isNaN(n)) return escapeHtml(String(val));
  // If looks like a percentage (0–100 with decimals typical of rates)
  return n % 1 === 0 ? String(n) : n.toFixed(1);
}

function formatDelta(delta) {
  if (delta === null || delta === undefined) return { html: '—', cls: 'delta-zero' };
  var n = Number(delta);
  if (isNaN(n) || n === 0) return { html: '0', cls: 'delta-zero' };
  var sign = n > 0 ? '+' : '';
  var cls = n > 0 ? 'delta-pos' : 'delta-neg';
  return { html: sign + (n % 1 === 0 ? String(n) : n.toFixed(1)), cls: cls };
}

/* ===== View Router ===== */

function showLibrary() {
  _editContext = null;
  _dashEditContext = null;
  var view = document.getElementById('view');
  view.innerHTML = '<p class="muted" style="padding:24px">Loading…</p>';

  // Render the tab chrome immediately, then load the active tab's content.
  if (_libraryTab === 'reports') {
    setTopbarActions('<button class="btn btn-primary" onclick="showBuilder(null)">＋ New report</button>');
    api('/reports').then(function (res) {
      if (!res.ok) {
        renderLibraryShell('<p class="muted" style="padding:24px">Could not load reports.</p>');
        return;
      }
      renderLibraryShell(renderReportsTab(res.body.reports || []));
    });
  } else {
    setTopbarActions('<button class="btn btn-primary" onclick="showDashboardEditor(null)">＋ New dashboard</button>');
    api('/dashboards').then(function (res) {
      if (!res.ok) {
        renderLibraryShell('<p class="muted" style="padding:24px">Could not load dashboards.</p>');
        return;
      }
      renderLibraryShell(renderDashboardsTab(res.body.dashboards || []));
    });
  }
}

function setLibraryTab(tab) {
  _libraryTab = tab;
  showLibrary();
}

function renderLibraryShell(contentHtml) {
  var view = document.getElementById('view');
  var reportsActive = _libraryTab === 'reports' ? ' active' : '';
  var dashActive = _libraryTab === 'dashboards' ? ' active' : '';
  view.innerHTML =
    '<div class="lib-tabs">' +
      '<button class="lib-tab' + reportsActive + '" onclick="setLibraryTab(\'reports\')">Reports</button>' +
      '<button class="lib-tab' + dashActive + '" onclick="setLibraryTab(\'dashboards\')">Dashboards</button>' +
    '</div>' +
    contentHtml;
}

function renderReportsTab(reports) {
  if (reports.length === 0) {
    return (
      '<div class="empty-state">' +
        '<div class="empty-icon">📊</div>' +
        '<h3>No reports yet</h3>' +
        '<p>Create your first report to start exploring your data.</p>' +
        '<button class="btn btn-primary" onclick="showBuilder(null)">＋ New report</button>' +
      '</div>'
    );
  }
  var cards = reports.map(function (r) {
    var tagCls = categoryTagClass(r.category);
    var catLabel = r.category ? escapeHtml(r.category) : 'Uncategorized';
    var visCls = r.visibility === 'shared' ? 'shared' : '';
    var visLabel = r.visibility === 'shared' ? 'Shared' : 'Private';
    return (
      '<div class="report-card" onclick="showViewer(' + r.id + ')">' +
        '<div class="report-card-name">' + escapeHtml(r.name) + '</div>' +
        '<div class="report-card-meta">' +
          '<span class="tag ' + tagCls + '">' + catLabel + '</span>' +
          '<span class="vis-badge ' + visCls + '"><span class="dot"></span>' + visLabel + '</span>' +
        '</div>' +
      '</div>'
    );
  }).join('');
  return (
    '<div class="library-header"><h2>Reports</h2></div>' +
    '<div class="report-grid">' + cards + '</div>'
  );
}

function renderDashboardsTab(dashboards) {
  if (dashboards.length === 0) {
    return (
      '<div class="empty-state">' +
        '<div class="empty-icon">🗂️</div>' +
        '<h3>No dashboards yet</h3>' +
        '<p>Compose saved reports into a grid to monitor multiple metrics at a glance.</p>' +
        '<button class="btn btn-primary" onclick="showDashboardEditor(null)">＋ New dashboard</button>' +
      '</div>'
    );
  }
  var cards = dashboards.map(function (d) {
    var visCls = d.visibility === 'shared' ? 'shared' : '';
    var visLabel = d.visibility === 'shared' ? 'Shared' : 'Private';
    var widgetCount = d.widget_count !== undefined ? d.widget_count : 0;
    return (
      '<div class="report-card" onclick="showDashboardViewer(' + d.id + ')">' +
        '<div class="report-card-name">' + escapeHtml(d.name) + '</div>' +
        '<div class="report-card-meta">' +
          '<span class="dash-widget-count">' + widgetCount + ' widget' + (widgetCount === 1 ? '' : 's') + '</span>' +
          '<span class="vis-badge ' + visCls + '"><span class="dot"></span>' + visLabel + '</span>' +
        '</div>' +
      '</div>'
    );
  }).join('');
  return (
    '<div class="library-header"><h2>Dashboards</h2></div>' +
    '<div class="report-grid">' + cards + '</div>'
  );
}


/* ===== Builder ===== */

function showBuilder(reportId) {
  // reportId: null = new, number = edit existing
  setTopbarActions(
    '<button class="btn btn-ghost btn-sm" onclick="showLibrary()">← Back to Library</button>'
  );
  var view = document.getElementById('view');
  view.innerHTML = '<p class="muted" style="padding:24px">Loading builder…</p>';

  var datasetsPromise = _datasets
    ? Promise.resolve(_datasets)
    : api('/datasets').then(function (res) {
        if (res.ok) { _datasets = res.body.datasets || []; }
        return _datasets || [];
      });

  var reportPromise = reportId
    ? api('/reports/' + reportId).then(function (res) { return res.ok ? res.body : null; })
    : Promise.resolve(null);

  Promise.all([datasetsPromise, reportPromise]).then(function (results) {
    var datasets = results[0];
    var reportDetail = results[1];
    if (reportDetail) {
      _editContext = { id: reportDetail.id, version: reportDetail.version || 0 };
    } else {
      _editContext = null;
    }
    renderBuilder(datasets, reportDetail);
  });
}

function renderBuilder(datasets, reportDetail) {
  var view = document.getElementById('view');
  if (!datasets || datasets.length === 0) {
    view.innerHTML = '<p class="muted" style="padding:24px">No datasets available.</p>';
    return;
  }

  var def = reportDetail ? (reportDetail.definition || {}) : {};
  var defPeriod = def.period || {};
  var initialDatasetKey = def.dataset_key || datasets[0].key;
  var initialDataset = datasets.find(function (d) { return d.key === initialDatasetKey; }) || datasets[0];

  // Build dataset options
  var dsOptions = datasets.map(function (d) {
    var sel = d.key === initialDataset.key ? ' selected' : '';
    return '<option value="' + escapeHtml(d.key) + '"' + sel + '>' + escapeHtml(d.label) + '</option>';
  }).join('');

  // Build measure options
  var measureOptions = buildMeasureOptions(initialDataset, def.measure_key);
  // Build group-by options
  var groupByOptions = buildGroupByOptions(initialDataset, def.group_by);

  // Filters html
  var filtersHtml = buildFiltersHtml(initialDataset, def.filters || []);

  // Period defaults
  var granularity = defPeriod.granularity || 'month';
  var count = defPeriod.count !== undefined ? defPeriod.count : 3;
  var rolling12 = defPeriod.include_rolling_12 ? ' checked' : '';
  var rolling12Disabled = granularity !== 'month' ? ' disabled' : '';

  // Save bar defaults
  var repName = reportDetail ? escapeHtml(reportDetail.name || '') : '';
  var repCategory = reportDetail ? (reportDetail.category || '') : '';
  var repVisibility = reportDetail ? (reportDetail.visibility || 'private') : 'private';

  var categoryOptions = ['Operations', 'Financial', 'Clinical', 'Patients', 'Other'].map(function (c) {
    var sel = c.toLowerCase() === (repCategory || '').toLowerCase() ? ' selected' : '';
    return '<option value="' + c + '"' + sel + '>' + c + '</option>';
  }).join('');

  var visOpts = ['private', 'shared'].map(function (v) {
    var sel = v === repVisibility ? ' selected' : '';
    return '<option value="' + v + '"' + sel + '>' + (v === 'shared' ? 'Shared' : 'Private') + '</option>';
  }).join('');

  var visChoices = ['bar', 'compare_table', 'trend', 'kpi', 'table'].map(function (v) {
    var labels = { bar: 'Bar', compare_table: 'Compare', trend: 'Trend', kpi: 'KPI', table: 'Table' };
    var active = v === 'bar' ? ' active' : '';
    return '<button class="seg-btn' + active + '" data-vis="' + v + '" onclick="selectVis(this)">' + labels[v] + '</button>';
  }).join('');

  view.innerHTML =
    '<div class="builder-layout">' +
      '<div class="builder-steps">' +

        '<!-- Step 1: Data -->' +
        '<div class="step-card">' +
          '<div class="step-header open active" onclick="toggleStep(this)">' +
            '<div class="step-num">1</div>' +
            '<span class="step-title">Data</span>' +
            '<span class="step-chevron">▼</span>' +
          '</div>' +
          '<div class="step-body open">' +
            '<div class="form-group">' +
              '<label class="form-label">Dataset</label>' +
              '<select class="form-control" id="sel-dataset" onchange="onDatasetChange()">' + dsOptions + '</select>' +
            '</div>' +
          '</div>' +
        '</div>' +

        '<!-- Step 2: Filter -->' +
        '<div class="step-card">' +
          '<div class="step-header" onclick="toggleStep(this)">' +
            '<div class="step-num">2</div>' +
            '<span class="step-title">Filter to</span>' +
            '<span class="step-chevron">▼</span>' +
          '</div>' +
          '<div class="step-body">' +
            '<div class="filter-rows" id="filter-rows">' + filtersHtml + '</div>' +
            '<button class="add-filter-btn" onclick="addFilterRow()">＋ Add filter</button>' +
          '</div>' +
        '</div>' +

        '<!-- Step 3: Summarize -->' +
        '<div class="step-card">' +
          '<div class="step-header" onclick="toggleStep(this)">' +
            '<div class="step-num">3</div>' +
            '<span class="step-title">Summarize</span>' +
            '<span class="step-chevron">▼</span>' +
          '</div>' +
          '<div class="step-body">' +
            '<div class="form-group">' +
              '<label class="form-label">Measure</label>' +
              '<select class="form-control" id="sel-measure" onchange="schedulePreview()">' + measureOptions + '</select>' +
            '</div>' +
            '<div class="form-group">' +
              '<label class="form-label">Group by</label>' +
              '<select class="form-control" id="sel-groupby" onchange="schedulePreview()">' + groupByOptions + '</select>' +
            '</div>' +
            '<div class="divider"></div>' +
            '<div class="form-label" style="margin-bottom:8px">Compare over time</div>' +
            '<div class="period-row">' +
              '<div class="form-group">' +
                '<label class="form-label">Granularity</label>' +
                '<select class="form-control" id="sel-granularity" onchange="onGranularityChange()">' +
                  '<option value="month"' + (granularity === 'month' ? ' selected' : '') + '>Month</option>' +
                  '<option value="week"'  + (granularity === 'week'  ? ' selected' : '') + '>Week</option>' +
                  '<option value="quarter"' + (granularity === 'quarter' ? ' selected' : '') + '>Quarter</option>' +
                '</select>' +
              '</div>' +
              '<div class="form-group">' +
                '<label class="form-label">Periods</label>' +
                '<input class="form-control" id="inp-count" type="number" min="1" max="24" value="' + count + '" onchange="schedulePreview()" />' +
              '</div>' +
            '</div>' +
            '<label class="form-check">' +
              '<input type="checkbox" id="chk-rolling12"' + rolling12 + rolling12Disabled + ' onchange="schedulePreview()" />' +
              '<span>Rolling 12-month trend</span>' +
            '</label>' +
          '</div>' +
        '</div>' +

        '<!-- Step 4: Visualize -->' +
        '<div class="step-card">' +
          '<div class="step-header" onclick="toggleStep(this)">' +
            '<div class="step-num">4</div>' +
            '<span class="step-title">Visualize as</span>' +
            '<span class="step-chevron">▼</span>' +
          '</div>' +
          '<div class="step-body">' +
            '<div class="vis-toggle-row">' +
              '<div class="seg-toggle" id="vis-toggle">' + visChoices + '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +

        '<!-- Save Bar -->' +
        '<div class="save-bar">' +
          '<div class="form-group">' +
            '<label class="form-label">Report name</label>' +
            '<input class="form-control" id="inp-name" type="text" placeholder="e.g. No-show rate by provider" value="' + repName + '" />' +
          '</div>' +
          '<div class="save-bar-row">' +
            '<div class="form-group">' +
              '<label class="form-label">Category</label>' +
              '<select class="form-control" id="sel-category">' + categoryOptions + '</select>' +
            '</div>' +
            '<div class="form-group">' +
              '<label class="form-label">Visibility</label>' +
              '<select class="form-control" id="sel-visibility">' + visOpts + '</select>' +
            '</div>' +
          '</div>' +
          '<div class="save-bar-actions">' +
            '<button class="btn btn-ghost" onclick="showLibrary()">Cancel</button>' +
            '<button class="btn btn-primary" onclick="saveReport()">Save report</button>' +
          '</div>' +
        '</div>' +

      '</div>' +

      '<!-- Preview Panel -->' +
      '<div class="preview-panel">' +
        '<div class="preview-panel-header">' +
          '<h3>Preview</h3>' +
          '<div class="preview-status" id="preview-status"></div>' +
        '</div>' +
        '<div id="preview-content"><p class="preview-empty">Configure your report and a preview will appear here.</p></div>' +
      '</div>' +

    '</div>';

  // Load live option lists for any reference-field filters (edit mode), then preview.
  initFilterOptionSelects();
  if (reportDetail) {
    schedulePreview();
  }
}

function buildMeasureOptions(dataset, selectedKey) {
  return (dataset.measures || []).map(function (m) {
    var sel = m.key === selectedKey ? ' selected' : '';
    return '<option value="' + escapeHtml(m.key) + '"' + sel + '>' + escapeHtml(m.label) + '</option>';
  }).join('');
}

function buildGroupByOptions(dataset, selectedKey) {
  var noneSelected = (!selectedKey || selectedKey === '') ? ' selected' : '';
  var opts = '<option value=""' + noneSelected + '>None</option>';
  opts += (dataset.dimensions || []).map(function (d) {
    var sel = d.key === selectedKey ? ' selected' : '';
    return '<option value="' + escapeHtml(d.key) + '"' + sel + '>' + escapeHtml(d.label) + '</option>';
  }).join('');
  return opts;
}

function buildFiltersHtml(dataset, filters) {
  if (!filters || filters.length === 0) return '';
  return filters.map(function (f) {
    return buildFilterRowHtml(dataset, f);
  }).join('');
}

function fieldByKey(dataset, key) {
  return (dataset && dataset.fields || []).find(function (f) { return f.key === key; });
}

function currentDataset() {
  var sel = document.getElementById('sel-dataset');
  if (!sel) return null;
  return (_datasets || []).find(function (d) { return d.key === sel.value; }) || null;
}

function hasChoices(field) {
  return !!(field && field.choices && field.choices.length);
}

function hasOptions(field) {
  return !!(field && field.has_options);
}

function isMultiSelectField(field) {
  return hasChoices(field) || hasOptions(field);
}

// Fetch (and cache) the live (value,label) options for a reference field.
function fetchFieldOptions(datasetKey, fieldKey) {
  var key = datasetKey + '::' + fieldKey;
  if (_fieldOptionsCache[key]) return Promise.resolve(_fieldOptionsCache[key]);
  return api('/field-options?dataset=' + encodeURIComponent(datasetKey) +
             '&field=' + encodeURIComponent(fieldKey)).then(function (res) {
    var opts = (res.ok && res.body && res.body.options) ? res.body.options : [];
    _fieldOptionsCache[key] = opts;
    return opts;
  });
}

// Populate a "Loading…" options multi-select with live data, preselecting data-selected.
function fillOptionsSelect(selectEl) {
  var ds = currentDataset();
  var fieldKey = selectEl.getAttribute('data-options-field');
  if (!ds || !fieldKey) return;
  var selected = [];
  try { selected = JSON.parse(selectEl.getAttribute('data-selected') || '[]'); } catch (e) {}
  fetchFieldOptions(ds.key, fieldKey).then(function (opts) {
    if (!opts.length) {
      selectEl.innerHTML = '<option disabled>No values found</option>';
      return;
    }
    selectEl.innerHTML = opts.map(function (o) {
      var sel = selected.indexOf(o.value) !== -1 ? ' selected' : '';
      return '<option value="' + escapeHtml(o.value) + '"' + sel + '>' + escapeHtml(o.label) + '</option>';
    }).join('');
  });
}

function initFilterOptionSelects() {
  var sels = document.querySelectorAll('#filter-rows [data-options-field]');
  Array.prototype.forEach.call(sels, function (sel) { fillOptionsSelect(sel); });
}

// Operator control: dropdown fields (enum OR reference) are always "is any of";
// other fields show their declared operators.
function buildOpControl(field, existing) {
  existing = existing || {};
  if (isMultiSelectField(field)) {
    return '<span class="filter-op-fixed">is any of</span>' +
           '<input type="hidden" data-role="filter-op" value="is_one_of" />';
  }
  var opOptions = (field ? field.operators || [] : []).map(function (op) {
    var sel = op === existing.operator ? ' selected' : '';
    return '<option value="' + escapeHtml(op) + '"' + sel + '>' + escapeHtml(op.replace(/_/g, ' ')) + '</option>';
  }).join('');
  return '<select class="form-control" data-role="filter-op" onchange="schedulePreview()">' + opOptions + '</select>';
}

// Value control: enum fields -> multi-select of choices; reference fields -> a
// multi-select populated from live data; other fields -> a free-text box.
function buildValueControl(field, existing) {
  existing = existing || {};
  var vals = existing.values || [];
  if (hasChoices(field)) {
    var opts = field.choices.map(function (c) {
      var sel = vals.indexOf(c.value) !== -1 ? ' selected' : '';
      return '<option value="' + escapeHtml(c.value) + '"' + sel + '>' + escapeHtml(c.label) + '</option>';
    }).join('');
    return '<select class="form-control filter-multi" data-role="filter-val" multiple size="5" onchange="schedulePreview()">' + opts + '</select>';
  }
  if (hasOptions(field)) {
    var selJson = escapeHtml(JSON.stringify(vals));
    return '<select class="form-control filter-multi" data-role="filter-val" data-options-field="' +
      escapeHtml(field.key) + '" data-selected="' + selJson +
      '" multiple size="5" onchange="schedulePreview()"><option disabled>Loading…</option></select>';
  }
  var valStr = vals.join(', ');
  return '<input class="form-control" data-role="filter-val" type="text" placeholder="value" value="' + escapeHtml(valStr) + '" onchange="schedulePreview()" />';
}

function buildFilterRowHtml(dataset, existing) {
  existing = existing || {};
  var placeholderSel = existing.field ? '' : ' selected';
  var fieldOptions = '<option value=""' + placeholderSel + '>Select a field…</option>' +
    (dataset.fields || []).map(function (f) {
      var sel = f.key === existing.field ? ' selected' : '';
      return '<option value="' + escapeHtml(f.key) + '"' + sel + '>' + escapeHtml(f.label) + '</option>';
    }).join('');

  var selectedField = existing.field ? fieldByKey(dataset, existing.field) : null;
  var controlsInner = selectedField
    ? (buildOpControl(selectedField, existing) + buildValueControl(selectedField, existing))
    : '';

  return (
    '<div class="filter-row">' +
      '<select class="form-control" data-role="filter-field" onchange="onFilterFieldChange(this)">' +
        fieldOptions +
      '</select>' +
      '<span class="filter-controls" data-role="filter-controls">' + controlsInner + '</span>' +
      '<button class="btn-icon" onclick="removeFilterRow(this)" title="Remove filter">✕</button>' +
    '</div>'
  );
}

function onDatasetChange() {
  var dsKey = document.getElementById('sel-dataset').value;
  var dataset = (_datasets || []).find(function (d) { return d.key === dsKey; });
  if (!dataset) return;

  // Rebuild filter rows with new dataset fields
  document.getElementById('filter-rows').innerHTML = '';

  // Rebuild measure + groupby selects
  var measureSel = document.getElementById('sel-measure');
  if (measureSel) measureSel.innerHTML = buildMeasureOptions(dataset, null);

  var groupBySel = document.getElementById('sel-groupby');
  if (groupBySel) groupBySel.innerHTML = buildGroupByOptions(dataset, null);

  schedulePreview();
}

function onFilterFieldChange(selectEl) {
  var row = selectEl.closest('.filter-row');
  if (!row) return;
  var dataset = currentDataset();
  var field = dataset ? fieldByKey(dataset, selectEl.value) : null;
  var controls = row.querySelector('[data-role="filter-controls"]');
  if (controls) {
    if (!field) {
      controls.innerHTML = '';  // "Select a field…" placeholder -> no value control yet
    } else {
      controls.innerHTML = buildOpControl(field, {}) + buildValueControl(field, {});
      var optSel = controls.querySelector('[data-options-field]');
      if (optSel) fillOptionsSelect(optSel);  // reference field -> load live options
    }
  }
  schedulePreview();
}

function onGranularityChange() {
  var gran = document.getElementById('sel-granularity').value;
  var chk = document.getElementById('chk-rolling12');
  if (chk) {
    chk.disabled = gran !== 'month';
    if (gran !== 'month') chk.checked = false;
  }
  schedulePreview();
}

function addFilterRow() {
  var dsKey = document.getElementById('sel-dataset').value;
  var dataset = (_datasets || []).find(function (d) { return d.key === dsKey; });
  if (!dataset || !dataset.fields || dataset.fields.length === 0) return;
  var rows = document.getElementById('filter-rows');
  var div = document.createElement('div');
  div.innerHTML = buildFilterRowHtml(dataset, null);
  // New rows open with the "Select a field…" placeholder and no value control;
  // controls appear once the user picks a field (onFilterFieldChange).
  rows.appendChild(div.firstChild);
}

function removeFilterRow(btn) {
  var row = btn.closest('.filter-row');
  if (row) row.parentNode.removeChild(row);
  schedulePreview();
}

function toggleStep(header) {
  var isOpen = header.classList.contains('open');
  header.classList.toggle('open', !isOpen);
  var body = header.nextElementSibling;
  if (body && body.classList.contains('step-body')) {
    body.classList.toggle('open', !isOpen);
  }
}

function selectVis(btn) {
  var toggle = document.getElementById('vis-toggle');
  if (!toggle) return;
  toggle.querySelectorAll('.seg-btn').forEach(function (b) { b.classList.remove('active'); });
  btn.classList.add('active');
  schedulePreview();
}

function schedulePreview() {
  clearTimeout(_previewTimer);
  _previewTimer = setTimeout(runPreview, 300);
}

function collectDefinition() {
  var dsKey = document.getElementById('sel-dataset');
  var measureSel = document.getElementById('sel-measure');
  var groupBySel = document.getElementById('sel-groupby');
  var granSel = document.getElementById('sel-granularity');
  var countInp = document.getElementById('inp-count');
  var rolling12Chk = document.getElementById('chk-rolling12');

  if (!dsKey || !measureSel) return null;

  // Collect filters
  var filters = [];
  var filterRows = document.querySelectorAll('#filter-rows .filter-row');
  filterRows.forEach(function (row) {
    var fieldEl = row.querySelector('[data-role="filter-field"]');
    if (!fieldEl || !fieldEl.value) return;  // no field chosen yet
    var opEl = row.querySelector('[data-role="filter-op"]');
    var valEl = row.querySelector('[data-role="filter-val"]');
    if (!opEl || !valEl) return;
    var operator = opEl.value;
    var values;
    if (valEl.tagName === 'SELECT' && valEl.multiple) {
      values = Array.prototype.map.call(valEl.selectedOptions, function (o) { return o.value; });
    } else {
      var rawVal = valEl.value.trim();
      values = operator === 'is_one_of'
        ? rawVal.split(',').map(function (v) { return v.trim(); }).filter(Boolean)
        : (rawVal ? [rawVal] : []);
    }
    if (!values.length) return;  // skip a filter with no value(s) chosen
    filters.push({ field: fieldEl.value, operator: operator, values: values });
  });

  var groupByVal = groupBySel ? groupBySel.value : '';
  var granularity = granSel ? granSel.value : 'month';
  var count = countInp ? Math.max(1, parseInt(countInp.value, 10) || 3) : 3;
  var rolling12 = rolling12Chk ? rolling12Chk.checked : false;

  return {
    dataset_key: dsKey.value,
    measure_key: measureSel.value,
    group_by: groupByVal || null,
    filters: filters,
    period: {
      granularity: granularity,
      count: count,
      include_rolling_12: rolling12,
    },
  };
}

function runPreview() {
  var def = collectDefinition();
  if (!def) return;

  var statusEl = document.getElementById('preview-status');
  var contentEl = document.getElementById('preview-content');
  if (!statusEl || !contentEl) return;

  statusEl.innerHTML = '<span class="spinner"></span> Loading…';
  contentEl.innerHTML = '';

  api('/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(def),
  }).then(function (res) {
    statusEl.innerHTML = '';
    if (!res.ok) {
      contentEl.innerHTML = '<div class="preview-error">Error: ' + escapeHtml((res.body && res.body.error) || 'Request failed') + '</div>';
      return;
    }
    var visBtn = document.querySelector('#vis-toggle .seg-btn.active');
    var visType = visBtn ? visBtn.getAttribute('data-vis') : 'bar';
    contentEl.innerHTML = renderVisualization(visType, res.body);
  }).catch(function (err) {
    if (statusEl) statusEl.innerHTML = '';
    if (contentEl) contentEl.innerHTML = '<div class="preview-error">Error: ' + escapeHtml(err.message) + '</div>';
  });
}

function saveReport() {
  var def = collectDefinition();
  if (!def) return;

  var nameInp = document.getElementById('inp-name');
  var catSel = document.getElementById('sel-category');
  var visSel = document.getElementById('sel-visibility');

  var name = nameInp ? nameInp.value.trim() : '';
  if (!name) { nameInp && nameInp.focus(); return; }

  var body = {
    name: name,
    category: catSel ? catSel.value : '',
    visibility: visSel ? visSel.value : 'private',
    definition: def,
  };

  var saveBtn = document.querySelector('.save-bar .btn-primary');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }

  var promise = _editContext
    ? api('/reports/' + _editContext.id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({}, body, { version: _editContext.version })),
      })
    : api('/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

  promise.then(function (res) {
    if (res.ok) {
      showLibrary();
    } else {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save report'; }
      var msg = (res.body && res.body.error) || ('Save failed (HTTP ' + res.status + ')');
      alert(msg);
    }
  }).catch(function (err) {
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save report'; }
    alert('Save failed: ' + err.message);
  });
}

/* ===== Viewer ===== */

function showViewer(reportId) {
  setTopbarActions(
    '<button class="btn btn-ghost btn-sm" onclick="showLibrary()">← Back to Library</button>'
  );
  var view = document.getElementById('view');
  view.innerHTML = '<p class="muted" style="padding:24px">Loading report…</p>';

  api('/reports/' + reportId).then(function (res) {
    if (!res.ok) {
      view.innerHTML = '<p class="muted" style="padding:24px">Report not found.</p>';
      return;
    }
    var report = res.body;
    var def = report.definition || {};

    // Run the report
    api('/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(def),
    }).then(function (runRes) {
      renderViewer(report, runRes.ok ? runRes.body : null, runRes.ok ? null : (runRes.body && runRes.body.error));
    }).catch(function (err) {
      renderViewer(report, null, err.message);
    });
  });
}

function renderViewer(report, runResult, error) {
  var view = document.getElementById('view');
  var tagCls = categoryTagClass(report.category);
  var catLabel = report.category ? escapeHtml(report.category) : 'Uncategorized';

  var contentHtml;
  if (error) {
    contentHtml = '<div class="preview-error">Error running report: ' + escapeHtml(error) + '</div>';
  } else if (runResult) {
    var def = report.definition || {};
    var period = def.period || {};
    // Default visualization: trend if multiple periods, else table
    var defaultVis = (period.count && period.count > 1) ? 'trend' : 'table';
    contentHtml = renderVisualization(defaultVis, runResult);
  } else {
    contentHtml = '<p class="preview-empty">No data.</p>';
  }

  view.innerHTML =
    '<div class="viewer-header">' +
      '<div class="viewer-title">' +
        '<h2>' + escapeHtml(report.name) + '</h2>' +
        '<div>' +
          '<span class="tag ' + tagCls + '">' + catLabel + '</span>' +
        '</div>' +
      '</div>' +
      '<div class="viewer-actions">' +
        '<button class="btn btn-secondary" onclick="showBuilder(' + escapeHtml(String(report.id)) + ')">Edit</button>' +
        '<button class="btn btn-danger" onclick="deleteReport(' + escapeHtml(String(report.id)) + ')">Delete</button>' +
      '</div>' +
    '</div>' +
    '<div class="viewer-card">' + contentHtml + '</div>';
}

function deleteReport(reportId) {
  if (!confirm('Delete this report? This cannot be undone.')) return;
  api('/reports/' + reportId, { method: 'DELETE' }).then(function (res) {
    if (res.ok) {
      showLibrary();
    } else {
      alert('Could not delete report.');
    }
  });
}

/* ===== Visualization Dispatcher ===== */

function renderVisualization(type, result) {
  if (!result || !result.rows) return '<p class="preview-empty">No data returned.</p>';
  switch (type) {
    case 'bar':           return renderBar(result);
    case 'compare_table': return renderCompareTable(result);
    case 'trend':         return renderTrend(result);
    case 'kpi':           return renderKpi(result);
    case 'table':
    default:              return renderTable(result);
  }
}

/* ===== Visualization Renderers ===== */

function renderTable(result) {
  var periods = result.periods || [];
  var rows = result.rows || [];

  if (rows.length === 0) return '<p class="preview-empty">No data for this period.</p>';

  var headerCols = periods.map(function (p) {
    return '<th class="num">' + escapeHtml(String(p)) + '</th>';
  }).join('');

  var bodyRows = rows.map(function (row) {
    var cells = periods.map(function (p) {
      return '<td class="num">' + formatNumber(row.values[p]) + '</td>';
    }).join('');
    return '<tr><td>' + escapeHtml(row.group_label) + '</td>' + cells + '</tr>';
  }).join('');

  return (
    '<div class="overflow-wrap">' +
      '<table class="data-table">' +
        '<thead><tr><th>' + escapeHtml(result.group_by || 'Group') + '</th>' + headerCols + '</tr></thead>' +
        '<tbody>' + bodyRows + '</tbody>' +
      '</table>' +
    '</div>'
  );
}

function renderCompareTable(result) {
  var periods = result.periods || [];
  var rows = result.rows || [];

  if (rows.length === 0) return '<p class="preview-empty">No data for this period.</p>';

  var headerCols = periods.map(function (p) {
    return '<th class="num">' + escapeHtml(String(p)) + '</th>';
  }).join('');
  var deltaHeader = periods.length >= 2 ? '<th class="num">Δ vs prior</th>' : '';

  var bodyRows = rows.map(function (row) {
    var cells = periods.map(function (p) {
      return '<td class="num">' + formatNumber(row.values[p]) + '</td>';
    }).join('');

    var deltaCell = '';
    if (periods.length >= 2) {
      var last = row.values[periods[periods.length - 1]];
      var prev = row.values[periods[periods.length - 2]];
      var delta = (last !== null && last !== undefined && prev !== null && prev !== undefined)
        ? Number(last) - Number(prev)
        : null;
      var d = formatDelta(delta);
      deltaCell = '<td class="num ' + d.cls + '">' + d.html + '</td>';
    }

    return '<tr><td>' + escapeHtml(row.group_label) + '</td>' + cells + deltaCell + '</tr>';
  }).join('');

  return (
    '<div class="overflow-wrap">' +
      '<table class="data-table">' +
        '<thead><tr><th>' + escapeHtml(result.group_by || 'Group') + '</th>' + headerCols + deltaHeader + '</tr></thead>' +
        '<tbody>' + bodyRows + '</tbody>' +
      '</table>' +
    '</div>'
  );
}

function renderBar(result) {
  var periods = result.periods || [];
  var rows = result.rows || [];

  if (rows.length === 0) return '<p class="preview-empty">No data for this period.</p>';

  // Find max value across all rows + periods for scaling
  var maxVal = 0;
  rows.forEach(function (row) {
    periods.forEach(function (p) {
      var v = Number(row.values[p] || 0);
      if (v > maxVal) maxVal = v;
    });
  });
  if (maxVal === 0) maxVal = 1;

  // Color palette for periods: gradient from muted to primary to secondary
  function barColor(periodIdx, totalPeriods) {
    if (totalPeriods <= 1) return 'var(--primary)';
    var t = totalPeriods === 1 ? 1 : periodIdx / (totalPeriods - 1);
    // Interpolate opacity: oldest = 40%, newest = 100%
    var opacity = 0.3 + 0.7 * t;
    return 'rgba(1, 164, 255, ' + opacity.toFixed(2) + ')';
  }

  var html = '<div class="bar-chart">';
  rows.forEach(function (row) {
    html += '<div class="bar-group">';
    html += '<div class="bar-group-label">' + escapeHtml(row.group_label) + '</div>';
    periods.forEach(function (p, i) {
      var val = Number(row.values[p] !== null && row.values[p] !== undefined ? row.values[p] : 0);
      var pct = maxVal > 0 ? (val / maxVal * 100).toFixed(1) : 0;
      var color = barColor(i, periods.length);
      html +=
        '<div class="bar-track-row">' +
          '<span class="bar-period-label" title="' + escapeHtml(String(p)) + '">' + escapeHtml(String(p)) + '</span>' +
          '<div class="bar-track">' +
            '<div class="bar-fill" style="width:' + pct + '%;background:' + color + '"></div>' +
          '</div>' +
          '<span class="bar-value">' + formatNumber(val) + '</span>' +
        '</div>';
    });
    html += '</div>';
  });
  html += '</div>';
  return html;
}

function renderTrend(result) {
  var periods = result.periods || [];
  var rows = result.rows || [];

  if (rows.length === 0 || periods.length === 0) return '<p class="preview-empty">No data for this period.</p>';

  var MAX_GROUPS = 8;
  var truncated = rows.length > MAX_GROUPS;
  var visibleRows = truncated ? rows.slice(0, MAX_GROUPS) : rows;

  // SVG dimensions
  var svgW = 600;
  var svgH = 240;
  var padTop = 16, padBottom = 36, padLeft = 52, padRight = 16;
  var chartW = svgW - padLeft - padRight;
  var chartH = svgH - padTop - padBottom;

  // Find max value
  var maxVal = 0;
  visibleRows.forEach(function (row) {
    periods.forEach(function (p) {
      var v = Number(row.values[p] || 0);
      if (v > maxVal) maxVal = v;
    });
  });
  if (maxVal === 0) maxVal = 1;

  // Color palette for groups
  var palette = [
    '#01A4FF', '#01ECFF', '#55F7A9', '#FFA24C', '#8041D0',
    '#02E3FB', '#FF6B6B', '#F7D155'
  ];

  function xPos(i) {
    return padLeft + (periods.length === 1 ? chartW / 2 : i * chartW / (periods.length - 1));
  }
  function yPos(val) {
    return padTop + chartH - (val / maxVal) * chartH;
  }

  var svg = '<svg viewBox="0 0 ' + svgW + ' ' + svgH + '" xmlns="http://www.w3.org/2000/svg" style="overflow:visible">';

  // X-axis gridlines + labels
  periods.forEach(function (p, i) {
    var x = xPos(i);
    svg += '<line x1="' + x + '" y1="' + padTop + '" x2="' + x + '" y2="' + (padTop + chartH) + '" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>';
    svg += '<text x="' + x + '" y="' + (padTop + chartH + 14) + '" text-anchor="middle" fill="#8496AA" font-size="10">' + escapeHtml(String(p)) + '</text>';
  });

  // Y-axis ticks (5 levels)
  for (var tick = 0; tick <= 4; tick++) {
    var yVal = (maxVal * tick / 4);
    var yPx = yPos(yVal);
    svg += '<line x1="' + padLeft + '" y1="' + yPx + '" x2="' + (padLeft + chartW) + '" y2="' + yPx + '" stroke="rgba(255,255,255,0.04)" stroke-width="1"/>';
    svg += '<text x="' + (padLeft - 6) + '" y="' + (yPx + 4) + '" text-anchor="end" fill="#8496AA" font-size="10">' + formatNumber(yVal) + '</text>';
  }

  // Polylines
  visibleRows.forEach(function (row, ri) {
    var color = palette[ri % palette.length];
    var points = periods.map(function (p, i) {
      var val = Number(row.values[p] !== null && row.values[p] !== undefined ? row.values[p] : 0);
      return xPos(i) + ',' + yPos(val);
    }).join(' ');
    svg += '<polyline points="' + points + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';

    // Dots
    periods.forEach(function (p, i) {
      var val = Number(row.values[p] !== null && row.values[p] !== undefined ? row.values[p] : 0);
      svg += '<circle cx="' + xPos(i) + '" cy="' + yPos(val) + '" r="3" fill="' + color + '"/>';
    });
  });

  svg += '</svg>';

  // Legend
  var legend = '<div class="trend-legend">';
  visibleRows.forEach(function (row, ri) {
    var color = palette[ri % palette.length];
    legend += '<div class="trend-legend-item"><div class="trend-legend-dot" style="background:' + color + '"></div>' + escapeHtml(row.group_label) + '</div>';
  });
  legend += '</div>';

  var truncationNote = truncated
    ? '<p class="trend-truncation">Showing first ' + MAX_GROUPS + ' of ' + rows.length + ' groups.</p>'
    : '';

  return '<div class="trend-chart">' + svg + '</div>' + legend + truncationNote;
}

function renderKpi(result) {
  var periods = result.periods || [];
  var rows = result.rows || [];

  if (rows.length === 0 || periods.length === 0) return '<p class="preview-empty">No data for this period.</p>';

  var lastPeriod = periods[periods.length - 1];
  var prevPeriod = periods.length >= 2 ? periods[periods.length - 2] : null;

  var tiles = rows.map(function (row) {
    var latestVal = row.values[lastPeriod];
    var prevVal = prevPeriod !== null ? row.values[prevPeriod] : null;

    var delta = (latestVal !== null && latestVal !== undefined && prevVal !== null && prevVal !== undefined)
      ? Number(latestVal) - Number(prevVal)
      : null;
    var d = formatDelta(delta);

    return (
      '<div class="kpi-tile">' +
        '<div class="kpi-label">' + escapeHtml(row.group_label) + '</div>' +
        '<div class="kpi-value">' + formatNumber(latestVal) + '</div>' +
        (delta !== null ? '<div class="kpi-delta ' + d.cls + '">' + d.html + ' vs prior</div>' : '') +
      '</div>'
    );
  }).join('');

  return '<div class="kpi-tiles">' + tiles + '</div>';
}

/* ===== Dashboard Viewer ===== */

function showDashboardViewer(id) {
  _libraryTab = 'dashboards';
  setTopbarActions(
    '<button class="btn btn-ghost btn-sm" onclick="setLibraryTab(\'dashboards\')">← Back to Library</button>'
  );
  var view = document.getElementById('view');
  view.innerHTML = '<p class="muted" style="padding:24px">Loading dashboard…</p>';

  api('/dashboards/' + id).then(function (res) {
    if (!res.ok) {
      view.innerHTML = '<p class="muted" style="padding:24px">Dashboard not found.</p>';
      return;
    }
    renderDashboardViewer(res.body, res.body.default_period || {});
  });
}

function defaultVizForPeriod(period) {
  return (period && period.count && period.count > 1) ? 'trend' : 'table';
}

function renderDashboardViewer(dashboard, overridePeriod) {
  var view = document.getElementById('view');
  var visCls = dashboard.visibility === 'shared' ? 'shared' : '';
  var visLabel = dashboard.visibility === 'shared' ? 'Shared' : 'Private';
  var period = overridePeriod || dashboard.default_period || {};

  var granularity = period.granularity || 'month';
  var count = period.count !== undefined ? period.count : 3;
  var rolling12 = period.include_rolling_12 ? true : false;

  var granOptions = ['month', 'week', 'quarter'].map(function (g) {
    var sel = g === granularity ? ' selected' : '';
    var label = g.charAt(0).toUpperCase() + g.slice(1);
    return '<option value="' + g + '"' + sel + '>' + label + '</option>';
  }).join('');

  var widgets = (dashboard.layout && dashboard.layout.widgets) ? dashboard.layout.widgets : [];

  var tilesHtml = widgets.map(function (w, idx) {
    return (
      '<div class="dash-tile" style="grid-column:span ' + (w.span || 2) + '"' +
        ' data-report-id="' + Number(w.report_id) + '"' +
        ' data-viz="' + escapeHtml(w.viz || '') + '"' +
        ' data-tile-idx="' + idx + '">' +
        '<div class="dash-tile-header" id="dash-tile-name-' + idx + '">Loading…</div>' +
        '<div class="dash-tile-body" id="dash-tile-body-' + idx + '"><p class="preview-empty">Loading…</p></div>' +
      '</div>'
    );
  }).join('');

  view.innerHTML =
    '<div class="viewer-header">' +
      '<div class="viewer-title">' +
        '<h2>' + escapeHtml(dashboard.name) + '</h2>' +
        '<span class="vis-badge ' + visCls + '"><span class="dot"></span>' + visLabel + '</span>' +
      '</div>' +
      '<div class="dash-period-controls" id="dash-period-controls">' +
        '<div class="form-group">' +
          '<label class="form-label">Granularity</label>' +
          '<select class="form-control" id="dash-gran" onchange="onDashPeriodChange(' + dashboard.id + ')">' + granOptions + '</select>' +
        '</div>' +
        '<div class="form-group">' +
          '<label class="form-label">Periods</label>' +
          '<input class="form-control" id="dash-count" type="number" min="1" max="24" value="' + count + '" onchange="onDashPeriodChange(' + dashboard.id + ')" />' +
        '</div>' +
      '</div>' +
      '<div class="viewer-actions">' +
        '<button class="btn btn-secondary" onclick="showDashboardEditor(' + dashboard.id + ')">Edit</button>' +
        '<button class="btn btn-danger" onclick="deleteDashboard(' + dashboard.id + ')">Delete</button>' +
      '</div>' +
    '</div>' +
    '<div class="dash-grid" id="dash-grid">' + tilesHtml + '</div>';

  // Store period on viewer for re-rendering
  view.setAttribute('data-dash-id', dashboard.id);
  view.setAttribute('data-dash-period', JSON.stringify(period));

  // Attach IntersectionObserver for lazy tile loading
  var tiles = view.querySelectorAll('.dash-tile');
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        var tile = entry.target;
        observer.unobserve(tile);
        loadDashTile(tile, period);
      }
    });
  }, { threshold: 0.1 });

  tiles.forEach(function (tile) { observer.observe(tile); });
}

function onDashPeriodChange(dashId) {
  var gran = document.getElementById('dash-gran');
  var countInp = document.getElementById('dash-count');
  if (!gran || !countInp) return;
  var newPeriod = {
    granularity: gran.value,
    count: Math.max(1, parseInt(countInp.value, 10) || 3),
    include_rolling_12: false,
  };
  // Re-render with overridden period (no persistence).
  api('/dashboards/' + dashId).then(function (res) {
    if (res.ok) {
      renderDashboardViewer(res.body, newPeriod);
    }
  });
}

function loadDashTile(tile, inheritedPeriod) {
  var reportId = Number(tile.getAttribute('data-report-id'));
  var vizAttr = tile.getAttribute('data-viz') || '';
  var idx = tile.getAttribute('data-tile-idx');
  var nameEl = document.getElementById('dash-tile-name-' + idx);
  var bodyEl = document.getElementById('dash-tile-body-' + idx);

  function getReport() {
    if (_reportDefCache[reportId]) return Promise.resolve(_reportDefCache[reportId]);
    return api('/reports/' + reportId).then(function (res) {
      if (res.ok && res.body && res.body.id) {
        _reportDefCache[reportId] = res.body;
        return res.body;
      }
      return null;
    });
  }

  getReport().then(function (report) {
    if (!report) {
      if (nameEl) nameEl.textContent = '(deleted report)';
      if (bodyEl) bodyEl.innerHTML = '<p class="preview-empty">Report unavailable.</p>';
      return;
    }
    if (nameEl) nameEl.textContent = report.name || 'Report';

    var def = Object.assign({}, report.definition || {});
    // Apply inherited period from dashboard if it's a non-empty object
    if (inheritedPeriod && Object.keys(inheritedPeriod).length > 0) {
      def.period = inheritedPeriod;
    }

    var vizType = vizAttr || defaultVizForPeriod(def.period);

    if (bodyEl) bodyEl.innerHTML = '<p class="preview-empty"><span class="spinner"></span></p>';

    api('/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(def),
    }).then(function (runRes) {
      if (!bodyEl) return;
      if (runRes.ok) {
        bodyEl.innerHTML = renderVisualization(vizType, runRes.body);
      } else {
        var errMsg = (runRes.body && runRes.body.error) || 'Run failed';
        bodyEl.innerHTML = '<p class="preview-error">' + escapeHtml(errMsg) + '</p>';
      }
    }).catch(function (err) {
      if (bodyEl) bodyEl.innerHTML = '<p class="preview-error">' + escapeHtml(err.message) + '</p>';
    });
  });
}

function deleteDashboard(dashId) {
  if (!confirm('Delete this dashboard? This cannot be undone.')) return;
  api('/dashboards/' + dashId, { method: 'DELETE' }).then(function (res) {
    if (res.ok) {
      setLibraryTab('dashboards');
    } else {
      alert('Could not delete dashboard.');
    }
  });
}

/* ===== Dashboard Editor ===== */

function showDashboardEditor(dashId) {
  _libraryTab = 'dashboards';
  setTopbarActions(
    '<button class="btn btn-ghost btn-sm" onclick="setLibraryTab(\'dashboards\')">← Back to Library</button>'
  );
  var view = document.getElementById('view');
  view.innerHTML = '<p class="muted" style="padding:24px">Loading editor…</p>';

  var reportsPromise = api('/reports').then(function (res) {
    return res.ok ? (res.body.reports || []) : [];
  });

  var dashPromise = dashId
    ? api('/dashboards/' + dashId).then(function (res) { return res.ok ? res.body : null; })
    : Promise.resolve(null);

  Promise.all([reportsPromise, dashPromise]).then(function (results) {
    var allReports = results[0];
    var dashboard = results[1];
    if (dashboard) {
      _dashEditContext = { id: dashboard.id, version: dashboard.version || 0 };
    } else {
      _dashEditContext = null;
    }
    renderDashboardEditor(dashboard, allReports);
  });
}

function renderDashboardEditor(dashboard, allReports) {
  var view = document.getElementById('view');

  var name = dashboard ? escapeHtml(dashboard.name || '') : '';
  var visibility = dashboard ? (dashboard.visibility || 'private') : 'private';
  var defPeriod = (dashboard && dashboard.default_period) ? dashboard.default_period : {};
  var granularity = defPeriod.granularity || 'month';
  var count = defPeriod.count !== undefined ? defPeriod.count : 3;
  var rolling12 = defPeriod.include_rolling_12 ? ' checked' : '';
  var rolling12Disabled = granularity !== 'month' ? ' disabled' : '';

  var visOpts = ['private', 'shared'].map(function (v) {
    var sel = v === visibility ? ' selected' : '';
    return '<option value="' + v + '"' + sel + '>' + (v === 'shared' ? 'Shared' : 'Private') + '</option>';
  }).join('');

  var granOptions = ['month', 'week', 'quarter'].map(function (g) {
    var sel = g === granularity ? ' selected' : '';
    var label = g.charAt(0).toUpperCase() + g.slice(1);
    return '<option value="' + g + '"' + sel + '>' + label + '</option>';
  }).join('');

  var existingWidgets = (dashboard && dashboard.layout && dashboard.layout.widgets)
    ? dashboard.layout.widgets
    : [];

  if (allReports.length === 0) {
    view.innerHTML =
      '<div class="editor-layout">' +
        '<div class="editor-form">' +
          '<p class="muted">Create a report first before building a dashboard.</p>' +
          '<button class="btn btn-ghost" onclick="setLibraryTab(\'reports\')">Go to Reports</button>' +
        '</div>' +
      '</div>';
    return;
  }

  var reportSelectOptions = allReports.map(function (r) {
    return '<option value="' + r.id + '">' + escapeHtml(r.name) + '</option>';
  }).join('');

  var widgetsHtml = existingWidgets.map(function (w, idx) {
    return buildWidgetRowHtml(allReports, w, idx);
  }).join('');

  view.innerHTML =
    '<div class="editor-layout">' +

      '<div class="editor-form">' +

        '<div class="step-card">' +
          '<div class="step-body open" style="padding:16px;display:flex;flex-direction:column;gap:12px;">' +
            '<div class="form-group">' +
              '<label class="form-label">Dashboard name</label>' +
              '<input class="form-control" id="dash-name" type="text" placeholder="e.g. Operations Overview" value="' + name + '" />' +
            '</div>' +
            '<div class="form-group">' +
              '<label class="form-label">Visibility</label>' +
              '<select class="form-control" id="dash-visibility">' + visOpts + '</select>' +
            '</div>' +
          '</div>' +
        '</div>' +

        '<div class="step-card">' +
          '<div class="step-header open active" onclick="toggleStep(this)">' +
            '<div class="step-num">P</div>' +
            '<span class="step-title">Default period</span>' +
            '<span class="step-chevron">▼</span>' +
          '</div>' +
          '<div class="step-body open">' +
            '<div class="period-row">' +
              '<div class="form-group">' +
                '<label class="form-label">Granularity</label>' +
                '<select class="form-control" id="dash-edit-gran" onchange="onDashEditorGranChange()">' + granOptions + '</select>' +
              '</div>' +
              '<div class="form-group">' +
                '<label class="form-label">Periods</label>' +
                '<input class="form-control" id="dash-edit-count" type="number" min="1" max="24" value="' + count + '" onchange="scheduleDashPreview()" />' +
              '</div>' +
            '</div>' +
            '<label class="form-check">' +
              '<input type="checkbox" id="dash-edit-rolling12"' + rolling12 + rolling12Disabled + ' onchange="scheduleDashPreview()" />' +
              '<span>Rolling 12-month trend</span>' +
            '</label>' +
          '</div>' +
        '</div>' +

        '<div class="step-card">' +
          '<div class="step-header open active" onclick="toggleStep(this)">' +
            '<div class="step-num">W</div>' +
            '<span class="step-title">Widgets</span>' +
            '<span class="step-chevron">▼</span>' +
          '</div>' +
          '<div class="step-body open">' +
            '<div id="dash-widgets">' + widgetsHtml + '</div>' +
            '<button class="add-filter-btn" onclick="addDashWidgetRow()">＋ Add widget</button>' +
          '</div>' +
        '</div>' +

        '<div class="save-bar">' +
          '<div class="save-bar-actions">' +
            '<button class="btn btn-ghost" onclick="setLibraryTab(\'dashboards\')">Cancel</button>' +
            '<button class="btn btn-primary" onclick="saveDashboard()">Save dashboard</button>' +
          '</div>' +
        '</div>' +

      '</div>' +

      '<div class="preview-panel" id="dash-preview-panel">' +
        '<div class="preview-panel-header">' +
          '<h3>Preview</h3>' +
          '<div class="preview-status" id="dash-preview-status"></div>' +
        '</div>' +
        '<div id="dash-preview-content">' +
          '<p class="preview-empty">Add widgets and configure the period to see a preview.</p>' +
        '</div>' +
      '</div>' +

    '</div>';

  // Attach change listeners to existing widget rows and trigger a first preview if editing.
  if (existingWidgets.length > 0) {
    scheduleDashPreview();
  }
}

// Store allReports on the window so widget rows can access them when added dynamically.
// We serialize them into the DOM via a hidden element to keep it clean.
function _getAllReportsFromDom() {
  var el = document.getElementById('dash-all-reports-json');
  if (!el) return [];
  try { return JSON.parse(el.textContent); } catch (e) { return []; }
}

function buildWidgetRowHtml(allReports, widget, idx) {
  widget = widget || {};
  var selectedReportId = widget.report_id || (allReports[0] && allReports[0].id) || '';
  var selectedSpan = widget.span || 2;
  var selectedViz = widget.viz || '';

  var reportOpts = allReports.map(function (r) {
    var sel = r.id === selectedReportId ? ' selected' : '';
    return '<option value="' + r.id + '"' + sel + '>' + escapeHtml(r.name) + '</option>';
  }).join('');

  var spanOpts = [1, 2, 3, 4].map(function (s) {
    var sel = s === selectedSpan ? ' selected' : '';
    return '<option value="' + s + '"' + sel + '>' + s + ' col' + (s === 1 ? '' : 's') + '</option>';
  }).join('');

  var vizLabels = { '': 'Auto', bar: 'Bar', compare_table: 'Compare', trend: 'Trend', kpi: 'KPI', table: 'Table' };
  var vizOpts = Object.keys(vizLabels).map(function (v) {
    var sel = v === selectedViz ? ' selected' : '';
    return '<option value="' + v + '"' + sel + '>' + vizLabels[v] + '</option>';
  }).join('');

  return (
    '<div class="dash-widget-row" data-widget-idx="' + idx + '">' +
      '<select class="form-control" data-role="w-report" onchange="scheduleDashPreview()">' + reportOpts + '</select>' +
      '<select class="form-control w-span-sel" data-role="w-span" onchange="scheduleDashPreview()">' + spanOpts + '</select>' +
      '<select class="form-control" data-role="w-viz" onchange="scheduleDashPreview()">' + vizOpts + '</select>' +
      '<button class="btn-icon" title="Move up" onclick="moveDashWidget(this,-1)">↑</button>' +
      '<button class="btn-icon" title="Move down" onclick="moveDashWidget(this,1)">↓</button>' +
      '<button class="btn-icon" title="Remove" onclick="removeDashWidget(this)">✕</button>' +
    '</div>'
  );
}

function addDashWidgetRow() {
  // Gather the current reports from existing select options (first w-report select as reference)
  var existing = document.querySelector('#dash-widgets [data-role="w-report"]');
  if (!existing) return;
  var allReports = Array.prototype.map.call(existing.options, function (o) {
    return { id: Number(o.value), name: o.text };
  });
  var container = document.getElementById('dash-widgets');
  var idx = container.querySelectorAll('.dash-widget-row').length;
  var div = document.createElement('div');
  div.innerHTML = buildWidgetRowHtml(allReports, {}, idx);
  container.appendChild(div.firstChild);
  scheduleDashPreview();
}

function removeDashWidget(btn) {
  var row = btn.closest('.dash-widget-row');
  if (row) row.parentNode.removeChild(row);
  scheduleDashPreview();
}

function moveDashWidget(btn, dir) {
  var row = btn.closest('.dash-widget-row');
  if (!row) return;
  var container = row.parentNode;
  var rows = Array.prototype.slice.call(container.querySelectorAll('.dash-widget-row'));
  var idx = rows.indexOf(row);
  var targetIdx = idx + dir;
  if (targetIdx < 0 || targetIdx >= rows.length) return;
  var target = rows[targetIdx];
  if (dir === -1) {
    container.insertBefore(row, target);
  } else {
    container.insertBefore(target, row);
  }
  scheduleDashPreview();
}

function onDashEditorGranChange() {
  var gran = document.getElementById('dash-edit-gran');
  var chk = document.getElementById('dash-edit-rolling12');
  if (gran && chk) {
    chk.disabled = gran.value !== 'month';
    if (gran.value !== 'month') chk.checked = false;
  }
  scheduleDashPreview();
}

function scheduleDashPreview() {
  clearTimeout(_dashPreviewTimer);
  _dashPreviewTimer = setTimeout(runDashPreview, 400);
}

function collectDashboard() {
  var nameInp = document.getElementById('dash-name');
  var visInp = document.getElementById('dash-visibility');
  var granInp = document.getElementById('dash-edit-gran');
  var countInp = document.getElementById('dash-edit-count');
  var rolling12Chk = document.getElementById('dash-edit-rolling12');

  var name = nameInp ? nameInp.value.trim() : '';
  var visibility = visInp ? visInp.value : 'private';
  var granularity = granInp ? granInp.value : 'month';
  var count = countInp ? Math.max(1, parseInt(countInp.value, 10) || 3) : 3;
  var rolling12 = rolling12Chk ? rolling12Chk.checked : false;

  var widgetRows = document.querySelectorAll('#dash-widgets .dash-widget-row');
  var widgets = [];
  widgetRows.forEach(function (row) {
    var reportSel = row.querySelector('[data-role="w-report"]');
    var spanSel = row.querySelector('[data-role="w-span"]');
    var vizSel = row.querySelector('[data-role="w-viz"]');
    if (!reportSel) return;
    widgets.push({
      report_id: Number(reportSel.value),
      span: Number(spanSel ? spanSel.value : 2),
      viz: (vizSel && vizSel.value) ? vizSel.value : null,
    });
  });

  return {
    name: name,
    visibility: visibility,
    layout: { widgets: widgets },
    default_period: {
      granularity: granularity,
      count: count,
      include_rolling_12: rolling12,
    },
  };
}

function runDashPreview() {
  var body = collectDashboard();
  var previewEl = document.getElementById('dash-preview-content');
  var statusEl = document.getElementById('dash-preview-status');
  if (!previewEl) return;

  var widgets = body.layout.widgets;
  if (widgets.length === 0) {
    previewEl.innerHTML = '<p class="preview-empty">Add widgets to see a preview.</p>';
    return;
  }

  var period = body.default_period;

  // Render a mini grid of tile placeholders then load each.
  var tilesHtml = widgets.map(function (w, idx) {
    return (
      '<div class="dash-tile" style="grid-column:span ' + (w.span || 2) + '"' +
        ' data-report-id="' + Number(w.report_id) + '"' +
        ' data-viz="' + escapeHtml(w.viz || '') + '"' +
        ' data-tile-idx="prev-' + idx + '">' +
        '<div class="dash-tile-header" id="dash-tile-name-prev-' + idx + '">Loading…</div>' +
        '<div class="dash-tile-body" id="dash-tile-body-prev-' + idx + '"><p class="preview-empty"><span class="spinner"></span></p></div>' +
      '</div>'
    );
  }).join('');

  previewEl.innerHTML = '<div class="dash-grid">' + tilesHtml + '</div>';

  widgets.forEach(function (w, idx) {
    var tile = previewEl.querySelector('[data-tile-idx="prev-' + idx + '"]');
    if (tile) loadDashTile(tile, period);
  });
}

function saveDashboard() {
  var body = collectDashboard();
  if (!body.name) {
    var nameInp = document.getElementById('dash-name');
    if (nameInp) nameInp.focus();
    return;
  }

  var saveBtn = document.querySelector('.save-bar .btn-primary');
  if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }

  var promise = _dashEditContext
    ? api('/dashboards/' + _dashEditContext.id, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({}, body, { version: _dashEditContext.version })),
      })
    : api('/dashboards', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

  promise.then(function (res) {
    if (res.ok) {
      setLibraryTab('dashboards');
    } else {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save dashboard'; }
      var msg = (res.body && res.body.error) || ('Save failed (HTTP ' + res.status + ')');
      alert(msg);
    }
  }).catch(function (err) {
    if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save dashboard'; }
    alert('Save failed: ' + err.message);
  });
}

/* ===== Top Bar Actions Helper ===== */

function setTopbarActions(html) {
  var el = document.getElementById('topbar-actions');
  if (el) el.innerHTML = html;
}

/* ===== Init ===== */
showLibrary();
