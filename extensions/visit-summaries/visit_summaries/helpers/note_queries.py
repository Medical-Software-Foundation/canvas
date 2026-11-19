"""Data query helpers for visit-summaries plugin."""
from __future__ import annotations

from typing import Any

import arrow

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.lab import LabReport
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.note import Note, NoteStates
from canvas_sdk.v1.data.task import Task, TaskStatus


LOCKED_STATES = {
    NoteStates.LOCKED,
    NoteStates.RELOCKED,
    NoteStates.SIGNED,
    NoteStates.DISCHARGED,
}

# Canvas stores datetime_of_service as a timezone-aware datetime in most
# configurations. When it arrives as a naive datetime (no tzinfo), we assume
# US Eastern. This fallback prevents dates from shifting forward by one day
# for US-timezone users.
_FALLBACK_TZ = "America/New_York"


def format_service_date(dt: Any, fmt: str = "MMMM D, YYYY") -> str:
    """Format a datetime_of_service value with timezone safety."""
    if dt is None:
        return ""
    a = arrow.get(dt)
    if a.tzinfo is None or a.tzinfo.tzname(None) in (None, "UTC", "utc"):
        a = a.to(_FALLBACK_TZ)
    return a.format(fmt)


def get_most_recent_locked_note(patient_id: str, exclude_note_id: str | None = None) -> Note | None:
    """Return the most recent locked note for a patient that occurred before the current note.

    If exclude_note_id is provided, the current note's service date is used as an upper bound
    so only notes chronologically before it are considered. If the current note has no service
    date or exclude_note_id is not provided, no upper bound is applied.
    """
    qs = (
        Note.objects.filter(
            patient__id=patient_id,
            current_state__state__in=LOCKED_STATES,
        )
        .select_related("patient")
        .order_by("-datetime_of_service")
    )
    if exclude_note_id:
        qs = qs.exclude(dbid=exclude_note_id)
        current_note = Note.objects.filter(dbid=exclude_note_id).only("datetime_of_service").first()
        if current_note and current_note.datetime_of_service:
            qs = qs.filter(datetime_of_service__lt=current_note.datetime_of_service)
    return qs.first()


def get_commands_for_note(note: Note, schema_keys: list[str] | None = None) -> list[Any]:
    """Return commands for a note, optionally filtered by schema_key list.

    Some Canvas instances leave committer as None even on locked notes, so we
    return all commands rather than filtering on committer__isnull=False.
    """
    qs = note.commands.all()
    if schema_keys:
        qs = qs.filter(schema_key__in=schema_keys)
    return list(qs)


def get_lab_reports_in_range(patient_id: str, start_date: Any, end_date: Any) -> list[Any]:
    """Return lab reports for a patient within a date range."""
    # Convert arrow.Arrow objects to ISO strings for Django ORM compatibility
    if hasattr(start_date, "format"):
        start_date = start_date.format("YYYY-MM-DD")
    if hasattr(end_date, "format"):
        end_date = end_date.format("YYYY-MM-DD")
    reports = (
        LabReport.objects.filter(
            patient__id=patient_id,
            date_performed__gte=start_date,
            date_performed__lte=end_date,
        )
        .prefetch_related("values")
        .order_by("date_performed")
    )
    return list(reports)


def extract_vitals_from_commands(commands: list[Any]) -> dict[str, str | None]:
    """
    Parse vitals data out of committed vitals commands.

    Returns a dict with keys: systolic, diastolic, heart_rate, spo2, weight, height, bmi,
    temperature. Values are strings or None.
    """
    vitals: dict[str, str | None] = {
        "systolic": None,
        "diastolic": None,
        "heart_rate": None,
        "spo2": None,
        "weight": None,
        "height": None,
        "bmi": None,
        "temperature": None,
    }
    for cmd in commands:
        if cmd.schema_key != "vitals":
            continue
        data = cmd.data or {}
        bp_sys = (
            data.get("blood_pressure_systole")
            or data.get("systolic_blood_pressure")
            or data.get("systolic")
        )
        if bp_sys:
            vitals["systolic"] = str(bp_sys)
        bp_dia = (
            data.get("blood_pressure_diastole")
            or data.get("diastolic_blood_pressure")
            or data.get("diastolic")
        )
        if bp_dia:
            vitals["diastolic"] = str(bp_dia)
        pulse = data.get("pulse") or data.get("heart_rate")
        if pulse:
            vitals["heart_rate"] = str(pulse)
        if data.get("oxygen_saturation"):
            vitals["spo2"] = str(data["oxygen_saturation"])
        if data.get("weight_lbs"):
            vitals["weight"] = str(data["weight_lbs"])
        ht = data.get("height") or data.get("height_inches") or data.get("height_cm")
        if ht:
            vitals["height"] = str(ht)
        if data.get("bmi"):
            vitals["bmi"] = str(data["bmi"])
        if data.get("body_temperature"):
            vitals["temperature"] = str(data["body_temperature"])
    return vitals


def extract_assess_plan_from_commands(commands: list[Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    Extract assess (diagnoses) and plan items from note commands.

    Returns (diagnoses, plan_items) where each plan_item is a dict with text and schema_key.
    """
    diagnoses: list[dict] = []
    plan_items: list[dict] = []
    for cmd in commands:
        if cmd.schema_key in ("assess", "diagnose"):
            data = cmd.data or {}
            # Format 1: {"icd10_codes": [{"code": "...", "display": "..."}]}
            icd_codes = data.get("icd10_codes", [])
            if isinstance(icd_codes, list) and icd_codes:
                for entry in icd_codes:
                    code = entry.get("code", "")
                    label = entry.get("display", "")
                    if code or label:
                        diagnoses.append({"code": code, "display": label, "tag": ""})
            # Format 2: {"diagnose": {"extra": {"coding": [{"code": "...", "display": "..."}]}}}
            elif isinstance(data.get("diagnose"), dict):
                dx = data["diagnose"]
                coding = (dx.get("extra") or {}).get("coding", [])
                if isinstance(coding, list) and coding:
                    for entry in coding:
                        system = str(entry.get("system", ""))
                        if "ICD" not in system.upper():
                            continue
                        code = str(entry.get("code", ""))
                        label = str(entry.get("display", ""))
                        if code or label:
                            diagnoses.append({"code": code, "display": label, "tag": ""})
                if not diagnoses and dx.get("text"):
                    diagnoses.append({"code": dx.get("value", ""), "display": str(dx["text"]), "tag": ""})
            elif data.get("condition"):
                cond = data["condition"]
                if isinstance(cond, dict):
                    display = (cond.get("text") or cond.get("display") or "").strip()
                    code = str(cond.get("value", ""))
                    if display:
                        diagnoses.append({"code": code, "display": display, "tag": ""})
                elif cond:
                    diagnoses.append({"code": "", "display": str(cond), "tag": ""})
        elif cmd.schema_key == "updateDiagnosis":
            data = cmd.data or {}
            new_cond = data.get("new_condition") or data.get("condition") or {}
            if isinstance(new_cond, dict):
                display = (new_cond.get("text") or "").strip()
                coding = (new_cond.get("extra") or {}).get("coding", [])
                code = ""
                for entry in coding if isinstance(coding, list) else []:
                    if isinstance(entry, dict) and "ICD" in str(entry.get("system", "")).upper():
                        code = str(entry.get("code", ""))
                        if not display:
                            display = str(entry.get("display", ""))
                        break
                if display:
                    diagnoses.append({"code": code, "display": display, "tag": "updated"})
        elif cmd.schema_key == "resolveCondition":
            data = cmd.data or {}
            cond = data.get("condition") or {}
            if isinstance(cond, dict):
                display = (cond.get("text") or "").strip()
                if display:
                    diagnoses.append({"code": "", "display": display, "tag": "resolved"})
        elif cmd.schema_key in ("plan", "instruct", "follow_up", "followUp"):
            data = cmd.data or {}
            narrative = data.get("narrative") or ""
            if not narrative and cmd.schema_key == "instruct":
                nested = data.get("instruct") or {}
                if isinstance(nested, dict):
                    narrative = nested.get("text") or nested.get("value") or ""
                if not narrative:
                    coding = data.get("coding") or {}
                    if isinstance(coding, dict):
                        narrative = coding.get("display") or ""
            if not narrative:
                narrative = data.get("comment") or ""
            if not narrative and cmd.schema_key == "followUp":
                narrative = data.get("reason_for_visit") or ""
                req_date = data.get("requested_date") or {}
                date_input = req_date.get("input") or req_date.get("date") or ""
                note_type = (data.get("note_type") or {}).get("text", "")
                if date_input:
                    narrative = f"Follow up in {date_input}"
                    if note_type:
                        narrative += f" ({note_type})"
            if narrative:
                plan_items.append({"text": str(narrative), "schema_key": cmd.schema_key})
    return diagnoses, plan_items


def extract_chief_complaint(commands: list[Any]) -> str:
    """Extract chief complaint from reason-for-visit commands, falling back to HPI."""
    for cmd in commands:
        if cmd.schema_key in ("reasonForVisit", "reason_for_visit", "rfv", "chief_complaint"):
            data = cmd.data or {}
            comment = data.get("comment") or data.get("narrative") or data.get("text") or ""
            if comment:
                return str(comment)
    for cmd in commands:
        if cmd.schema_key in ("hpi", "history_of_present_illness"):
            data = cmd.data or {}
            comment = data.get("narrative") or data.get("comment") or data.get("text") or ""
            if comment:
                return str(comment)
    return ""


def extract_medications_from_commands(commands: list[Any]) -> list[dict[str, str]]:
    """Extract medication entries from prescribe/medication_statement commands."""
    meds: list[dict] = []
    for cmd in commands:
        if cmd.schema_key in (
            "prescribe", "medicationStatement", "medication_statement",
            "stopMedication", "refill",
        ):
            data = cmd.data or {}
            med_field = data.get("prescribe") or data.get("medication") or {}
            if isinstance(med_field, dict):
                name = med_field.get("text") or med_field.get("value") or ""
            else:
                name = str(med_field) if med_field else ""
            sig = data.get("sig") or ""
            dose = data.get("quantity_to_dispense") or ""
            status = data.get("status") or ""
            if not status and cmd.schema_key == "stopMedication":
                status = "stopped"
            elif not status and cmd.schema_key == "refill":
                status = "refill"
            if name:
                meds.append(
                    {
                        "name": str(name),
                        "sig": str(sig),
                        "dose": str(dose),
                        "status": str(status),
                        "schema_key": cmd.schema_key,
                    }
                )
    return meds


def extract_questionnaires_from_commands(commands: list[Any]) -> list[dict[str, str]]:
    """Extract questionnaire responses from committed questionnaire commands."""
    results: list[dict[str, str]] = []
    for cmd in commands:
        if cmd.schema_key != "questionnaire":
            continue
        data = cmd.data or {}
        q_meta = data.get("questionnaire") or {}
        name = q_meta.get("text") or q_meta.get("extra", {}).get("name", "")
        if not name:
            continue

        questions = (q_meta.get("extra") or {}).get("questions", [])
        answers: list[str] = []
        for q in questions:
            q_name = q.get("name", "")
            q_label = q.get("label", "")
            raw_answer = data.get(q_name)
            if raw_answer is None:
                continue
            options = q.get("options", [])
            answer_text = str(raw_answer)
            for opt in options:
                if str(opt.get("value", "")) == str(raw_answer):
                    answer_text = opt.get("label", answer_text)
                    break
            if q_label:
                answers.append(f"{q_label}: {answer_text}")
            else:
                answers.append(answer_text)

        if answers:
            results.append({"name": str(name), "answers": ", ".join(answers)})
    return results


def extract_orders_from_commands(commands: list[Any]) -> list[dict[str, str]]:
    """Extract referrals, lab orders, and imaging orders from note commands."""
    orders: list[dict[str, str]] = []
    for cmd in commands:
        if cmd.schema_key == "refer":
            data = cmd.data or {}
            refer_to = data.get("refer_to") or {}
            name = refer_to.get("text", "") if isinstance(refer_to, dict) else ""
            name = name.strip()
            priority = data.get("priority") or ""
            notes = data.get("notes_to_specialist") or data.get("clinical_question") or ""
            if name:
                orders.append({
                    "type": "Referral",
                    "description": name,
                    "priority": priority,
                    "notes": str(notes),
                })
        elif cmd.schema_key == "labOrder":
            data = cmd.data or {}
            tests = data.get("tests") or []
            comment = data.get("comment") or ""
            fasting = data.get("fasting_status")
            test_names = []
            for t in tests:
                if isinstance(t, dict):
                    text = (t.get("text") or "").strip()
                    if text:
                        test_names.append(text)
                elif t:
                    test_names.append(str(t))
            if test_names:
                desc = ", ".join(test_names)
                if fasting:
                    desc += " (fasting required)"
                orders.append({
                    "type": "Lab order",
                    "description": desc,
                    "priority": "",
                    "notes": str(comment),
                })
        elif cmd.schema_key == "imagingOrder":
            data = cmd.data or {}
            image = data.get("image") or {}
            name = image.get("text", "") if isinstance(image, dict) else ""
            name = name.strip()
            priority = data.get("priority") or ""
            details = data.get("additional_details") or data.get("comment") or ""
            if name:
                orders.append({
                    "type": "Imaging order",
                    "description": name,
                    "priority": priority,
                    "notes": str(details),
                })
    return orders


def extract_allergies_from_commands(commands: list[Any]) -> list[dict[str, str]]:
    """Extract allergy entries from allergy commands."""
    allergies: list[dict[str, str]] = []
    for cmd in commands:
        if cmd.schema_key != "allergy":
            continue
        data = cmd.data or {}
        allergy_field = data.get("allergy") or {}
        if isinstance(allergy_field, dict):
            name = allergy_field.get("text", "")
        else:
            name = str(allergy_field) if allergy_field else ""
        name = name.strip()
        if not name:
            continue
        severity = data.get("severity") or ""
        narrative = data.get("narrative") or ""
        allergies.append({
            "name": name,
            "severity": str(severity),
            "narrative": str(narrative),
        })
    return allergies


def extract_immunizations_from_commands(commands: list[Any]) -> list[dict[str, str]]:
    """Extract immunization entries from immunize and immunizationStatement commands."""
    immunizations: list[dict[str, str]] = []
    for cmd in commands:
        if cmd.schema_key == "immunize":
            data = cmd.data or {}
            coding = data.get("coding") or {}
            name = coding.get("text", "") if isinstance(coding, dict) else ""
            name = name.strip()
            if name:
                immunizations.append({"name": name, "date": ""})
        elif cmd.schema_key == "immunizationStatement":
            data = cmd.data or {}
            statement = data.get("statement") or {}
            name = statement.get("text", "") if isinstance(statement, dict) else ""
            name = name.strip()
            date_field = data.get("date") or {}
            date_str = ""
            if isinstance(date_field, dict):
                date_str = date_field.get("input") or date_field.get("date") or ""
            if name:
                immunizations.append({"name": name, "date": str(date_str)})
    return immunizations


def build_note_context_for_llm(note: Note) -> str:
    """
    Build a structured text context from a note's committed commands for LLM consumption.
    """
    commands = get_commands_for_note(note)
    lines: list[str] = []

    service_date = format_service_date(note.datetime_of_service)
    lines.append(f"Note date: {service_date}")

    chief_complaint = extract_chief_complaint(commands)
    if chief_complaint:
        lines.append(f"\nChief Complaint: {chief_complaint}")

    vitals = extract_vitals_from_commands(commands)
    has_vitals = any(v is not None for v in vitals.values())
    if has_vitals:
        lines.append("\nVitals:")
        if vitals["systolic"] and vitals["diastolic"]:
            lines.append(f"  Blood Pressure: {vitals['systolic']}/{vitals['diastolic']} mmHg")
        if vitals["heart_rate"]:
            lines.append(f"  Heart Rate: {vitals['heart_rate']} bpm")
        if vitals["spo2"]:
            lines.append(f"  SpO2: {vitals['spo2']}%")
        if vitals["height"]:
            lines.append(f"  Height: {vitals['height']} in")
        if vitals["weight"]:
            lines.append(f"  Weight: {vitals['weight']} lbs")
        if vitals["bmi"]:
            lines.append(f"  BMI: {vitals['bmi']}")
        if vitals["temperature"]:
            lines.append(f"  Temperature: {vitals['temperature']} F")

    diagnoses, plan_items = extract_assess_plan_from_commands(commands)

    # Fallback: if no diagnoses found in commands, query the Condition model for
    # conditions linked to this note. The SDK Condition model does not expose note_id
    # as a field, so we use .extra(where=...) to access it in the underlying table.
    if not diagnoses:
        note_conditions = (
            Condition.objects.filter(
                patient=note.patient,
                deleted=False,
            )
            .extra(
                where=["canvas_sdk_data_api_condition_001.note_id = %s"],
                params=[note.dbid],
            )
            .prefetch_related("codings")
        )
        for cond in note_conditions:
            coding = cond.codings.first()
            if coding:
                code = getattr(coding, "code", "")
                display = getattr(coding, "display", "")
                if code or display:
                    diagnoses.append({"code": str(code), "display": str(display), "tag": ""})

    if diagnoses:
        lines.append("\nDiagnoses:")
        for dx in diagnoses:
            code_str = f" ({dx['code']})" if dx.get("code") else ""
            tag_str = f" [{dx['tag'].upper()}]" if dx.get("tag") else ""
            lines.append(f"  - {dx['display']}{code_str}{tag_str}")

    if plan_items:
        lines.append("\nPlan:")
        for item in plan_items:
            text = item.get("text", "") or str(item)
            lines.append(f"  - {text}")

    meds = extract_medications_from_commands(commands)
    if meds:
        lines.append("\nMedications:")
        for med in meds:
            dose_str = f" {med['dose']}" if med["dose"] else ""
            sig_str = f" - {med['sig']}" if med["sig"] else ""
            status_str = f" [{med['status'].upper()}]" if med.get("status") else ""
            lines.append(f"  - {med['name']}{dose_str}{sig_str}{status_str}")

    orders = extract_orders_from_commands(commands)
    if orders:
        lines.append("\nOrders & Referrals:")
        for order in orders:
            priority_str = f" [{order['priority']}]" if order["priority"] else ""
            notes_str = f" - {order['notes']}" if order["notes"] else ""
            lines.append(f"  - {order['type']}: {order['description']}{priority_str}{notes_str}")

    allergies = extract_allergies_from_commands(commands)
    if allergies:
        lines.append("\nAllergies:")
        for allergy in allergies:
            severity_str = f" ({allergy['severity']})" if allergy["severity"] else ""
            lines.append(f"  - {allergy['name']}{severity_str}")

    immunizations = extract_immunizations_from_commands(commands)
    if immunizations:
        lines.append("\nImmunizations:")
        for imm in immunizations:
            date_str = f" (given {imm['date']})" if imm["date"] else ""
            lines.append(f"  - {imm['name']}{date_str}")

    questionnaires = extract_questionnaires_from_commands(commands)
    if questionnaires:
        lines.append("\nQuestionnaires:")
        for q in questionnaires:
            lines.append(f"  - {q['name']}: {q['answers']}")

    return "\n".join(lines)


def _format_medication_changes(patient_id: str, since_date: Any, until_date: Any) -> list[str]:
    """Return lines describing medication changes in the date range."""
    lines: list[str] = []
    new_meds = Medication.objects.filter(
        patient__id=patient_id,
        start_date__gte=since_date,
        start_date__lte=until_date,
    ).select_related("patient")

    stopped_meds = Medication.objects.filter(
        patient__id=patient_id,
        end_date__gte=since_date,
        end_date__lte=until_date,
    ).select_related("patient")

    new_list = list(new_meds)
    stopped_list = list(stopped_meds)

    if new_list or stopped_list:
        lines.append("\nMedication Changes:")
        for med in new_list:
            name = getattr(med, "clinical_quantity_description", "") or str(med)
            date_str = ""
            if med.start_date:
                date_str = f" (started {arrow.get(med.start_date).format('MMM D, YYYY')})"
            lines.append(f"  - NEW: {name}{date_str}")
        for med in stopped_list:
            name = getattr(med, "clinical_quantity_description", "") or str(med)
            date_str = ""
            if med.end_date:
                date_str = f" (stopped {arrow.get(med.end_date).format('MMM D, YYYY')})"
            lines.append(f"  - STOPPED: {name}{date_str}")
    else:
        lines.append("\nMedication Changes: None in this period")
    return lines


def _format_new_conditions(
    patient_id: str,
    since_date: Any,
    until_date: Any,
    since_datetime: Any = None,
    until_datetime: Any = None,
) -> list[str]:
    """Return lines describing new or resolved conditions in the date range."""
    since_dt = since_datetime or since_date
    until_dt = until_datetime or until_date
    lines: list[str] = []
    new_conditions = Condition.objects.filter(
        patient__id=patient_id,
    ).extra(
        where=[
            "((onset_date >= %s AND onset_date <= %s) OR (onset_date IS NULL AND canvas_sdk_data_api_condition_001.created >= %s AND canvas_sdk_data_api_condition_001.created <= %s))"
        ],
        params=[since_date, until_date, since_dt, until_dt],
    ).prefetch_related("codings")

    resolved_conditions = Condition.objects.filter(
        patient__id=patient_id,
        resolution_date__gte=since_date,
        resolution_date__lte=until_date,
    ).prefetch_related("codings")

    new_list = list(new_conditions)
    resolved_list = list(resolved_conditions)

    if new_list or resolved_list:
        lines.append("\nDiagnosis Changes:")
        for cond in new_list:
            coding = cond.codings.first()
            display = getattr(coding, "display", "") if coding else ""
            code = getattr(coding, "code", "") if coding else ""
            code_str = f" ({code})" if code else ""
            label = display or "Unknown condition"
            lines.append(f"  - NEW: {label}{code_str}")
        for cond in resolved_list:
            coding = cond.codings.first()
            display = getattr(coding, "display", "") if coding else ""
            label = display or "Unknown condition"
            lines.append(f"  - RESOLVED: {label}")
    else:
        lines.append("\nDiagnosis Changes: None in this period")
    return lines


def _format_completed_tasks(patient_id: str, since_date: Any, until_date: Any) -> list[str]:
    """Return lines describing tasks completed in the date range."""
    lines: list[str] = []
    completed_tasks = Task.objects.filter(
        patient__id=patient_id,
        status=TaskStatus.COMPLETED,
        modified__gte=since_date,
        modified__lte=until_date,
    )
    task_list = list(completed_tasks)

    if task_list:
        lines.append("\nCompleted Care Tasks:")
        for task in task_list:
            title = getattr(task, "title", "") or "Untitled task"
            lines.append(f"  - {title}")
    else:
        lines.append("\nCompleted Care Tasks: None in this period")
    return lines


def _format_other_encounters(patient_id: str, since_date: Any, until_date: Any) -> list[str]:
    """Return lines describing other appointments/encounters in the date range."""
    lines: list[str] = []
    appointments = Appointment.objects.filter(
        patient__id=patient_id,
        start_time__gte=since_date,
        start_time__lte=until_date,
    ).select_related("provider")
    appt_list = list(appointments)

    if appt_list:
        lines.append("\nOther Encounters:")
        for appt in appt_list:
            appt_date = ""
            if appt.start_time:
                appt_date = arrow.get(appt.start_time).format("MMM D, YYYY")
            status = getattr(appt, "status", "") or ""
            description = getattr(appt, "description", "") or "Appointment"
            provider_name = ""
            if appt.provider:
                first = getattr(appt.provider, "first_name", "") or ""
                last = getattr(appt.provider, "last_name", "") or ""
                provider_name = f" with {first} {last}".strip()
            lines.append(f"  - {description}{provider_name} on {appt_date} [{status}]")
    else:
        lines.append("\nOther Encounters: None in this period")
    return lines


def has_interim_activity(patient_id: str, since_date: Any, until_date: Any) -> bool:
    """Check whether any interim clinical activity exists in the date window.

    Runs .exists() on each activity type, short circuiting on the first True.
    Ordered by most common activity type first to minimize queries.
    """
    since_arrow = arrow.get(since_date)
    until_arrow = arrow.get(until_date)
    since_iso = since_arrow.format("YYYY-MM-DD")
    until_iso = until_arrow.format("YYYY-MM-DD")
    since_dt_iso = since_arrow.format("YYYY-MM-DDTHH:mm:ssZ")
    until_dt_iso = until_arrow.format("YYYY-MM-DDTHH:mm:ssZ")

    if LabReport.objects.filter(
        patient__id=patient_id,
        date_performed__gte=since_iso,
        date_performed__lte=until_iso,
    ).exists():
        return True

    if Medication.objects.filter(
        patient__id=patient_id,
        start_date__gte=since_iso,
        start_date__lte=until_iso,
    ).exists():
        return True

    if Medication.objects.filter(
        patient__id=patient_id,
        end_date__gte=since_iso,
        end_date__lte=until_iso,
    ).exists():
        return True

    if Condition.objects.filter(
        patient__id=patient_id,
    ).extra(
        where=[
            "((onset_date >= %s AND onset_date <= %s) OR (onset_date IS NULL AND canvas_sdk_data_api_condition_001.created >= %s AND canvas_sdk_data_api_condition_001.created <= %s))"
        ],
        params=[since_iso, until_iso, since_dt_iso, until_dt_iso],
    ).exists():
        return True

    if Task.objects.filter(
        patient__id=patient_id,
        status=TaskStatus.COMPLETED,
        modified__gte=since_dt_iso,
        modified__lte=until_dt_iso,
    ).exists():
        return True

    if Appointment.objects.filter(
        patient__id=patient_id,
        start_time__gte=since_dt_iso,
        start_time__lte=until_dt_iso,
    ).exists():
        return True

    return False


def build_interim_context_for_llm(
    patient_id: str,
    since_date: Any,
    until_date: Any,
) -> str:
    """
    Build structured text of interim clinical activity between two dates for LLM consumption.

    Includes: lab results, medication changes, new/resolved conditions,
    completed tasks, and other encounters.
    """
    lines: list[str] = []

    since_arrow = arrow.get(since_date)
    until_arrow = arrow.get(until_date)
    since_str = since_arrow.format("MMMM D, YYYY")
    until_str = until_arrow.format("MMMM D, YYYY")
    days_between = (until_arrow - since_arrow).days
    lines.append(f"Period: {since_str} to {until_str} ({days_between} days)")

    # Convert to ISO date strings for Django ORM DateField compatibility
    since_iso = since_arrow.format("YYYY-MM-DD")
    until_iso = until_arrow.format("YYYY-MM-DD")
    # Convert to ISO datetime strings for Django ORM DateTimeField compatibility
    since_dt_iso = since_arrow.format("YYYY-MM-DDTHH:mm:ssZ")
    until_dt_iso = until_arrow.format("YYYY-MM-DDTHH:mm:ssZ")

    # Lab results
    lab_reports = get_lab_reports_in_range(patient_id, since_iso, until_iso)
    if lab_reports:
        lines.append("\nLab Results:")
        for report in lab_reports:
            report_date = ""
            if report.date_performed:
                report_date = arrow.get(report.date_performed).format("MMM D, YYYY")
            lines.append(f"  Report date: {report_date}")
            for value in report.values.all():
                name = getattr(value, "name", "") or ""
                val = getattr(value, "value", "") or ""
                units = getattr(value, "units", "") or ""
                ref_range = getattr(value, "reference_range", "") or ""
                flag = getattr(value, "abnormal_flag", "") or ""
                flag_str = f" [{flag}]" if flag else ""
                ref_str = f" (ref: {ref_range})" if ref_range else ""
                lines.append(f"    - {name}: {val} {units}{ref_str}{flag_str}")
    else:
        lines.append("\nLab Results: None in this period")

    # Medication changes (DateField → use ISO date strings)
    lines.extend(_format_medication_changes(patient_id, since_iso, until_iso))

    # New/resolved conditions (onset_date is DateField, created fallback is DateTimeField)
    lines.extend(_format_new_conditions(patient_id, since_iso, until_iso, since_dt_iso, until_dt_iso))

    # Completed tasks (DateTimeField → use ISO datetime strings)
    lines.extend(_format_completed_tasks(patient_id, since_dt_iso, until_dt_iso))

    # Other encounters (DateTimeField → use ISO datetime strings)
    lines.extend(_format_other_encounters(patient_id, since_dt_iso, until_dt_iso))

    return "\n".join(lines)
