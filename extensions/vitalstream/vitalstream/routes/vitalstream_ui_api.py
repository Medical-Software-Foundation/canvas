import datetime
import html
import json
import random
import uuid
from http import HTTPStatus

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.observation import CodingData, Observation, ObservationComponentData
from canvas_sdk.effects.simple_api import Broadcast, HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note

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
from vitalstream.util import session_key

from logger import log


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


def _parse_vitals_datetime(time_str: str) -> datetime.datetime:
    """Combine a time string (HH:MM:SS or HH:MM) with today's date."""
    today = datetime.date.today()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.datetime.strptime(time_str, fmt).time()
            return datetime.datetime.combine(today, t)
        except (ValueError, TypeError):
            continue
    # datetime.time is not in Canvas sandbox ALLOWED_MODULES, so use strptime
    fallback_t = datetime.datetime.strptime("00:00", "%H:%M").time()
    return datetime.datetime.combine(today, fallback_t)


def _create_interval_observations(
    rows: list[dict[str, str]], patient_id: str, note_dbid: int
) -> list[Effect]:
    """Create Observation effects for each vital sign in the interval rows."""
    effects: list[Effect] = []

    for row in rows:
        time_str = row.get("time", "")
        if not time_str:
            continue

        effective_dt = _parse_vitals_datetime(time_str)
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
        time_str = bucket.get("time", "")
        if not time_str:
            continue

        effective_dt = _parse_vitals_datetime(time_str)
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


class VitalstreamUIAPI(StaffSessionAuthMixin, SimpleAPI):
    """API to serve the VitalStream integration UI."""

    def validate_session(self, session_id: str) -> dict | None:
        """Validate that the session exists and belongs to the logged-in staff."""
        logged_in_staff_id = self.request.headers["canvas-logged-in-user-id"]
        session = get_cache().get(session_key(session_id))

        if session is None or session.get("staff_id") != logged_in_staff_id:
            return None
        return session

    @api.get("/vitalstream-ui/sessions/<session_id>/")
    def index(self) -> list[Response | Effect]:
        """Render the custom UI for the chart application."""
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                HTMLResponse(
                    render_to_string("templates/session-not-found.html"),
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        note = Note.objects.select_related("note_type_version").get(dbid=session["note_id"])
        note_type = note.note_type_version
        check = (
            ((note_type.name if note_type else "") + " " + (note.title or "")).lower()
        )
        is_spravato = "treatment" in check or "spravato" in check

        context = {
            "session_id": session_id,
            "subdomain": self.environment["CUSTOMER_IDENTIFIER"],
            "enable_mock_vitals": bool(self.secrets.get("ENABLE_MOCK_VITALS")),
            "treatment_intervals": TREATMENT_INTERVALS,
            "is_spravato": is_spravato,
        }
        return [
            HTMLResponse(
                render_to_string("templates/vitalstream-ui.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/vitalstream-ui/sessions/<session_id>/mock-vitals/")
    def mock_vitals(self) -> list[Response | Effect]:
        """Generate a mock vital sign reading and broadcast via WebSocket."""
        session_id = self.request.path_params["session_id"]
        session = self.validate_session(session_id)

        if session is None:
            return [
                JSONResponse(
                    {"error": "Session not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        if not self.secrets.get("ENABLE_MOCK_VITALS"):
            return [
                JSONResponse(
                    {"error": "Mock vitals not enabled"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        measurements = {
            now: {
                "hr": random.randint(60, 100),
                "sys": random.randint(110, 140),
                "dia": random.randint(65, 90),
                "resp": random.randint(12, 20),
                "spo2": random.randint(95, 100),
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
        """Save interval vitals as a CustomCommand and create Observations."""
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

        note = Note.objects.select_related("patient").get(dbid=session["note_id"])
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

        # Store individual BP metadata for REMS extractor
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
        log.info(f"[VitalStream] Broadcasting vitals_saved on spravato_notify for note {note.id}")
        effects.append(
            Broadcast(
                channel="spravato_notify",
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

    @api.post("/vitalstream-ui/sessions/<session_id>/save-summary/")
    def save_summary(self) -> list[Response | Effect]:
        """Save summary vitals (10-min bucket averages) as a CustomCommand and Observations."""
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
        buckets = data.get("buckets", [])

        if not buckets:
            return [
                JSONResponse(
                    {"error": "No summary data provided"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        note = Note.objects.select_related("patient").get(dbid=session["note_id"])
        patient_id = note.patient.id

        bp_placement = data.get("bp_placement", "left_wrist")
        treatment_start = data.get("treatment_start", "") or ""
        treatment_end = data.get("treatment_end", "") or ""
        html_content = _build_summary_html_table(
            buckets, bp_placement, treatment_start, treatment_end
        )

        custom_command = CustomCommand(
            schema_key="vitalstreamSummary",
            content=html_content,
        )
        custom_command.command_uuid = str(uuid.uuid4())
        custom_command.note_uuid = str(note.id)

        log.info(f"[VitalStream] Saving summary for note {note.id}: {len(buckets)} buckets")
        effects: list[Response | Effect] = [custom_command.originate()]
        effects.extend(
            _create_summary_observations(buckets, str(patient_id), note.dbid)
        )

        effects.append(JSONResponse({"status": "ok"}))

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
