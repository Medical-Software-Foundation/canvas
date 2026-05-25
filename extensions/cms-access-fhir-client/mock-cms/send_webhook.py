"""Fire a CMS-style FHIR Subscription notification at the deployed plugin webhook.

Usage:
    uv run python send_webhook.py <event_type> [--secret X] [--patient-id Y]

Event types:
    provider-lock-in-ending
    data-reporting-due-baseline
    data-reporting-due-quarterly
    data-reporting-due-end-of-period
    alignment-renewal-due
    unalignment-cms
    unalignment-participant
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

import httpx

WEBHOOK_URL = "https://allison-training.canvasmedical.com/plugin-io/api/cms_access_fhir_client/webhook"

EVENT_TYPES = {
    "provider-lock-in-ending",
    "data-reporting-due-baseline",
    "data-reporting-due-quarterly",
    "data-reporting-due-end-of-period",
    "alignment-renewal-due",
    "unalignment-cms",
    "unalignment-participant",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event_type", choices=sorted(EVENT_TYPES))
    parser.add_argument("--secret", required=True, help="Value of ACCESS_WEBHOOK_SECRET configured in the plugin")
    parser.add_argument("--patient-id", default="unknown-patient", help="Canvas patient FHIR id to reference")
    parser.add_argument("--alignment-id", default="ALIGN-TEST0001", help="CMS alignment id to reference")
    parser.add_argument("--url", default=WEBHOOK_URL, help="Webhook endpoint URL")
    args = parser.parse_args()

    payload = {
        "resourceType": "Bundle",
        "type": "history",
        "entry": [
            {
                "resource": {
                    "resourceType": "SubscriptionStatus",
                    "status": "active",
                    "type": "event-notification",
                    "notificationEvent": [{"eventNumber": str(uuid.uuid4())}],
                    "subscription": {"reference": f"Subscription/{args.event_type}"},
                }
            },
            {
                "resource": {
                    "resourceType": "Parameters",
                    "parameter": [
                        {"name": "eventType", "valueString": args.event_type},
                        {"name": "alignmentId", "valueString": args.alignment_id},
                        {"name": "patient", "valueReference": {"reference": f"Patient/{args.patient_id}"}},
                    ],
                }
            },
        ],
    }

    headers = {
        "Content-Type": "application/fhir+json",
        "X-Access-Webhook-Secret": args.secret,
    }

    response = httpx.post(args.url, json=payload, headers=headers, timeout=30)
    print(f"{response.status_code} {response.reason_phrase}")
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)
    return 0 if response.is_success else 1


if __name__ == "__main__":
    sys.exit(main())
