"""Shared logic for building metadata-driven banner effects.

Used by both the event-driven handler (single patient, real time) and the
backfill cron task (rolling reconciliation across the panel), so the two
paths stay in sync.
"""
import re

from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert

BANNER_KEY = "patient-metadata"
MAX_NARRATIVE_LENGTH = 90

VARIABLE_PATTERN = re.compile(r"\{(\w+)\}")


def build_banner_for_patient(patient, template):
    """Build an AddBannerAlert for a single patient, or None if no matching metadata.

    Returns None when the template has no placeholders, or when the patient is
    missing any referenced metadata key (so partial banners are never shown).
    """
    referenced_keys = set(VARIABLE_PATTERN.findall(template))
    if not referenced_keys:
        return None

    metadata_map = {}
    for entry in patient.metadata.all():
        if entry.key in referenced_keys and entry.value and entry.value.strip():
            metadata_map[entry.key] = entry.value

    if referenced_keys != set(metadata_map.keys()):
        return None

    narrative = VARIABLE_PATTERN.sub(
        lambda m: metadata_map.get(m.group(1), ""),
        template,
    )
    narrative = narrative.strip()

    if not narrative:
        return None

    if len(narrative) > MAX_NARRATIVE_LENGTH:
        narrative = narrative[: MAX_NARRATIVE_LENGTH - 3] + "..."

    return AddBannerAlert(
        patient_id=str(patient.id),
        key=BANNER_KEY,
        narrative=narrative,
        placement=[AddBannerAlert.Placement.CHART],
        intent=AddBannerAlert.Intent.INFO,
    )


def banner_effect_for_patient(patient, template):
    """Return the single add-or-remove Effect that reconciles this patient's banner.

    Adds the banner when the patient's metadata fills the template, otherwise
    removes any stale banner. Idempotent, so it is safe to re-run every sweep.
    """
    banner = build_banner_for_patient(patient, template)
    if banner:
        return banner.apply()
    return RemoveBannerAlert(
        patient_id=str(patient.id),
        key=BANNER_KEY,
    ).apply()
