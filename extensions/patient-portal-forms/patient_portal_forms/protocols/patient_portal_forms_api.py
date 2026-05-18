import uuid

import arrow
from http import HTTPStatus

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.commands.commands.questionnaire.question import ResponseOption
from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.message import Message
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import NoteType, NoteTypeCategories
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.questionnaire import Questionnaire
from canvas_sdk.v1.data.staff import Staff

from logger import log

from patient_portal_forms.services import (
    DailyNoteService,
    QuestionnaireAssignmentService,
)


class ProviderQuestionnaireAPI(StaffSessionAuthMixin, SimpleAPI):
    """
    A provider-facing API that serves the Canvas chart. This is for a provider
    to view or assign questionnaires to a patient.
    """

    @api.get("/provider-view/patient/<patient_id>")
    def get_patient_forms(self) -> list[Response | Effect]:
        """Render the provider view for managing a patient's questionnaires."""
        patient_id = self.request.path_params["patient_id"]
        if not Patient.objects.filter(id=patient_id).exists():
            return [
                HTMLResponse(
                    render_to_string("templates/404.html"),
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        staff_id = self.event.context["headers"]["canvas-logged-in-user-id"]
        staff = Staff.objects.get(id=staff_id)

        grouped = QuestionnaireAssignmentService.list_grouped(patient_id)

        # Questionnaires to populate the dropdown of choices when assigning
        questionnaire_assignment_choices = Questionnaire.objects.filter(
            use_case_in_charting="QUES",
            status="AC",
        ).order_by("name")

        return [
            HTMLResponse(
                render_to_string(
                    "templates/provider_view_questionnaires.html",
                    context={
                        "pending_items": grouped["pending_items"],
                        "completed_groups": grouped["completed_groups"],
                        "pending_names": grouped["pending_names"],
                        "questionnaire_assignment_choices": questionnaire_assignment_choices,
                        "patient_id": patient_id,
                        "staff": staff,
                    },
                ),
                status_code=HTTPStatus.OK,
            )
        ]

    def create_message_to_patient(self, questionnaires_json, staff_id, patient_id):
        """Render the portal-message body and build a Message effect."""
        message_content = render_to_string(
            "templates/patient_message.html",
            context={"assigned_questionnaires": questionnaires_json},
        )
        return Message(
            content=message_content,
            sender_id=staff_id,
            recipient_id=patient_id,
        )

    @api.post("/provider-view/patient/<patient_id>/assign")
    def assign_forms(self) -> list[Response | Effect]:
        """Assign one or more questionnaires and notify the patient.

        Security: the assigning staff is taken from the trusted session
        header, not from the request body. Any ``assigning_provider`` field
        the frontend sends in the body (still included for back-compat)
        is ignored — otherwise an authenticated staff member could craft
        a POST substituting another staff's UUID, and the resulting
        Patient Portal Form note (on submit) would land under the
        impersonated staff's name, location, and worklist.
        """
        patient_id = self.request.path_params["patient_id"]
        staff_id = self.event.context["headers"]["canvas-logged-in-user-id"]
        request_payload = self.request.json()
        new_questionnaires = request_payload.get("questionnaires", []) or []

        QuestionnaireAssignmentService.assign(
            patient_id,
            new_questionnaires,
            assigning_provider_uuid=staff_id,
        )

        patient_message = self.create_message_to_patient(
            {"questionnaires": new_questionnaires},
            staff_id=staff_id,
            patient_id=patient_id,
        )

        return [
            patient_message.create_and_send(),
            Response(status_code=HTTPStatus.CREATED),
        ]

    @api.post("/provider-view/patient/<patient_id>/remind")
    def send_reminder(self) -> list[Response | Effect]:
        """Send a reminder message about a single assigned questionnaire."""
        patient_id = self.request.path_params["patient_id"]
        staff_id = self.event.context["headers"]["canvas-logged-in-user-id"]
        request_json = self.request.json()
        patient_message = self.create_message_to_patient(
            {"questionnaires": [request_json]},
            staff_id=staff_id,
            patient_id=patient_id,
        )
        return [
            patient_message.create_and_send(),
            Response(status_code=HTTPStatus.CREATED),
        ]

    @api.post("/provider-view/patient/<patient_id>/unassign")
    def unassign_form(self) -> list[Response | Effect]:
        """Remove a questionnaire assignment from a patient."""
        patient_id = self.request.path_params["patient_id"]
        request_json = self.request.json()
        QuestionnaireAssignmentService.unassign(
            patient_id, request_json["questionnaire_name"]
        )
        return [Response(status_code=HTTPStatus.CREATED)]


class PatientQuestionnaireAPI(SimpleAPI):
    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Restrict patient endpoints to the logged-in patient's own data."""
        return all(
            [
                self.request.path_params.get("patient_id"),
                self.request.path_params["patient_id"]
                == credentials.logged_in_user["id"],
                credentials.logged_in_user["type"] == "Patient",
            ]
        )

    @api.get("/patient-view/patient/<patient_id>")
    def get_patient_forms(self) -> list[Response | Effect]:
        """Render the patient view of assigned questionnaires."""
        patient_id = self.request.path_params["patient_id"]
        if not Patient.objects.filter(id=patient_id).exists():
            return [
                HTMLResponse(
                    render_to_string("templates/404.html"),
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        grouped = QuestionnaireAssignmentService.list_grouped(patient_id)
        return [
            HTMLResponse(
                render_to_string(
                    "templates/patient_view_questionnaires.html",
                    context={
                        "pending_items": grouped["pending_items"],
                        "completed_groups": grouped["completed_groups"],
                        "patient_id": patient_id,
                    },
                ),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/patient-view/patient/<patient_id>/questionnaire/<questionnaire_name>")
    def get_questionnaire_questions(self) -> list[Response | Effect]:
        """Render a questionnaire form for fill-out OR a read-only review.

        Routing:
            outstanding row exists           → fill-out template
            only completed history exists    → review template
            neither questionnaire nor history → 404

        An outstanding row takes precedence over history so that a
        reassignment (new pending row alongside completed rows) routes to
        fill-out, not review.
        """
        patient_id = self.request.path_params["patient_id"]
        questionnaire_name = self.request.path_params["questionnaire_name"]

        questionnaire = Questionnaire.objects.filter(
            name=questionnaire_name, status="AC"
        ).first()
        if questionnaire is None:
            return [
                HTMLResponse(
                    render_to_string("templates/404.html"),
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        questionnaire_data = {
            "id": str(questionnaire.id),
            "name": questionnaire.name,
            "questions": [
                {
                    "id": question.dbid,
                    "question_text": question.name,
                    "question_type": question.response_option_set.type,
                    "options": [
                        {"id": option.dbid, "name": option.name}
                        for option in question.response_option_set.options.all()
                    ],
                }
                for question in questionnaire.questions.order_by("dbid")
                .select_related("response_option_set")
                .prefetch_related("response_option_set__options")
            ],
        }

        outstanding = QuestionnaireAssignmentService.get_one(
            patient_id, questionnaire_name
        )
        if outstanding is not None:
            return [
                HTMLResponse(
                    render_to_string(
                        "templates/patient_fill_out_questionnaire.html",
                        context={
                            "questionnaire": questionnaire_data,
                            "due_date": outstanding["due_date"],
                            "patient_id": patient_id,
                            "assigning_provider_id": outstanding["assigning_provider"]["key"],
                        },
                    ),
                    status_code=HTTPStatus.OK,
                )
            ]

        completed_entries = QuestionnaireAssignmentService.get_completed_entries(
            patient_id, questionnaire_name
        )
        if not completed_entries:
            return [
                HTMLResponse(
                    render_to_string("templates/404.html"),
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]

        # Build one submission per completed entry, each with a qid -> display
        # list. The template renders the latest by default and swaps client-side
        # when the patient picks a different submission.
        def build_answer_display(question: dict, saved: dict | None) -> list[str]:
            if saved is None:
                return []
            raw = saved.get("answer")
            qtype = question["question_type"]
            options_by_id = {o["id"]: o["name"] for o in question["options"]}
            if qtype in ("TXT", "INT"):
                return [str(raw)] if raw not in (None, "") else []
            if qtype == "SING":
                return [options_by_id[raw]] if raw in options_by_id else []
            if qtype == "MULT" and isinstance(raw, list):
                return [options_by_id[o] for o in raw if o in options_by_id]
            return []

        submissions = []
        for entry in completed_entries:
            entry_answers = {a["question_id"]: a for a in entry.get("submitted_answers", [])}
            answers_by_qid = {}
            for q in questionnaire_data["questions"]:
                saved = entry_answers.get(q["id"]) or entry_answers.get(str(q["id"]))
                answers_by_qid[str(q["id"])] = build_answer_display(q, saved)
            submissions.append({
                "completed_date": entry["completed_date"],
                "answers_by_qid": answers_by_qid,
            })

        latest_answers = submissions[0]["answers_by_qid"] if submissions else {}
        review_questions = [
            {
                "question_id": str(q["id"]),
                "question_text": q["question_text"],
                "answer_display": latest_answers.get(str(q["id"]), []),
            }
            for q in questionnaire_data["questions"]
        ]
        return [
            HTMLResponse(
                render_to_string(
                    "templates/patient_review_questionnaire.html",
                    context={
                        "questionnaire_name": questionnaire.name,
                        "completed_date": submissions[0]["completed_date"] if submissions else "",
                        "questions": review_questions,
                        "submissions": submissions,
                        "submission_count": len(submissions),
                        "patient_id": patient_id,
                    },
                ),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/patient-view/patient/<patient_id>/questionnaire/submit")
    def submit_questionnaire(self) -> list[Response | Effect]:
        """Submit a completed questionnaire, create a note, mark the assignment completed.

        Security: the assigning provider and the questionnaire identity are
        both derived from server-side state, not the request body.

        - ``assigning_provider`` comes from the outstanding assignment row.
          The body's ``assigning_staff_id`` (still sent by the frontend for
          back-compat) is ignored.
        - ``questionnaire_id`` is resolved from the active Questionnaire
          matching the server-validated ``questionnaire_name``. The body's
          ``questionnaire_id`` is ignored — otherwise a patient could pair
          their own outstanding ``questionnaire_name`` with an unrelated
          ``questionnaire_id`` and produce a ``QuestionnaireCommand``
          structured under the wrong questionnaire.

        Order of operations: every Effect is built first, then ``mark_completed``
        is the last thing this function does before returning. Effect
        constructors validate their inputs (e.g. pydantic on NoteEffect), so if
        the data is bad the function raises *before* the assignment is stamped
        as completed. This makes the function transactional from the caller's
        perspective — either the row gets stamped AND a complete set of valid
        effects is returned, or neither.

        (Note: this does not cover failures that happen when the plugin runtime
        applies the returned effects server-side. For that, completion would
        need to be deferred to a NoteStateChangeEvent handler.)
        """
        patient_id = self.request.path_params["patient_id"]
        questionnaire_answers = self.request.json()
        questionnaire_name = questionnaire_answers["questionnaire_name"]

        # Find the outstanding assignment row server-side. This is the
        # trusted source for the assigning provider — never the request body.
        outstanding_row = QuestionnaireAssignmentService.get_outstanding_row(
            patient_id, questionnaire_name
        )
        if outstanding_row is None:
            return [
                JSONResponse(
                    {"error": "No pending assignment for this questionnaire"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]
        if outstanding_row.assigning_provider is None:
            return [
                JSONResponse(
                    {"error": "Assignment is missing an assigning provider"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        # Resolve questionnaire id from the validated name. Name is the
        # canonical handle (ids change across published versions); the
        # body's questionnaire_id is ignored.
        questionnaire = Questionnaire.objects.filter(
            name=questionnaire_name, status="AC"
        ).first()
        if questionnaire is None:
            return [
                JSONResponse(
                    {"error": "No active questionnaire found for this assignment"},
                    status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                )
            ]

        staff = outstanding_row.assigning_provider

        # Prefer the operator-configured "Patient Portal Form" note type. If
        # it isn't set up, fall back to a Data Import note. The two paths
        # behave very differently: Patient Portal Form notes accept multiple
        # commands across the day (so we bundle all of a patient's same-day
        # submissions into one note); DATA notes are one-shot writes (verified
        # empirically), so each submission gets its own note.
        note_type_id = (
            NoteType.objects.filter(name="Patient Portal Form", is_active=True)
            .values_list("id", flat=True)
            .first()
        )
        bundle = note_type_id is not None
        if not bundle:
            note_type_id = (
                NoteType.objects.filter(category=NoteTypeCategories.DATA)
                .order_by("-dbid")
                .values_list("id", flat=True)
                .first()
            )

        today = arrow.now().date()
        note_id_assignment, reuse_existing_note = DailyNoteService.resolve(
            patient_id, today, bundle=bundle
        )

        note_effect = None
        if not reuse_existing_note:
            note_title = (
                f"Patient portal forms - {today.isoformat()}"
                if bundle
                else f"{questionnaire_name} submitted via patient app"
            )
            note_effect = NoteEffect(
                note_type_id=note_type_id,
                datetime_of_service=arrow.now().datetime,
                patient_id=patient_id,
                practice_location_id=str(staff.primary_practice_location.id),
                provider_id=str(staff.id),
                instance_id=note_id_assignment,
                title=note_title,
            )

        ques_command = QuestionnaireCommand(
            note_uuid=str(note_id_assignment),
            questionnaire_id=str(questionnaire.id),
            command_uuid=str(uuid.uuid4()),
        )

        # Look up answers by question ID
        questions_answers_dict = {
            q["question_id"]: {"question_type": q["question_type"], "answer": q["answer"]}
            for q in questionnaire_answers["questions_and_answers"]
        }

        for question in ques_command.questions:
            answer = questions_answers_dict.get(question.id, {}).get("answer")
            if answer:
                if question.type == ResponseOption.TYPE_TEXT:
                    question.add_response(text=answer)
                elif question.type == ResponseOption.TYPE_RADIO:
                    answered_option_list = [o for o in question.options if o.dbid == answer]
                    if answered_option_list:
                        question.add_response(option=answered_option_list[0])
                elif question.type == ResponseOption.TYPE_CHECKBOX:
                    answered_option_list = [o for o in question.options if o.dbid in answer]
                    for a in answered_option_list:
                        question.add_response(option=a, selected=True)

        # Build every effect BEFORE the DB write so any constructor-time
        # validation failure short-circuits the function without ever
        # stamping the assignment as completed. NoteEffect is only created
        # when we're not reusing an existing bundled note for the day.
        effects: list[Response | Effect] = []
        if note_effect is not None:
            effects.append(note_effect.create())
        effects.extend([
            ques_command.originate(),
            ques_command.edit(),
            ques_command.commit(),
        ])

        effects.append(
            JSONResponse(
                {"status": "ok"},
                status_code=HTTPStatus.OK,
            )
        )

        # Stamp the assignment as completed only after every effect has been
        # built without error. The patient's answers are snapshotted onto the
        # row so the review template can re-render them later, independent
        # of any questionnaire-version changes. If a parallel submission
        # stamped it first, mark_completed returns 0 and we short-circuit so
        # we don't emit a duplicate note.
        completed = QuestionnaireAssignmentService.mark_completed(
            patient_id,
            questionnaire_name,
            submitted_answers=questionnaire_answers.get("questions_and_answers", []),
        )
        if not completed:
            return []

        return effects
