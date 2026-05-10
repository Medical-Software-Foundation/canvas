from collections import defaultdict

from canvas_sdk.effects import Effect
from canvas_sdk.effects.banner_alert import AddBannerAlert, RemoveBannerAlert

from patient_tags.constants import (
    BANNER_KEY_PREFIX,
    BANNER_NARRATIVE_MAX_CHARS,
    LEGACY_BANNER_KEYS,
)
from patient_tags.models import BannerGroup, PatientLabel

INTENT_MAP = {
    "info": AddBannerAlert.Intent.INFO,
    "warning": AddBannerAlert.Intent.WARNING,
    "alert": AddBannerAlert.Intent.ALERT,
}

PLACEMENT_MAP = {
    "CHART": AddBannerAlert.Placement.CHART,
    "TIMELINE": AddBannerAlert.Placement.TIMELINE,
    "APPOINTMENT_CARD": AddBannerAlert.Placement.APPOINTMENT_CARD,
    "SCHEDULING_CARD": AddBannerAlert.Placement.SCHEDULING_CARD,
    "PROFILE": AddBannerAlert.Placement.PROFILE,
}


def banner_key_for_group(group_dbid: int) -> str:
    return f"{BANNER_KEY_PREFIX}{group_dbid}"


def truncate_narrative(text: str) -> str:
    if len(text) <= BANNER_NARRATIVE_MAX_CHARS:
        return text
    return text[: BANNER_NARRATIVE_MAX_CHARS - 1].rstrip() + "…"


def compute_banner_effects(patient_id: str) -> list[Effect]:
    """Reconcile banner alerts for a patient based on their current label assignments.

    For each BannerGroup: emit AddBannerAlert if the patient has ≥1 label in the
    group, else RemoveBannerAlert. Labels with no banner_group contribute nothing
    to banners (they only show in the modal/profile UI).
    """
    # Avoid chained select_related across nullable FKs (Canvas CustomModels treat
    # all columns as nullable at the DB layer; chained INNER JOINs silently exclude
    # rows whose nested FK is NULL). Query labels directly by FK id instead.
    label_ids = list(
        PatientLabel.objects
        .filter(patient__id=patient_id)
        .values_list("label_id", flat=True)
    )

    labels_by_group: dict[int, list[str]] = defaultdict(list)
    if label_ids:
        from patient_tags.models import Label

        for name, banner_group_id in (
            Label.objects
            .filter(dbid__in=label_ids)
            .values_list("name", "banner_group_id")
        ):
            if banner_group_id:
                labels_by_group[banner_group_id].append(name)

    effects: list[Effect] = []
    all_groups = BannerGroup.objects.all()

    for group in all_groups:
        key = banner_key_for_group(group.dbid)
        names = labels_by_group.get(group.dbid, [])
        if not names:
            effects.append(RemoveBannerAlert(patient_id=patient_id, key=key).apply())
            continue

        narrative = truncate_narrative(group.separator.join(names))
        placements = [
            PLACEMENT_MAP[p] for p in group.placements if p in PLACEMENT_MAP
        ] or [AddBannerAlert.Placement.CHART]
        intent = INTENT_MAP.get(group.intent, AddBannerAlert.Intent.INFO)

        kwargs = {
            "patient_id": patient_id,
            "key": key,
            "narrative": narrative,
            "placement": placements,
            "intent": intent,
        }
        if group.href:
            kwargs["href"] = group.href

        effects.append(AddBannerAlert(**kwargs).apply())

    # Self-heal legacy per-label banners from the pre-bannergroup schema. The
    # current code uses BANNER_KEY_PREFIX-prefixed keys, but instances upgraded
    # from older versions still have orphaned banners under the old keys; emit
    # RemoveBannerAlert for each on every reconcile pass so they fall away the
    # next time any label change touches the patient.
    for legacy_key in LEGACY_BANNER_KEYS:
        effects.append(
            RemoveBannerAlert(patient_id=patient_id, key=legacy_key).apply()
        )

    return effects
