from canvas_sdk.protocols.clinical_quality_measure import ClinicalQualityMeasure
from canvas_sdk.events import EventType
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.v1.data.detected_issue import DetectedIssue
from logger import log


class SurfaceNonvalidatedCodingGaps(ClinicalQualityMeasure):
    """

    """

    class Meta:
        title = "Validate Coding Gaps"
        identifiers = ["HCCCapturev1"]
        description = "..."
        information = "https://canvasmedical.com"
        references = ["None"]
        types = ["None"]
        authors = ["Canvas Medical"]

    RESPONDS_TO = [
        EventType.Name(EventType.DETECTED_ISSUE_CREATED),
        EventType.Name(EventType.DETECTED_ISSUE_UPDATED),
    ]

    def surface_non_validated_coding_gaps(self, patient, nonvalidated_coding_gaps):
        card = ProtocolCard(
            patient_id=patient.id,
            key="hcccapturev1",
            title="Coding Gaps",
            narrative="These codings gaps have not been validated.",
            status=ProtocolCard.Status.DUE,
            feedback_enabled=False,
        )

        for coding_gap in nonvalidated_coding_gaps:
            coding_gap_title_strings = []

            log.info(str(coding_gap.id))
            for evidence in coding_gap.evidence.all():
                log.info(f"{evidence.display} ({evidence.code})")
                coding_gap_title_strings.append(f"{evidence.display} ({evidence.code})")
            card.add_recommendation(
                title="\n".join(coding_gap_title_strings),
                button="Validate",
                command="validateCodingGap",
                context={"detected_issue_id": coding_gap.dbid},
            )

        return [card.apply()]

    def resolve_coding_gaps_protocol_card(self, patient):
        card = ProtocolCard(
            patient_id=patient.id,
            key="hcccapturev1",
            title="Coding Gaps",
            narrative="There are no non-validated coding gaps for this patient.",
            status=ProtocolCard.Status.SATISFIED,
            feedback_enabled=False,
        )

        return [card.apply()]


    def compute(self) -> list:
        detected_issue_from_the_event = DetectedIssue.objects.get(id=self.target)
        if detected_issue_from_the_event.code != "CODINGGAP":
            # This detected issue has no impact on the protocol card, so we
            # don't need to do any work.
            return []

        patient = detected_issue_from_the_event.patient
        all_of_that_patients_non_validated_detected_issues = patient.detected_issues.filter(status="registered", code="CODINGGAP")
        
        if all_of_that_patients_non_validated_detected_issues.count() > 0:
            return self.surface_non_validated_coding_gaps(patient, all_of_that_patients_non_validated_detected_issues)
        else:
            return self.resolve_coding_gaps_protocol_card(patient)
