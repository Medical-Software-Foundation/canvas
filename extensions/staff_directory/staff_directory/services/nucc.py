from __future__ import annotations

from django.db.models import Q

from staff_directory.models.nucc import NuccTaxonomyCode


def search_nucc(query: str, limit: int = 25) -> list[NuccTaxonomyCode]:
    """Case-insensitive search across NUCC fields for typeahead."""
    query = (query or "").strip()
    if not query:
        return []

    limit = max(1, min(int(limit), 100))

    queryset = NuccTaxonomyCode.objects.filter(
        Q(code__icontains=query)
        | Q(classification__icontains=query)
        | Q(specialization__icontains=query)
        | Q(display_name__icontains=query)
    ).order_by("classification", "specialization", "code")

    return list(queryset[:limit])


def get_nucc_by_code(code: str) -> NuccTaxonomyCode | None:
    code = (code or "").strip()
    if not code:
        return None
    return NuccTaxonomyCode.objects.filter(code=code).first()


def serialize_nucc(code: NuccTaxonomyCode) -> dict:
    return {
        "code": code.code,
        "grouping": code.grouping,
        "classification": code.classification,
        "specialization": code.specialization,
        "display_name": code.display_name,
        "definition": code.definition,
    }


def seed_nucc_codes(rows: list[dict], batch_size: int = 500) -> tuple[int, int]:
    """Idempotently insert NUCC codes from a list of dicts.

    Returns (created_count, skipped_count).
    Skips rows whose `code` already exists so the seed is safe to re-run.
    """
    if not rows:
        return (0, 0)

    existing = set(
        NuccTaxonomyCode.objects.values_list("code", flat=True)
    )

    to_create: list[NuccTaxonomyCode] = []
    skipped = 0
    for row in rows:
        code = (row.get("code") or "").strip()
        if not code:
            skipped += 1
            continue
        if code in existing:
            skipped += 1
            continue
        to_create.append(
            NuccTaxonomyCode(
                code=code,
                grouping=row.get("grouping", "") or "",
                classification=row.get("classification", "") or "",
                specialization=row.get("specialization", "") or "",
                definition=row.get("definition", "") or "",
                display_name=row.get("display_name")
                or _compose_display(
                    row.get("classification", ""), row.get("specialization", "")
                ),
            )
        )
        existing.add(code)

    created = 0
    for start in range(0, len(to_create), batch_size):
        chunk = to_create[start : start + batch_size]
        NuccTaxonomyCode.objects.bulk_create(chunk, batch_size=batch_size)
        created += len(chunk)

    return (created, skipped)


def _compose_display(classification: str, specialization: str) -> str:
    classification = (classification or "").strip()
    specialization = (specialization or "").strip()
    if classification and specialization:
        return f"{classification} — {specialization}"
    return classification or specialization or ""
