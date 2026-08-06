"""Fake Surescripts medication-history rows for demos and testing.

Gated behind the `mock_history_data` plugin secret (see `settings.py`) and off
by default. The rows are injected into the modal payload alongside real history
so they exercise the whole workflow — matching against active meds, grouping,
dismissal, and `+ Add` — rather than being a purely cosmetic overlay. The drugs
carry real RxNorm/NDC codes, so `+ Add` resolves through FDB and originates a
genuine MedicationStatement.

Ported from the `Load Test Data` button that used to live in the chart_app
guided-consult medications module.
"""

from typing import Any

import arrow

# Each row becomes one or more history items in `_build_history_item` shape.
# `days_ago` entries are the fills for that drug — two entries produce a
# grouped row with a fill count, mirroring how real Surescripts data arrives
# as separate claim and fill records.
_MOCK_ROWS: list[dict[str, Any]] = [
    {
        "drug_description": "LORazepam 2 mg tablet",
        "strength": "2 mg tablet",
        "sig": "",
        "rxnorm": "197902",
        "ndc": "00591024001",
        "prescriber": "Test Prescriber",
        "pharmacy_name": "Test Pharmacy #1234",
        "fills": [21, 51],
    },
    {
        "drug_description": "Vimpat 50 mg tablet",
        "strength": "50 mg tablet",
        "sig": "Take 1 tablet by mouth twice daily",
        "rxnorm": "810002",
        "ndc": "00131247835",
        "prescriber": "Test Prescriber",
        "pharmacy_name": "Test Pharmacy #1234",
        "fills": [45],
    },
    {
        "drug_description": "buspirone HCl 10 mg tablet",
        "strength": "10 mg tablet",
        "sig": "Take 1 tablet by mouth twice daily with food",
        "rxnorm": "866083",
        "ndc": "00591024605",
        "prescriber": "Test Prescriber",
        "pharmacy_name": "Test Pharmacy #1234",
        "fills": [60],
    },
    {
        "drug_description": "Amoxicillin 125 MG/5 ML suspension",
        "strength": "125 mg/5 mL suspension",
        "sig": "",
        "rxnorm": "313797",
        "ndc": "00093416773",
        "prescriber": "Test Prescriber",
        "pharmacy_name": "Test Pharmacy #5678",
        "fills": [90],
    },
    {
        "drug_description": "cetirizine HCl / Pseudoephedrine HCl 5-120 mg ER tablet",
        "strength": "5-120 mg ER tablet",
        "sig": "",
        "rxnorm": "1014571",
        "ndc": "00069415066",
        "prescriber": "",
        "pharmacy_name": "Test Pharmacy #5678",
        "fills": [120],
    },
]


def _matches(
    row: dict,
    active_rxnorm_codes: set[str],
    active_ndc_codes: set[str],
    active_descriptions: list[str],
) -> tuple[bool, str]:
    """Match a mock row against the patient's active meds.

    Mirrors `action_button._is_matched` minus the NDC→RxNorm FDB cross-reference
    — mock data isn't worth a network round trip, and its RxNorm codes are
    already populated.
    """
    if row["rxnorm"] and row["rxnorm"] in active_rxnorm_codes:
        return True, "rxnorm"
    if row["ndc"] and row["ndc"].replace("-", "") in active_ndc_codes:
        return True, "ndc"

    drug_desc = row["drug_description"].lower()
    for desc in active_descriptions:
        if drug_desc in desc:
            return True, "description"
    return False, ""


def mock_history_items(
    active_rxnorm_codes: set[str],
    active_ndc_codes: set[str],
    active_descriptions: list[str],
) -> list[dict]:
    """Build fake history items in `action_button._build_history_item` shape.

    Fill dates are relative to today so a demo always shows recent activity.
    """
    today = arrow.utcnow()
    items = []

    for row in _MOCK_ROWS:
        is_match, match_method = _matches(
            row, active_rxnorm_codes, active_ndc_codes, active_descriptions
        )
        for index, days_ago in enumerate(row["fills"]):
            fill_date = today.shift(days=-days_ago)
            # First (most recent) fill is modeled as a claim, like real data,
            # so the group header prefers its description.
            is_claim = index == 0
            items.append(
                {
                    "drug_description": row["drug_description"],
                    "strength": row["strength"],
                    "last_fill_date": fill_date.format("MMM DD, YYYY"),
                    "last_fill_date_sort": fill_date.date().isoformat(),
                    "written_date": fill_date.shift(days=-3).format("MMM DD, YYYY"),
                    "prescriber": row["prescriber"],
                    "pharmacy_name": row["pharmacy_name"],
                    "source_description": "Test data",
                    "source_type": "Claim" if is_claim else "Fill",
                    "sig": row["sig"],
                    "is_match": is_match,
                    "match_method": match_method,
                    "rxnorm_codes": [row["rxnorm"]] if row["rxnorm"] else [],
                    "ndc_codes": [row["ndc"]] if row["ndc"] else [],
                }
            )

    return items
