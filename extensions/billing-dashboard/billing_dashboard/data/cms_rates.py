"""CMS Physician Fee Schedule benchmark rates and CPT descriptions.

Values taken from the CMS Physician Fee Schedule. Matches the values used in
the original Trends tab mock. Extend this table as new CPT codes are surfaced
by the Trends aggregation.
"""

from __future__ import annotations

CMS_RATES: dict[str, float] = {
    "99214": 128.94,
    "99213": 97.52,
    "99215": 193.46,
    "99203": 118.98,
    "99204": 188.28,
    "99395": 160.14,
}

CPT_DESCRIPTIONS: dict[str, str] = {
    "99214": "Office visit, established patient (moderate)",
    "99213": "Office visit, established patient (low)",
    "99215": "Office visit, established patient (high)",
    "99203": "Office visit, new patient (low)",
    "99204": "Office visit, new patient (moderate)",
    "99395": "Preventive visit, established (18-39)",
}

CMS_PRIMARY_BENCHMARK: float = CMS_RATES["99214"]


def get_cms_rate(cpt: str) -> float | None:
    return CMS_RATES.get(cpt)


def get_cpt_description(cpt: str) -> str | None:
    return CPT_DESCRIPTIONS.get(cpt)
