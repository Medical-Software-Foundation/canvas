import datetime
from http import HTTPStatus
from uuid import uuid4

import arrow
from django.db.models import Q

from canvas_sdk.commands.commands.questionnaire import QuestionnaireCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert
from canvas_sdk.effects.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import api
from canvas_sdk.handlers.simple_api.api import SimpleAPI
from canvas_sdk.handlers.simple_api.security import (
    StaffSessionAuthMixin,
)
from canvas_sdk.templates.utils import render_to_string
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.note import Note, NoteStates, NoteType, NoteTypeCategories
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.questionnaire import Questionnaire
from canvas_sdk.v1.data.staff import Staff
from logger import log


class CcmatApi(StaffSessionAuthMixin, SimpleAPI):
    """API for the Chronic Care Management Activity Tracker application."""

    BASE_PATH = "/plugin-io/api/chronic_care_management_activity_tracker"

    NOTE_TYPE_CODE = "chronic_care_management_note"

    QUESTIONNAIRE_CODE = "ccm_session_questionnaire"

    BANNER_TEMPLATE_KEY = "ccm_monthly_banner"

    ACTIVITIES = (
        ("Medication review", "medication_review"),
        ("Care plan update", "care_plan_update"),
        ("Provider coordination", "provider_coordination"),
        ("Patient or caregiver contact", "patient_or_caregiver_contact"),
        ("Symptom or condition monitoring", "symptom_or_condition_monitoring"),
        ("Referral or transition management", "referral_or_transition_management"),
        ("Other care management", "other_care_management"),
    )

    # Serve templated HTML
    @api.get("/<patient_id>/app")
    def index(self) -> list[Response | Effect]:
        """Serve the main dashboard page."""
        logged_in_staff = Staff.objects.get(id=self.request.headers["canvas-logged-in-user-id"])

        patient = self._get_patient()

        context = {
            "staff_name": logged_in_staff.full_name,
            "patient_name": patient.preferred_full_name if patient else "N/A",
            "current_date": arrow.utcnow().format("YYYY-MM-DD"),
            "activities": list(self.ACTIVITIES),
        }

        return [
            HTMLResponse(
                render_to_string("templates/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    # Serve the contents of a css file
    @api.get("/<patient_id>/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the contents of a CSS file."""
        return [
            Response(
                render_to_string("static/css/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    # Serve the contents of a js file
    @api.get("/<patient_id>/scripts.js")
    def get_scripts(self) -> list[Response | Effect]:
        """Serve the contents of a JavaScript file."""
        return [
            Response(
                render_to_string("static/js/scripts.js", {"patient_id": self._patient_id}).encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
            )
        ]

    @api.post("/<patient_id>/sessions")
    def save_session(self) -> list[Response | Effect]:
        """Handle saving a session (stub implementation)."""
        try:
            staff = self._get_staff()
            patient = self._get_patient()
            note_id = str(uuid4())

            now = datetime.datetime.utcnow()

            note = NoteEffect(
                instance_id=note_id,
                note_type_id=self._get_chronic_note_type_id(),
                patient_id=patient.id,
                provider_id=staff.id,
                datetime_of_service=now,
                practice_location_id=self._get_practice_location_id(patient, staff),
                title="Chronic Care Management Note",
            )

            questionnaire_id = self._get_questionnaire_id()
            questionnaire_command = QuestionnaireCommand(
                note_uuid=note_id,
                command_uuid=str(uuid4()),
                questionnaire_id=str(questionnaire_id),
            )

            json_data = self.request.json()

            activity_codes = list(json_data["activities"])
            activities = [
                desc for desc, code in self.ACTIVITIES if code.strip().lower() in activity_codes
            ]

            time_logs = list(json_data["timeLogs"])
            session_logs = []
            time_spent = 0
            for i in range(0, len(time_logs) - 1, 2):
                start = time_logs[i]['timestamp']
                end = time_logs[i + 1]['timestamp']
                start_formatted = arrow.get(start).format("YYYY-MM-DD HH:mm:ss ZZZ")
                end_formatted = arrow.get(end).format("YYYY-MM-DD HH:mm:ss ZZZ")
                session_logs.append(f"{start_formatted} - {end_formatted}")
                time_spent += (arrow.get(end) - arrow.get(start)).seconds

            # Format current session time as hh:mm:ss
            hours = time_spent // 3600
            minutes = (time_spent % 3600) // 60
            seconds = time_spent % 60
            session_duration_formatted = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            notes = str(json_data["notes"]).strip()

            # Calculate cumulative month time in seconds
            previous_month_seconds = self._get_this_month_seconds(patient)
            total_month_seconds = previous_month_seconds + time_spent

            # Format cumulative month time as hh:mm:ss
            month_hours = total_month_seconds // 3600
            month_minutes = (total_month_seconds % 3600) // 60
            month_seconds = total_month_seconds % 60
            total_month_time_formatted = f"{month_hours:02d}:{month_minutes:02d}:{month_seconds:02d}"

            for question in questionnaire_command.questions:
                if question.coding.get("code") == "ccm_session_pt_name_question":
                    question.add_response(text=patient.preferred_full_name)
                elif question.coding.get("code") == "ccm_session_staff_name_question":
                    question.add_response(text=staff.full_name)
                elif question.coding.get("code") == "ccm_session_activities_question":
                    question.add_response(text=", ".join(activities))
                elif question.coding.get("code") == "ccm_session_notes_question":
                    question.add_response(text=notes)
                elif question.coding.get("code") == "ccm_session_time_log_question":
                    question.add_response(text=", ".join(session_logs))
                elif question.coding.get("code") == "ccm_session_duration_question":
                    question.add_response(text=session_duration_formatted)
                elif question.coding.get("code") == "ccm_month_minutes_question":
                    question.add_response(text=total_month_time_formatted)

            # Create banner alert with updated cumulative time
            banner = AddBannerAlert(
                key=self.BANNER_TEMPLATE_KEY,
                narrative=f"Chronic Care Management Recorded This Month: {total_month_time_formatted}",
                placement=[AddBannerAlert.Placement.CHART, AddBannerAlert.Placement.PROFILE],
                intent=AddBannerAlert.Intent.INFO,
                patient_id=patient.id,
            )

            return [
                JSONResponse(
                    {
                        "message": f"Creating Chronic Care Management Note for {patient.id}.",
                        "note_id": note_id,
                    },
                    status_code=HTTPStatus.OK,
                ),
                note.create(),
                questionnaire_command.originate(),
                questionnaire_command.edit(),
                questionnaire_command.commit(),
                banner.apply(),
            ]
        except Patient.DoesNotExist:
            log.error("Patient does not exist.")
            return [
                JSONResponse(
                    {"error": "Patient does not exist."}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        except Exception as e:
            log.error(f"Error saving session: {e}")
            return [
                JSONResponse(
                    {"error": "Failed to save session."},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]

    @property
    def _patient_id(self):
        return self.request.path_params["patient_id"]

    def _get_staff(self) -> Staff:
        return Staff.objects.get(id=self.request.headers["canvas-logged-in-user-id"])

    def _get_patient(self) -> Patient:
        log.info(f"Fetching patient with ID: {self._patient_id}")
        return Patient.objects.get(id=self._patient_id)

    def _get_chronic_note_type_id(self) -> str:
        return NoteType.objects.get(code=self.NOTE_TYPE_CODE, is_active=True).id

    def _get_last_visit_place_of_service(self, patient: Patient) -> str | None:
        return (
            Note.objects.values_list("place_of_service", flat=True)
            .filter(
                patient=patient,
                note_type_version__category=NoteTypeCategories.ENCOUNTER,
            )
            .exclude(
                Q(current_state__state=NoteStates.DELETED)
                | Q(current_state__state=NoteStates.CANCELLED)
            )
            .order_by("-datetime_of_service")
            .first()
        )

    def _get_patient_most_recent_practice_location(self, patient: Patient, staff: Staff) -> str:
        last_visit_place_of_service = self._get_last_visit_place_of_service(patient)
        return last_visit_place_of_service or staff.primary_practice_location.id

    def _get_practice_location_id(self, patient: Patient, staff: Staff):
        appointment_location_id = (
            Appointment.objects.filter(
                patient=patient,
                provider=staff,
            )
            .values_list("location__id", flat=True)
            .order_by("-start_time")
            .first()
        )

        return appointment_location_id or staff.primary_practice_location.id

    def _get_questionnaire_id(self) -> str:
        return Questionnaire.objects.values_list("id", flat=True).get(code=self.QUESTIONNAIRE_CODE, status="AC")

    def _get_this_month_seconds(self, patient: Patient) -> int:
        """Get the cumulative time in seconds from this month's sessions.

        Returns the most recent cumulative total, since each session already stores
        the running total for the month (not just that session's time).
        """
        questionnaire_id = self._get_questionnaire_id()
        this_month = arrow.utcnow().month
        this_year = arrow.utcnow().year

        # Get the most recent interview from this month
        most_recent_interview = (
            patient.interviews.filter(questionnaires__id=questionnaire_id)
            .filter(created__month=this_month, created__year=this_year)
            .filter(committer_id__isnull=False, entered_in_error_id__isnull=True)
            .order_by("-created")
            .first()
        )

        if not most_recent_interview:
            return 0

        # Get the cumulative month time from the most recent interview
        response_option_value = most_recent_interview.interview_responses.filter(
            question__code="ccm_month_minutes_question"
        ).values_list("response_option_value", flat=True).first()

        if not response_option_value:
            return 0

        time_str = response_option_value.strip()

        # Try to parse hh:mm:ss format
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 3:
                try:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    seconds = int(parts[2])
                    return hours * 3600 + minutes * 60 + seconds
                except ValueError:
                    return 0

        return 0
