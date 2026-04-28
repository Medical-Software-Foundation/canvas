"""SimpleAPI handler for the note production dashboard.

Endpoints:
  GET /dashboard              — full-page HTML dashboard
  GET /providers              — JSON provider list with locked-note counts
  GET /providers/<id>/notes   — JSON note rows for a single provider
"""

from datetime import datetime, timezone
from http import HTTPStatus

import arrow
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data.billing import BillingLineItemStatus
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates
from django.conf import settings
from django.db.models import Prefetch
from logger import log

# Cache-bust token: generated once at module load so every deploy gets a fresh value.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

# ─── time-window helpers ──────────────────────────────────────────────────────


def _instance_tz() -> str:
    """Return the Django TIME_ZONE setting (falls back to UTC)."""
    return getattr(settings, "TIME_ZONE", "UTC")


def _window(period: str, week_start: str) -> tuple[datetime, datetime]:
    """Return (start, end) as UTC-aware datetimes for the requested period.

    All edges are calendar-aligned in the instance timezone.
    The right edge is the end-of-period (not 'now').
    """
    tz = _instance_tz()
    now = arrow.now(tz)

    if period == "monthly":
        start = now.floor("month")
        end = start.shift(months=1)
    elif period == "weekly":
        # arrow uses Monday=0 … Sunday=6 for weekday()
        # week_start='sunday' → anchor to most-recent Sunday
        # week_start='monday' → anchor to most-recent Monday
        anchor_weekday = 6 if week_start == "sunday" else 0  # arrow weekday ints
        days_back = (now.weekday() - anchor_weekday) % 7
        start = now.shift(days=-days_back).floor("day")
        end = start.shift(weeks=1)
    else:
        # daily (default)
        start = now.floor("day")
        end = start.shift(days=1)

    return start.datetime, end.datetime


# ─── data helpers ─────────────────────────────────────────────────────────────


def _format_dos(dt: datetime) -> str:
    """Format a datetime-of-service in the instance timezone."""
    tz = _instance_tz()
    local = arrow.get(dt).to(tz)
    return local.format("MM/DD HH:mm")


def _provider_display_name(staff: object) -> str:
    """Return 'First Last' or 'First Last, Credentials' for a Staff record."""
    name = f"{getattr(staff, 'first_name', '')} {getattr(staff, 'last_name', '')}".strip()
    # Staff.credentialed_name is a property that appends credentials if set;
    # fall back to plain name if credentials are not present.
    cred: str | None = getattr(staff, "credentialed_name", None)
    if cred and cred != name:
        return cred
    return name


def _rfv_text(note: object) -> str:
    """Return the reason-for-visit text for the first RFV command on a note.

    Priority:
      1. Structured coding display / text
      2. Unstructured comment text
      3. Em-dash fallback
    """
    # note.commands is prefetched; filter client-side to avoid a DB round-trip.
    rfv_commands = [
        c for c in getattr(note, "commands", None).all()  # type: ignore[union-attr]
        if getattr(c, "schema_key", None) == "reasonForVisit"
    ]
    if not rfv_commands:
        return "—"

    # Sort by dbid ascending to get the earliest-added command.
    rfv_commands.sort(key=lambda c: getattr(c, "dbid", 0))
    data: dict[str, object] = getattr(rfv_commands[0], "data", None) or {}

    coding: dict[str, object] = (data.get("coding") or {})  # type: ignore[assignment]
    # Structured RFV has a 'text' key inside coding (display/text field).
    structured_text = str(coding.get("display") or coding.get("text") or "")
    if structured_text:
        return structured_text

    comment = str(data.get("comment") or "")
    if comment:
        return comment

    return "—"


def _fetch_locked_state_events(start: datetime, end: datetime, provider_id: str | None = None):  # type: ignore[no-untyped-def]
    """Return a queryset of CurrentNoteStateEvent for locked notes in [start, end).

    Uses select_related and prefetch_related to avoid N+1:
      - select_related: note__provider, note__patient, note__note_type_version
      - prefetch_related: note__billing_line_items (filtered to ACTIVE), note__commands
    """
    qs = CurrentNoteStateEvent.objects.filter(
        state__in=[NoteStates.LKD, NoteStates.RLK],
        note__datetime_of_service__gte=start,
        note__datetime_of_service__lt=end,
    ).select_related(
        "note__provider",
        "note__patient",
        "note__note_type_version",
    ).prefetch_related(
        Prefetch(
            "note__billing_line_items",
            queryset=__import__(
                "canvas_sdk.v1.data.billing",
                fromlist=["BillingLineItem"],
            ).BillingLineItem.objects.filter(status=BillingLineItemStatus.ACTIVE),
            to_attr="active_billing_items",
        ),
        Prefetch(
            "note__commands",
            queryset=Command.objects.filter(schema_key="reasonForVisit").order_by("dbid"),
            to_attr="rfv_commands_prefetched",
        ),
    )

    if provider_id is not None:
        qs = qs.filter(note__provider__id=provider_id)

    return qs


# ─── SimpleAPI ────────────────────────────────────────────────────────────────


class NoteProductionDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    """HTTP endpoints backing the note production dashboard."""

    @api.get("/dashboard")
    def dashboard_page(self) -> list[Response | Effect]:
        """Return the single-page dashboard HTML."""
        period = self.request.query_params.get("period", "daily")
        week_start = self.request.query_params.get("week_start", "sunday")
        # Validate inputs server-side; unknown values fall back to defaults.
        if period not in ("daily", "weekly", "monthly"):
            period = "daily"
        if week_start not in ("sunday", "monday"):
            week_start = "sunday"
        html = _render_dashboard_html(period, week_start, _CACHE_BUST)
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/providers")
    def providers_list(self) -> list[Response | Effect]:
        """Return [{provider_id, name, count}] sorted by count desc, then name."""
        period = self.request.query_params.get("period", "daily")
        week_start = self.request.query_params.get("week_start", "sunday")
        if period not in ("daily", "weekly", "monthly"):
            period = "daily"
        if week_start not in ("sunday", "monday"):
            week_start = "sunday"

        start, end = _window(period, week_start)
        log.info(
            f"[NoteProductionDashboardAPI] providers list: period={period} "
            f"week_start={week_start} window=[{start}, {end})"
        )

        events = _fetch_locked_state_events(start, end)

        # Aggregate counts by provider.
        provider_counts: dict[str, dict] = {}
        for event in events:
            provider = event.note.provider
            if provider is None:
                continue
            pid = str(provider.id)
            if pid not in provider_counts:
                provider_counts[pid] = {
                    "provider_id": pid,
                    "name": _provider_display_name(provider),
                    "count": 0,
                }
            provider_counts[pid]["count"] += 1

        result = sorted(
            provider_counts.values(),
            key=lambda x: (-x["count"], x["name"]),
        )
        return [JSONResponse(result, status_code=HTTPStatus.OK)]

    @api.get("/providers/<provider_id>/notes")
    def provider_notes(self) -> list[Response | Effect]:
        """Return note rows for a single provider in the requested period."""
        provider_id = self.request.path_params["provider_id"]
        period = self.request.query_params.get("period", "daily")
        week_start = self.request.query_params.get("week_start", "sunday")
        if period not in ("daily", "weekly", "monthly"):
            period = "daily"
        if week_start not in ("sunday", "monday"):
            week_start = "sunday"

        start, end = _window(period, week_start)

        events = _fetch_locked_state_events(start, end, provider_id=provider_id)

        rows = []
        for event in events:
            note = event.note
            patient = note.patient
            patient_name = (
                f"{patient.first_name} {patient.last_name}".strip()
                if patient
                else ""
            )

            # CPT codes from prefetched active billing items.
            active_items = getattr(note, "active_billing_items", [])
            cpts = ", ".join(item.cpt for item in active_items if item.cpt)

            # Note type name.
            note_type = (
                note.note_type_version.name if note.note_type_version else ""
            )

            # RFV: use prefetched commands.
            rfv_commands = getattr(note, "rfv_commands_prefetched", [])
            if rfv_commands:
                data = rfv_commands[0].data or {}
                coding = data.get("coding") or {}
                rfv = (
                    coding.get("display")
                    or coding.get("text")
                    or data.get("comment")
                    or "—"
                )
            else:
                rfv = "—"

            rows.append({
                "note_id": str(note.id),
                "patient": patient_name,
                "datetime_of_service": _format_dos(note.datetime_of_service),
                "cpt": cpts,
                "note_type": note_type,
                "rfv": rfv,
            })

        # Sort by datetime_of_service descending (the formatted string is MM/DD HH:mm
        # which sorts correctly within a single year; sort on the raw datetime instead).
        rows_with_dt = []
        for event, row in zip(events, rows):
            rows_with_dt.append((event.note.datetime_of_service, row))
        rows_with_dt.sort(key=lambda x: x[0], reverse=True)
        rows = [r for _, r in rows_with_dt]

        return [JSONResponse(rows, status_code=HTTPStatus.OK)]


# ─── HTML template ────────────────────────────────────────────────────────────


def _render_dashboard_html(period: str, week_start: str, cache_bust: str) -> str:
    """Return the full dashboard HTML as a string (no file I/O)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Note Production Dashboard</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      background: #f4f6f9;
      color: #1a2333;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    /* ── top bar ── */
    #topbar {{
      background: #1a6fa8;
      color: #fff;
      padding: 10px 18px;
      display: flex;
      align-items: center;
      gap: 20px;
      flex-shrink: 0;
      flex-wrap: wrap;
    }}
    #topbar h1 {{
      font-size: 16px;
      font-weight: 600;
      margin-right: auto;
    }}
    .toggle-group {{
      display: flex;
      gap: 4px;
      align-items: center;
    }}
    .toggle-group label {{
      font-size: 12px;
      opacity: 0.85;
      margin-right: 4px;
    }}
    .toggle-btn {{
      background: rgba(255,255,255,0.15);
      border: 1px solid rgba(255,255,255,0.35);
      color: #fff;
      padding: 4px 12px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 13px;
      transition: background 0.15s;
    }}
    .toggle-btn.active {{
      background: #fff;
      color: #1a6fa8;
      font-weight: 600;
      border-color: #fff;
    }}
    .toggle-btn:hover:not(.active) {{
      background: rgba(255,255,255,0.25);
    }}
    /* ── two-pane layout ── */
    #main {{
      display: flex;
      flex: 1;
      overflow: hidden;
    }}
    #left-pane {{
      width: 240px;
      flex-shrink: 0;
      background: #fff;
      border-right: 1px solid #dde3ec;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    #left-pane h2 {{
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #5a6a82;
      padding: 12px 14px 8px;
      border-bottom: 1px solid #edf0f5;
      flex-shrink: 0;
    }}
    #provider-list {{
      flex: 1;
      overflow-y: auto;
      list-style: none;
      padding: 6px 0;
    }}
    .provider-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 14px;
      cursor: pointer;
      border-left: 3px solid transparent;
      transition: background 0.1s;
    }}
    .provider-item:hover {{ background: #f0f5fa; }}
    .provider-item.selected {{
      background: #e8f1f9;
      border-left-color: #1a6fa8;
    }}
    .provider-name {{
      font-size: 13px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .count-badge {{
      background: #1a6fa8;
      color: #fff;
      border-radius: 10px;
      padding: 1px 7px;
      font-size: 11px;
      font-weight: 600;
      flex-shrink: 0;
      margin-left: 6px;
    }}
    .empty-msg {{
      padding: 18px 14px;
      color: #8a9ab5;
      font-style: italic;
      font-size: 13px;
    }}
    /* ── right pane ── */
    #right-pane {{
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: #fff;
    }}
    #right-pane h2 {{
      font-size: 13px;
      font-weight: 600;
      color: #2a3d54;
      padding: 12px 16px 8px;
      border-bottom: 1px solid #edf0f5;
      flex-shrink: 0;
    }}
    #notes-table-wrapper {{
      flex: 1;
      overflow: auto;
      padding: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    thead th {{
      background: #f8f9fb;
      padding: 8px 12px;
      text-align: left;
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: #5a6a82;
      border-bottom: 1px solid #dde3ec;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    tbody tr:nth-child(even) {{ background: #fafbfd; }}
    tbody tr:hover {{ background: #eef4fb; }}
    tbody td {{
      padding: 7px 12px;
      border-bottom: 1px solid #edf0f5;
      vertical-align: top;
    }}
    .spinner {{
      padding: 24px 16px;
      color: #8a9ab5;
      font-style: italic;
    }}
    /* ── loading/error states ── */
    .state-msg {{
      padding: 18px 16px;
      color: #8a9ab5;
      font-style: italic;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div id="topbar">
    <h1>Note Production Dashboard</h1>

    <div class="toggle-group">
      <button class="toggle-btn" id="btn-daily" onclick="setPeriod('daily')">Daily</button>
      <button class="toggle-btn" id="btn-weekly" onclick="setPeriod('weekly')">Weekly</button>
      <button class="toggle-btn" id="btn-monthly" onclick="setPeriod('monthly')">Monthly</button>
    </div>

    <div class="toggle-group">
      <label>Week starts:</label>
      <button class="toggle-btn" id="btn-sunday" onclick="setWeekStart('sunday')">Sun</button>
      <button class="toggle-btn" id="btn-monday" onclick="setWeekStart('monday')">Mon</button>
    </div>
  </div>

  <div id="main">
    <div id="left-pane">
      <h2>Providers</h2>
      <ul id="provider-list"><li class="state-msg">Loading&hellip;</li></ul>
    </div>
    <div id="right-pane">
      <h2 id="notes-header">Notes</h2>
      <div id="notes-table-wrapper"><p class="state-msg">Select a provider.</p></div>
    </div>
  </div>

<script>
(function () {{
  "use strict";

  // ── state ──────────────────────────────────────────────────────────────────
  let period = "{period}";
  let weekStart = localStorage.getItem("npd_week_start") || "{week_start}";
  let selectedProviderId = null;
  let selectedProviderName = "";

  // ── boot ───────────────────────────────────────────────────────────────────
  function init() {{
    syncButtons();
    fetchProviders();
  }}

  // ── button state ───────────────────────────────────────────────────────────
  function syncButtons() {{
    ["daily", "weekly", "monthly"].forEach(function (p) {{
      document.getElementById("btn-" + p).classList.toggle("active", p === period);
    }});
    ["sunday", "monday"].forEach(function (w) {{
      document.getElementById("btn-" + w).classList.toggle("active", w === weekStart);
    }});
  }}

  // ── period / week-start changes ────────────────────────────────────────────
  window.setPeriod = function (p) {{
    period = p;
    syncButtons();
    selectedProviderId = null;
    fetchProviders();
  }};

  window.setWeekStart = function (w) {{
    weekStart = w;
    localStorage.setItem("npd_week_start", w);
    syncButtons();
    if (period === "weekly") {{
      selectedProviderId = null;
      fetchProviders();
    }}
  }};

  // ── fetch providers ────────────────────────────────────────────────────────
  function fetchProviders() {{
    const list = document.getElementById("provider-list");
    list.innerHTML = '<li class="state-msg">Loading&hellip;</li>';
    document.getElementById("notes-header").textContent = "Notes";
    document.getElementById("notes-table-wrapper").innerHTML =
      '<p class="state-msg">Select a provider.</p>';

    const url = "/plugin-io/api/note_production_dashboard/providers" +
      "?period=" + encodeURIComponent(period) +
      "&week_start=" + encodeURIComponent(weekStart) +
      "&v={cache_bust}";

    fetch(url, {{ credentials: "same-origin" }})
      .then(function (r) {{ return r.json(); }})
      .then(function (providers) {{
        if (!providers || providers.length === 0) {{
          list.innerHTML = '<li class="empty-msg">No locked notes in this period.</li>';
          document.getElementById("notes-table-wrapper").innerHTML =
            '<p class="state-msg">No locked notes in this period.</p>';
          return;
        }}
        list.innerHTML = "";
        providers.forEach(function (p, idx) {{
          const li = document.createElement("li");
          li.className = "provider-item";
          li.dataset.id = p.provider_id;

          const nameSpan = document.createElement("span");
          nameSpan.className = "provider-name";
          nameSpan.textContent = p.name;

          const badge = document.createElement("span");
          badge.className = "count-badge";
          badge.textContent = String(p.count);

          li.appendChild(nameSpan);
          li.appendChild(badge);
          li.addEventListener("click", function () {{
            selectProvider(p.provider_id, p.name);
          }});
          list.appendChild(li);

          // Auto-select first provider.
          if (idx === 0) {{
            selectProvider(p.provider_id, p.name);
          }}
        }});
      }})
      .catch(function (err) {{
        list.innerHTML = '<li class="state-msg">Error loading providers.</li>';
        console.error("providers fetch error", err);
      }});
  }}

  // ── select provider ────────────────────────────────────────────────────────
  function selectProvider(providerId, providerName) {{
    selectedProviderId = providerId;
    selectedProviderName = providerName;

    // Highlight selected row.
    document.querySelectorAll(".provider-item").forEach(function (el) {{
      el.classList.toggle("selected", el.dataset.id === providerId);
    }});

    fetchNotes(providerId, providerName);
  }}

  // ── fetch notes ────────────────────────────────────────────────────────────
  function fetchNotes(providerId, providerName) {{
    const periodLabels = {{ daily: "Daily", weekly: "Weekly", monthly: "Monthly" }};
    document.getElementById("notes-header").textContent =
      "Notes for: " + providerName + " (" + (periodLabels[period] || period) + ")";

    const wrapper = document.getElementById("notes-table-wrapper");
    wrapper.innerHTML = '<p class="state-msg">Loading&hellip;</p>';

    const url = "/plugin-io/api/note_production_dashboard/providers/" +
      encodeURIComponent(providerId) + "/notes" +
      "?period=" + encodeURIComponent(period) +
      "&week_start=" + encodeURIComponent(weekStart) +
      "&v={cache_bust}";

    fetch(url, {{ credentials: "same-origin" }})
      .then(function (r) {{ return r.json(); }})
      .then(function (notes) {{
        if (!notes || notes.length === 0) {{
          wrapper.innerHTML = '<p class="state-msg">No locked notes in this period.</p>';
          return;
        }}
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        thead.innerHTML =
          "<tr><th>Patient</th><th>Date / Time</th><th>CPT</th>" +
          "<th>Type</th><th>Reason for Visit</th></tr>";
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        notes.forEach(function (note) {{
          const tr = document.createElement("tr");

          function cell(text) {{
            const td = document.createElement("td");
            td.textContent = text || "";
            return td;
          }}

          tr.appendChild(cell(note.patient));
          tr.appendChild(cell(note.datetime_of_service));
          tr.appendChild(cell(note.cpt));
          tr.appendChild(cell(note.note_type));
          tr.appendChild(cell(note.rfv));
          tbody.appendChild(tr);
        }});
        table.appendChild(tbody);
        wrapper.innerHTML = "";
        wrapper.appendChild(table);
      }})
      .catch(function (err) {{
        wrapper.innerHTML = '<p class="state-msg">Error loading notes.</p>';
        console.error("notes fetch error", err);
      }});
  }}

  // ── start ──────────────────────────────────────────────────────────────────
  init();
}})();
</script>
</body>
</html>"""
