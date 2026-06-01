import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Union
from urllib.parse import urlencode
from uuid import uuid4

from canvas_sdk.commands import (
    AssessCommand,
    DiagnoseCommand,
    HistoryOfPresentIllnessCommand,
    ImagingOrderCommand,
    LabOrderCommand,
    PhysicalExamCommand,
    PlanCommand,
    PrescribeCommand,
    ReasonForVisitCommand,
    ReferCommand,
    ReviewOfSystemsCommand,
    VitalsCommand,
)
from canvas_sdk.commands.base import _BaseCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.questionnaires import questionnaire_from_yaml
from canvas_sdk.templates import render_to_string
from canvas_sdk.utils.http import ontologies_http
from canvas_sdk.v1.data import Condition
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.questionnaire import Questionnaire
from canvas_sdk.value_set.value_set import CodeConstants

from django.core.exceptions import ObjectDoesNotExist

from soap_note.models.soap_note_data import SoapNoteData

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

SOAP_FIELDS = ("subjective", "objective", "assessment", "plan")

QUESTIONNAIRE_CODE_ROS = "SOAP_BRIEF_ROS"
QUESTIONNAIRE_CODE_EXAM = "SOAP_BRIEF_EXAM"

ORDER_COMMANDS = {
    "lab": LabOrderCommand,
    "imaging": ImagingOrderCommand,
    "refer": ReferCommand,
    "prescribe": PrescribeCommand,
}

VITALS_FIELD_MAP = {
    "systolic": ("blood_pressure_systole", int),
    "diastolic": ("blood_pressure_diastole", int),
    "pulse": ("pulse", int),
    "temperature": ("body_temperature", float),
    "respiration": ("respiration_rate", int),
    "oxygen": ("oxygen_saturation", int),
    "height": ("height", int),
    "weight": ("weight_lbs", int),
}


def _originate(cmd: _BaseCommand) -> Effect:
    """Assign a UUID and return the originate effect."""
    cmd.command_uuid = str(uuid4())
    return cmd.originate()


class SoapNoteAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the SOAP Note UI and handles save/load/command origination."""

    PREFIX = "/soap"

    @api.get("/app")
    def get_app(self) -> list[Union[Response, Effect]]:
        note_uuid = self.request.query_params.get("note_id", "")
        if not note_uuid:
            return [
                HTMLResponse(
                    "<html><body>Error: note_id is required</body></html>",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            note = Note.objects.get(id=note_uuid)
        except ObjectDoesNotExist:
            return [HTMLResponse(
                "<html><body>Error: Note not found</body></html>",
                status_code=HTTPStatus.NOT_FOUND,
            )]

        patient_id = str(note.patient.id)
        existing = SoapNoteData.objects.filter(note_id=note.dbid).first()

        sections = {
            field: getattr(existing, field, "") if existing else ""
            for field in SOAP_FIELDS
        }

        html = render_to_string(
            "templates/soap_note.html",
            {
                "note_id": note_uuid,
                "note_id_json": json.dumps(note_uuid),
                "patient_id_json": json.dumps(patient_id),
                "sections_json": json.dumps(sections),
                "cache_bust": _CACHE_BUST,
            },
        )
        return [HTMLResponse(html)]

    def _load_questionnaire(self, yaml_path: str, code: str, transform_question) -> list[Union[Response, Effect]]:
        """Shared loader for questionnaire endpoints."""
        config = questionnaire_from_yaml(yaml_path)
        if not config:
            return [JSONResponse({"error": "Questionnaire not found"}, status_code=HTTPStatus.NOT_FOUND)]

        questions = [transform_question(q) for q in config.get("questions", [])]

        questionnaire_id = None
        qs = Questionnaire.objects.filter(code=code).first()
        if qs:
            questionnaire_id = str(qs.id)

        return [JSONResponse({"questionnaire_id": questionnaire_id, "questions": questions})]

    @api.get("/ros-questions")
    def ros_questions(self) -> list[Union[Response, Effect]]:
        """Return the bundled Brief ROS questionnaire structure."""
        def transform(q):
            return {
                "content": q["content"],
                "code": q["code"],
                "responses": [
                    {"name": r["name"], "code": r["code"], "value": r["value"]}
                    for r in q.get("responses", [])
                ],
            }
        return self._load_questionnaire("questionnaires/brief_ros.yml", QUESTIONNAIRE_CODE_ROS, transform)

    @api.get("/exam-questions")
    def exam_questions(self) -> list[Union[Response, Effect]]:
        """Return the bundled Brief Exam questionnaire structure."""
        def transform(q):
            default_value = q["responses"][0].get("value", "") if q.get("responses") else ""
            return {"content": q["content"], "code": q["code"], "default_value": default_value}
        return self._load_questionnaire("questionnaires/brief_exam.yml", QUESTIONNAIRE_CODE_EXAM, transform)

    @api.post("/save-commands")
    def save_commands(self) -> list[Union[Response, Effect]]:
        """Originate SOAP commands in the note and persist data."""
        body = self.request.json() or {}
        note_uuid = body.get("note_uuid", "")
        if not note_uuid:
            return [JSONResponse({"error": "note_uuid required"}, status_code=HTTPStatus.BAD_REQUEST)]

        rfv = body.get("rfv", "").strip()
        subjective = body.get("subjective", "").strip()
        objective = body.get("objective", "").strip()
        vitals = body.get("vitals", {})
        ros_selections = body.get("ros_selections", {})
        exam_findings = body.get("exam_findings", {})
        conditions = body.get("conditions", [])
        plan_text = body.get("plan", "").strip()

        effects: list[Effect] = []

        # Reason for Visit
        if rfv:
            effects.append(_originate(ReasonForVisitCommand(note_uuid=note_uuid, comment=rfv)))

        # Subjective → HPI
        if subjective:
            effects.append(_originate(HistoryOfPresentIllnessCommand(note_uuid=note_uuid, narrative=subjective)))

        # Objective → Vitals
        vitals_kwargs = {}
        for form_key, (cmd_key, coerce) in VITALS_FIELD_MAP.items():
            val = vitals.get(form_key, "")
            if val != "":
                try:
                    vitals_kwargs[cmd_key] = coerce(val)
                except (ValueError, TypeError):
                    pass

        if vitals_kwargs:
            effects.append(_originate(VitalsCommand(note_uuid=note_uuid, **vitals_kwargs)))

        # Batch-load questionnaires for ROS + Exam
        questionnaires = {}
        needed_codes = []
        if ros_selections:
            needed_codes.append(QUESTIONNAIRE_CODE_ROS)
        if exam_findings:
            needed_codes.append(QUESTIONNAIRE_CODE_EXAM)
        if needed_codes:
            questionnaires = {
                q.code: q for q in Questionnaire.objects.filter(code__in=needed_codes)
            }

        # Objective → ROS command
        if ros_selections and QUESTIONNAIRE_CODE_ROS in questionnaires:
            all_selected = set()
            for codes in ros_selections.values():
                all_selected.update(codes)

            result_text = "ROS reviewed: " + ", ".join(
                f"{system}: {', '.join(codes)}" for system, codes in ros_selections.items() if codes
            ) if any(ros_selections.values()) else "ROS reviewed, all systems negative"

            ros_cmd = ReviewOfSystemsCommand(
                note_uuid=note_uuid,
                questionnaire_id=str(questionnaires[QUESTIONNAIRE_CODE_ROS].id),
                result=result_text,
            )
            ros_cmd.command_uuid = str(uuid4())
            for question in ros_cmd.questions:
                for option in question.options:
                    if option.name in all_selected:
                        question.add_response(option=option)
            effects.append(ros_cmd.originate())

        # Objective → Physical Exam command
        if exam_findings and QUESTIONNAIRE_CODE_EXAM in questionnaires:
            filled = {k: v for k, v in exam_findings.items() if v.strip()}
            if filled:
                result_text = "; ".join(f"{system}: {finding}" for system, finding in filled.items())
                exam_cmd = PhysicalExamCommand(
                    note_uuid=note_uuid,
                    questionnaire_id=str(questionnaires[QUESTIONNAIRE_CODE_EXAM].id),
                    result=result_text,
                )
                exam_cmd.command_uuid = str(uuid4())
                for question in exam_cmd.questions:
                    finding_text = exam_findings.get(question.label, "")
                    if finding_text.strip():
                        question.add_response(text=finding_text)
                effects.append(exam_cmd.originate())

        # Assessment → Diagnose or Assess for each condition
        for cond in conditions:
            icd10_code = cond.get("icd10_code", "").replace(".", "")
            narrative = cond.get("narrative", "")
            existing_condition_id = cond.get("condition_id")

            if existing_condition_id:
                status_map = {
                    "improved": AssessCommand.Status.IMPROVED,
                    "stable": AssessCommand.Status.STABLE,
                    "deteriorated": AssessCommand.Status.DETERIORATED,
                }
                cmd = AssessCommand(
                    note_uuid=note_uuid,
                    condition_id=existing_condition_id,
                    narrative=narrative,
                    status=status_map.get(cond.get("status", "stable"), AssessCommand.Status.STABLE),
                )
            else:
                cmd = DiagnoseCommand(
                    note_uuid=note_uuid,
                    icd10_code=icd10_code,
                    today_assessment=narrative,
                )
            effects.append(_originate(cmd))

        # Plan → PlanCommand
        if plan_text:
            effects.append(_originate(PlanCommand(note_uuid=note_uuid, narrative=plan_text)))

        # Persist to custom data
        try:
            note = Note.objects.get(id=note_uuid)
        except ObjectDoesNotExist:
            return [JSONResponse({"error": "Note not found"}, status_code=HTTPStatus.NOT_FOUND)]

        SoapNoteData.objects.update_or_create(
            note_id=note.dbid,
            defaults={
                "subjective": subjective,
                "objective": objective,
                "assessment": json.dumps(conditions),
                "plan": plan_text,
            },
        )

        return [JSONResponse({"status": "commands_created", "count": len(effects)}), *effects]

    @api.get("/search-conditions")
    def search_conditions(self) -> list[Union[Response, Effect]]:
        """Search ICD-10 codes via the ontologies API."""
        query = self.request.query_params.get("q", "").strip()
        if len(query) < 2:
            return [JSONResponse({"results": []})]

        try:
            resp = ontologies_http.get_json(f"/icd/condition?{urlencode({'search': query})}")
        except RuntimeError:
            return [JSONResponse({"results": []})]

        data = resp.json()
        results = [
            {"icd10_code": r.get("icd10_code", ""), "icd10_text": r.get("icd10_text", "")}
            for r in data.get("results", [])[:15]
        ]
        return [JSONResponse({"results": results})]

    @api.get("/patient-conditions")
    def patient_conditions(self) -> list[Union[Response, Effect]]:
        """Load active conditions for the patient."""
        patient_id = self.request.query_params.get("patient_id", "")
        if not patient_id:
            return [JSONResponse({"conditions": []})]

        conditions = []
        for cond in Condition.objects.for_patient(patient_id).committed().prefetch_related("codings"):
            codings = [
                c for c in cond.codings.all()
                if c.system == CodeConstants.URL_ICD10
            ][:1]
            if codings:
                conditions.append({
                    "condition_id": str(cond.id),
                    "icd10_code": codings[0].code,
                    "display": codings[0].display,
                    "clinical_status": cond.clinical_status or "active",
                })

        return [JSONResponse({"conditions": conditions})]

    @api.post("/originate-order")
    def originate_order(self) -> list[Union[Response, Effect]]:
        """Originate a blank order command in the note."""
        body = self.request.json() or {}
        note_uuid = body.get("note_uuid", "")
        order_type = body.get("order_type", "")

        if not note_uuid or order_type not in ORDER_COMMANDS:
            return [JSONResponse(
                {"error": f"Invalid order_type: {order_type}. Use: {list(ORDER_COMMANDS)}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        cmd = ORDER_COMMANDS[order_type](note_uuid=note_uuid)
        return [JSONResponse({"status": "order_created", "order_type": order_type}), _originate(cmd)]
