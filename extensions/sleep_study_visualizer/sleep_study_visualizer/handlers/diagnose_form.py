from canvas_sdk.effects import Effect
from canvas_sdk.effects.command_metadata import (
    CommandMetadataCreateFormEffect,
    FormField,
    InputType,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class DiagnoseAdditionalFieldsHandler(BaseHandler):
    """Appends an 'Order home sleep study?' Yes/No field to every Diagnose command.

    Responds to COMMAND__FORM__GET_ADDITIONAL_FIELDS.  Fires for all command types
    so we filter to schema_key == 'diagnose' before returning anything.

    The stored key 'sleep_study_order' is read by DiagnoseOrderHandler on
    DIAGNOSE_COMMAND__POST_COMMIT to decide whether to create a task.
    """

    RESPONDS_TO = EventType.Name(EventType.COMMAND__FORM__GET_ADDITIONAL_FIELDS)

    def compute(self) -> list[Effect]:
        if self.event.context.get("schema_key") != "diagnose":
            return []

        form = CommandMetadataCreateFormEffect(
            command_uuid=self.event.target.id,
            form_fields=[
                FormField(
                    key="sleep_study_order",
                    label="Order home sleep study?",
                    type=InputType.SELECT,
                    options=["No", "Yes"],
                    value="No",
                ),
            ],
        )
        return [form.apply()]
