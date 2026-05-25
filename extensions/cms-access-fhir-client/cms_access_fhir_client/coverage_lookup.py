"""Look up a patient's active Medicare Part B Coverage record.

Matching rules (evaluated in order):
1. If ``ACCESS_MEDICARE_PART_B_PAYER_IDS`` is set (comma-separated Transactor UUIDs),
   filter ``coverage.issuer.id`` against that allowlist.
2. Otherwise, do a case-insensitive substring match of
   ``ACCESS_PAYER_NAME_PATTERN`` (default ``"Medicare Part B"``) against
   ``coverage.issuer.name``.
3. Always require ``coverage.state == "active"``.
4. Among any matching active coverages, return the one with the lowest
   ``coverage_rank`` (primary preferred).  Returns ``None`` when no match is
   found.
"""
from canvas_sdk.v1.data.coverage import Coverage

_DEFAULT_PAYER_NAME_PATTERN = "Medicare Part B"


def get_active_medicare_part_b_coverage(patient, secrets: dict):
    """Return the patient's active primary Medicare Part B Coverage, or None.

    Parameters
    ----------
    patient:
        A ``Patient`` (or ``CustomPatient``) instance.
    secrets:
        The handler's ``self.secrets`` mapping.

    Returns
    -------
    Coverage | None
    """
    payer_ids_raw = secrets.get("ACCESS_MEDICARE_PART_B_PAYER_IDS", "")
    payer_ids = [pid.strip() for pid in payer_ids_raw.split(",") if pid.strip()]

    qs = Coverage.objects.select_related("issuer").filter(
        patient=patient,
        state="active",
    )

    if payer_ids:
        qs = qs.filter(issuer__id__in=payer_ids)
    else:
        name_pattern = secrets.get("ACCESS_PAYER_NAME_PATTERN", _DEFAULT_PAYER_NAME_PATTERN)
        qs = qs.filter(issuer__name__icontains=name_pattern)

    return qs.order_by("coverage_rank").first()
