"""SimpleAPI: Vitals session capture + end-of-session note creation."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.observation import CodingData, Observation, ObservationComponentData
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data import Note, NoteType, Patient, PracticeLocation, Staff

from logger import log
from vitals_dashboard.commands.vitals_summary import VitalsSummaryCommand
from vitals_dashboard.models import CUFF_LOCATIONS, POSITIONS, VITAL_TYPES, VitalsMeasurement, VitalsSession


_SINCE_WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _parse_since(param: str):
    """Return a cutoff datetime for the given window param, or None for 'all'."""
    key = (param or "").strip().lower()
    if key == "all":
        return None
    delta = _SINCE_WINDOWS.get(key, timedelta(days=7))
    return datetime.now(timezone.utc) - delta


UNIT_BY_TYPE = {
    "bp_systolic": "mmHg",
    "bp_diastolic": "mmHg",
    "heart_rate": "bpm",
    "weight_current": "lbs",
    "weight_dry": "lbs",
    "urine_output": "mL",
    "oxygen_saturation": "%",
    "respiration_rate": "breaths/min",
    "temperature": "F",
    "pain_score": "",
    "edema": "",
}

LABEL_BY_TYPE = {
    "heart_rate": "Heart Rate",
    "weight_current": "Current Weight",
    "weight_dry": "Dry Weight",
    "oxygen_saturation": "O2 Saturation",
    "respiration_rate": "Respiration Rate",
    "temperature": "Temperature",
    "pain_score": "Pain Score",
    "edema": "Edema",
}

CUFF_LABEL = {
    "right_arm": "Right arm",
    "left_arm": "Left arm",
    "right_thigh": "Right thigh",
    "left_thigh": "Left thigh",
    "right_wrist": "Right wrist",
    "left_wrist": "Left wrist",
}

def _loinc(code: str, display: str) -> CodingData:
    return CodingData(code=code, display=display, system="http://loinc.org")


# Position-specific BP LOINCs (CCDA-valid, distinct from the standard 8480-6 / 8462-4).
# Orthostatic BP is emitted as discrete observations — each code carries its own
# position semantic, so readers don't need to inspect the name suffix to classify.
_ORTHO_BP_LOINC = {
    ("bp_systolic", "laying"): ("8461-1", "Systolic blood pressure--lying"),
    ("bp_systolic", "sitting"): ("8459-0", "Systolic blood pressure--sitting"),
    ("bp_systolic", "standing"): ("8460-3", "Systolic blood pressure--standing"),
    ("bp_diastolic", "laying"): ("8455-8", "Diastolic blood pressure--lying"),
    ("bp_diastolic", "sitting"): ("8453-3", "Diastolic blood pressure--sitting"),
    ("bp_diastolic", "standing"): ("8454-1", "Diastolic blood pressure--standing"),
}


def _obs_name(base: str, *, cuff: str = "", position: str = "") -> str:
    """Encode cuff location and position into the Observation name.

    The Canvas SDK's Observation effect does not expose targetSiteCode /
    methodCode, so cuff location has no native home. We append it to `name`
    with a pipe delimiter so the field stays single-source-of-truth and the
    read path can parse it back out (see _parse_obs_name).

    Examples:
        _obs_name("blood_pressure") -> "blood_pressure"
        _obs_name("blood_pressure", cuff="right_arm") -> "blood_pressure|cuff=right_arm"
        _obs_name("pulse", position="standing") -> "pulse|pos=standing"
    """
    parts = [base]
    if cuff:
        parts.append(f"cuff={cuff}")
    if position:
        parts.append(f"pos={position}")
    return "|".join(parts)


def build_vital_observations(patient_key, note_dbid, session_dt, measurements):
    """Build CCDA-compliant FHIR Observation effects for a completed vitals session.

    Emitted synchronously with the Vitals note (patient-scoped, category=vital-signs).
    Each measurement becomes one Observation with a LOINC code, UCUM unit, and
    cuff/position encoded into `name` when applicable. Standard BP is a panel
    observation with systole/diastole components (LOINC 85354-9); orthostatic BP
    is emitted as discrete observations using position-specific LOINCs.

    note_dbid is Optional — at Finish-Session emit time the note's dbid is not
    yet resolved; pass None. The Observations still link to the patient + session.
    """
    by_type = {}
    for m in measurements:
        by_type.setdefault(m.vital_type, []).append(m)

    effects = []

    def _emit_simple(m, *, name_base, loinc_code, loinc_display, unit,
                     value=None, include_cuff=False):
        effective = m.recorded_at or session_dt
        v = value if value is not None else (
            str(m.value_numeric) if m.value_numeric is not None else None
        )
        if v is None or v == "":
            return
        cuff = getattr(m, "cuff_location", "") if include_cuff else ""
        pos = getattr(m, "position", "") or ""
        effects.append(Observation(
            patient_id=patient_key,
            note_id=note_dbid,
            name=_obs_name(name_base, cuff=cuff, position=pos),
            effective_datetime=effective,
            category="vital-signs",
            codings=[_loinc(loinc_code, loinc_display)],
            value=v,
            units=unit,
        ).create())

    # Standard (non-orthostatic) BP as a panel with components — mirrors Canvas's
    # VitalsCommand output so chart-detail queries render consistently.
    std_sys = next((m for m in by_type.get("bp_systolic", []) if not m.position), None)
    std_dia = next((m for m in by_type.get("bp_diastolic", []) if not m.position), None)
    if (std_sys and std_sys.value_numeric is not None) or (std_dia and std_dia.value_numeric is not None):
        sys_v = str(std_sys.value_numeric) if std_sys and std_sys.value_numeric is not None else ""
        dia_v = str(std_dia.value_numeric) if std_dia and std_dia.value_numeric is not None else ""
        components = []
        if sys_v:
            components.append(ObservationComponentData(
                value_quantity=sys_v,
                value_quantity_unit="mm[Hg]",
                name="systole",
                codings=[_loinc("8480-6", "Systolic blood pressure")],
            ))
        if dia_v:
            components.append(ObservationComponentData(
                value_quantity=dia_v,
                value_quantity_unit="mm[Hg]",
                name="diastole",
                codings=[_loinc("8462-4", "Diastolic blood pressure")],
            ))
        combined = f"{sys_v}/{dia_v}" if sys_v or dia_v else ""
        bp_dt = (std_sys and std_sys.recorded_at) or (std_dia and std_dia.recorded_at) or session_dt
        cuff = ""
        for src in (std_sys, std_dia):
            if src and getattr(src, "cuff_location", ""):
                cuff = src.cuff_location
                break
        effects.append(Observation(
            patient_id=patient_key,
            note_id=note_dbid,
            name=_obs_name("blood_pressure", cuff=cuff),
            effective_datetime=bp_dt,
            category="vital-signs",
            codings=[_loinc("85354-9", "Blood pressure panel with all children optional")],
            value=combined,
            units="mm[Hg]",
            components=components,
        ).create())

    # Orthostatic BP — discrete observations, position-specific LOINCs.
    for vt in ("bp_systolic", "bp_diastolic"):
        for m in by_type.get(vt, []):
            if not m.position or m.value_numeric is None:
                continue
            key = (vt, m.position)
            if key not in _ORTHO_BP_LOINC:
                continue
            loinc_code, loinc_display = _ORTHO_BP_LOINC[key]
            # Name base stays "blood_pressure" for read-path grouping; LOINC + pos suffix
            # carry the discriminator.
            _emit_simple(
                m,
                name_base="blood_pressure",
                loinc_code=loinc_code,
                loinc_display=loinc_display,
                unit="mm[Hg]",
                include_cuff=True,
            )

    # Heart rate — standard + orthostatic (plain 8867-4 for all; position in name suffix)
    for m in by_type.get("heart_rate", []):
        _emit_simple(
            m,
            name_base="pulse",
            loinc_code="8867-4",
            loinc_display="Heart rate",
            unit="/min",
        )

    # Current weight — 29463-7, lbs (UCUM [lb_av]). Plugin is source of truth;
    # no longer converting to Canvas-internal oz.
    for m in by_type.get("weight_current", []):
        _emit_simple(
            m,
            name_base="weight",
            loinc_code="29463-7",
            loinc_display="Body weight",
            unit="[lb_av]",
        )

    # Dry weight — CCDA-valid LOINC 75292-3 (Dry body weight Estimated)
    for m in by_type.get("weight_dry", []):
        _emit_simple(
            m,
            name_base="dry_weight",
            loinc_code="75292-3",
            loinc_display="Dry body weight Estimated",
            unit="[lb_av]",
        )

    # Oxygen saturation (pulse ox)
    for m in by_type.get("oxygen_saturation", []):
        _emit_simple(
            m,
            name_base="oxygen_saturation",
            loinc_code="59408-5",
            loinc_display="Oxygen saturation in Arterial blood by Pulse oximetry",
            unit="%",
        )

    # Respiration rate
    for m in by_type.get("respiration_rate", []):
        _emit_simple(
            m,
            name_base="respiration_rate",
            loinc_code="9279-1",
            loinc_display="Respiratory rate",
            unit="/min",
        )

    # Body temperature — Fahrenheit
    for m in by_type.get("temperature", []):
        _emit_simple(
            m,
            name_base="body_temperature",
            loinc_code="8310-5",
            loinc_display="Body temperature",
            unit="[degF]",
        )

    # Pain score (0-10 NRS)
    for m in by_type.get("pain_score", []):
        _emit_simple(
            m,
            name_base="pain_score",
            loinc_code="38208-5",
            loinc_display="Pain severity - 0-10 verbal numeric rating [Score] - Reported",
            unit="{score}",
        )

    # Urine output — one Observation per void (effective_datetime carries the void time)
    for m in by_type.get("urine_output", []):
        _emit_simple(
            m,
            name_base="urine_output",
            loinc_code="9187-6",
            loinc_display="Urine output",
            unit="mL",
        )

    # Edema — qualitative text value (grade + location descriptor), no unit
    for m in by_type.get("edema", []):
        if not m.value_text:
            continue
        effects.append(Observation(
            patient_id=patient_key,
            note_id=note_dbid,
            name="edema",
            effective_datetime=m.recorded_at or session_dt,
            category="vital-signs",
            codings=[_loinc("38378-0", "Edema")],
            value=m.value_text,
        ).create())

    return effects


def _parse_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def _parse_datetime(value, default=None):
    if not value:
        return default or datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return default or datetime.now(timezone.utc)


def _fmt_num(val):
    if val is None:
        return ""
    s = str(val)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _render_summary_html(session, measurements, display_dt_str):
    """Render a clinical HTML summary of a session for the Vitals note.

    Uses ASCII-only characters (no em-dash/middle-dot) to avoid UTF-8 double-encoding
    in the Canvas CustomCommand content pipeline.
    """
    by_type = {}
    for m in measurements:
        by_type.setdefault(m.vital_type, []).append(m)

    parts = [
        '<div style="font-family:system-ui,sans-serif;color:#1a1a1a;">',
        f'<p style="margin:0 0 .5rem;"><strong>Vitals Session:</strong> {display_dt_str}</p>',
    ]

    # Standard (non-positional) BP first
    std_sys = [m for m in by_type.get("bp_systolic", []) if not m.position]
    std_dia = [m for m in by_type.get("bp_diastolic", []) if not m.position]
    std_hr_pos = [m for m in by_type.get("heart_rate", []) if not m.position]
    if std_sys or std_dia or std_hr_pos:
        ssys = _fmt_num(std_sys[0].value_numeric) if std_sys else "-"
        sdia = _fmt_num(std_dia[0].value_numeric) if std_dia else "-"
        shr = _fmt_num(std_hr_pos[0].value_numeric) if std_hr_pos else "-"
        std_cuff = ""
        for src in (std_sys, std_dia, std_hr_pos):
            if src and getattr(src[0], "cuff_location", ""):
                std_cuff = CUFF_LABEL.get(src[0].cuff_location, "")
                break
        cuff_suffix = f" ({std_cuff})" if std_cuff else ""
        parts.append(f'<p style="margin:.5rem 0;"><strong>Blood Pressure{cuff_suffix}:</strong> {ssys}/{sdia} mmHg | HR {shr} bpm</p>')

    bp_rows = []
    ortho_cuff = ""
    for pos_key, pos_label in [("laying", "Laying"), ("sitting", "Sitting"), ("standing", "Standing")]:
        sys_ms = [m for m in by_type.get("bp_systolic", []) if m.position == pos_key]
        dia_ms = [m for m in by_type.get("bp_diastolic", []) if m.position == pos_key]
        hr_ms = [m for m in by_type.get("heart_rate", []) if m.position == pos_key]
        if not (sys_ms or dia_ms or hr_ms):
            continue
        if not ortho_cuff:
            for src in (sys_ms, dia_ms, hr_ms):
                if src and getattr(src[0], "cuff_location", ""):
                    ortho_cuff = CUFF_LABEL.get(src[0].cuff_location, "")
                    break
        sys_val = _fmt_num(sys_ms[0].value_numeric) if sys_ms else "-"
        dia_val = _fmt_num(dia_ms[0].value_numeric) if dia_ms else "-"
        hr_val = _fmt_num(hr_ms[0].value_numeric) if hr_ms else "-"
        bp_rows.append(f"<li>{pos_label}: {sys_val}/{dia_val} mmHg | HR {hr_val} bpm</li>")
    if bp_rows:
        header = "Orthostatic BP &amp; HR"
        if ortho_cuff:
            header += f" ({ortho_cuff})"
        parts.append(f'<p style="margin:.75rem 0 .25rem;"><strong>{header}</strong></p><ul style="margin:0;padding-left:1.25rem;">')
        parts.extend(bp_rows)
        parts.append("</ul>")

    weight_cur = by_type.get("weight_current", [])
    weight_dry = by_type.get("weight_dry", [])
    if weight_cur or weight_dry:
        cur = _fmt_num(weight_cur[0].value_numeric) if weight_cur else "-"
        dry = _fmt_num(weight_dry[0].value_numeric) if weight_dry else "-"
        parts.append(f'<p style="margin:.5rem 0;"><strong>Weight:</strong> Current {cur} lbs | Dry {dry} lbs</p>')

    urine = sorted(by_type.get("urine_output", []), key=lambda m: m.recorded_at or session.session_datetime)
    if urine:
        parts.append('<p style="margin:.75rem 0 .25rem;"><strong>Urine Output</strong></p><ul style="margin:0;padding-left:1.25rem;">')
        total = Decimal("0")
        for m in urine:
            t = m.recorded_at.strftime("%H:%M") if m.recorded_at else "-"
            vol = _fmt_num(m.value_numeric)
            desc = f" ({m.value_text})" if m.value_text else ""
            parts.append(f"<li>{t} - {vol} mL{desc}</li>")
            if m.value_numeric is not None:
                total += m.value_numeric
        parts.append(f'<li style="list-style:none;margin-top:.25rem;"><em>Total: {_fmt_num(total)} mL</em></li>')
        parts.append("</ul>")

    other_labels = []
    for vt in ("oxygen_saturation", "respiration_rate", "temperature", "pain_score"):
        rows = by_type.get(vt, [])
        if rows and rows[0].value_numeric is not None:
            other_labels.append(f"{LABEL_BY_TYPE[vt]}: {_fmt_num(rows[0].value_numeric)} {UNIT_BY_TYPE[vt]}".strip())
    edema = by_type.get("edema", [])
    if edema and edema[0].value_text:
        other_labels.append(f"Edema: {edema[0].value_text}")
    if other_labels:
        parts.append('<p style="margin:.75rem 0 .25rem;"><strong>Other Vitals</strong></p><ul style="margin:0;padding-left:1.25rem;">')
        parts.extend(f"<li>{label}</li>" for label in other_labels)
        parts.append("</ul>")

    parts.append("</div>")
    return "".join(parts)


class VitalsAPI(StaffSessionAuthMixin, SimpleAPI):
    PREFIX = None

    def _logged_in_staff_id(self) -> str:
        # StaffSessionAuthMixin guarantees any request reaching a handler is a staff session,
        # so Canvas has set these headers to the authenticated staff user.
        headers = getattr(self.request, "headers", {}) or {}
        return headers.get("canvas-logged-in-user-id", "") or ""

    @api.post("/sessions")
    def create_session(self) -> list[Response | Effect]:
        """Create a VitalsSession and measurements. If `finish: true`, also create a Vitals note."""
        data = self.request.json()

        patient_key = (data.get("patient_key") or "").strip()
        # Always attribute to the authenticated staff user; do not trust body value.
        entered_by = self._logged_in_staff_id()
        finish = bool(data.get("finish"))
        display_dt_str = (data.get("session_datetime_display") or "").strip()

        if not patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]
        if not entered_by:
            return [JSONResponse({"error": "entered_by_staff_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        measurements = data.get("measurements") or []
        if not isinstance(measurements, list) or not measurements:
            return [JSONResponse({"error": "measurements must be a non-empty list"}, status_code=HTTPStatus.BAD_REQUEST)]

        session_dt = _parse_datetime(data.get("session_datetime"))
        update_id_raw = (data.get("update_session_id") or "").strip()

        session = None
        if update_id_raw and update_id_raw.isdigit():
            session = VitalsSession.objects.filter(dbid=int(update_id_raw)).first()
            if session and session.patient_key != patient_key:
                return [JSONResponse(
                    {"error": "update_session_id belongs to a different patient"},
                    status_code=HTTPStatus.FORBIDDEN,
                )]

        if session is not None:
            session.session_datetime = session_dt
            session.entered_by_staff_key = entered_by
            session.save()
            VitalsMeasurement.objects.filter(session_id=str(session.dbid)).delete()
        else:
            session = VitalsSession.objects.create(
                patient_key=patient_key,
                note_id=(data.get("note_id") or "").strip(),
                entered_by_staff_key=entered_by,
                provider_of_record_key=(data.get("provider_of_record_key") or "").strip(),
                session_datetime=session_dt,
            )

        rows_to_create = []
        for m in measurements:
            vital_type = (m.get("vital_type") or "").strip()
            if vital_type not in VITAL_TYPES:
                continue

            position = (m.get("position") or "").strip()
            if position and position not in POSITIONS:
                position = ""

            cuff_location = (m.get("cuff_location") or "").strip()
            if cuff_location and cuff_location not in CUFF_LOCATIONS:
                cuff_location = ""

            value_numeric = _parse_decimal(m.get("value_numeric"))
            value_text = (m.get("value_text") or "").strip()
            if value_numeric is None and not value_text:
                continue

            rows_to_create.append(VitalsMeasurement(
                session_id=str(session.dbid),
                patient_key=patient_key,
                vital_type=vital_type,
                position=position,
                cuff_location=cuff_location,
                value_numeric=value_numeric,
                value_text=value_text,
                unit=UNIT_BY_TYPE.get(vital_type, ""),
                recorded_at=_parse_datetime(m.get("recorded_at"), default=session_dt),
                entered_by_staff_key=entered_by,
            ))

        created = VitalsMeasurement.objects.bulk_create(rows_to_create) if rows_to_create else []

        log.info(
            f"[vitals-dashboard] Session {session.dbid} saved for patient={patient_key} "
            f"with {len(created)} measurements (finish={finish})"
        )

        response_payload = {
            "session_id": str(session.dbid),
            "measurement_count": len(created),
            "note_id": "",
            "note_created": False,
        }

        effects: list = []
        if finish:
            try:
                note_effect, command_effect, note_uuid = self._build_finish_effects(
                    session, created, entered_by, display_dt_str
                )
                effects.append(note_effect)
                effects.append(command_effect)
                # Observations are emitted by protocols.vitals_flush on the next
                # NOTE_STATE_CHANGE_EVENT_CREATED — Canvas silently drops Observation
                # effects with note_id=None, and the note's int dbid doesn't exist
                # until the NoteEffect above is committed.
                session.note_id = note_uuid
                session.save()
                response_payload["note_id"] = note_uuid
                response_payload["note_created"] = True
                log.info(
                    f"[vitals-dashboard] Vitals note {note_uuid} created for "
                    f"session {session.dbid}; observations deferred to flush"
                )
            except _FinishError as exc:
                log.warning(f"[vitals-dashboard] Could not finish session {session.dbid}: {exc}")
                response_payload["note_error"] = str(exc)
                return [JSONResponse(response_payload, status_code=HTTPStatus.UNPROCESSABLE_ENTITY)]

        return [JSONResponse(response_payload, status_code=HTTPStatus.CREATED), *effects]

    @api.post("/sync_observations")
    def sync_observations(self) -> list[Response | Effect]:
        """Emit FHIR Observations for a finished VitalsSession once the note is committed.

        Called by the dashboard with a small delay after a successful Finish
        Session. At that point the NoteEffect from `/sessions?finish=true` has
        been processed by Canvas and `Note.objects.get(id=note_uuid).dbid` is
        resolvable. Observation effects emitted from a SimpleAPI handler *do*
        persist (unlike effects returned from a BaseHandler responding to
        NOTE_STATE_CHANGE_EVENT_CREATED, which Canvas silently drops).

        Idempotent: `observations_synced` flag prevents re-emit.
        Retry-aware: returns 503 with `retry: true` if the note's dbid isn't
        yet resolvable, so the client can back off and call again.
        """
        data = self.request.json()
        session_id_raw = str(data.get("session_id") or "").strip()
        if not session_id_raw.isdigit():
            return [JSONResponse(
                {"error": "session_id (integer) required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        session = VitalsSession.objects.filter(dbid=int(session_id_raw)).first()
        if not session:
            return [JSONResponse(
                {"error": "session not found"},
                status_code=HTTPStatus.NOT_FOUND,
            )]

        if session.observations_synced:
            return [JSONResponse(
                {"session_id": session_id_raw, "synced": True, "observation_count": 0}
            )]

        if not session.note_id:
            return [JSONResponse(
                {"error": "session has no note_id; finish the session first"},
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            )]

        try:
            note = Note.objects.get(id=session.note_id)
        except Note.DoesNotExist:
            return [JSONResponse(
                {"error": "note not yet committed", "retry": True},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )]

        note_dbid = getattr(note, "dbid", None)
        if note_dbid is None:
            return [JSONResponse(
                {"error": "note has no dbid yet", "retry": True},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )]

        measurements = list(
            VitalsMeasurement.objects
            .filter(session_id=str(session.dbid), is_deleted=False)
            .order_by("recorded_at")
        )
        if not measurements:
            session.observations_synced = True
            session.save()
            return [JSONResponse(
                {"session_id": session_id_raw, "synced": True, "observation_count": 0}
            )]

        obs_effects = build_vital_observations(
            patient_key=session.patient_key,
            note_dbid=note_dbid,
            session_dt=session.session_datetime,
            measurements=measurements,
        )
        session.observations_synced = True
        session.save()

        log.info(
            f"[vitals-dashboard] sync: emitted {len(obs_effects)} observations "
            f"for session {session.dbid} -> note {session.note_id} (dbid={note_dbid})"
        )
        return [
            JSONResponse(
                {"session_id": session_id_raw, "synced": True,
                 "observation_count": len(obs_effects)},
                status_code=HTTPStatus.CREATED,
            ),
            *obs_effects,
        ]

    def _build_finish_effects(self, session, measurements, entered_by, display_dt_str=""):
        note_type = NoteType.objects.filter(name__iexact="Vitals").first()
        if not note_type:
            note_type = NoteType.objects.filter(name__icontains="vitals").first()
        if not note_type:
            raise _FinishError("No 'Vitals' NoteType found on this instance.")

        provider_id = entered_by
        if not Staff.objects.filter(id=provider_id).exists():
            fallback_staff = Staff.objects.first()
            if not fallback_staff:
                raise _FinishError("No Staff records available to assign as provider.")
            provider_id = str(fallback_staff.id)

        practice_location = PracticeLocation.objects.first()
        if not practice_location:
            raise _FinishError("No PracticeLocation records available on this instance.")

        note_uuid = str(uuid.uuid4())

        title_dt = display_dt_str or (
            session.session_datetime.strftime("%Y-%m-%d") if session.session_datetime else ""
        )
        note_title = f"Vitals - {title_dt}".strip().rstrip(" -")

        note_effect = NoteEffect(
            instance_id=note_uuid,
            note_type_id=str(note_type.id),
            patient_id=session.patient_key,
            provider_id=str(provider_id),
            practice_location_id=str(practice_location.id),
            datetime_of_service=session.session_datetime or datetime.now(timezone.utc),
            title=note_title,
        ).create()

        summary_html = _render_summary_html(session, measurements, title_dt)
        command = VitalsSummaryCommand(
            note_uuid=note_uuid,
            content=summary_html,
            print_content=summary_html,
        )
        command_effect = command.originate()

        return note_effect, command_effect, note_uuid

    @api.get("/report_context")
    def get_report_context(self) -> list[Response | Effect]:
        """Return patient demographics + practice info for the Print Report header."""
        patient_key = (self.request.query_params.get("patient_key") or "").strip()
        if not patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        patient = (
            Patient.objects
            .filter(id=patient_key)
            .prefetch_related("telecom", "addresses")
            .first()
        )
        if not patient:
            return [JSONResponse({"error": "patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        patient_phone = ""
        try:
            for cp in patient.telecom.all()[:10]:
                if getattr(cp, "system", "") and "phone" in cp.system.lower() and cp.value:
                    patient_phone = cp.value
                    break
        except Exception:
            pass

        patient_address_lines = []
        try:
            addr = patient.addresses.first()
            if addr:
                line = (addr.line1 or "").strip()
                if getattr(addr, "line2", ""):
                    line = f"{line} {addr.line2}".strip()
                if line:
                    patient_address_lines.append(line)
                csz = ", ".join([p for p in [getattr(addr, "city", ""), getattr(addr, "state_code", ""), getattr(addr, "postal_code", "")] if p])
                if csz:
                    patient_address_lines.append(csz)
        except Exception:
            pass

        age = None
        if patient.birth_date:
            from datetime import date as _date
            today = _date.today()
            age = today.year - patient.birth_date.year - (
                (today.month, today.day) < (patient.birth_date.month, patient.birth_date.day)
            )

        location = (
            PracticeLocation.objects
            .prefetch_related("telecom", "addresses")
            .first()
        )
        practice_name = ""
        practice_logo = ""
        practice_phone = ""
        practice_address_lines = []
        if location:
            practice_name = getattr(location, "full_name", "") or ""
            practice_logo = getattr(location, "background_image_url", "") or ""
            try:
                ptel = location.telecom.first()
                if ptel:
                    practice_phone = ptel.value or ""
            except Exception:
                pass
            try:
                paddr = location.addresses.first()
                if paddr:
                    line = (paddr.line1 or "").strip()
                    if getattr(paddr, "line2", ""):
                        line = f"{line} {paddr.line2}".strip()
                    if line:
                        practice_address_lines.append(line)
                    csz = ", ".join([p for p in [getattr(paddr, "city", ""), getattr(paddr, "state_code", ""), getattr(paddr, "postal_code", "")] if p])
                    if csz:
                        practice_address_lines.append(csz)
            except Exception:
                pass

        return [JSONResponse({
            "patient": {
                "full_name": f"{patient.first_name or ''} {patient.last_name or ''}".strip(),
                "mrn": patient.mrn or "",
                "birth_date": patient.birth_date.isoformat() if patient.birth_date else "",
                "age": age,
                "sex": patient.sex_at_birth or "",
                "phone": patient_phone,
                "address_lines": patient_address_lines,
            },
            "practice": {
                "name": practice_name,
                "logo_url": practice_logo,
                "phone": practice_phone,
                "address_lines": practice_address_lines,
            },
        }, status_code=HTTPStatus.OK)]

    @api.get("/sessions/draft")
    def get_draft(self) -> list[Response | Effect]:
        """Return the most recent unfinished (no note created) session for a patient.

        Used to auto-restore form values when a user navigates back to the Vitals tab
        without having clicked Finish Session.
        """
        patient_key = (self.request.query_params.get("patient_key") or "").strip()
        if not patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        session = (
            VitalsSession.objects
            .filter(patient_key=patient_key, note_id="")
            .order_by("-updated_at")
            .first()
        )
        if session is None:
            return [JSONResponse({"draft": None}, status_code=HTTPStatus.OK)]

        measurements = VitalsMeasurement.objects.filter(
            session_id=str(session.dbid),
            is_deleted=False,
        ).order_by("recorded_at")

        return [JSONResponse({
            "draft": {
                "session_id": str(session.dbid),
                "session_datetime": session.session_datetime.isoformat() if session.session_datetime else None,
                "measurements": [
                    {
                        "vital_type": m.vital_type,
                        "position": m.position,
                        "cuff_location": getattr(m, "cuff_location", "") or "",
                        "value_numeric": str(m.value_numeric) if m.value_numeric is not None else None,
                        "value_text": m.value_text,
                        "recorded_at": m.recorded_at.isoformat() if m.recorded_at else None,
                    }
                    for m in measurements
                ],
            }
        }, status_code=HTTPStatus.OK)]

    @api.get("/measurements")
    def list_measurements(self) -> list[Response | Effect]:
        """List measurements for a patient within a time window.

        Query params:
          patient_key (required)
          since: 24h | 7d (default) | 30d | 90d | all
        """
        patient_key = (self.request.query_params.get("patient_key") or "").strip()
        if not patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        since_dt = _parse_since(self.request.query_params.get("since") or "7d")

        qs = VitalsMeasurement.objects.filter(patient_key=patient_key)
        if since_dt is not None:
            qs = qs.filter(recorded_at__gte=since_dt)
        measurements = list(qs.order_by("-recorded_at")[:2000])

        session_ids = list({m.session_id for m in measurements if m.session_id})
        sessions = {
            str(s.dbid): s
            for s in VitalsSession.objects.filter(dbid__in=[int(sid) for sid in session_ids if sid.isdigit()])
        }

        staff_ids: set = set()
        for m in measurements:
            if m.entered_by_staff_key:
                staff_ids.add(m.entered_by_staff_key)
        for s in sessions.values():
            if s.provider_of_record_key:
                staff_ids.add(s.provider_of_record_key)

        staff_names = {}
        if staff_ids:
            for s in Staff.objects.filter(id__in=list(staff_ids)):
                first = getattr(s, "first_name", "") or ""
                last = getattr(s, "last_name", "") or ""
                full = f"{first} {last}".strip()
                staff_names[str(s.id)] = full or str(s.id)

        rows = []
        for m in measurements:
            session = sessions.get(m.session_id)
            provider_id = session.provider_of_record_key if session else ""
            rows.append({
                "id": str(m.dbid),
                "session_id": m.session_id,
                "recorded_at": m.recorded_at.isoformat() if m.recorded_at else None,
                "vital_type": m.vital_type,
                "position": m.position,
                "cuff_location": getattr(m, "cuff_location", "") or "",
                "value_numeric": str(m.value_numeric) if m.value_numeric is not None else None,
                "value_text": m.value_text,
                "unit": m.unit,
                "entered_by": {
                    "id": m.entered_by_staff_key,
                    "name": staff_names.get(m.entered_by_staff_key, ""),
                },
                "provider_of_record": {
                    "id": provider_id,
                    "name": staff_names.get(provider_id, "") if provider_id else "",
                },
                "note_id": session.note_id if session else "",
                "is_deleted": bool(m.is_deleted),
            })

        return [JSONResponse(rows, status_code=HTTPStatus.OK)]

    @api.get("/sessions/last")
    def get_last_finished_session(self) -> list[Response | Effect]:
        """Return the most recent FINISHED session (has note_id) + its measurements, for carry-forward."""
        patient_key = (self.request.query_params.get("patient_key") or "").strip()
        if not patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        session = (
            VitalsSession.objects
            .filter(patient_key=patient_key)
            .exclude(note_id="")
            .order_by("-session_datetime")
            .first()
        )
        if session is None:
            return [JSONResponse({"session": None}, status_code=HTTPStatus.OK)]

        measurements = VitalsMeasurement.objects.filter(
            session_id=str(session.dbid),
            is_deleted=False,
        ).order_by("recorded_at")

        return [JSONResponse({
            "session": {
                "session_id": str(session.dbid),
                "session_datetime": session.session_datetime.isoformat() if session.session_datetime else None,
                "measurements": [
                    {
                        "vital_type": m.vital_type,
                        "position": m.position,
                        "cuff_location": getattr(m, "cuff_location", "") or "",
                        "value_numeric": str(m.value_numeric) if m.value_numeric is not None else None,
                        "value_text": m.value_text,
                        "recorded_at": m.recorded_at.isoformat() if m.recorded_at else None,
                    }
                    for m in measurements
                ],
            }
        }, status_code=HTTPStatus.OK)]

    @api.patch("/measurements/<measurement_id>")
    def update_measurement(self) -> list[Response | Effect]:
        """Update a single measurement's value_numeric, value_text, and/or recorded_at."""
        mid_raw = self.request.path_params.get("measurement_id", "").strip()
        if not mid_raw or not mid_raw.isdigit():
            return [JSONResponse({"error": "invalid measurement id"}, status_code=HTTPStatus.BAD_REQUEST)]

        requested_patient_key = (self.request.query_params.get("patient_key") or "").strip()
        if not requested_patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        m = VitalsMeasurement.objects.filter(dbid=int(mid_raw), is_deleted=False).first()
        if not m:
            return [JSONResponse({"error": "measurement not found"}, status_code=HTTPStatus.NOT_FOUND)]
        if m.patient_key != requested_patient_key:
            return [JSONResponse({"error": "measurement not found"}, status_code=HTTPStatus.NOT_FOUND)]

        data = self.request.json() or {}

        if "value_numeric" in data:
            parsed = _parse_decimal(data.get("value_numeric"))
            m.value_numeric = parsed
        if "value_text" in data:
            m.value_text = (data.get("value_text") or "").strip()
        if "recorded_at" in data and data.get("recorded_at"):
            m.recorded_at = _parse_datetime(data.get("recorded_at"), default=m.recorded_at)
        m.save()

        log.info(f"[vitals-dashboard] Measurement {m.dbid} updated")
        return [JSONResponse({
            "id": str(m.dbid),
            "value_numeric": str(m.value_numeric) if m.value_numeric is not None else None,
            "value_text": m.value_text,
            "recorded_at": m.recorded_at.isoformat() if m.recorded_at else None,
        }, status_code=HTTPStatus.OK)]

    @api.delete("/measurements/<measurement_id>")
    def delete_measurement(self) -> list[Response | Effect]:
        """Soft-delete a measurement (sets is_deleted=True)."""
        mid_raw = self.request.path_params.get("measurement_id", "").strip()
        if not mid_raw or not mid_raw.isdigit():
            return [JSONResponse({"error": "invalid measurement id"}, status_code=HTTPStatus.BAD_REQUEST)]

        requested_patient_key = (self.request.query_params.get("patient_key") or "").strip()
        if not requested_patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        m = VitalsMeasurement.objects.filter(dbid=int(mid_raw), is_deleted=False).first()
        if not m:
            return [JSONResponse({"error": "measurement not found"}, status_code=HTTPStatus.NOT_FOUND)]
        if m.patient_key != requested_patient_key:
            return [JSONResponse({"error": "measurement not found"}, status_code=HTTPStatus.NOT_FOUND)]

        m.is_deleted = True
        m.save()
        log.info(f"[vitals-dashboard] Measurement {m.dbid} soft-deleted")
        return [JSONResponse({"id": str(m.dbid), "deleted": True}, status_code=HTTPStatus.OK)]

    @api.get("/sessions")
    def list_sessions(self) -> list[Response | Effect]:
        """List sessions for a patient (most recent first)."""
        patient_key = (self.request.query_params.get("patient_key") or "").strip()
        if not patient_key:
            return [JSONResponse({"error": "patient_key required"}, status_code=HTTPStatus.BAD_REQUEST)]

        sessions = VitalsSession.objects.filter(patient_key=patient_key).order_by("-session_datetime")[:200]
        return [JSONResponse(
            [
                {
                    "id": str(s.dbid),
                    "session_datetime": s.session_datetime.isoformat() if s.session_datetime else None,
                    "note_id": s.note_id or "",
                    "entered_by_staff_key": s.entered_by_staff_key,
                    "provider_of_record_key": s.provider_of_record_key or "",
                    "note_stale": s.note_stale,
                }
                for s in sessions
            ],
            status_code=HTTPStatus.OK,
        )]


class _FinishError(Exception):
    pass
