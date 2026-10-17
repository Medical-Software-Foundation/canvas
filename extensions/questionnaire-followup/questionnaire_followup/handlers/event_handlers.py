"""Present the long-form questionnaire in the patient portal after a screen fires a rule.

Canvas asks this handler which forms a patient should see every time the portal
loads a page, so the answer is recomputed from the chart each time rather than
stored: a form is returned while it is still owed and stops being returned as
soon as it is answered. There is no queue to drain and nothing to backfill for
patients who were screened before the plugin was installed.

The pairings themselves - which short instrument leads to which long one, what
a screen has to score to count, and how long to leave a patient alone afterwards
- are admin-configured (see ``services.config_store``), not written here. A rule
fires on a score at or above a cutoff, at or below one, inside a band, or on the
patient having completed the short form at all.

The decision itself lives in ``services.decision``, which the admin diagnostic
calls too - so what the diagnostic explains is what this handler actually did.
That module also carries the query budget this runs on: batched across rules
rather than repeated per rule, one query for a patient with no recent screen.
"""

from datetime import UTC, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_portal.form_result import FormResult
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from logger import log

from questionnaire_followup.services.config_store import active_rules, load_config
from questionnaire_followup.services.decision import editable_note_ids, owed_forms


class PortalFollowUpForms(BaseHandler):
    """Assign the paired follow-up questionnaire to a patient in the portal."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_PORTAL__GET_FORMS)

    def compute(self) -> list[Effect]:
        """Return one FormResult per follow-up this patient currently owes."""
        patient_id = self.event.target.id
        if not patient_id:
            return []

        rules = active_rules(load_config())
        if not rules:
            return []

        now = datetime.now(UTC)
        owed = owed_forms(rules, patient_id, now)
        if not owed:
            return []

        note_ids = editable_note_ids({screen.note_id for _, screen, _ in owed})
        effects: list[Effect] = []
        assigned: set[str] = set()
        presented: list[str] = []

        for rule, screen, followup in owed:
            questionnaire_id = str(followup.id)
            # Two rules can name the same long instrument (a broad screener and a
            # targeted one both leading to the PHQ-9). The patient fills it once.
            if questionnaire_id in assigned:
                continue
            assigned.add(questionnaire_id)
            if not followup.can_originate_in_charting:
                # It will still be shown, but committing the response into a note
                # needs this flag set on the questionnaire in Canvas.
                log.warning(
                    f"questionnaire_followup: '{followup.name}' (code={rule['followup_code']}) "
                    "is not enabled to originate in charting; the portal response may "
                    "not commit into a note"
                )
            note_id = note_ids.get(screen.note_id)
            effects.append(
                FormResult(
                    questionnaire_id=questionnaire_id,
                    # Without this the response is only an Interview and never
                    # reaches the chart, so the care team never sees the answer
                    # they asked the patient for.
                    create_command=True,
                    note_id=note_id,
                ).apply()
            )
            presented.append(
                f"'{rule['name']}' -> {followup.name} ({rule['followup_code']}) "
                + (f"into note {note_id}" if note_id else "into a new note")
            )

        # One line, only when something was actually presented. The handler runs on
        # every portal page load and almost always returns nothing, so logging the
        # quiet path would bury this. Reaching here guarantees at least one form: the
        # early return above covers the empty case, and the first rule is never
        # deduplicated. Deliberately no score or answer - which pairing fired is
        # enough to debug, and the score is clinical detail that does not belong in
        # a log aggregator.
        log.info(
            f"questionnaire_followup: presenting {len(presented)} form(s) in the portal "
            f"to patient {patient_id}: " + "; ".join(presented)
        )
        return effects
