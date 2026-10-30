"""Attribution rules, a chain of responsibility.

Each rule looks at one incident and either claims it, by returning who it counts
against, or passes it along by returning None. No rule knows about any other
rule, and the order they run in is decided once in the composition root. Adding a
rule is a new class here plus one line there.

The chain always ends in a rule that claims everything, which is what makes every
total a definite number. Nothing is ever left waiting for a person to say what an
incident was.
"""

from typing import Any

from attendance_policy_tracker.core.config import KIND_NO_SHOW
from attendance_policy_tracker.core.contracts import CLINIC, PATIENT, Incident


def is_correctable(incident: Incident) -> bool:
    """True when a person may change who this incident counts against.

    This lives beside the rules rather than on the incident, because it is a
    statement about what the chain will do rather than a property of the data. It
    mirrors the two rules that sit ahead of the label. A missed visit is claimed
    by NoShowRule and a portal action by PatientPortalRule, so in both cases a
    label is written and no number moves. Offering a correction on either would
    be a control that appears to work and does nothing.

    Keep this in step with the rule order in the composition root. If a rule is
    ever inserted ahead of ClinicTagRule, it belongs here too.
    """
    if incident.kind == KIND_NO_SHOW:
        return False
    return not incident.by_patient_portal


class NoShowRule:
    """A patient who did not turn up counts against the patient, always.

    A no show is the one incident with no ambiguity about who caused it, so it
    is deliberately placed ahead of both the tag and the default. Tagging an
    appointment cannot excuse a no show.
    """

    def resolve(self, incident: Incident) -> str | None:
        """Claim no shows for the patient, pass everything else along."""
        if incident.kind == KIND_NO_SHOW:
            return PATIENT
        return None


class PatientPortalRule:
    """A visit the patient cancelled or moved themselves counts against them.

    This is knowable without any tag, because the person who performed the state
    change resolves to the patient rather than to a member of staff. It sits
    ahead of the tag and the default so that the configured default can never
    hand a patient's own cancellation to the clinic.
    """

    def resolve(self, incident: Incident) -> str | None:
        """Claim incidents the patient performed, pass the rest along."""
        if incident.by_patient_portal:
            return PATIENT
        return None


class ClinicTagRule:
    """A cancellation carrying the clinic tag counts against the clinic.

    The tag is the record, so this is where a person's correction takes effect.
    Because totals are recomputed on read, removing the tag moves the incident
    back onto the patient with no repair step anywhere.
    """

    def __init__(self, clinic_tag: str) -> None:
        self._clinic_tag = clinic_tag

    def resolve(self, incident: Incident) -> str | None:
        """Claim tagged incidents for the clinic, pass the rest along."""
        if self._clinic_tag in incident.labels:
            return CLINIC
        return None


class ConfiguredDefaultRule:
    """The end of the chain, which claims whatever is left.

    Canvas records who clicked cancel and never who asked for it, so a staff
    cancellation carrying no tag is genuinely unknowable. Rather than hold it,
    the policy decides it in advance and a person corrects it by tagging.
    """

    def __init__(self, default_attribution: str) -> None:
        self._default = default_attribution

    def resolve(self, incident: Incident) -> str:
        """Always claim."""
        return self._default


class AttributionChain:
    """Runs the rules in order and stamps the first answer onto the incident."""

    def __init__(self, rules: list[Any]) -> None:
        if not rules:
            raise ValueError("An attribution chain needs at least one rule.")
        self._rules = list(rules)

    def apply(self, incident: Incident) -> Incident:
        """Stamp the incident with the first attribution any rule claims."""
        for rule in self._rules:
            claimed = rule.resolve(incident)
            if claimed is not None:
                incident.attribution = claimed
                return incident
        # Unreachable while the chain ends in a rule that claims everything.
        # Raising rather than defaulting means a misconfigured chain is loud.
        raise RuntimeError(
            f"No attribution rule claimed {incident!r}. The chain must end in a "
            "rule that claims every incident."
        )
