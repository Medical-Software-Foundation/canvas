"""Link assessments to billing line items after assess/diagnose commands are committed."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.billing_line_item import UpdateBillingLineItem
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data import Assessment, BillingLineItem, Command
from logger import log

from group_therapy.services.config_store import billing_cpt_codes, load_config


class BillingAssessmentLinker(BaseProtocol):
    """React to assess/diagnose post-commit to link the assessment to the group
    therapy billing line item (the CPT configured for any template)."""

    RESPONDS_TO = [
        EventType.Name(EventType.ASSESS_COMMAND__POST_COMMIT),
        EventType.Name(EventType.DIAGNOSE_COMMAND__POST_COMMIT),
    ]

    def compute(self) -> list[Effect]:
        command = Command.objects.get(id=self.target)
        note = command.note

        assessments = list(Assessment.objects.filter(note_id=note.dbid))
        if not assessments:
            log.info(f"BillingAssessmentLinker: no assessment found on note {note.id}")
            return []

        cpt_codes = billing_cpt_codes(load_config())
        bli = BillingLineItem.objects.filter(note=note, cpt__in=cpt_codes).first()
        if not bli:
            log.info(
                f"BillingAssessmentLinker: no group therapy billing line item "
                f"({', '.join(cpt_codes) or 'none configured'}) on note {note.id}"
            )
            return []

        assessment_ids = [str(a.id) for a in assessments]
        log.info(
            f"BillingAssessmentLinker: linking {len(assessment_ids)} assessment(s) "
            f"to billing line item {bli.id} on note {note.id}"
        )
        return [
            UpdateBillingLineItem(
                billing_line_item_id=str(bli.id),
                assessment_ids=assessment_ids,
            ).apply()
        ]
