import datetime
import html
import json
import random
import uuid
from http import HTTPStatus
from uuid import uuid4

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.observation import CodingData, Observation, ObservationComponentData
from canvas_sdk.effects.simple_api import Broadcast, HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note

from logger import log

from vitalstream.constants import (
    LOINC_BP_DIA,
    LOINC_BP_DIA_MEAN,
    LOINC_BP_PANEL,
    LOINC_BP_PANEL_MEAN,
    LOINC_BP_SYS,
    LOINC_BP_SYS_MEAN,
    LOINC_HR,
    LOINC_HR_MEAN,
    LOINC_RR,
    LOINC_RR_MEAN,
    LOINC_SPO2,
    LOINC_SPO2_MEAN,
    TREATMENT_INTERVALS,
)
from vitalstream.models import (
    SessionStatus,
    VitalstreamReading,
    VitalstreamSession,
)


_VALID_INCREMENTS = {5, 10, 15, 20, 30}
_DEFAULT_INCREMENT = 10
_WINDOW_HALF_MINUTES = 0.5  # 30s before and after each Nth-minute mark
_PREF_TTL_SECONDS = 60 * 60 * 48  # 48 hours — VitalStream sessions are short-lived

# Whitelisted preference keys. Anything else the client sends is dropped so
# the cache can't be used as a generic dumping ground.
_PREF_KEYS = (
    "treatment_type",
    "increment_minutes",
    "bp_placement",
    "treatment_start",
    "treatment_end",
)


def _prefs_cache_key(session_id: str) -> str:
    return f"vs_prefs:{session_id}"


def _load_prefs(session_id: str) -> dict:
    value = get_cache().get(_prefs_cache_key(session_id))
    return value if isinstance(value, dict) else {}


def _save_prefs(session_id: str, prefs: dict) -> dict:
    """Filter to whitelisted keys, persist, and return the stored shape."""
    clean = {k: prefs[k] for k in _PREF_KEYS if k in prefs}
    get_cache().set(_prefs_cache_key(session_id), clean, timeout_seconds=_PREF_TTL_SECONDS)
    return clean


def _build_interval_html_table(rows: list[dict[str, str]], bp_placement: str = "left_wrist") -> str:
    """Build an inline-styled HTML table for the vitals CustomCommand."""
    cell = "padding:3px 5px;text-align:left;white-space:nowrap;"
    header = (
        '<table style="border-collapse:collapse;font-size:11px;'
        'font-family:sans-serif;width:100%;">'
        "<thead>"
        f'<tr style="background:#f5f5f5;border-bottom:2px solid #ddd;">'
        f'<th style="{cell}">Interval</th>'
        f'<th style="{cell}">Time</th>'
        f'<th style="{cell}">HR</th>'
        f'<th style="{cell}">BP</th>'
        f'<th style="{cell}">RR</th>'
        f'<th style="{cell}">SpO2</th>'
        "</tr>"
        "</thead><tbody>"
    )

    body_rows = ""
    for row in rows:
        label = html.escape(str(row.get("label", "")))
        time_val = html.escape(str(row.get("time", "")))
        hr = html.escape(str(row.get("hr", "")))
        bp_sys = html.escape(str(row.get("bp_sys", "")))
        bp_dia = html.escape(str(row.get("bp_dia", "")))
        bp_display = f"{bp_sys}/{bp_dia}" if bp_sys and bp_dia else ""
        rr = html.escape(str(row.get("rr", "")))
        spo2 = html.escape(str(row.get("spo2", "")))

        body_rows += (
            '<tr style="border-bottom:1px solid #eee;">'
            f'<td style="{cell}">{label}</td>'
            f'<td style="{cell}">{time_val}</td>'
            f'<td style="{cell}">{hr}</td>'
            f'<td style="{cell}">{bp_display}</td>'
            f'<td style="{cell}">{rr}</td>'
            f'<td style="{cell}">{spo2}</td>'
            "</tr>"
        )

    raw_data = json.dumps({"rows": rows, "bp_placement": bp_placement})
    escaped_data = (
        raw_data
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )

    footer = (
        "</tbody></table>"
        f'<div id="vitals-raw-data" style="display:none" '
        f'data-vitals="{escaped_data}"></div>'
    )

    return header + body_rows + footer


_TRUTHY_SECRET_VALUES = {"1", "true", "yes", "on", "enabled"}


def _parse_bool_secret(value: str | None) -> bool:
    """Parse a string secret as a boolean. Accepts 1/true/yes/on/enabled (case-insensitive)."""
    return (value or "").strip().lower() in _TRUTHY_SECRET_VALUES


def _parse_vitals_datetime(timestamp: str) -> datetime.datetime:
    """Parse an ISO8601 timestamp from the client into a TZ-aware UTC datetime."""
    if timestamp:
        normalized = timestamp.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass
    return datetime.datetime.now(datetime.timezone.utc)


def _create_interval_observations(
    rows: list[dict[str, str]], patient_id: str, note_dbid: int
) -> list[Effect]:
    """Create Observation effects for each vital sign in the interval rows."""
    effects: list[Effect] = []

    for row in rows:
        timestamp = row.get("timestamp", "")
        if not timestamp:
            continue

        effective_dt = _parse_vitals_datetime(timestamp)
        label = row.get("label", "Vitals")

        hr = row.get("hr", "")
        sys_val = row.get("bp_sys", "")
        dia_val = row.get("bp_dia", "")
        rr = row.get("rr", "")
        spo2 = row.get("spo2", "")

        if hr:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"Heart Rate ({label})",
                category="vital-signs",
                value=str(hr),
                units="bpm",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_HR,
                        display="Heart rate",
                        system="http://loinc.org",
                    ),
                ],
            )
            effects.append(obs.create())

        if sys_val and dia_val:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"Blood Pressure ({label})",
                category="vital-signs",
                value=f"{sys_val}/{dia_val}",
                units="mmHg",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_BP_PANEL,
                        display="Blood pressure panel with all children optional",
                        system="http://loinc.org",
                    ),
                ],
                components=[
                    ObservationComponentData(
                        value_quantity=str(sys_val),
                        value_quantity_unit="mmHg",
                        name="Systolic Blood Pressure",
                        codings=[
                            CodingData(
                                code=LOINC_BP_SYS,
                                display="Systolic blood pressure",
                                system="http://loinc.org",
                            ),
                        ],
                    ),
                    ObservationComponentData(
                        value_quantity=str(dia_val),
                        value_quantity_unit="mmHg",
                        name="Diastolic Blood Pressure",
                        codings=[
                            CodingData(
                                code=LOINC_BP_DIA,
                                display="Diastolic blood pressure",
                                system="http://loinc.org",
                            ),
                        ],
                    ),
                ],
            )
            effects.append(obs.create())

        if spo2:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"SpO2 ({label})",
                category="vital-signs",
                value=str(spo2),
                units="%",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_SPO2,
                        display="Oxygen saturation",
                        system="http://loinc.org",
                    ),
                ],
            )
            effects.append(obs.create())

        if rr:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"Respiratory Rate ({label})",
                category="vital-signs",
                value=str(rr),
                units="breaths/min",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_RR,
                        display="Respiratory rate",
                        system="http://loinc.org",
                    ),
                ],
            )
            effects.append(obs.create())

    return effects


def _build_summary_html_table(
    buckets: list[dict[str, str]],
    bp_placement: str = "left_wrist",
    treatment_start: str = "",
    treatment_end: str = "",
) -> str:
    """Build an inline-styled HTML table for the summary CustomCommand."""
    cell = "padding:3px 5px;text-align:left;white-space:nowrap;"
    header = (
        '<table style="border-collapse:collapse;font-size:11px;'
        'font-family:sans-serif;width:100%;">'
        "<thead>"
        f'<tr style="background:#f5f5f5;border-bottom:2px solid #ddd;">'
        f'<th style="{cell}">Phase</th>'
        f'<th style="{cell}">Time</th>'
        f'<th style="{cell}"># Readings</th>'
        f'<th style="{cell}">HR (avg)</th>'
        f'<th style="{cell}">BP (avg)</th>'
        f'<th style="{cell}">RR (avg)</th>'
        f'<th style="{cell}">SpO2 (avg)</th>'
        "</tr>"
        "</thead><tbody>"
    )

    body_rows = ""
    for bucket in buckets:
        phase = html.escape(str(bucket.get("phase", "")))
        time_val = html.escape(str(bucket.get("time", "")))
        count = html.escape(str(bucket.get("count", "")))
        hr = html.escape(str(bucket.get("hr", "")))
        bp_sys = html.escape(str(bucket.get("bp_sys", "")))
        bp_dia = html.escape(str(bucket.get("bp_dia", "")))
        bp_display = f"{bp_sys}/{bp_dia}" if bp_sys and bp_dia else ""
        rr = html.escape(str(bucket.get("rr", "")))
        spo2 = html.escape(str(bucket.get("spo2", "")))

        body_rows += (
            '<tr style="border-bottom:1px solid #eee;">'
            f'<td style="{cell}">{phase}</td>'
            f'<td style="{cell}">{time_val}</td>'
            f'<td style="{cell}">{count}</td>'
            f'<td style="{cell}">{hr}</td>'
            f'<td style="{cell}">{bp_display}</td>'
            f'<td style="{cell}">{rr}</td>'
            f'<td style="{cell}">{spo2}</td>'
            "</tr>"
        )

    if treatment_start or treatment_end:
        ts = html.escape(treatment_start) if treatment_start else "&mdash;"
        te = html.escape(treatment_end) if treatment_end else "&mdash;"
        body_rows = (
            '<tr style="border-bottom:1px solid #eee;background:#fafafa;">'
            f'<td colspan="7" style="{cell};font-style:italic;color:#555;">'
            f"Treatment window: {ts} &ndash; {te}"
            "</td></tr>"
        ) + body_rows

    raw_data = json.dumps(
        {
            "buckets": buckets,
            "bp_placement": bp_placement,
            "treatment_start": treatment_start,
            "treatment_end": treatment_end,
        }
    )
    escaped_data = (
        raw_data
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )

    footer = (
        "</tbody></table>"
        f'<div id="vitals-raw-data" style="display:none" '
        f'data-vitals="{escaped_data}"></div>'
    )

    return header + body_rows + footer


def _create_summary_observations(
    buckets: list[dict[str, str]], patient_id: str, note_dbid: int
) -> list[Effect]:
    """Create Observation effects for each vital sign mean in the summary buckets."""
    effects: list[Effect] = []

    for bucket in buckets:
        timestamp = bucket.get("timestamp", "")
        if not timestamp:
            continue

        effective_dt = _parse_vitals_datetime(timestamp)
        label = bucket.get("label", "Vitals")

        hr = bucket.get("hr", "")
        sys_val = bucket.get("bp_sys", "")
        dia_val = bucket.get("bp_dia", "")
        rr = bucket.get("rr", "")
        spo2 = bucket.get("spo2", "")

        if hr:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"Mean Heart Rate ({label})",
                category="vital-signs",
                value=str(hr),
                units="bpm",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_HR_MEAN,
                        display="Mean heart rate",
                        system="http://loinc.org",
                    ),
                ],
            )
            effects.append(obs.create())

        if sys_val and dia_val:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"Mean Blood Pressure ({label})",
                category="vital-signs",
                value=f"{sys_val}/{dia_val}",
                units="mmHg",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_BP_PANEL_MEAN,
                        display="Blood pressure panel mean systolic and mean diastolic",
                        system="http://loinc.org",
                    ),
                ],
                components=[
                    ObservationComponentData(
                        value_quantity=str(sys_val),
                        value_quantity_unit="mmHg",
                        name="Mean Systolic Blood Pressure",
                        codings=[
                            CodingData(
                                code=LOINC_BP_SYS_MEAN,
                                display="Systolic blood pressure mean",
                                system="http://loinc.org",
                            ),
                        ],
                    ),
                    ObservationComponentData(
                        value_quantity=str(dia_val),
                        value_quantity_unit="mmHg",
                        name="Mean Diastolic Blood Pressure",
                        codings=[
                            CodingData(
                                code=LOINC_BP_DIA_MEAN,
                                display="Diastolic blood pressure mean",
                                system="http://loinc.org",
                            ),
                        ],
                    ),
                ],
            )
            effects.append(obs.create())

        if spo2:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"Mean SpO2 ({label})",
                category="vital-signs",
                value=str(spo2),
                units="%",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_SPO2_MEAN,
                        display="Mean oxygen saturation",
                        system="http://loinc.org",
                    ),
                ],
            )
            effects.append(obs.create())

        if rr:
            obs = Observation(
                patient_id=patient_id,
                note_id=note_dbid,
                name=f"Mean Respiratory Rate ({label})",
                category="vital-signs",
                value=str(rr),
                units="breaths/min",
                effective_datetime=effective_dt,
                codings=[
                    CodingData(
                        code=LOINC_RR_MEAN,
                        display="Mean respiratory rate",
                        system="http://loinc.org",
                    ),
                ],
            )
            effects.append(obs.create())

    return effects


def _coerce_elapsed_min(value) -> float | None:
    """Coerce a wire value to a float elapsed-minute, returning None on junk."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _classify_phase(
    elapsed_min: float | None,
    start_elapsed: float | None,
    end_elapsed: float | None,
) -> str:
    if start_elapsed is None and end_elapsed is None:
        return ""
    if elapsed_min is None:
        return ""
    if start_elapsed is not None and elapsed_min < start_elapsed:
        return "pre"
    if end_elapsed is not None and elapsed_min > end_elapsed:
        return "post"
    return "during"


def _mean_int(values: list[int]) -> str:
    """Round to the nearest int and return as a string; empty if no values."""
    return str(round(sum(values) / len(values))) if values else ""


def _format_local_time(dt: datetime.datetime, tz_offset_minutes: int) -> str:
    """Render dt as the user's local wall-clock HH:MM.

    `dt` is a UTC datetime from the DB; `tz_offset_minutes` is what JS's
    `Date.prototype.getTimezoneOffset()` returns — positive for west of UTC
    (e.g. 240 in EDT). Local = UTC - offset.
    """
    local = dt - datetime.timedelta(minutes=tz_offset_minutes)
    return local.strftime("%H:%M")


def _compute_buckets(
    readings: list[VitalstreamReading],
    session_start: datetime.datetime,
    increment_minutes: int,
    tz_offset_minutes: int = 0,
) -> list[dict]:
    """Compute Nth-minute-mark buckets from persisted readings.

    Each bucket averages readings within a 1-minute window (±30s) around the
    mark. Marks with no readings in their window are skipped — same algorithm
    that ran client-side previously.
    """
    if not readings:
        return []

    elapsed = [
        (r, (r.reading_time - session_start).total_seconds() / 60.0)
        for r in readings
    ]
    max_elapsed = max(em for _, em in elapsed)

    buckets: list[dict] = []
    t = 0.0
    while t <= max_elapsed + _WINDOW_HALF_MINUTES:
        lo = t - _WINDOW_HALF_MINUTES
        hi = t + _WINDOW_HALF_MINUTES
        window = [r for r, em in elapsed if lo <= em <= hi]
        if window:
            buckets.append(_bucket_from_readings(
                window,
                label=f"{int(t)} min",
                anchor_dt=session_start + datetime.timedelta(minutes=t),
                elapsed_min=t,
                tz_offset_minutes=tz_offset_minutes,
            ))
        t += increment_minutes
    return buckets


def _bucket_from_readings(
    readings: list[VitalstreamReading],
    *,
    label: str,
    anchor_dt: datetime.datetime,
    elapsed_min: float,
    tz_offset_minutes: int = 0,
) -> dict:
    hr = [r.hr for r in readings if r.hr is not None]
    sys_vals = [r.sys for r in readings if r.sys is not None]
    dia_vals = [r.dia for r in readings if r.dia is not None]
    rr = [r.resp for r in readings if r.resp is not None]
    spo2 = [r.spo2 for r in readings if r.spo2 is not None]
    return {
        "label": label,
        "count": str(len(readings)),
        "timestamp": anchor_dt.isoformat(),
        "time": _format_local_time(anchor_dt, tz_offset_minutes),
        "elapsed_min": elapsed_min,
        "hr": _mean_int(hr),
        "bp_sys": _mean_int(sys_vals),
        "bp_dia": _mean_int(dia_vals),
        "rr": _mean_int(rr),
        "spo2": _mean_int(spo2),
    }


def _compute_discharge_bucket(
    readings: list[VitalstreamReading],
    session_start: datetime.datetime,
    tz_offset_minutes: int = 0,
) -> dict | None:
    """Average over the trailing 30 seconds of readings."""
    if not readings:
        return None
    elapsed = [
        (r, (r.reading_time - session_start).total_seconds() / 60.0)
        for r in readings
    ]
    max_elapsed = max(em for _, em in elapsed)
    cutoff = max_elapsed - _WINDOW_HALF_MINUTES
    window = [r for r, em in elapsed if em >= cutoff]
    if not window:
        return None
    last = window[-1]
    last_elapsed = (last.reading_time - session_start).total_seconds() / 60.0
    bucket = _bucket_from_readings(
        window,
        label="Discharge",
        anchor_dt=last.reading_time,
        elapsed_min=last_elapsed,
        tz_offset_minutes=tz_offset_minutes,
    )
    return bucket


def _serialize_reading(reading: VitalstreamReading) -> dict:
    """Wire format for backfill on UI open — matches what the JS expects."""
    return {
        "timestamp": reading.reading_time.isoformat(),
        "hr": reading.hr,
        "sys": reading.sys,
        "dia": reading.dia,
        "resp": reading.resp,
        "spo2": reading.spo2,
    }


class VitalstreamUIAPI(StaffSessionAuthMixin, SimpleAPI):
    """API to serve the VitalStream integration UI."""

    def validate_session(self, session_id: str) -> VitalstreamSession | None:
        """Return the VitalstreamSession if it belongs to the logged-in staff."""
        logged_in_staff_id = self.request.headers["canvas-logged-in-user-id"]
        session = (
            VitalstreamSession.objects.filter(session_id=session_id).first()
        )
        if session is None or session.staff_id != logged_in_staff_id:
            return None
        return session

    @api.get("/vitalstream-ui/notes/<note_dbid>/")
    def index(self) -> list[Response | Effect]:
        """Render the custom UI for a note, creating the session if needed.

        The action button routes here with the note's dbid. We resolve the
        VitalstreamSession for this note (reusing the open one, or the most
        recent closed one for read-only revisit, otherwise creating a fresh
        open row) and render the UI with the resolved session_id baked in.
        This keeps the DB write inside a SimpleAPI handler — the persistence
        path other MSF plugins use.
        """
        note_dbid = self.request.path_params["note_dbid"]
        logged_in_staff_id = self.request.headers["canvas-logged-in-user-id"]

        try:
            note = Note.objects.select_related("note_type_version").get(dbid=note_dbid)
        except Note.DoesNotExist:
            return [
                HTMLResponse(
                    render_to_string("templates/session-not-found.html"),
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        session = self._get_or_create_session(note_dbid, logged_in_staff_id)

        note_type = note.note_type_version
        check = (
            ((note_type.name if note_type else "") + " " + (note.title or "")).lower()
        )
        is_spravato = "spravato" in check

        context = {
            "session_id": session.session_id,
            "subdomain": self.environment["CUSTOMER_IDENTIFIER"],
            "enable_mock_vitals": _parse_bool_secret(self.secrets.get("ENABLE_MOCK_VITALS")),
            "treatment_intervals": TREATMENT_INTERVALS,
            "is_spravato": is_spravato,
            "session_status": session.status,
        }
        return [
            HTMLResponse(
                render_to_string("templates/vitalstream-ui.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    def _get_or_create_session(
        self, note_dbid: int | str, staff_id: str
    ) -> VitalstreamSession:
        """Return the session row for this note, creating one if absent."""
        existing = (
            VitalstreamSession.objects.filter(
                note__dbid=note_dbid, status=SessionStatus.OPEN
            )
            .order_by("-started_at")
            .first()
        )
        if existing is not None:
            return existing

        # Fall back to the most recent closed session so revisiting the chart
        # pane after end-of-session lands on a read-only history view rather
        # than silently spinning up a new session.
        most_recent = (
            VitalstreamSession.objects.filter(note__dbid=note_dbid)
            .order_by("-started_at")
            .first()
        )
        if most_recent is not None:
            return most_recent

        session = VitalstreamSession(
            note_id=note_dbid,
            session_id=str(uuid4()),
            staff_id=staff_id,
            status=SessionStatus.OPEN,
        )
        session.save()
        return session

    @api.get("/vitalstream-ui/sessions/<session_id>/readings/")
    def list_readings(self) -> list[Response | Effect]:
        """Single-roundtrip UI hydration: status, persisted readings, and the
        last-saved form preferences for this session."""
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        readings = list(
            VitalstreamReading.objects.filter(session=session).order_by("reading_time")
        )
        return [
            JSONResponse(
                {
                    "status": session.status,
                    "readings": [_serialize_reading(r) for r in readings],
                    "preferences": _load_prefs(session_id),
                }
            )
        ]

    @api.put("/vitalstream-ui/sessions/<session_id>/preferences/")
    def save_preferences(self) -> list[Response | Effect]:
        """Persist the form inputs (treatment type, increment, wrist, treatment
        times) in the SDK cache so they survive a chart-pane close/reopen.

        Cache TTL is 48h — VitalStream sessions run for hours, not days, so
        the cache is the appropriate store rather than a CustomModel."""
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)
        if session is None:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        try:
            body = self.request.json() or {}
        except (ValueError, TypeError):
            body = {}
        if not isinstance(body, dict):
            body = {}

        stored = _save_prefs(session_id, body)
        return [JSONResponse({"preferences": stored})]

    @api.post("/vitalstream-ui/sessions/<session_id>/mock-vitals/")
    def mock_vitals(self) -> list[Response | Effect]:
        """Generate a mock vital sign reading, persist it, and broadcast via WebSocket."""
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        if not _parse_bool_secret(self.secrets.get("ENABLE_MOCK_VITALS")):
            return [
                JSONResponse(
                    {"error": "Mock vitals not enabled"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        if session.status != SessionStatus.OPEN:
            return [
                JSONResponse(
                    {"error": "Session is closed"},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        now = datetime.datetime.now(datetime.timezone.utc)
        reading = VitalstreamReading(
            session=session,
            reading_time=now,
            hr=random.randint(60, 100),
            sys=random.randint(110, 140),
            dia=random.randint(65, 90),
            resp=random.randint(12, 20),
            spo2=random.randint(95, 100),
        )
        reading.save()

        measurements = {
            now.isoformat(): {
                "hr": reading.hr,
                "sys": reading.sys,
                "dia": reading.dia,
                "resp": reading.resp,
                "spo2": reading.spo2,
            }
        }
        channel = session_id.replace("-", "_")

        return [
            Broadcast(
                message={"measurements": measurements}, channel=channel
            ).apply(),
            JSONResponse({"status": "ok"}),
        ]

    @api.post("/vitalstream-ui/sessions/<session_id>/save-intervals/")
    def save_intervals(self) -> list[Response | Effect]:
        """Save interval vitals as a CustomCommand and create Observations.

        Spravato workflow only — does not end the session.
        """
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        data = self.request.json()
        rows = data.get("rows", [])

        if not rows:
            return [
                JSONResponse(
                    {"error": "No interval data provided"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        note = Note.objects.select_related("patient").get(dbid=session.note_id)
        patient_id = note.patient.id

        bp_placement = data.get("bp_placement", "left_wrist")
        html_content = _build_interval_html_table(rows, bp_placement)

        custom_command = CustomCommand(
            schema_key="spravatoVitals",
            content=html_content,
        )
        custom_command.command_uuid = str(uuid.uuid4())
        custom_command.note_uuid = str(note.id)

        log.info(f"[VitalStream] Saving intervals for note {note.id}: {len(rows)} rows")
        effects: list[Response | Effect] = [custom_command.originate()]
        effects.extend(
            _create_interval_observations(rows, str(patient_id), note.dbid)
        )

        # Write note metadata so the Spravato charting app can reload
        # vitals on note refresh (mirrors spravato_charting api.py:404-423)
        from canvas_sdk.effects.note.note import Note as NoteEffect

        note_effect = NoteEffect(instance_id=str(note.id))
        vitals_json = json.dumps({"rows": rows, "bp_placement": bp_placement})
        effects.append(
            note_effect.upsert_metadata("spravato:vitals_data", vitals_json)
        )

        # Labels match Spravato charting app: Pre-administration, 40-min post, Pre-discharge
        for row in rows:
            bp_sys = row.get("bp_sys", "")
            bp_dia = row.get("bp_dia", "")
            if bp_sys and bp_dia:
                label = row.get("label", "").lower()
                bp_val = f"{bp_sys}/{bp_dia}"
                if "pre" in label and ("admin" in label or "administration" in label):
                    effects.append(
                        note_effect.upsert_metadata("spravato:bp_pre_admin", bp_val)
                    )
                elif "40" in label and ("min" in label or "post" in label):
                    effects.append(
                        note_effect.upsert_metadata("spravato:bp_40min_post", bp_val)
                    )
                elif "discharge" in label or "completion" in label:
                    effects.append(
                        note_effect.upsert_metadata("spravato:bp_pre_completion", bp_val)
                    )

        # Notify the Spravato charting app via WebSocket so it can
        # live-reload the vitals section without a page refresh.
        note_channel = f"spravato_notify_{str(note.id).replace('-', '_')}"
        log.info(f"[VitalStream] Broadcasting vitals_saved on {note_channel}")
        effects.append(
            Broadcast(
                channel=note_channel,
                message={
                    "event_type": "vitals_saved",
                    "note_uuid": str(note.id),
                    "schema_key": "spravatoVitals",
                },
            ).apply()
        )
        log.info(f"[VitalStream] Returning {len(effects)} effects")

        effects.append(JSONResponse({"status": "ok"}))

        return effects

    @api.post("/vitalstream-ui/sessions/<session_id>/end-session/")
    def end_session(self) -> list[Response | Effect]:
        """Atomically close the session, then summarize and write Observations.

        The "End Session & Save Summary" button hits this endpoint. Steps:

        1. Flip session.status to "closed" so any in-flight device posts are
           rejected from this point forward (status check happens in the
           device endpoint before persisting).
        2. Read all persisted VitalstreamReading rows for the session.
        3. Compute per-increment means using a 1-min window around each Nth
           minute mark (algorithm previously implemented client-side).
        4. Write mean Observations + vitalstreamSummary CustomCommand.
        5. Broadcast session_closed so any other open UIs disable input.
        """
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        # Idempotency: a closed session has already had its summary written.
        # Re-running would duplicate the CustomCommand + Observations and use
        # a now-different snapshot of readings (any that raced in before the
        # close commit). Just acknowledge.
        if session.status == SessionStatus.CLOSED:
            log.info(
                f"[VitalStream] end_session called on already-closed "
                f"session {session_id}; returning without re-saving."
            )
            channel = session_id.replace("-", "_")
            return [
                Broadcast(
                    channel=channel,
                    message={"event_type": "session_closed"},
                ).apply(),
                JSONResponse({"status": "closed", "already_closed": True}),
            ]

        data = self.request.json() or {}
        increment_minutes = data.get("summary_increment_minutes", _DEFAULT_INCREMENT)
        try:
            increment_minutes = int(increment_minutes)
        except (TypeError, ValueError):
            increment_minutes = _DEFAULT_INCREMENT
        if increment_minutes not in _VALID_INCREMENTS:
            increment_minutes = _DEFAULT_INCREMENT

        bp_placement = data.get("bp_placement", "left_wrist")
        treatment_start = (data.get("treatment_start") or "").strip()
        treatment_end = (data.get("treatment_end") or "").strip()
        # Elapsed-minute offsets computed client-side from sessionStartTime and
        # the local HH:MM inputs. The server can't resolve HH:MM against UTC
        # readings without the user's tz, so it trusts what the browser sent.
        start_elapsed = _coerce_elapsed_min(data.get("treatment_start_elapsed_min"))
        end_elapsed = _coerce_elapsed_min(data.get("treatment_end_elapsed_min"))
        # Browser's Date.prototype.getTimezoneOffset(): positive west of UTC.
        try:
            tz_offset_minutes = int(data.get("tz_offset_minutes") or 0)
        except (TypeError, ValueError):
            tz_offset_minutes = 0

        # Step 1: close the session atomically. This stops the device endpoint
        # from persisting any further readings.
        session.status = SessionStatus.CLOSED
        session.ended_at = datetime.datetime.now(datetime.timezone.utc)
        session.summary_increment_minutes = increment_minutes
        session.save()

        # Step 2: read all persisted readings. Done AFTER the close so any
        # in-flight device POSTs are race-rejected at most once.
        readings = list(
            VitalstreamReading.objects.filter(session=session).order_by("reading_time")
        )
        log.info(
            f"[VitalStream] end_session {session_id}: "
            f"closed at {session.ended_at}, {len(readings)} readings persisted, "
            f"increment={increment_minutes}min"
        )

        note = Note.objects.select_related("patient").get(dbid=session.note_id)
        patient_id = note.patient.id

        effects: list[Response | Effect] = []

        if not readings:
            # No data to summarize, but we still close the session and notify.
            channel = session_id.replace("-", "_")
            effects.append(
                Broadcast(
                    channel=channel,
                    message={"event_type": "session_closed"},
                ).apply()
            )
            effects.append(
                JSONResponse({"status": "closed", "buckets": []})
            )
            return effects

        # Step 3: compute mean buckets.
        session_start = readings[0].reading_time
        buckets = _compute_buckets(
            readings, session_start, increment_minutes, tz_offset_minutes
        )

        # Phase classification + optional discharge bucket. start_elapsed and
        # end_elapsed already arrived as elapsed-minute floats from the client,
        # so no further timezone math here.
        for bucket in buckets:
            bucket["phase"] = _classify_phase(
                bucket.get("elapsed_min"), start_elapsed, end_elapsed
            )

        if treatment_end and end_elapsed is not None:
            discharge = _compute_discharge_bucket(readings, session_start, tz_offset_minutes)
            if discharge is not None and discharge["elapsed_min"] > end_elapsed:
                discharge["phase"] = "discharge"
                buckets.append(discharge)

        # Strip the float elapsed_min before serializing — the wire format and
        # the persisted HTML table only care about the human-facing fields.
        for bucket in buckets:
            bucket.pop("elapsed_min", None)

        # Step 4: persist as CustomCommand + Observations.
        html_content = _build_summary_html_table(
            buckets, bp_placement, treatment_start, treatment_end
        )
        custom_command = CustomCommand(
            schema_key="vitalstreamSummary",
            content=html_content,
        )
        custom_command.command_uuid = str(uuid.uuid4())
        custom_command.note_uuid = str(note.id)
        effects.append(custom_command.originate())
        effects.extend(
            _create_summary_observations(buckets, str(patient_id), note.dbid)
        )

        # Step 5: broadcast that the session is closed.
        channel = session_id.replace("-", "_")
        effects.append(
            Broadcast(
                channel=channel,
                message={"event_type": "session_closed"},
            ).apply()
        )

        log.info(
            f"[VitalStream] Ended session {session_id}: "
            f"{len(readings)} readings, {len(buckets)} buckets"
        )
        effects.append(JSONResponse({"status": "closed", "buckets": buckets}))
        return effects

    @api.get("/main.js")
    def get_main_js(self) -> list[Response | Effect]:
        """Serve the main JavaScript file."""
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the CSS styles file."""
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
