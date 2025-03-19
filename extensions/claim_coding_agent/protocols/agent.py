from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data import Command, Assessment, BillingLineItem
from canvas_sdk.effects.billing_line_item import (
    AddBillingLineItem,
    RemoveBillingLineItem,
    UpdateBillingLineItem,
)

from llms.llm_openai import LlmOpenai

from logger import log

class ClaimCodingAgent(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PERFORM_COMMAND__POST_ORIGINATE),
    ]
    
    def compute(self) -> list[Effect]:
        command = Command.objects.get(id=self.target)

        llm = LlmOpenai(self.secrets['OPENAI_SECRET_KEY'], 'gpt-4o')
        llm
        log.info(f'Got perform command {command}')
        assessments = (Assessment.objects.filter(note_id=command.note.dbid)
                       .values_list("id", flat=True))
        assessment_str_ids = [str(a) for a in assessments]
        log.info(f'Got note assessments: {assessment_str_ids}')
        charge_code = AddBillingLineItem(
            note_id=str(command.note.id),
            cpt="99213",
            units=2,
            assessment_ids=assessment_str_ids,
            modifiers=[
                {"code": "25", "system": "http://www.ama-assn.org/go/cpt"},
                {"code": "59", "system": "http://www.ama-assn.org/go/cpt"},
            ],
        )
        return [charge_code.apply()]


class ExampleFromMichela(BaseProtocol):
    RESPONDS_TO = [
        EventType.Name(EventType.PERFORM_COMMAND__POST_ORIGINATE),
        EventType.Name(EventType.PERFORM_COMMAND__POST_COMMIT),
        EventType.Name(EventType.PERFORM_COMMAND__POST_ENTER_IN_ERROR),
    ]

    def create_billing_line_item(self) -> list[Effect]:
        command_id = self.target
        command = Command.objects.get(id=command_id)
        note = command.note

        assessments = [
            str(i)
            for i in Assessment.objects.filter(note_id=note.dbid).values_list(
                "id", flat=True
            )
        ]

        b = AddBillingLineItem(
            note_id=str(note.id),
            cpt="99213",
            units=2,
            assessment_ids=assessments,
            modifiers=[
                {"code": "25", "system": "http://www.ama-assn.org/go/cpt"},
                {"code": "59", "system": "http://www.ama-assn.org/go/cpt"},
            ],
        )
        return [b.apply()]

    def update_billing_line_item(self) -> list[Effect]:
        command_id = self.target
        command = Command.objects.get(id=command_id)
        note = command.note

        cpt = command.data["perform"]["value"]

        b_ids = BillingLineItem.objects.filter(cpt="99213", note=note).values_list(
            "id", flat=True
        )
        assessment = Assessment.objects.filter(note_id=note.dbid).first()
        updates = [
            UpdateBillingLineItem(
                billing_line_item_id=str(b_id),
                cpt=cpt,
                units=1,
                assessment_ids=[str(assessment.id)],
                modifiers=[{"code": "47", "system": "http://www.ama-assn.org/go/cpt"}],
            )
            for b_id in b_ids
        ]
        return [update.apply() for update in updates]

    def remove_billing_line_item(self) -> list[Effect]:
        command_id = self.target
        command = Command.objects.get(id=command_id)

        cpt = command.data["perform"]["value"]
        note_id = command.note.dbid
        b_ids = BillingLineItem.objects.filter(cpt=cpt, note_id=note_id).values_list(
            "id", flat=True
        )
        return [
            RemoveBillingLineItem(billing_line_item_id=str(b_id)).apply()
            for b_id in b_ids
        ]

    def compute(self) -> list[Effect]:
        if self.event.type == EventType.PERFORM_COMMAND__POST_ORIGINATE:
            return self.create_billing_line_item()
        if self.event.type == EventType.PERFORM_COMMAND__POST_COMMIT:
            return self.update_billing_line_item()
        if self.event.type == EventType.PERFORM_COMMAND__POST_ENTER_IN_ERROR:
            return self.remove_billing_line_item()