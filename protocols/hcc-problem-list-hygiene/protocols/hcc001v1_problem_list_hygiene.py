"""HCC problem-list hygiene protocol.

Flags active HCC conditions on a patient's problem list that have not been
assessed within the last year (or the per-patient override cycle).
"""

from functools import cached_property

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.condition import Condition
from canvas_sdk.v1.data.protocol_override import ProtocolOverride
from canvas_sdk.value_set.hcc2018 import HCCConditions


class Hcc001v1(ClinicalQualityMeasure):
    """Surface unassessed active HCC conditions for action."""

    class Meta:
        title = "Problem List Hygiene"
        version = "2019-02-12v1"
        description = "All patients with active condition not assessed within the last year."
        information = (
            "https://canvas-medical.help.usepylon.com/articles/"
            "9943822292-protocol-problem-list-hygiene"
        )
        identifiers = ["HCC001v1"]
        types = ["HCC"]
        authors = ["Canvas Medical Team"]
        references = [
            "Canvas Medical HCC, "
            "https://canvas-medical.help.usepylon.com/articles/"
            "9943822292-protocol-problem-list-hygiene"
        ]

    PROTOCOL_KEY = "HCC001v1"

    RESPONDS_TO = [
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_CREATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_UPDATED),
        EventType.Name(EventType.PROTOCOL_OVERRIDE_DELETED),
    ]

    @cached_property
    def patient_id(self) -> str:
        """Resolve the patient id from the triggering event."""
        return self.patient_id_from_target()

    @cached_property
    def protocol_override(self) -> ProtocolOverride | None:
        """Return the active adjustment override for this protocol, if any."""
        return (
            ProtocolOverride.objects.for_patient(self.patient_id)
            .committed()
            .filter(protocol_key=self.PROTOCOL_KEY, is_adjustment=True, status="active")
            .order_by("-modified")
            .first()
        )

    @property
    def timeframe(self) -> Timeframe:
        """One-year window ending at ``self.now``, narrowed/widened by any override."""
        override = self.protocol_override
        end = self.now
        if override and override.cycle_in_days:
            start = end.shift(days=-override.cycle_in_days)
        else:
            start = end.shift(years=-1)
        return Timeframe(start=start, end=end)

    @cached_property
    def active_hcc_conditions(self) -> list[Condition]:
        """All active HCC conditions on the patient's problem list."""
        return list(
            Condition.objects.for_patient(self.patient_id).find(HCCConditions).active()
        )

    def _last_assessed(self, condition: Condition) -> arrow.Arrow:
        """The most recent assessment time for ``condition``, falling back to its modified/created."""
        last_assessment = (
            condition.assessments.order_by("-created").values_list("created", flat=True).first()
        )
        if last_assessment is not None:
            return arrow.get(last_assessment)
        return arrow.get(condition.modified or condition.created)

    def _icd10_code(self, condition: Condition) -> str | None:
        """Return the first ICD-10 code attached to ``condition``, if any."""
        coding = condition.codings.filter(system="ICD-10").first()
        return coding.code if coding else None

    @cached_property
    def hcc_assessments(self) -> list[dict]:
        """Per-condition ICD-10 + last-assessed pairs for every active HCC condition."""
        items: list[dict] = []
        for condition in self.active_hcc_conditions:
            code = self._icd10_code(condition)
            if not code:
                continue
            items.append({"ICD10": code, "date": self._last_assessed(condition)})
        return items

    @cached_property
    def overdue_assessments(self) -> list[dict]:
        """HCC conditions whose last assessment falls before the timeframe start."""
        start = self.timeframe.start
        return [item for item in self.hcc_assessments if item["date"] < start]

    def _build_due_card(self) -> ProtocolCard:
        """Build a DUE protocol card listing each overdue HCC condition."""
        narratives = [
            (
                f"{HCCConditions.label_icd10_for(item['ICD10'])} ({item['ICD10']}) is a "
                f"significant condition which should be assessed annually. "
                f"The condition was last assessed on {item['date'].format('M/D/YY')} and "
                f"carries a RAF value of {HCCConditions.raf_for(item['ICD10'])}"
            )
            for item in self.overdue_assessments
        ]

        card = ProtocolCard(
            patient_id=self.patient_id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=" ".join(narratives),
            status=ProtocolCard.Status.DUE,
            due_in=-1,
        )
        card.add_recommendation(
            title="Assess, update or resolve conditions as clinically appropriate",
            button="Assess",
            command="assess",
        )
        card.add_recommendation(
            title="Resolve conditions as clinically appropriate",
            button="Assess",
            command="resolveCondition",
        )
        return card

    def _build_satisfied_card(self) -> ProtocolCard:
        """Build a SATISFIED protocol card when no HCC conditions are overdue."""
        duration = self.timeframe.duration
        # ``humanize`` formats a duration like "12 months" or "6 months".
        humanized = self.now.shift(days=-duration).humanize(
            other=self.now, granularity="month", only_distance=True
        )
        narrative = (
            f"All Significant Condition have been assessed within the last {humanized}."
        )

        # The earliest assessment date drives how soon the next one is due.
        next_due_date = min(item["date"] for item in self.hcc_assessments).shift(days=duration)
        due_in = (next_due_date - self.now).days

        return ProtocolCard(
            patient_id=self.patient_id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=narrative,
            status=ProtocolCard.Status.SATISFIED,
            due_in=due_in,
        )

    def _build_not_applicable_card(self) -> ProtocolCard:
        """Build a NOT_APPLICABLE card when the patient has no active HCC conditions."""
        return ProtocolCard(
            patient_id=self.patient_id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            status=ProtocolCard.Status.NOT_APPLICABLE,
        )

    def compute(self) -> list[Effect]:
        """Return a single ProtocolCard effect describing the patient's HCC status."""
        if not self.hcc_assessments:
            return [self._build_not_applicable_card().apply()]

        if self.overdue_assessments:
            return [self._build_due_card().apply()]

        return [self._build_satisfied_card().apply()]


__exports__ = ("Hcc001v1",)
