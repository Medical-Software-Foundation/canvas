"""Mock payloads for the billing dashboard.

Shape-identical to the original handler-local mock functions. Phase 2 will
reshape these to carry `source` flags; Phase 1 only relocates them.
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
            {"date": "Feb 3", "visits": 12, "revenue": 1560},
            {"date": "Feb 4", "visits": 15, "revenue": 1980},
            {"date": "Feb 5", "visits": 11, "revenue": 1430},
            {"date": "Feb 6", "visits": 18, "revenue": 2340},
            {"date": "Feb 7", "visits": 14, "revenue": 1820},
            {"date": "Feb 10", "visits": 16, "revenue": 2080},
            {"date": "Feb 11", "visits": 13, "revenue": 1690},
            {"date": "Feb 12", "visits": 17, "revenue": 2210},
            {"date": "Feb 13", "visits": 15, "revenue": 1950},
            {"date": "Feb 14", "visits": 10, "revenue": 1300},
            {"date": "Feb 18", "visits": 19, "revenue": 2470},
            {"date": "Feb 19", "visits": 14, "revenue": 1820},
            {"date": "Feb 20", "visits": 16, "revenue": 2080},
            {"date": "Feb 21", "visits": 13, "revenue": 1690},
            {"date": "Feb 24", "visits": 17, "revenue": 2210},
            {"date": "Feb 25", "visits": 12, "revenue": 1560},
            {"date": "Feb 26", "visits": 18, "revenue": 2340},
            {"date": "Feb 27", "visits": 14, "revenue": 1820},
            {"date": "Feb 28", "visits": 16, "revenue": 2080},
        ],
        "monthly": [
            {"month": "Apr", "revenue": 35200},
            {"month": "May", "revenue": 37800},
            {"month": "Jun", "revenue": 34100},
            {"month": "Jul", "revenue": 38900},
            {"month": "Aug", "revenue": 41200},
            {"month": "Sep", "revenue": 39500},
            {"month": "Oct", "revenue": 40800},
            {"month": "Nov", "revenue": 36400},
            {"month": "Dec", "revenue": 33900},
            {"month": "Jan", "revenue": 39400},
            {"month": "Feb", "revenue": 42580},
            {"month": "Mar", "revenue": 18340},
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
            {"name": "Blue Cross Blue Shield", "total_reimbursement": 45230.00, "acceptance_rate": 94.2, "avg_99214": 132.50, "cms_delta": 3.56},
            {"name": "Aetna",                  "total_reimbursement": 32100.00, "acceptance_rate": 91.8, "avg_99214": 118.75, "cms_delta": -10.19},
            {"name": "UnitedHealthcare",       "total_reimbursement": 28750.00, "acceptance_rate": 89.5, "avg_99214": 125.00, "cms_delta": -3.94},
            {"name": "Cigna",                  "total_reimbursement": 19800.00, "acceptance_rate": 93.1, "avg_99214": 130.25, "cms_delta": 1.31},
            {"name": "Medicare",               "total_reimbursement": 15400.00, "acceptance_rate": 97.8, "avg_99214": 128.94, "cms_delta": 0.00},
            {"name": "Medicaid",               "total_reimbursement":  8900.00, "acceptance_rate": 88.3, "avg_99214":  95.50, "cms_delta": -33.44},
        ]
    }


def trends() -> dict:
    return {
        "cpt_codes": [
            {"code": "99214", "description": "Office visit, established patient (moderate)", "your_avg": 131.20, "cms_rate": 128.94, "trend":  1},
            {"code": "99213", "description": "Office visit, established patient (low)",      "your_avg":  92.50, "cms_rate":  97.52, "trend":  0},
            {"code": "99215", "description": "Office visit, established patient (high)",     "your_avg": 198.40, "cms_rate": 193.46, "trend":  1},
            {"code": "99203", "description": "Office visit, new patient (low)",              "your_avg": 112.80, "cms_rate": 118.98, "trend": -1},
            {"code": "99204", "description": "Office visit, new patient (moderate)",         "your_avg": 178.90, "cms_rate": 188.28, "trend": -1},
            {"code": "99395", "description": "Preventive visit, established (18-39)",        "your_avg": 155.60, "cms_rate": 160.14, "trend":  0},
        ],
        "monthly_avg": [
            {"month": "Apr 2025", "avg": 118.50},
            {"month": "May 2025", "avg": 121.30},
            {"month": "Jun 2025", "avg": 119.80},
            {"month": "Jul 2025", "avg": 124.60},
            {"month": "Aug 2025", "avg": 126.10},
            {"month": "Sep 2025", "avg": 123.40},
            {"month": "Oct 2025", "avg": 127.90},
            {"month": "Nov 2025", "avg": 130.20},
            {"month": "Dec 2025", "avg": 128.50},
            {"month": "Jan 2026", "avg": 131.80},
            {"month": "Feb 2026", "avg": 133.10},
            {"month": "Mar 2026", "avg": 132.40},
        ],
        "cms_benchmark": CMS_PRIMARY_BENCHMARK,
    }
