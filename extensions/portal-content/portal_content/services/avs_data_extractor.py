"""Extract After Visit Summary data from Canvas note."""

from __future__ import annotations
from datetime import datetime
from typing import cast

import arrow

from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.lab import LabOrder
from canvas_sdk.v1.data.medication import Medication
from logger import log


# Vitals enum mappings - converts numeric values to human-readable descriptions
VITALS_ENUM_DICT = {
    "blood_pressure_position_and_site": {
        "0": "Sitting, Right Upper Extremity",
        "1": "Sitting, Left Upper Extremity",
        "2": "Sitting, Right Lower Extremity",
        "3": "Sitting, Left Lower Extremity",
        "4": "Standing, Right Upper Extremity",
        "5": "Standing, Left Upper Extremity",
        "6": "Standing, Right Lower Extremity",
        "7": "Standing, Left Lower Extremity",
        "8": "Supine, Right Upper Extremity",
        "9": "Supine, Left Upper Extremity",
        "10": "Supine, Right Lower Extremity",
        "11": "Supine, Left Lower Extremity",
    },
    "body_temperature_site": {
        "0": "Axillary",
        "1": "Oral",
        "2": "Rectal",
        "3": "Temporal",
        "4": "Tympanic",
    },
    "pulse_rhythm": {
        "0": "Regular",
        "1": "Irregularly Irregular",
        "2": "Regularly Irregular",
    },
}


def format_icd10_code(icd10_code: str) -> str:
    """Format ICD-10 code with proper dot placement (e.g., "E119" -> "E11.9")."""
    if not icd10_code:
        return ""
    icd10_code = icd10_code.strip().upper()
    if "." in icd10_code:
        return icd10_code
    if len(icd10_code) > 3:
        return icd10_code[:3] + "." + icd10_code[3:]
    return icd10_code


def format_diagnosis_entry(data: dict, prefix: str = "") -> str | None:
    """Format one diagnosis/condition entry, trying icd10 -> coding -> text/value/description."""
    display = None
    code = None

    icd10_data = data.get("icd10") or {}
    if isinstance(icd10_data, dict):
        display = icd10_data.get("display")
        code = icd10_data.get("code")

    if not display or not code:
        coding = data.get("coding")
        if isinstance(coding, list) and coding:
            first_coding = coding[0]
            if isinstance(first_coding, dict):
                display = display or first_coding.get("display")
                code = code or first_coding.get("code")

    if not display:
        display = data.get("text") or data.get("value", "") or data.get("description")

    if not display:
        return None

    label = f"{prefix} {display}".strip() if prefix else display
    if code:
        return f"{label} ({format_icd10_code(code)})"
    return label


def format_medication_data(data: dict, schema_key: str, status: str = "") -> dict | None:
    """Format medication command data, trying fdbMedId -> text -> extra.coding -> value -> medication/name/display."""
    if not data:
        return None

    med_data = data.get(schema_key) or {}

    if not med_data and schema_key in ("changeMedication", "stopMedication", "medicationStatement"):
        medication_field = data.get("medication")
        if isinstance(medication_field, dict):
            med_data = medication_field

    if not med_data:
        med_data = data

    med_name = None

    fdb_med_id = med_data.get("fdbMedId")
    if isinstance(fdb_med_id, dict):
        med_name = fdb_med_id.get("display") or fdb_med_id.get("name")

    if not med_name:
        text = med_data.get("text")
        if text and isinstance(text, str):
            med_name = text

    if not med_name:
        extra = med_data.get("extra")
        if isinstance(extra, dict):
            coding_list = extra.get("coding")
            if isinstance(coding_list, list) and coding_list:
                first_coding = coding_list[0]
                if isinstance(first_coding, dict):
                    med_name = first_coding.get("display")

    if not med_name:
        value = med_data.get("value")
        if value and isinstance(value, str) and not value.isdigit():
            med_name = value

    if not med_name:
        med_name = med_data.get("medication") or med_data.get("name") or med_data.get("display")

    if not med_name:
        return None

    sig = med_data.get("sig", "")
    quantity = med_data.get("quantityToDispense") or med_data.get("quantity_to_dispense", "")
    refills = med_data.get("refills", "")
    rationale = med_data.get("rationale", "")

    description_parts = []
    if sig:
        description_parts.append(sig)
    if quantity:
        description_parts.append(f"Qty: {quantity}")
    if refills:
        description_parts.append(f"Refills: {refills}")
    if rationale:
        description_parts.append(f"Reason: {rationale}")

    return {
        "name": med_name,
        "description": ", ".join(description_parts) if description_parts else None,
        "status": status,
    }


class AVSDataExtractor:
    """Extract all relevant data for After Visit Summary from a Canvas note."""

    def __init__(self, note_id: str):
        self.note_id = note_id
        self.note = Note.objects.select_related("patient", "provider").get(id=note_id)
        self.patient = self.note.patient

    # -------------------------------------------------------------------------
    # Command query helpers
    # -------------------------------------------------------------------------

    def fetch_latest_command_data_in_note_by_type(self, schema_key: str) -> dict | None:
        """Fetch the most recent committed command data of a given type from the note."""
        return cast(
            "dict | None",
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("-dbid")
            .values_list("data", flat=True)
            .first(),
        )

    def fetch_all_commands_data_in_note_by_type(self, schema_key: str) -> list[dict]:
        """Fetch all committed command data of a given type from the note."""
        return list(
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("dbid")
            .values_list("data", flat=True)
            .all()
        )

    # -------------------------------------------------------------------------
    # Main extraction method
    # -------------------------------------------------------------------------

    def extract(self) -> dict:
        """Extract all AVS data into a structured dictionary."""
        log.info(f"Extracting AVS data for note {self.note_id}")

        return {
            "patient_name": self._get_patient_name(),
            "patient_dob": self._get_patient_dob(),
            "reason_for_visit": self._get_reason_for_visit(),
            "appointment_date_time": self._get_appointment_datetime(),
            "appointment_provider": self._get_provider_name(),
            "generated_at": self._get_generated_timestamp(),
            "to_do_list": self._extract_todo_list(),
            "medications": self._extract_medications(),
            "vitals": self._extract_vitals(),
            "diagnoses": self._extract_diagnoses(),
            "immunizations": self._extract_immunizations(),
            "procedures": self._extract_procedures(),
            "upcoming_appointments": self._extract_upcoming_appointments(),
        }

    # -------------------------------------------------------------------------
    # Patient info
    # -------------------------------------------------------------------------

    def _get_patient_name(self) -> str:
        return f"{self.patient.first_name} {self.patient.last_name}"

    def _get_patient_dob(self) -> str:
        if self.patient.birth_date:
            return str(self.patient.birth_date.strftime("%m/%d/%Y"))
        return ""

    def _get_reason_for_visit(self) -> str:
        rfv_data = self.fetch_latest_command_data_in_note_by_type("reasonForVisit")

        if rfv_data:
            coding = rfv_data.get("coding")
            if coding:
                if isinstance(coding, dict):
                    text = coding.get("text") or coding.get("display")
                    if text:
                        return str(text)
                elif isinstance(coding, list) and coding:
                    first = coding[0]
                    if isinstance(first, dict):
                        text = first.get("display") or first.get("text")
                        if text:
                            return str(text)

            if rfv_data.get("comment"):
                return str(rfv_data.get("comment", ""))

            narrative_json = rfv_data.get("narrative_json") or rfv_data.get("narrativeJson")
            if narrative_json:
                if isinstance(narrative_json, str):
                    return narrative_json
                elif isinstance(narrative_json, dict) and narrative_json.get("value"):
                    return str(narrative_json.get("value"))

            codings = rfv_data.get("codings")
            if isinstance(codings, list) and codings:
                first_coding = codings[0]
                if isinstance(first_coding, dict):
                    display = first_coding.get("display")
                    if display:
                        return str(display)

        return "Follow-up visit"

    def _get_appointment_datetime(self) -> str:
        """Get formatted appointment date and time in patient's timezone."""
        appointment = (
            Appointment.objects.filter(note=self.note, entered_in_error__isnull=True)
            .order_by("-dbid")
            .only("start_time")
            .first()
        )

        if appointment and appointment.start_time:
            dt = appointment.start_time
        elif self.note.datetime_of_service:
            dt = self.note.datetime_of_service
        elif self.note.created:
            dt = self.note.created
        else:
            return ""

        timezone_str = self.patient.last_known_timezone or "America/New_York"
        return arrow.get(dt).to(timezone_str).format("MMMM D, YYYY [at] h:mm A ZZZ")

    def _get_generated_timestamp(self) -> str:
        timezone_str = self.patient.last_known_timezone or "America/New_York"
        return arrow.now(timezone_str).format("MMMM D, YYYY [at] h:mm A ZZZ")

    def _get_provider_name(self) -> str:
        if self.note.provider:
            return str(self.note.provider.full_name)
        return "Provider"

    # -------------------------------------------------------------------------
    # Vitals
    # -------------------------------------------------------------------------

    def _extract_vitals(self) -> dict:
        vitals = {}

        for vitals_data in self.fetch_all_commands_data_in_note_by_type("vitals"):
            # Apply enum mappings
            for key in VITALS_ENUM_DICT:
                if key in vitals_data:
                    vitals_data[key] = VITALS_ENUM_DICT[key].get(str(vitals_data[key]), "")

            systolic = vitals_data.get("blood_pressure_systole")
            diastolic = vitals_data.get("blood_pressure_diastole")
            if systolic and diastolic:
                bp_entry = {
                    "sign": "Blood Pressure",
                    "sign_unit": "mmHg",
                    "value": f"{systolic}/{diastolic}",
                }
                if vitals_data.get("blood_pressure_position_and_site"):
                    bp_entry["position"] = vitals_data["blood_pressure_position_and_site"]
                vitals["blood_pressure"] = bp_entry

            heart_rate = vitals_data.get("pulse")
            if heart_rate:
                hr_entry = {
                    "sign": "Heart Rate",
                    "sign_unit": "bpm",
                    "value": str(heart_rate),
                }
                if vitals_data.get("pulse_rhythm"):
                    hr_entry["rhythm"] = vitals_data["pulse_rhythm"]
                vitals["heart_rate"] = hr_entry

            resp_rate = vitals_data.get("respiration_rate")
            if resp_rate:
                vitals["respiratory_rate"] = {
                    "sign": "Respiratory Rate",
                    "sign_unit": "breaths/min",
                    "value": str(resp_rate),
                }

            temperature = vitals_data.get("body_temperature")
            if temperature:
                temp_entry = {
                    "sign": "Temperature",
                    "sign_unit": "\u00b0F",
                    "value": str(temperature),
                }
                if vitals_data.get("body_temperature_site"):
                    temp_entry["site"] = vitals_data["body_temperature_site"]
                vitals["temperature"] = temp_entry

            weight_lbs = vitals_data.get("weight_lbs")
            weight_oz = vitals_data.get("weight_oz", 0)
            if weight_lbs is not None:
                try:
                    total_weight = float(weight_lbs)
                    if weight_oz:
                        total_weight += float(weight_oz) / 16
                    vitals["weight"] = {
                        "sign": "Weight",
                        "sign_unit": "lbs",
                        "value": str(round(total_weight, 1)),
                    }
                except (ValueError, TypeError):
                    log.warning(f"Could not parse weight values: lbs={weight_lbs}, oz={weight_oz}")

            height = vitals_data.get("height")
            if height:
                vitals["height"] = {
                    "sign": "Height",
                    "sign_unit": "inches",
                    "value": str(height),
                }

            o2_sat = vitals_data.get("oxygen_saturation")
            if o2_sat:
                vitals["oxygen_saturation"] = {
                    "sign": "Oxygen Saturation",
                    "sign_unit": "%",
                    "value": str(o2_sat),
                }

        return vitals

    # -------------------------------------------------------------------------
    # Diagnoses
    # -------------------------------------------------------------------------

    def _extract_diagnoses(self) -> list[str]:
        diagnoses = []

        for data in self.fetch_all_commands_data_in_note_by_type("diagnose"):
            diagnose_data = data.get("diagnose") or data
            formatted = self._format_diagnosis_entry(diagnose_data, prefix="Diagnosed")
            if formatted:
                diagnoses.append(formatted)

        for data in self.fetch_all_commands_data_in_note_by_type("assess"):
            assess_data = data.get("assess") or data

            has_condition = (
                assess_data.get("icd10")
                or assess_data.get("conditions")
                or assess_data.get("condition")
            )
            if not has_condition:
                continue

            conditions = assess_data.get("conditions") or assess_data.get("condition")
            if conditions:
                if isinstance(conditions, list) and conditions:
                    for condition in conditions:
                        if not isinstance(condition, dict):
                            continue
                        formatted = self._format_diagnosis_entry(condition, prefix="Assessed")
                        if formatted:
                            diagnoses.append(formatted)
                    continue
                elif isinstance(conditions, dict):
                    assess_data = conditions

            formatted = self._format_diagnosis_entry(assess_data, prefix="Assessed")
            if formatted:
                diagnoses.append(formatted)

        log.info(f"Extracted {len(diagnoses)} diagnoses")
        return diagnoses

    def _format_diagnosis_entry(self, data: dict, prefix: str = "") -> str | None:
        return format_diagnosis_entry(data, prefix)

    # -------------------------------------------------------------------------
    # Medications
    # -------------------------------------------------------------------------

    def _extract_medications(self) -> dict:
        start_meds = []
        adjust_meds = []
        stop_meds = []
        keep_meds = []

        for data in self.fetch_all_commands_data_in_note_by_type("prescribe"):
            med_data = self._format_medication_data(data, "prescribe", status="start")
            if med_data:
                start_meds.append(med_data)

        for data in self.fetch_all_commands_data_in_note_by_type("refill"):
            med_data = self._format_medication_data(data, "refill", status="start")
            if med_data:
                start_meds.append(med_data)

        for data in self.fetch_all_commands_data_in_note_by_type("changeMedication"):
            med_data = self._format_medication_data(data, "changeMedication", status="adjust")
            if med_data:
                adjust_meds.append(med_data)

        for data in self.fetch_all_commands_data_in_note_by_type("adjustPrescription"):
            med_data = self._format_medication_data(data, "adjustPrescription", status="adjust")
            if med_data:
                adjust_meds.append(med_data)

        for data in self.fetch_all_commands_data_in_note_by_type("stopMedication"):
            med_data = self._format_medication_data(data, "stopMedication", status="stop")
            if med_data:
                stop_meds.append(med_data)

        # Get active meds but exclude any that already appear in start/adjust/stop
        # to avoid showing a medication in both "New" and "Keep Taking"
        # Normalize names: lowercase, strip whitespace, collapse spaces for fuzzy matching
        # since command data names ("Lisinopril 10mg") differ from Medication model
        # names ("LISINOPRIL 10 MG ORAL TABLET")
        def _token_set(name: str) -> frozenset:
            return frozenset(name.lower().split())

        changed_med_token_sets = set()
        for med in start_meds + adjust_meds + stop_meds:
            name = med.get("name")
            if isinstance(name, str) and name.strip():
                changed_med_token_sets.add(_token_set(name))

        def _is_changed_med(active_name: str) -> bool:
            """An active med is treated as a duplicate of a changed med only when their
            normalized token sets match exactly. Substring matching is intentionally
            avoided: it hid combination products (prescribing 'Tylenol' must not hide
            'Tylenol PM'). When names differ, the med is shown - the safe direction."""
            return _token_set(active_name) in changed_med_token_sets

        keep_meds = [
            med for med in self._get_active_medications()
            if not _is_changed_med(med["name"])
        ]

        return {
            "start": start_meds,
            "adjust": adjust_meds,
            "stop": stop_meds,
            "keep": keep_meds,
        }

    def _get_active_medications(self) -> list[dict]:
        """Get the patient's full active medication list from the Medication model."""
        active_meds = []
        medications = Medication.objects.filter(
            patient=self.patient,
            status="active",
            entered_in_error__isnull=True,
        ).prefetch_related("codings")

        for med in medications:
            coding = med.codings.first()
            med_name = coding.display if coding else None
            if med_name:
                active_meds.append({"name": med_name, "status": "keep"})

        return active_meds

    def _format_medication_data(self, data: dict, schema_key: str, status: str = "") -> dict | None:
        return format_medication_data(data, schema_key, status)

    # -------------------------------------------------------------------------
    # To-Do List
    # -------------------------------------------------------------------------

    def _extract_todo_list(self) -> dict:
        imaging = []
        labs = []
        referrals = []
        instructions = []
        follow_ups = []

        for data in self.fetch_all_commands_data_in_note_by_type("imagingOrder"):
            image_data = data.get("image") or {}
            imaging_name = image_data.get("text") or image_data.get("value", "") or "Imaging order"
            imaging.append(imaging_name)

        lab_orders = LabOrder.objects.filter(
            note=self.note,
            entered_in_error__isnull=True,
        ).prefetch_related("tests")
        for order in lab_orders:
            for test in order.tests.all():
                test_name = test.ontology_test_name
                if test_name:
                    labs.append(test_name)

        # Fall back to labOrder command data when the data model exposes no tests.
        if not labs:
            for data in self.fetch_all_commands_data_in_note_by_type("labOrder"):
                order_data = data.get("labOrder") or data
                lab_name = (
                    order_data.get("text")
                    or order_data.get("value")
                    or order_data.get("comment", "")
                    or "Lab order"
                )
                labs.append(lab_name)

        for data in self.fetch_all_commands_data_in_note_by_type("refer"):
            refer_to = data.get("refer_to")
            referral_text = None

            if isinstance(refer_to, dict):
                referral_text = (
                    refer_to.get("display")
                    or refer_to.get("name")
                    or refer_to.get("specialty")
                    or refer_to.get("text")
                )
            elif isinstance(refer_to, str):
                referral_text = refer_to

            if not referral_text:
                referral_text = (
                    data.get("indications") or data.get("clinical_question") or "Referral"
                )
            referrals.append(referral_text)

        for data in self.fetch_all_commands_data_in_note_by_type("instruct"):
            instruction_data = data.get("instruct") or {}
            title = instruction_data.get("text") or instruction_data.get("value", "")
            narrative = data.get("narrative", "")

            if title and narrative:
                instructions.append(f"{title}: {narrative}")
            elif narrative:
                instructions.append(narrative)
            elif title:
                instructions.append(title)

        for follow_up_data in self.fetch_all_commands_data_in_note_by_type("followUp"):
            note_type = follow_up_data.get("note_type", {})
            appointment_type = (
                (note_type.get("text") or "Follow-up") if isinstance(note_type, dict) else "Follow-up"
            )

            coding = follow_up_data.get("coding")
            if isinstance(coding, dict):
                reason = coding.get("text", "")
            elif isinstance(coding, list) and coding and isinstance(coding[0], dict):
                reason = coding[0].get("display", "") or coding[0].get("text", "")
            else:
                reason = follow_up_data.get("reason_for_visit", "")

            requested_date_data = follow_up_data.get("requested_date", {})
            appointment_date = "as directed"

            if isinstance(requested_date_data, dict) and requested_date_data.get("date"):
                date_str = requested_date_data.get("date")
                if isinstance(date_str, str):
                    try:
                        appointment_date = arrow.get(date_str).format("MMM D, YYYY")
                    except (ValueError, TypeError) as e:
                        log.warning(f"Could not parse followUp date '{date_str}': {e}")
                        appointment_date = date_str

            comment = follow_up_data.get("comment", "")
            full_reason = f"{reason} {comment}".strip() if reason or comment else "Follow Up"

            follow_ups.append(
                {
                    "type": appointment_type,
                    "appointment_date": appointment_date,
                    "reason_for_visit": full_reason,
                }
            )

        return {
            "imaging_orders": imaging,
            "lab_orders": labs,
            "referrals": referrals,
            "instructions": instructions,
            "follow_ups": follow_ups,
        }

    # -------------------------------------------------------------------------
    # Immunizations and Procedures
    # -------------------------------------------------------------------------

    def _extract_immunizations(self) -> list[str]:
        immunizations = []

        for data in self.fetch_all_commands_data_in_note_by_type("immunize"):
            vaccine_name = None
            coding = data.get("coding")

            if isinstance(coding, dict):
                vaccine_name = (
                    coding.get("display")
                    or coding.get("text")
                    or coding.get("name")
                    or coding.get("code")
                )
            elif isinstance(coding, list) and len(coding) > 0:
                first_coding = coding[0]
                if isinstance(first_coding, dict):
                    vaccine_name = (
                        first_coding.get("display")
                        or first_coding.get("text")
                        or first_coding.get("name")
                        or first_coding.get("code")
                    )

            if not vaccine_name:
                vaccine_name = data.get("manufacturer") or "Immunization"

            immunizations.append(f"{vaccine_name} (administered today)")

        return immunizations

    def _extract_procedures(self) -> list[str]:
        procedures = []

        for data in self.fetch_all_commands_data_in_note_by_type("perform"):
            procedure_name = None

            coding = data.get("coding")
            if isinstance(coding, list) and coding:
                first_coding = coding[0]
                if isinstance(first_coding, dict):
                    procedure_name = first_coding.get("display") or first_coding.get("code")
            elif isinstance(coding, dict):
                procedure_name = coding.get("display") or coding.get("code")

            if not procedure_name:
                perform_data = data.get("perform") or {}
                cpt_code = perform_data.get("cptCode")
                if isinstance(cpt_code, dict):
                    procedure_name = cpt_code.get("display") or cpt_code.get("name")
                if not procedure_name:
                    procedure_name = perform_data.get("text") or perform_data.get("value")

            if not procedure_name:
                procedure_name = data.get("notes") or "Procedure"

            procedures.append(procedure_name)

        return procedures

    # -------------------------------------------------------------------------
    # Upcoming Appointments
    # -------------------------------------------------------------------------

    def _extract_upcoming_appointments(self) -> list[dict]:
        upcoming = []
        timezone_str = self.patient.last_known_timezone or "America/New_York"

        future_appointments = (
            Appointment.objects.filter(
                patient=self.patient,
                start_time__gte=arrow.utcnow().datetime,
                status__in=[
                    AppointmentProgressStatus.CONFIRMED,
                    AppointmentProgressStatus.UNCONFIRMED,
                ],
            )
            .select_related("provider")
            .order_by("start_time")[:5]
        )

        for appt in future_appointments:
            appt_date = ""
            if appt.start_time:
                appt_date = (
                    arrow.get(appt.start_time).to(timezone_str).format("MMMM D, YYYY [at] h:mm A ZZZ")
                )

            upcoming.append(
                {
                    "appointment_date": appt_date,
                    "provider": appt.provider.full_name if appt.provider else "Provider",
                    "type": "Office Visit",
                    "reason_for_visit": appt.comment or "Follow-up",
                }
            )

        return upcoming
