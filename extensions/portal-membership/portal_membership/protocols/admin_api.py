"""Staff-facing membership directory.

Backs the ``MembershipAdminApp`` Application — when staff open *Memberships*
from the provider menu, the SDK launches a new browser window pointed at
``GET /admin/page``, which renders a single-page table of every membership
on the instance.

Endpoints (require an authenticated staff session):
  GET /admin/page          — HTML directory page (Canvas dark theme)
  GET /admin/memberships   — JSON list backing the table

The table is intentionally read-only. Staff redirect patients to the portal
to manage their own memberships.

Base URL:
  https://<instance>.canvasmedical.com/plugin-io/api/portal_membership/admin
"""
import json
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data.patient import Patient

from portal_membership.models import Membership
from portal_membership.protocols.membership_api import _esc
from portal_membership.utils.billing_cycle import cadence_suffix

# Statuses staff care about. ``pending_signup`` is a transient mutex state and
# is always excluded from the directory.
_LISTED_STATUSES = ("active", "cancelled")
_VALID_FILTERS = ("all", "active", "cancelled")


class MembershipAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """Read-only membership directory for staff."""

    PREFIX = "/admin"

    @api.get("/memberships")
    def get_memberships(self) -> list[Response | Effect]:
        """Return all memberships, joined with patient name + DOB.

        Query params:
          ``status`` — ``all`` (default), ``active``, or ``cancelled``.
        """
        status_filter = (self.request.query_params.get("status") or "all").lower()
        if status_filter not in _VALID_FILTERS:
            return [
                JSONResponse(
                    {"error": f"Unknown status filter: {status_filter}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if status_filter == "all":
            qs = Membership.objects.filter(status__in=_LISTED_STATUSES)
        else:
            qs = Membership.objects.filter(status=status_filter)
        qs = qs.order_by("-created_at")
        memberships = list(qs)

        patient_map = _build_patient_map([m.patient_id for m in memberships])

        rows: list[dict[str, Any]] = []
        for m in memberships:
            patient = patient_map.get(m.patient_id)
            rows.append(
                {
                    "patient_id": m.patient_id,
                    "patient_name": _patient_name(patient),
                    "dob": patient.birth_date.isoformat()
                    if patient and patient.birth_date
                    else "",
                    "plan": m.plan_name or m.plan or "",
                    "status": m.status,
                    "next_billing_date": m.next_billing_date.isoformat()
                    if m.next_billing_date
                    else "",
                    "amount_display": _format_amount(m.amount_cents, m.currency, m.cadence),
                    "signed_up_at": m.created_at.date().isoformat() if m.created_at else "",
                }
            )

        return [JSONResponse({"memberships": rows, "total": len(rows)})]

    @api.get("/page")
    def get_page(self) -> list[Response | Effect]:
        """Serve the HTML staff directory page."""
        instance = self.environment.get("CUSTOMER_IDENTIFIER", "")
        chart_base = f"https://{instance}.canvasmedical.com/patient" if instance else "/patient"
        api_base = "/plugin-io/api/portal_membership/admin"
        html = _render_admin_page(chart_base=chart_base, api_base=api_base)
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_patient_map(patient_ids: list[str]) -> dict[str, Patient]:
    """Return a ``{patient_id: Patient}`` map keyed by the membership's id form.

    The membership table stores ``patient_id`` as bare 32-char hex (no hyphens),
    while ``Patient.id`` may be hyphenated. We try the bare form first, then a
    hyphens-inserted form for any ids that didn't match.
    """
    if not patient_ids:
        return {}

    bare_ids = list({pid for pid in patient_ids if pid})
    found: dict[str, Patient] = {}
    try:
        for p in Patient.objects.filter(id__in=bare_ids):
            found[str(p.id).replace("-", "")] = p
    except Exception:  # noqa: BLE001 — directory should degrade, never crash
        pass

    missing = [pid for pid in bare_ids if pid not in found]
    if missing:
        hyphenated = [_with_hyphens(pid) for pid in missing if len(pid) == 32]
        try:
            for p in Patient.objects.filter(id__in=hyphenated):
                found[str(p.id).replace("-", "")] = p
        except Exception:  # noqa: BLE001
            pass

    return found


def _with_hyphens(bare: str) -> str:
    """Convert a 32-char hex string to canonical UUID form. Returns input unchanged on bad length."""
    if len(bare) != 32:
        return bare
    return f"{bare[0:8]}-{bare[8:12]}-{bare[12:16]}-{bare[16:20]}-{bare[20:32]}"


def _patient_name(patient: Patient | None) -> str:
    if patient is None:
        return "(unknown)"
    name = f"{patient.first_name} {patient.last_name}".strip()
    return name or "(unknown)"


def _format_amount(amount_cents: int | None, currency: str | None, cadence: str | None) -> str:
    if not amount_cents:
        return ""
    symbol = "$" if (currency or "usd").lower() == "usd" else ""
    return f"{symbol}{amount_cents / 100:.2f}{cadence_suffix(cadence)}"


def _render_admin_page(chart_base: str, api_base: str) -> str:
    """Return the staff directory HTML.

    The page fetches ``/admin/memberships`` on load and renders rows client-side
    so filter changes don't require a full page reload.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Memberships</title>
  <style>
    :root {{
      --bg: #030B14;
      --surface: #051222;
      --surface-2: #07182D;
      --border: rgba(255,255,255,0.10);
      --border-soft: rgba(255,255,255,0.06);
      --text: #EBF5FC;
      --muted: #DCE5EB;
      --tertiary: #8496AA;
      --primary: #01A4FF;
      --secondary: #01ECFF;
      --green: #55F7A9;
      --orange: #FFA24C;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Inter", system-ui, sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
    h1 {{
      color: #fff;
      font-size: 22px;
      margin: 0 0 4px 0;
      font-weight: 600;
    }}
    .subtitle {{ color: var(--tertiary); margin-bottom: 24px; font-size: 13px; }}
    .toolbar {{ display: flex; gap: 8px; align-items: center; margin-bottom: 16px; }}
    .pill {{
      background: var(--surface-2);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 6px 14px;
      border-radius: 999px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      transition: all 0.15s;
    }}
    .pill:hover {{ border-color: rgba(255,255,255,0.18); }}
    .pill.active {{
      background: linear-gradient(135deg, var(--primary), var(--secondary));
      color: #fff;
      border-color: transparent;
    }}
    .total {{ color: var(--tertiary); margin-left: auto; font-size: 13px; }}
    .table-wrap {{
      background: var(--surface);
      border: 1px solid var(--border-soft);
      border-radius: 12px;
      overflow: hidden;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    thead th {{
      text-align: left;
      padding: 12px 16px;
      background: var(--surface-2);
      color: var(--tertiary);
      font-weight: 500;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid var(--border-soft);
    }}
    tbody td {{
      padding: 14px 16px;
      border-bottom: 1px solid var(--border-soft);
      vertical-align: middle;
    }}
    tbody tr:last-child td {{ border-bottom: none; }}
    tbody tr:hover {{ background: rgba(255,255,255,0.02); }}
    .patient-link {{ color: var(--primary); text-decoration: none; font-weight: 500; }}
    .patient-link:hover {{ color: var(--secondary); text-decoration: underline; }}
    .status-badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 500;
    }}
    .status-active {{ background: rgba(85, 247, 169, 0.12); color: var(--green); }}
    .status-cancelled {{ background: rgba(255, 162, 76, 0.12); color: var(--orange); }}
    .empty {{ padding: 48px 24px; text-align: center; color: var(--tertiary); }}
    .loading {{ padding: 24px; text-align: center; color: var(--tertiary); }}
    .muted {{ color: var(--tertiary); }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Memberships</h1>
    <div class="subtitle">All active and cancelled memberships on this instance.</div>

    <div class="toolbar">
      <button class="pill active" data-filter="all">All</button>
      <button class="pill" data-filter="active">Active</button>
      <button class="pill" data-filter="cancelled">Cancelled</button>
      <span class="total" id="total"></span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Patient</th>
            <th>DOB</th>
            <th>Plan</th>
            <th>Status</th>
            <th>Next billing</th>
            <th>Amount</th>
            <th>Signed up</th>
          </tr>
        </thead>
        <tbody id="tbody">
          <tr><td colspan="7" class="loading">Loading…</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    var API_BASE = {json.dumps(api_base)};
    var CHART_BASE = {json.dumps(chart_base)};
    var currentFilter = "all";

    function escapeHtml(s) {{
      return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
    }}

    function statusBadge(status) {{
      var cls = "status-badge status-" + escapeHtml(status);
      var label = status.charAt(0).toUpperCase() + status.slice(1);
      return '<span class="' + cls + '">' + escapeHtml(label) + '</span>';
    }}

    function chartUrl(patientId) {{
      return CHART_BASE + "/" + encodeURIComponent(patientId);
    }}

    function renderRows(memberships) {{
      var tbody = document.getElementById("tbody");
      if (!memberships.length) {{
        tbody.innerHTML = '<tr><td colspan="7" class="empty">No memberships in this view.</td></tr>';
        return;
      }}
      tbody.innerHTML = memberships.map(function(m) {{
        var name = m.patient_name || "(unknown)";
        var nameCell = m.patient_id
          ? '<a class="patient-link" href="' + escapeHtml(chartUrl(m.patient_id))
            + '" target="_blank" rel="noopener">' + escapeHtml(name) + '</a>'
          : escapeHtml(name);
        return '<tr>'
          + '<td>' + nameCell + '</td>'
          + '<td>' + escapeHtml(m.dob || '') + '</td>'
          + '<td>' + escapeHtml(m.plan || '') + '</td>'
          + '<td>' + statusBadge(m.status || 'unknown') + '</td>'
          + '<td>' + escapeHtml(m.next_billing_date || '') + '</td>'
          + '<td>' + escapeHtml(m.amount_display || '') + '</td>'
          + '<td>' + escapeHtml(m.signed_up_at || '') + '</td>'
          + '</tr>';
      }}).join('');
    }}

    function load(filter) {{
      var tbody = document.getElementById("tbody");
      tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading…</td></tr>';
      fetch(API_BASE + "/memberships?status=" + encodeURIComponent(filter), {{
        credentials: "include",
        headers: {{ "Accept": "application/json" }}
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        renderRows(data.memberships || []);
        document.getElementById("total").textContent = (data.total || 0) + " "
          + ((data.total === 1) ? "membership" : "memberships");
      }})
      .catch(function() {{
        tbody.innerHTML = '<tr><td colspan="7" class="empty">Failed to load memberships.</td></tr>';
      }});
    }}

    document.querySelectorAll(".pill").forEach(function(btn) {{
      btn.addEventListener("click", function() {{
        document.querySelectorAll(".pill").forEach(function(b) {{ b.classList.remove("active"); }});
        btn.classList.add("active");
        currentFilter = btn.getAttribute("data-filter");
        load(currentFilter);
      }});
    }});

    load(currentFilter);
  </script>
</body>
</html>"""
