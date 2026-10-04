"""What the patient portal is offered when a questionnaire step is live."""

import json

from medication_followup_protocol.handlers.portal_forms import PortalForms
from medication_followup_protocol.models import EnrollmentStatus, StepKind, StepStatus
from tests.conftest import make_event

QUESTIONNAIRE_ID = "b21c5f0a-3d84-4c19-9f77-2e6a8c4d5b31"


def forms_for(patient):
    """Ask the plugin which forms this patient's portal should show."""
    event = make_event(
        "PATIENT_PORTAL__GET_FORMS", context={"patient": {"id": patient.id}}
    )
    return PortalForms(event).compute()


def test_the_portal_offers_the_questionnaire_of_a_live_step(enrolment, add_step, patient):
    """Covers scenario: AC11, the portal offers the questionnaire of a live step. Covers criterion: AC11."""
    step = add_step(kind=StepKind.QUESTIONNAIRE, questionnaire_id=QUESTIONNAIRE_ID)
    step.status = StepStatus.FIRED
    step.save()

    effects = forms_for(patient)

    assert len(effects) == 1
    assert json.loads(effects[0].payload)["data"]["questionnaire_id"] == QUESTIONNAIRE_ID


def test_a_step_that_has_not_gone_live_is_not_offered(enrolment, add_step, patient):
    """Covers criterion: AC11."""
    add_step(kind=StepKind.QUESTIONNAIRE, questionnaire_id=QUESTIONNAIRE_ID)

    assert forms_for(patient) == []


def test_an_already_answered_step_is_not_offered_again(enrolment, add_step, patient):
    """Covers criterion: AC11."""
    step = add_step(kind=StepKind.QUESTIONNAIRE, questionnaire_id=QUESTIONNAIRE_ID)
    step.status = StepStatus.FIRED
    step.interview_id = "an-interview"
    step.save()

    assert forms_for(patient) == []


def test_a_stopped_enrolment_offers_nothing(enrolment, add_step, patient):
    """Covers criterion: AC11."""
    step = add_step(kind=StepKind.QUESTIONNAIRE, questionnaire_id=QUESTIONNAIRE_ID)
    step.status = StepStatus.FIRED
    step.save()
    enrolment.status = EnrollmentStatus.STOPPED
    enrolment.save()

    assert forms_for(patient) == []
