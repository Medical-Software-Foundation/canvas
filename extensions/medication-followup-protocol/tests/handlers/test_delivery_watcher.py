"""What happens to a step whose message never arrived."""

from canvas_sdk.v1.data import Message as MessageModel
from canvas_sdk.v1.data.message import MessageTransmission

from medication_followup_protocol.handlers.delivery_watcher import DeliveryWatcher
from medication_followup_protocol.models import StepKind, StepStatus
from tests.conftest import make_event


def transmission_for(message, failed: bool) -> MessageTransmission:
    """A transmission record for a message, delivered or failed."""
    return MessageTransmission.objects.create(
        message=message,
        delivered=not failed,
        failed=failed,
        contact_point_system="sms",
        contact_point_value="+15555550123",
    )


def watch(transmission):
    """Drive the watcher over one transmission update."""
    event = make_event("MESSAGE_TRANSMISSION_UPDATED", target=str(transmission.id))
    return DeliveryWatcher(event).compute()


def test_a_message_that_fails_to_deliver_is_recorded_against_its_step(enrolment, add_step):
    """Covers scenario: AC13, a message that fails to deliver is recorded against its step. Covers criterion: AC13."""
    message = MessageModel.objects.create(content="Starting a GLP-1, what to expect")
    step = add_step(kind=StepKind.MESSAGE, message_body="Starting a GLP-1, what to expect")
    step.status = StepStatus.FIRED
    step.message_id = str(message.id)
    step.save()

    assert watch(transmission_for(message, failed=True)) == []

    step.refresh_from_db()
    assert step.status == StepStatus.FAILED
    assert step.failure_reason


def test_a_delivered_message_leaves_its_step_alone(enrolment, add_step):
    """Covers criterion: AC13."""
    message = MessageModel.objects.create(content="Starting a GLP-1, what to expect")
    step = add_step(kind=StepKind.MESSAGE, message_body="Starting a GLP-1, what to expect")
    step.status = StepStatus.FIRED
    step.message_id = str(message.id)
    step.save()

    watch(transmission_for(message, failed=False))

    step.refresh_from_db()
    assert step.status == StepStatus.FIRED
