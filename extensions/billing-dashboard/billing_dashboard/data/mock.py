"""Mock payloads for the billing dashboard.

Returned by data builders when the real DB query yields zero rows. Field names
match the real-path shape so the JS renders the same way on the empty-data
path as it does on the real-data path.
"""

from __future__ import annotations

from billing_dashboard.data.cms_rates import CMS_PRIMARY_BENCHMARK


def financial_overview() -> dict:
    return {
        "summary": {
            "last_month_collected": 42580.00,
            "this_month_to_date": 18340.00,
            "next_month_projected": 45200.00,
            "claim_acceptance_rate": 93.4,
            "last_month_trend_pct": 8.2,
            "next_month_appt_count": 312,
        },
        "daily": [
            {"date": "Feb 3", "visits": 12, "collected": 1560},
            {"date": "Feb 4", "visits": 15, "collected": 1980},
            {"date": "Feb 5", "visits": 11, "collected": 1430},
            {"date": "Feb 6", "visits": 18, "collected": 2340},
            {"date": "Feb 7", "visits": 14, "collected": 1820},
            {"date": "Feb 10", "visits": 16, "collected": 2080},
            {"date": "Feb 11", "visits": 13, "collected": 1690},
            {"date": "Feb 12", "visits": 17, "collected": 2210},
            {"date": "Feb 13", "visits": 15, "collected": 1950},
            {"date": "Feb 14", "visits": 10, "collected": 1300},
            {"date": "Feb 18", "visits": 19, "collected": 2470},
            {"date": "Feb 19", "visits": 14, "collected": 1820},
            {"date": "Feb 20", "visits": 16, "collected": 2080},
            {"date": "Feb 21", "visits": 13, "collected": 1690},
            {"date": "Feb 24", "visits": 17, "collected": 2210},
            {"date": "Feb 25", "visits": 12, "collected": 1560},
            {"date": "Feb 26", "visits": 18, "collected": 2340},
            {"date": "Feb 27", "visits": 14, "collected": 1820},
            {"date": "Feb 28", "visits": 16, "collected": 2080},
        ],
        "monthly": [
            {"month": "Apr", "collected": 35200},
            {"month": "May", "collected": 37800},
            {"month": "Jun", "collected": 34100},
            {"month": "Jul", "collected": 38900},
            {"month": "Aug", "collected": 41200},
            {"month": "Sep", "collected": 39500},
            {"month": "Oct", "collected": 40800},
            {"month": "Nov", "collected": 36400},
            {"month": "Dec", "collected": 33900},
            {"month": "Jan", "collected": 39400},
            {"month": "Feb", "collected": 42580},
            {"month": "Mar", "collected": 18340},
        ],
        "insights": [
            {"severity": "warning", "title": "Aetna reimbursement declining",
             "description": "Average 99214 reimbursement from Aetna dropped 6.2% over the past 3 months. Consider renegotiating contract terms.",
             "tag": "Payer"},
            {"severity": "critical", "title": "Medicaid acceptance rate below threshold",
             "description": "Medicaid claim acceptance at 88.3%, below the 90% target. Review recent denials for common rejection reasons.",
             "tag": "Claims"},
            {"severity": "info", "title": "Revenue trending upward",
             "description": "Monthly collections increased 12.4% over the trailing quarter, driven by higher volume and improved coding accuracy.",
             "tag": "Revenue"},
        ],
    }


def payer_analysis() -> dict:
    return {
        "payers": [
            {"name": "Blue Cross Blue Shield", "collected": 45230.00, "acceptance_rate": 94.2, "cms_delta": 3.56},
            {"name": "Aetna",                  "collected": 32100.00, "acceptance_rate": 91.8, "cms_delta": -10.19},
            {"name": "UnitedHealthcare",       "collected": 28750.00, "acceptance_rate": 89.5, "cms_delta": -3.94},
            {"name": "Cigna",                  "collected": 19800.00, "acceptance_rate": 93.1, "cms_delta": 1.31},
            {"name": "Medicare",               "collected": 15400.00, "acceptance_rate": 97.8, "cms_delta": 0.00},
            {"name": "Medicaid",               "collected":  8900.00, "acceptance_rate": 88.3, "cms_delta": -33.44},
        ]
    }


def trends() -> dict:
    return {
        "cpt_codes": [
            {"code": "99214", "description": "Office visit, established patient (moderate)", "your_avg_charge": 131.20, "cms_rate": 128.94, "trend":  1},
            {"code": "99213", "description": "Office visit, established patient (low)",      "your_avg_charge":  92.50, "cms_rate":  97.52, "trend":  0},
            {"code": "99215", "description": "Office visit, established patient (high)",     "your_avg_charge": 198.40, "cms_rate": 193.46, "trend":  1},
            {"code": "99203", "description": "Office visit, new patient (low)",              "your_avg_charge": 112.80, "cms_rate": 118.98, "trend": -1},
            {"code": "99204", "description": "Office visit, new patient (moderate)",         "your_avg_charge": 178.90, "cms_rate": 188.28, "trend": -1},
            {"code": "99395", "description": "Preventive visit, established (18-39)",        "your_avg_charge": 155.60, "cms_rate": 160.14, "trend":  0},
        ],
        "monthly_avg": [
            {"month": "Apr 2025", "avg_charge": 118.50},
            {"month": "May 2025", "avg_charge": 121.30},
            {"month": "Jun 2025", "avg_charge": 119.80},
            {"month": "Jul 2025", "avg_charge": 124.60},
            {"month": "Aug 2025", "avg_charge": 126.10},
            {"month": "Sep 2025", "avg_charge": 123.40},
            {"month": "Oct 2025", "avg_charge": 127.90},
            {"month": "Nov 2025", "avg_charge": 130.20},
            {"month": "Dec 2025", "avg_charge": 128.50},
            {"month": "Jan 2026", "avg_charge": 131.80},
            {"month": "Feb 2026", "avg_charge": 133.10},
            {"month": "Mar 2026", "avg_charge": 132.40},
        ],
        "cms_benchmark": CMS_PRIMARY_BENCHMARK,
    }
