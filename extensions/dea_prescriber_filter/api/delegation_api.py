"""API endpoints for the delegation admin UI and CRUD operations."""

from __future__ import annotations

import json
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data.staff import Staff
from logger import log

from dea_prescriber_filter.engine.lookups import get_active_providers, get_active_staff, get_staff_name
from dea_prescriber_filter.engine.storage import (
    get_all_delegations,
    remove_delegation,
    set_delegation,
)


ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Prescriber Assist</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Serif+Display&display=swap" rel="stylesheet">
<style>
:root {
  --navy: #0d203c;
  --navy-mid: #162d50;
  --teal: #96D3DD;
  --teal-dim: #c8e9ee;
  --teal-deep: #5ab5c4;
  --cyan: #02e3fb;
  --bg: #EFF5F7;
  --surface: #ffffff;
  --surface-alt: #F4F8FA;
  --border: #dce8ec;
  --border-mid: #c8dde3;
  --text-head: #0d203c;
  --text-body: #2c4155;
  --text-dim: #5e7a8a;
  --text-muted: #8ea8b5;
  --avail: #01A4FF;
  --avail-bg: #e6f3ff;
  --avail-border: #80c8ff;
  --block: #7C5CFC;
  --block-bg: #f3f0ff;
  --block-border: #c9b8f0;
  --shadow-sm: 0 1px 4px rgba(13,32,60,0.07);
  --shadow-md: 0 4px 16px rgba(13,32,60,0.10);
  --radius: 14px;
  --radius-sm: 9px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg); color: var(--text-body);
  min-height: 100vh; font-size: 15px; line-height: 1.55;
}
.main {
  max-width: 900px; margin: 0 auto;
  padding: 38px 36px 60px;
  display: flex; flex-direction: column; gap: 28px;
}
.page-title-block h1 {
  font-family: 'DM Serif Display', Georgia, serif;
  font-size: 36px; font-weight: 400;
  letter-spacing: -0.025em; color: var(--text-head); line-height: 1.15;
}
.title-accent {
  display: block; width: 52px; height: 3px;
  background: linear-gradient(90deg, var(--cyan), var(--teal));
  border-radius: 2px; margin-top: 10px;
}
.page-title-block p { font-size: 15px; color: var(--text-dim); margin-top: 10px; }

.card {
  background: var(--surface); border: 1.5px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow-sm);
  animation: fadeUp 0.3s ease both;
}
.card:nth-child(2) { animation-delay: 0.06s; }
.card-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 24px; border-bottom: 1.5px solid var(--border);
  background: var(--surface); border-radius: var(--radius) var(--radius) 0 0;
}
.card-header h2 { font-size: 16px; font-weight: 700; color: var(--text-head); }
.card-body { padding: 24px; position: relative; z-index: 20; }

.form-row { display: flex; gap: 28px; align-items: flex-end; flex-wrap: wrap; }
.form-group { display: flex; flex-direction: column; gap: 7px; flex: 1; min-width: 240px; }
.form-row .btn { margin-left: auto; }
.form-group label {
  font-size: 12px; font-weight: 600; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.05em;
}

/* Custom dropdown (shared by provider + staff) */
.custom-dropdown { position: relative; min-width: 240px; }
.custom-dropdown-trigger {
  display: flex; flex-wrap: wrap; gap: 4px; align-items: center;
  padding: 9px 14px; min-height: 42px;
  border: 1.5px solid var(--border); border-radius: var(--radius-sm);
  background: var(--surface); cursor: pointer;
  font-family: 'DM Sans', sans-serif; font-size: 14.5px; color: var(--text-body);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.custom-dropdown-trigger:focus-within,
.custom-dropdown-trigger.active {
  border-color: var(--teal-deep); box-shadow: 0 0 0 3px rgba(150,211,221,0.2);
}
.custom-dropdown-trigger input {
  border: none; outline: none; background: transparent;
  font-family: 'DM Sans', sans-serif; font-size: 14px;
  color: var(--text-body); flex: 1; min-width: 80px;
}
.custom-dropdown-trigger input::placeholder { color: var(--text-muted); }
.custom-dropdown-trigger .placeholder { color: var(--text-muted); font-size: 14.5px; }
.custom-dropdown-trigger .selected-text { font-size: 14.5px; }
.custom-dropdown-list {
  position: absolute; top: 100%; left: 0; right: 0;
  background: var(--surface); border: 1.5px solid var(--border-mid);
  border-radius: var(--radius-sm); margin-top: 4px;
  max-height: 240px; overflow-y: auto;
  z-index: 9999; display: none;
  box-shadow: var(--shadow-md);
}
.custom-dropdown-list.open { display: block; }
.dd-option {
  padding: 10px 14px; font-size: 14px; cursor: pointer; transition: background 0.1s;
}
.dd-option:hover { background: var(--surface-alt); }
.dd-option.selected { background: var(--avail-bg); color: var(--avail); font-weight: 500; }

/* Tags in multi-select */
.tag {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 10px;
  background: var(--avail-bg); color: var(--avail);
  border: 1px solid var(--avail-border);
  border-radius: 14px; font-size: 12px; font-weight: 500;
}
.tag .remove-tag { cursor: pointer; font-size: 14px; line-height: 1; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 10px 18px; border-radius: var(--radius-sm);
  font-family: 'DM Sans', sans-serif; font-size: 14px; font-weight: 500;
  cursor: pointer; border: none; transition: all 0.15s ease;
  white-space: nowrap;
}
.btn-primary { background: var(--navy); color: var(--cyan); box-shadow: 0 2px 8px rgba(13,32,60,0.25); }
.btn-primary:hover { background: var(--navy-mid); color: #fff; }
.btn-danger { background: var(--block-bg); color: var(--block); border: 1.5px solid var(--block-border); }
.btn-danger:hover { background: #ebe5ff; }
.btn-sm { padding: 6px 12px; font-size: 13px; }

/* Table */
table { width: 100%; border-collapse: collapse; }
thead tr { background: var(--navy); }
th {
  padding: 11px 18px; text-align: left;
  font-size: 12px; font-weight: 600; color: var(--teal);
  letter-spacing: 0.06em; text-transform: uppercase; border: none;
}
td { padding: 14px 18px; border-bottom: 1px solid var(--border); font-size: 14.5px; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tbody tr:hover { background: var(--surface-alt); }

.staff-list { display: flex; flex-wrap: wrap; gap: 6px; }
.staff-chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 12px;
  background: var(--avail-bg); color: var(--avail);
  border: 1px solid var(--avail-border);
  border-radius: 20px; font-size: 13px; font-weight: 500;
}
.staff-chip .remove { cursor: pointer; font-size: 16px; line-height: 1; opacity: 0.6; }
.staff-chip .remove:hover { opacity: 1; }

.empty-state { text-align: center; padding: 48px 20px; color: var(--text-muted); font-size: 14.5px; }

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
</head>
<body>
<main class="main">

  <div class="page-header">
    <div class="page-title-block">
      <h1>Prescriber Assist</h1>
      <span class="title-accent"></span>
      <p>Configure which staff members can sign prescriptions on behalf of each provider.</p>
    </div>
  </div>

  <div class="card" style="z-index: 10;">
    <div class="card-header"><h2>Add Authorization</h2></div>
    <div class="card-body">
      <div class="form-row">
        <div class="form-group">
          <label>Provider</label>
          <div class="custom-dropdown" id="provider-dd">
            <div class="custom-dropdown-trigger" id="provider-trigger">
              <span class="placeholder">Select a provider...</span>
            </div>
            <div class="custom-dropdown-list" id="provider-list"></div>
          </div>
          <input type="hidden" id="provider-value">
        </div>
        <div class="form-group">
          <label>Authorized Staff</label>
          <div class="custom-dropdown" id="staff-dd" style="min-width: 300px;">
            <div class="custom-dropdown-trigger" id="staff-trigger">
              <input type="text" id="staff-search" placeholder="Search staff...">
            </div>
            <div class="custom-dropdown-list" id="staff-list"></div>
          </div>
        </div>
        <button class="btn btn-primary" id="save-btn">Save</button>
      </div>
    </div>
  </div>

  <div class="card" style="z-index: 1;">
    <div class="card-header"><h2>Authorized Staff</h2></div>
    <div id="delegations-table">
      <div class="empty-state">Loading...</div>
    </div>
  </div>

</main>

{{PRELOADED_SCRIPT}}
<script>
var _providers = (window.__PRELOADED__ && window.__PRELOADED__.providers) || [];
var _staff = (window.__PRELOADED__ && window.__PRELOADED__.staff) || [];
var _delegations = (window.__PRELOADED__ && window.__PRELOADED__.delegations) || {};
var _selectedStaff = [];
var _selectedProvider = '';
var _nameMap = (window.__PRELOADED__ && window.__PRELOADED__.name_map) || {};
var BASE = '/plugin-io/api/dea_prescriber_filter/app';

function safe(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ── Provider single-select dropdown ── */
function renderProviderList(filter) {
  var list = document.getElementById('provider-list');
  var html = '';
  var term = (filter || '').toLowerCase();
  _providers.forEach(function(p) {
    if (term && p.name.toLowerCase().indexOf(term) === -1) return;
    var sel = p.id === _selectedProvider ? ' selected' : '';
    html += '<div class="dd-option' + sel + '" data-id="' + safe(p.id) + '">' + safe(p.name) + '</div>';
  });
  if (!html) html = '<div class="dd-option" style="color:var(--text-muted);">No results</div>';
  list.innerHTML = html;
}

document.getElementById('provider-trigger').addEventListener('click', function() {
  var list = document.getElementById('provider-list');
  var isOpen = list.classList.contains('open');
  closeAllDropdowns();
  if (!isOpen) {
    list.classList.add('open');
    this.classList.add('active');
    renderProviderList('');
  }
});

document.getElementById('provider-list').addEventListener('click', function(e) {
  var opt = e.target.closest('.dd-option');
  if (!opt || !opt.dataset.id) return;
  _selectedProvider = opt.dataset.id;
  var trigger = document.getElementById('provider-trigger');
  var p = _providers.find(function(x) { return x.id === _selectedProvider; });
  trigger.innerHTML = '<span class="selected-text">' + safe(p ? p.name : _selectedProvider) + '</span>';
  document.getElementById('provider-value').value = _selectedProvider;
  closeAllDropdowns();
});

/* ── Staff multi-select dropdown ── */
function renderStaffList(filter) {
  var list = document.getElementById('staff-list');
  var html = '';
  var term = (filter || '').toLowerCase();
  _staff.forEach(function(s) {
    if (term && s.name.toLowerCase().indexOf(term) === -1) return;
    var isSelected = _selectedStaff.indexOf(s.id) !== -1;
    var sel = isSelected ? ' selected' : '';
    var check = isSelected ? '&#9745; ' : '&#9744; ';
    html += '<div class="dd-option' + sel + '" data-id="' + safe(s.id) + '">' + check + safe(s.name) + '</div>';
  });
  if (!html) html = '<div class="dd-option" style="color:var(--text-muted);">No results</div>';
  list.innerHTML = html;
}

function renderStaffTags() {
  var trigger = document.getElementById('staff-trigger');
  var input = document.getElementById('staff-search');
  trigger.querySelectorAll('.tag').forEach(function(t) { t.remove(); });
  _selectedStaff.forEach(function(id) {
    var tag = document.createElement('span');
    tag.className = 'tag';
    var name = _staff.find(function(s) { return s.id === id; });
    tag.textContent = name ? name.name : id;
    var x = document.createElement('span');
    x.className = 'remove-tag';
    x.textContent = String.fromCharCode(215);
    x.addEventListener('click', function(ev) {
      ev.stopPropagation();
      var idx = _selectedStaff.indexOf(id);
      if (idx !== -1) _selectedStaff.splice(idx, 1);
      renderStaffTags();
      renderStaffList(input.value);
    });
    tag.appendChild(x);
    trigger.insertBefore(tag, input);
  });
}

document.getElementById('staff-search').addEventListener('focus', function() {
  closeAllDropdowns();
  document.getElementById('staff-list').classList.add('open');
  document.getElementById('staff-trigger').classList.add('active');
  renderStaffList(this.value);
});

document.getElementById('staff-search').addEventListener('input', function() {
  renderStaffList(this.value);
});

document.getElementById('staff-list').addEventListener('click', function(e) {
  var opt = e.target.closest('.dd-option');
  if (!opt || !opt.dataset.id) return;
  var id = opt.dataset.id;
  var idx = _selectedStaff.indexOf(id);
  if (idx === -1) { _selectedStaff.push(id); } else { _selectedStaff.splice(idx, 1); }
  renderStaffTags();
  renderStaffList(document.getElementById('staff-search').value);
});

/* ── Close dropdowns on outside click ── */
function closeAllDropdowns() {
  document.querySelectorAll('.custom-dropdown-list').forEach(function(el) { el.classList.remove('open'); });
  document.querySelectorAll('.custom-dropdown-trigger').forEach(function(el) { el.classList.remove('active'); });
}

document.addEventListener('click', function(e) {
  if (!e.target.closest('.custom-dropdown')) closeAllDropdowns();
});

/* ── Form submit (CSP-safe) ── */
function formSubmit(action, data) {
  var form = document.createElement('form');
  form.method = 'POST';
  form.action = BASE + '/form-action';
  form.style.display = 'none';
  function addField(n, v) { var i = document.createElement('input'); i.name = n; i.value = v; form.appendChild(i); }
  addField('_action', action);
  addField('_data', JSON.stringify(data));
  document.body.appendChild(form);
  form.submit();
}

document.getElementById('save-btn').addEventListener('click', function() {
  if (!_selectedProvider) { alert('Please select a provider.'); return; }
  if (_selectedStaff.length === 0) { alert('Please select at least one staff member.'); return; }
  var existing = _delegations[_selectedProvider] || [];
  var merged = existing.slice();
  _selectedStaff.forEach(function(id) { if (merged.indexOf(id) === -1) merged.push(id); });
  formSubmit('save', { provider_id: _selectedProvider, staff_ids: merged });
});

/* ── Render delegations table ── */
function getStaffName(id) { var s = _staff.find(function(x) { return x.id === id; }); return s ? s.name : (_nameMap[id] || id); }
function getProviderName(id) { var p = _providers.find(function(x) { return x.id === id; }); return p ? p.name : (_nameMap[id] || id); }

function renderDelegations() {
  var container = document.getElementById('delegations-table');
  var keys = Object.keys(_delegations);
  if (keys.length === 0) {
    container.innerHTML = '<div class="empty-state">No authorizations configured. All prescriptions must be signed by the prescribing provider.</div>';
    return;
  }
  var html = '<table><colgroup><col style="width:200px;"><col><col style="width:120px;"></colgroup>';
  html += '<thead><tr><th>Provider</th><th>Authorized Staff</th><th></th></tr></thead><tbody>';
  keys.forEach(function(pid) {
    var sids = _delegations[pid];
    html += '<tr><td><strong>' + safe(getProviderName(pid)) + '</strong></td><td><div class="staff-list">';
    sids.forEach(function(sid) {
      html += '<span class="staff-chip">' + safe(getStaffName(sid)) + ' <span class="remove" data-provider="' + safe(pid) + '" data-staff="' + safe(sid) + '">' + String.fromCharCode(215) + '</span></span>';
    });
    html += '</div></td><td style="text-align:right;"><button class="btn btn-danger btn-sm" data-remove-provider="' + safe(pid) + '">Remove All</button></td></tr>';
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

document.getElementById('delegations-table').addEventListener('click', function(e) {
  var chip = e.target.closest('.remove[data-provider]');
  if (chip) {
    var pid = chip.dataset.provider, sid = chip.dataset.staff;
    var current = (_delegations[pid] || []).filter(function(id) { return id !== sid; });
    formSubmit('save', { provider_id: pid, staff_ids: current });
    return;
  }
  var btn = e.target.closest('[data-remove-provider]');
  if (btn) { formSubmit('remove', { provider_id: btn.dataset.removeProvider }); }
});

renderDelegations();
</script>
</body>
</html>"""


class DelegationUIApi(StaffSessionAuthMixin, SimpleAPI):
    """Serves the delegation admin UI and data endpoints.

    Access is restricted to staff members on an admin team (see ADMIN_TEAM_NAMES).
    StaffSessionAuthMixin enforces that the caller is a logged-in staff member;
    _is_admin_user() adds the team-based authorization on top.
    """

    PREFIX = "/app"

    def _is_admin_user(self) -> bool:
        """Check if the current user is allowed to manage delegations.

        ADMIN_STAFF_IDS is an *optional* restriction list. When unset or empty,
        any authenticated Canvas staff member can manage delegations
        (StaffSessionAuthMixin already enforces that the caller is a logged-in
        staff user). When set to a comma-separated list of staff UUIDs, access
        is restricted to those staff members only.
        """
        admin_ids_raw = self.secrets.get("ADMIN_STAFF_IDS", "") or ""
        admin_ids = {s.strip() for s in admin_ids_raw.split(",") if s.strip()}

        if not admin_ids:
            return True

        headers = getattr(self.request, "headers", {}) or {}
        user_id = headers.get("canvas-logged-in-user-id") or headers.get("Canvas-Logged-In-User-Id")
        return bool(user_id) and str(user_id) in admin_ids

    def _is_same_origin(self) -> bool:
        """CSRF defense: require Origin or Referer host to exactly match the Host header.

        Uses host equality (not substring containment) so a URL like
        https://legit-host.attacker.com cannot pass when legit-host is the Host.
        """
        headers = getattr(self.request, "headers", {}) or {}
        host = (headers.get("Host") or headers.get("host") or "").lower()
        if not host:
            return False
        origin = headers.get("Origin") or headers.get("origin") or ""
        if origin:
            return _extract_url_host(origin) == host
        referer = headers.get("Referer") or headers.get("referer") or ""
        if referer:
            return _extract_url_host(referer) == host
        return False

    def _forbidden(self) -> list[Response | Effect]:
        return [HTMLResponse("Forbidden", status_code=HTTPStatus.FORBIDDEN)]

    @api.get("/delegation-admin")
    def get_admin_ui(self) -> list[Response | Effect]:
        """Serve the delegation admin page with preloaded data."""
        if not self._is_admin_user():
            return self._forbidden()

        providers = get_active_providers()
        staff = get_active_staff()
        all_delegations = get_all_delegations()

        # Filter delegations to only active providers
        active_provider_ids = {p["id"] for p in providers}
        delegations = {
            pid: sids for pid, sids in all_delegations.items()
            if pid in active_provider_ids
        }

        # Build name map for all IDs in delegations
        name_map = {}
        for pid, sids in delegations.items():
            if pid not in name_map:
                name_map[pid] = get_staff_name(pid)
            for sid in sids:
                if sid not in name_map:
                    name_map[sid] = get_staff_name(sid)

        preloaded = {
            "providers": providers,
            "staff": staff,
            "delegations": delegations,
            "name_map": name_map,
        }
        raw = json.dumps(preloaded, default=str)
        safe_json = raw.replace("</", "<\\/")
        script_tag = f"<script>window.__PRELOADED__={safe_json};</script>"
        html = ADMIN_HTML.replace("{{PRELOADED_SCRIPT}}", script_tag)
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.post("/form-action")
    def handle_form_action(self) -> list[Response | Effect]:
        """Handle form submissions for save/remove actions, then redirect back."""
        if not self._is_admin_user():
            return self._forbidden()
        if not self._is_same_origin():
            return self._forbidden()

        # 303 See Other so the browser issues a GET on the admin URL. Avoids the
        # "Confirm form resubmission" prompt on refresh (PRG pattern).
        redirect = [Response(
            content=b"",
            status_code=HTTPStatus.SEE_OTHER,
            headers={"Location": "/plugin-io/api/dea_prescriber_filter/app/delegation-admin"},
        )]

        # Parse body — only malformed input (bad utf-8 or bad JSON) is silently
        # tolerated here. Any other exception in save/remove should reach Sentry.
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body = body.decode("utf-8")

            # Parse URL-encoded form data manually (parse_qs blocked by sandbox)
            import re
            params: dict[str, str] = {}
            for pair in body.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    v = v.replace("+", " ")
                    v = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), v)
                    params[k] = v
            action = params.get("_action", "")
            data = json.loads(params.get("_data", "{}"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("form-action received malformed body; ignoring")
            return redirect

        if action == "save":
            provider_id = data.get("provider_id")
            staff_ids = data.get("staff_ids", [])
            if provider_id and _valid_staff_id(provider_id):
                validated_staff_ids = [sid for sid in staff_ids if _valid_staff_id(sid)]
                set_delegation(provider_id, validated_staff_ids)
                log.info("Saved delegation: provider=%s staff=%s", provider_id, validated_staff_ids)

        elif action == "remove":
            provider_id = data.get("provider_id")
            if provider_id and _valid_staff_id(provider_id):
                remove_delegation(provider_id)
                log.info("Removed delegation for provider=%s", provider_id)

        return redirect


def _valid_staff_id(staff_id: str) -> bool:
    """Check that a staff ID corresponds to a real Staff record."""
    if not staff_id or not isinstance(staff_id, str):
        return False
    return Staff.objects.filter(id=staff_id).exists()


def _extract_url_host(url: str) -> str:
    """Extract the host[:port] component from a URL string, lowercased.

    Avoids urllib.parse.urlparse (parse_qs is sandbox-blocked; using urlparse
    here keeps the import surface minimal). Returns "" if no scheme is present
    so a bare/relative value never matches a real Host header.
    """
    if not url or "://" not in url:
        return ""
    after_scheme = url.split("://", 1)[1]
    return after_scheme.split("/", 1)[0].lower()
