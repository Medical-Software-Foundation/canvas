"""Shared service for extracting all command data from a note.

This class centralizes the DB queries and data formatting logic
so that multiple UI protocols (Patient Visit Summary, Customize & Print)
can consume the same data without duplicating queries.
"""

from __future__ import annotations

from typing import Any

import arrow
from django.db.models import Q

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.assessment import Assessment
from canvas_sdk.v1.data.billing import BillingLineItemStatus
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import InterviewQuestionResponse
from canvas_sdk.v1.data.staff import StaffRole
from canvas_sdk.v1.data.goal import GoalPriority, GoalAchievementStatus

from patient_visit_summary.services.code_utils import coded_title


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

ASSESSMENT_STATUS_DICT = {
    "improved": "Improved",
    "stable": "Unchanged",
    "deteriorated": "Deteriorated",
}


def format_icd10_code(icd10_code: str) -> str:
    """Format an ICD-10 code with a dot after the third character."""
    if not icd10_code:
        return ""
    icd10_code = icd10_code.strip().upper()
    if len(icd10_code) > 3:
        return icd10_code[:3] + "." + icd10_code[3:]
    return icd10_code


def _annotate_coded_titles(entries: list, field_key: str) -> None:
    """Attach a ``coded_title`` (name + CPT/CVX suffix) to each command dict.

    ``field_key`` is the entry's main coding field (e.g. "coding" for immunize,
    "perform" for procedures, "statement" for immunization statements).
    """
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        coding_field = entry.get(field_key)
        text = coding_field.get("text", "") if isinstance(coding_field, dict) else ""
        entry["coded_title"] = coded_title(text, coding_field)


class NoteDataExtractor:
    """Extracts all command and contextual data from a note for rendering.

    Usage:
        extractor = NoteDataExtractor(patient_id="123", note_id="456")
        context = extractor.get_template_context()
    """

    def __init__(self, patient_id: str, note_id: str) -> None:
        # `note_id` is the Note's external UUID (`Note.id`), not the internal dbid.
        self.patient = Patient.objects.get(id=patient_id)
        self.note = Note.objects.get(id=note_id)

    def _fetch_latest_command_data(self, schema_key: str) -> dict | None:
        """Fetch the data dict of the most recent committed command of a type in this note."""
        return (
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("-dbid")
            .values_list("data", flat=True)
            .first()
        )

    def _fetch_all_commands_data(self, schema_key: str) -> list[dict]:
        """Fetch data dicts for all committed commands of a type in this note."""
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

    def _fetch_commands_fields(self, schema_key: str, *fields: str) -> list[dict]:
        """Fetch specific fields for all committed commands of a type in this note."""
        return list(
            Command.objects.filter(
                schema_key=schema_key,
                note=self.note,
                entered_in_error__isnull=True,
                state="committed",
            )
            .order_by("dbid")
            .values(*fields)
            .all()
        )

    def _format_questionnaires(
        self,
        questionnaire_names: list[str] | None = None,
        questionnaire_type: str | None = None,
    ) -> list[dict]:
        """Format questionnaire or structured assessment commands into display dicts."""
        schema_key = questionnaire_type or "questionnaire"

        raw_data = self._fetch_commands_fields(schema_key, "data", "modified")

        if questionnaire_names:
            q_filter = Q()
            for name in questionnaire_names:
                q_filter = q_filter | Q(data__questionnaire__text=name)
            # Re-query with filter since we have a list
            raw_data = [d for d in raw_data if any(
                d["data"].get("questionnaire", {}).get("text", "") == name
                for name in questionnaire_names
            )]

        result = []
        for item in raw_data:
            last_updated_dt = arrow.get(item["modified"]).to("US/Eastern")
            last_updated = f'{last_updated_dt.format("M/D/YY")} at {last_updated_dt.format("h:mm A")} EDT'
            assessment: dict[str, Any] = {
                "name": item["data"]["questionnaire"]["text"],
                "last_updated": last_updated,
            }
            if item_result := item["data"].get("result"):
                assessment["result"] = item_result

            questions_and_answers = []
            for question in item["data"]["questionnaire"]["extra"]["questions"]:
                qa: dict[str, Any] = {
                    "label": question["label"],
                    "code": question["coding"]["code"],
                }
                response_type = question["type"]
                question_answer = item["data"][question["name"]]

                answer = ""
                if response_type == "MULT":
                    selected_parts = []
                    for q in question_answer or []:
                        if q.get("selected") is not True:
                            continue
                        text = q.get("text", "")
                        comment = (q.get("comment") or "").strip()
                        if comment:
                            selected_parts.append(f"{text} ({comment})")
                        else:
                            selected_parts.append(text)
                    answer = ", ".join(selected_parts)
                elif response_type in ("TXT", "INT"):
                    if question_answer is not None and question_answer != "":
                        answer = str(question_answer)
                elif response_type == "SING":
                    single = [
                        c["label"]
                        for c in question["options"]
                        if c["pk"] == question_answer
                    ]
                    if single:
                        answer = single[0]

                if not answer.strip():
                    continue

                qa["answer"] = answer
                questions_and_answers.append(qa)
            assessment["questions_and_answers"] = questions_and_answers
            result.append(assessment)
        return result

    def _format_ros_or_exam(self, schema_key: str) -> list[dict]:
        """Format ROS or physical exam commands into display dicts."""
        raw_data = self._fetch_all_commands_data(schema_key)
        result = []
        for ros in raw_data:
            ros_answers: dict[str, Any] = {
                "questionnaire": ros["questionnaire"]["text"],
                "questions_and_answers": [],
            }
            for question in ros["questionnaire"]["extra"]["questions"]:
                question_id = question["pk"]
                if ros.get(f"skip-{question_id}") is False:
                    continue
                answers = []
                question_name = question["label"]
                if question["type"] == "MULT":
                    for q in ros[question["name"]]:
                        if q.get("selected") is not True:
                            continue
                        text = q.get("text", "")
                        comment = (q.get("comment") or "").strip()
                        answers.append(f"{text} ({comment})" if comment else text)
                elif question["type"] == "TXT":
                    answers = [ros[question["name"]]]
                if answers:
                    ros_answers["questions_and_answers"].append(
                        {"label": question_name, "answer": ", ".join(answers)}
                    )
            result.append(ros_answers)
        return result

    def _get_diagnoses_from_structured_assessments(self) -> list[tuple[str, str]]:
        """Extract ICD-10 diagnoses triggered by structured assessment answers."""
        structured_data = self._fetch_all_commands_data("structuredAssessment")
        if not structured_data:
            return []

        # Resolve the ICD-10 trigger questions for every questionnaire on the
        # note in a single query, then group in Python — rather than one query
        # per structured assessment.
        questionnaire_ids = {
            a["questionnaire"]["extra"]["pk"] for a in structured_data
        }
        triggers_by_questionnaire: dict[Any, set] = {}
        for q_id, question_id in InterviewQuestionResponse.objects.filter(
            questionnaire_id__in=questionnaire_ids,
            question__response_option_set__code_system="ICD-10",
        ).values_list("questionnaire_id", "question_id"):
            triggers_by_questionnaire.setdefault(q_id, set()).add(question_id)

        icd10_codes: list[str] = []
        for assessment_data in structured_data:
            question_option_code_map: dict[str, dict] = {}
            questionnaire_id = assessment_data["questionnaire"]["extra"]["pk"]
            trigger_question_ids = triggers_by_questionnaire.get(questionnaire_id, set())

            for question in assessment_data["questionnaire"]["extra"]["questions"]:
                if question["pk"] in trigger_question_ids:
                    question_option_code_map[question["name"]] = {
                        "type": question["type"],
                        "codes": {opt["pk"]: opt["code"] for opt in question["options"]},
                    }

            for question_name, info in question_option_code_map.items():
                response = assessment_data[question_name]
                if info["type"] == "MULT":
                    codes = [
                        info["codes"][c["value"]]
                        for c in response
                        if c.get("selected") is True and info["codes"].get(c["value"])
                    ]
                    icd10_codes.extend(codes)
                elif info["type"] == "SING":
                    code = info["codes"].get(response)
                    if code:
                        icd10_codes.append(code)

        icd10_codes = list(set(icd10_codes))
        if not icd10_codes:
            return []

        note_assessments = (
            Assessment.objects.filter(
                note=self.note,
                condition__entered_in_error__isnull=True,
                condition__codings__system="ICD-10",
                condition__codings__code__in=icd10_codes,
                interview__isnull=False,
            )
            .select_related("condition")
            .prefetch_related("condition__codings")
        )

        result = []
        for assessment in note_assessments:
            # Read from the prefetched `condition__codings` cache (`.all()`) — a
            # `.filter()` here would issue a fresh query per assessment and defeat
            # the prefetch above.
            coding = next(
                (c for c in assessment.condition.codings.all() if c.system == "ICD-10"),
                None,
            )
            if coding:
                result.append((coding.display, format_icd10_code(coding.code)))
        return result

    def _get_header_context(self) -> dict[str, Any]:
        """Extract appointment, provider, and header info."""
        appointment = (
            Appointment.objects.filter(note=self.note)
            .order_by("-dbid")
            .only("id", "start_time", "provider")
            .first()
        )

        if appointment:
            appointment_date = arrow.get(appointment.start_time).to("US/Eastern").format("MMMM D, YYYY")
            provider = appointment.provider
        else:
            appointment_date = arrow.get(self.note.datetime_of_service).to("US/Eastern").format("MMMM D, YYYY")
            provider = self.note.provider

        provider_top_role = (
            provider.roles.filter(domain__in=StaffRole.RoleDomain.clinical_domains())
            .order_by("-domain_privilege_level")
            .first()
        )

        return {
            "appointment_date": appointment_date,
            "provider": provider,
            "provider_top_role": provider_top_role,
        }

    def _get_billing_line_items(self) -> list[dict]:
        """Active billing line items for the note as patient-facing rows.

        Returns ``{code, description, units}`` dicts — the CPT (with any
        modifiers appended, e.g. ``90686-25``), the description, and units.
        No charge amounts: this is patient-facing, not a superbill.
        """
        items = (
            self.note.billing_line_items
            .filter(status=BillingLineItemStatus.ACTIVE)
            .order_by("dbid")
            .prefetch_related("modifiers")
        )
        result: list[dict] = []
        for item in items:
            cpt = (item.cpt or "").strip()
            if not cpt:
                continue
            modifiers = [m.code for m in item.modifiers.all() if m.code]
            code = "-".join([cpt, *modifiers]) if modifiers else cpt
            result.append({
                "code": code,
                "description": item.description or "",
                "units": item.units,
            })
        return result

    def _get_reasons_for_visit(self) -> list[dict[str, str]]:
        """Extract each RFV as {text, comment}. Both fields may be present."""
        rfv_commands = Command.objects.filter(
            note__dbid=self.note.dbid,
            schema_key="reasonForVisit",
        ).order_by("dbid")
        results: list[dict[str, str]] = []
        for cmd in rfv_commands:
            coding = cmd.data.get("coding") or {}
            text = coding.get("text", "") if isinstance(coding, dict) else ""
            comment = (cmd.data.get("comment") or "").strip()
            # If there's no coding, fall back to the comment as the main text.
            if not text and comment:
                results.append({"text": comment, "comment": ""})
                continue
            if text or comment:
                results.append({"text": text, "comment": comment})
        return results

    def _get_reason_for_visit(self) -> str:
        """Single-string RFV for templates that expect a scalar (joins all RFVs)."""
        parts: list[str] = []
        for rfv in self._get_reasons_for_visit():
            text = rfv.get("text", "")
            comment = rfv.get("comment", "")
            if text and comment:
                parts.append(f"{text} ({comment})")
            elif text:
                parts.append(text)
            elif comment:
                parts.append(comment)
        return "; ".join(parts)

    def get_template_context(self) -> dict[str, Any]:
        """Build the full template context dict with all note data.

        Returns a dict suitable for passing directly to render_to_string
        for either the Patient Visit Summary or Customize & Print templates.
        """
        header = self._get_header_context()
        reasons_for_visit = self._get_reasons_for_visit()
        reason_for_visit = self._get_reason_for_visit()

        # Subjective
        hpi_data = self._fetch_all_commands_data("hpi")
        ros_data = self._format_ros_or_exam("ros")
        questionnaire_data = self._format_questionnaires()

        # Objective - Vitals
        # Local import avoids the command_blocks <-> note_data_extractor cycle.
        from patient_visit_summary.services.command_blocks import compute_bmi

        vitals_data = self._fetch_all_commands_data("vitals")
        for vitals in vitals_data:
            for key in VITALS_ENUM_DICT:
                description = VITALS_ENUM_DICT[key].get(vitals.get(key, ""), "")
                vitals[key] = description
            # Surface BMI on the printout, mirroring the Customize & Print path.
            vitals["bmi"] = compute_bmi(vitals)

        # Objective - Physical Exam
        physical_exam_data = self._format_ros_or_exam("exam")

        # Assessments
        assessments_data = self._fetch_all_commands_data("assess")
        for assessment in assessments_data:
            if assessment.get("status"):
                assessment["status"] = ASSESSMENT_STATUS_DICT.get(
                    assessment["status"], assessment["status"]
                )

        # Diagnoses
        diagnose_raw = self._fetch_commands_fields("diagnose", "data", "modified")
        diagnose_data = []
        for diag in diagnose_raw:
            modified_dt = arrow.get(diag["modified"]).to("US/Eastern")
            diagnose_data.append({
                "data": diag["data"],
                "modified": f'{modified_dt.format("M.D.YY")} at {modified_dt.format("h:mm A")} EDT',
            })

        diagnoses_from_sa = self._get_diagnoses_from_structured_assessments()

        # Reviews
        lab_reviews = self._fetch_all_commands_data("labReview")
        imaging_reviews = self._fetch_all_commands_data("imagingReview")
        referral_reviews = self._fetch_all_commands_data("referralReview")
        uncat_reviews = self._fetch_all_commands_data("uncategorizedDocumentReview")
        structured_assessments = self._format_questionnaires(questionnaire_type="structuredAssessment")
        resolve_conditions = self._fetch_all_commands_data("resolveCondition")
        change_diagnoses = self._fetch_all_commands_data("updateDiagnosis")

        # Plan
        plan_data = self._fetch_all_commands_data("plan")
        prescribe_data = self._fetch_all_commands_data("prescribe")
        refill_data = self._fetch_all_commands_data("refill")
        stop_med_data = self._fetch_all_commands_data("stopMedication")
        adjust_rx_data = self._fetch_all_commands_data("adjustPrescription")
        change_med_data = self._fetch_all_commands_data("changeMedication")
        referral_data = self._fetch_all_commands_data("refer")
        lab_order_data = self._fetch_all_commands_data("labOrder")
        imaging_order_data = self._fetch_all_commands_data("imagingOrder")
        instruct_data = self._fetch_all_commands_data("instruct")

        # Follow-up(s)
        follow_ups: list[dict[str, str]] = []
        for fu in self._fetch_all_commands_data("followUp"):
            requested = fu.get("requested_date") if isinstance(fu.get("requested_date"), dict) else {}
            raw_date = (requested.get("date") or "") if isinstance(requested, dict) else ""
            input_text = (requested.get("input") or "").strip() if isinstance(requested, dict) else ""
            # Preserve both parts so downstream can show "2 weeks (around 2026-04-17)".
            if input_text and raw_date and input_text != raw_date:
                date_str = f"{input_text} (around {raw_date})"
            else:
                date_str = input_text or raw_date
            if fu.get("coding"):
                rfv = fu.get("coding", {}).get("text", "")
            else:
                rfv = fu.get("reason_for_visit", "")
            note_type = fu.get("note_type", {}).get("text", "") if isinstance(fu.get("note_type"), dict) else ""
            comment = (fu.get("comment") or "").strip()
            if date_str or rfv or note_type or comment:
                follow_ups.append({
                    "date": date_str,
                    "rfv": rfv,
                    "note_type": note_type,
                    "comment": comment,
                })

        # Keep the singular fields for templates that expect them (latest follow-up).
        if follow_ups:
            latest_fu = follow_ups[-1]
            follow_up_date = latest_fu["date"] or None
            follow_up_rfv = latest_fu["rfv"]
            follow_up_note_type = latest_fu["note_type"]
        else:
            follow_up_date = None
            follow_up_rfv = ""
            follow_up_note_type = ""

        # Tasks & Goals
        task_data = self._fetch_all_commands_data("task")
        goal_data = self._fetch_all_commands_data("goal")
        for goal in goal_data:
            if goal.get("priority"):
                goal["priority"] = GoalPriority(goal["priority"]).label
            if goal.get("achievement_status"):
                goal["achievement_status"] = GoalAchievementStatus(goal["achievement_status"]).label

        update_goal_data = self._fetch_all_commands_data("updateGoal")
        for goal in update_goal_data:
            if goal.get("priority"):
                goal["priority"] = GoalPriority(goal["priority"]).label
            if goal.get("achievement_status"):
                goal["achievement_status"] = GoalAchievementStatus(goal["achievement_status"]).label

        # Procedures
        immunize_data = self._fetch_all_commands_data("immunize")
        perform_data = self._fetch_all_commands_data("perform")
        # Surface CPT/CVX codes on the template's name line for each command type
        # whose coding field carries them.
        _annotate_coded_titles(immunize_data, "coding")
        _annotate_coded_titles(perform_data, "perform")

        # Billed services (patient-facing: CPT + description + units, no charges)
        billing_line_items = self._get_billing_line_items()

        # History
        allergy_data = self._fetch_all_commands_data("allergy")
        remove_allergy_data = self._fetch_all_commands_data("removeAllergy")
        med_statement_data = self._fetch_all_commands_data("medicationStatement")
        imm_statement_data = self._fetch_all_commands_data("immunizationStatement")
        _annotate_coded_titles(imm_statement_data, "statement")
        family_history_data = self._fetch_all_commands_data("familyHistory")
        medical_history_data = self._fetch_all_commands_data("medicalHistory")
        for mh in medical_history_data:
            if mh.get("past_medical_history", {}).get("annotations"):
                mh["past_medical_history"]["annotations"][0] = format_icd10_code(
                    mh["past_medical_history"]["annotations"][0]
                )
        surgical_history_data = self._fetch_all_commands_data("surgicalHistory")

        return {
            "patient": self.patient,
            "note": self.note,
            "provider": header["provider"],
            "provider_top_role": header["provider_top_role"],
            "appointment_date": header["appointment_date"],
            # Subjective
            "reason_for_visit": reason_for_visit,
            "reasons_for_visit": reasons_for_visit,
            "history_of_present_illness_commands_data": hpi_data,
            "review_of_systems_data": ros_data,
            "questionnaire_data": questionnaire_data,
            # Objective
            "vitals_commands_data": vitals_data,
            "physical_exam_data": physical_exam_data,
            "assessments_commands_data": assessments_data,
            "diagnose_commands_data": diagnose_data,
            "diagnoses_from_structured_assessments": diagnoses_from_sa,
            "resolve_condition_commands_data": resolve_conditions,
            "change_diagnosis_commands_data": change_diagnoses,
            "lab_reviews": lab_reviews,
            "imaging_reviews": imaging_reviews,
            "consult_report_reviews": referral_reviews,
            "uncategorized_document_reviews": uncat_reviews,
            "structured_assessment_data": structured_assessments,
            # Plan
            "plan_commands_data": plan_data,
            "prescribe_commands_data": prescribe_data,
            "refill_commands_data": refill_data,
            "stop_medication_commands_data": stop_med_data,
            "adjust_prescription_commands_data": adjust_rx_data,
            "change_medication_commands_data": change_med_data,
            "referral_commands_data": referral_data,
            "lab_order_commands_data": lab_order_data,
            "imaging_order_commands_data": imaging_order_data,
            "instruct_commands_data": instruct_data,
            "follow_up_date": follow_up_date,
            "follow_up_rfv": follow_up_rfv,
            "follow_up_note_type": follow_up_note_type,
            "follow_ups": follow_ups,
            "task_commands_data": task_data,
            "goal_commands_data": goal_data,
            "update_goal_commands_data": update_goal_data,
            # Procedures
            "immunize_commands_data": immunize_data,
            "perform_commands_data": perform_data,
            # History
            "allergy_commands_data": allergy_data,
            "remove_allergy_commands_data": remove_allergy_data,
            "medication_statement_commands_data": med_statement_data,
            "immunization_statement_commands_data": imm_statement_data,
            "patient_family_history_commands_data": family_history_data,
            "medical_history_commands_data": medical_history_data,
            "surgical_history_commands_data": surgical_history_data,
            # Billed services
            "billing_line_items_data": billing_line_items,
        }

    def get_commands_by_section(
        self, sections: list[dict] | None = None,
    ) -> list[dict]:
        """Return every command in the note grouped by section, with per-entry
        titles and pre-built display blocks — ready for any print UI.

        See `services.command_blocks.enumerate_sections` for the output shape.
        Pass a custom `sections` config to override the default mapping.
        """
        # Imported lazily to avoid a circular import at module load time.
        from patient_visit_summary.services.command_blocks import enumerate_sections
        return enumerate_sections(self.get_template_context(), sections=sections)
