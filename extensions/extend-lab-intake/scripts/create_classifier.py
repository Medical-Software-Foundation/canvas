#!/usr/bin/env python3
"""Create an Extend AI classifier processor.

This script creates a classifier processor that categorizes documents
into defined classifications.

Usage:
    python scripts/create_classifier.py --name "Lipid Panel Classifier" \
        --classifications "lipid_panel:Lipid Panel Lab Report" "other:Not a Lipid Panel"

Environment variables:
    EXTEND_AI_KEY: Extend AI API key (required)
"""

import argparse
import json
import os
import sys

import requests
from extend_ai import Extend


def create_classifier_processor(
    api_key: str,
    name: str,
    classifications: list[dict],
    classification_rules: str | None = None,
) -> dict | None:
    """Create a classifier processor in Extend AI."""
    config = {
        "type": "CLASSIFY",
        "classifications": classifications,
    }
    if classification_rules:
        config["classificationRules"] = classification_rules

    payload = {
        "name": name,
        "type": "CLASSIFY",
        "config": config,
    }

    print(f"Sending payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(
            "https://api.extend.ai/v1/processors",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "x-extend-api-version": "2025-04-21",
            },
            json=payload,
            timeout=60,
        )

        if response.status_code in (200, 201):
            return response.json()
        else:
            print(f"Extend API error: {response.status_code}")
            print(response.text)
            return None
    except Exception as e:
        print(f"Request error: {e}")
        return None


def list_classifiers(client: Extend) -> None:
    """List all classifier processors."""
    try:
        response = client.processor.list(type="CLASSIFY")
        if response.processors:
            print("Existing CLASSIFY processors:")
            for p in response.processors:
                print(f"  - {p.name} (ID: {p.id})")
        else:
            print("No CLASSIFY processors found.")
    except Exception as e:
        print(f"Error listing processors: {e}")


def parse_classification(spec: str) -> dict:
    """Parse a classification spec like 'key:Description'.

    The Classification type requires: id, type, and description.
    We use the key for both id and type.
    """
    if ":" in spec:
        key, description = spec.split(":", 1)
        key = key.strip()
        return {"id": key, "type": key, "description": description.strip()}
    else:
        key = spec.strip()
        return {"id": key, "type": key, "description": key}


def main():
    parser = argparse.ArgumentParser(
        description="Create an Extend AI classifier processor"
    )
    parser.add_argument(
        "--name",
        help="Name for the processor"
    )
    parser.add_argument(
        "--classifications",
        nargs="+",
        help="Classifications in format 'key:description' (e.g., 'lipid_panel:Lipid Panel Lab Report')"
    )
    parser.add_argument(
        "--rules",
        help="Optional classification rules in natural language"
    )
    parser.add_argument(
        "--config-file",
        help="JSON file with classifications config"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing classifier processors"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show config but don't create processor"
    )

    args = parser.parse_args()

    extend_key = os.environ.get("EXTEND_AI_KEY")

    # Handle --list command
    if args.list:
        if not extend_key:
            print("Error: EXTEND_AI_KEY environment variable required")
            sys.exit(1)
        client = Extend(token=extend_key)
        list_classifiers(client)
        return

    # Require --name for creation
    if not args.name:
        print("Error: --name is required")
        sys.exit(1)

    if not args.dry_run and not extend_key:
        print("Error: EXTEND_AI_KEY environment variable required")
        sys.exit(1)

    # Build classifications
    if args.config_file:
        config_path = args.config_file
        with open(config_path) as f:
            config_data = json.load(f)
        classifications = config_data.get("classifications", [])
    elif args.classifications:
        classifications = [parse_classification(c) for c in args.classifications]
    else:
        print("Error: --classifications or --config-file is required")
        sys.exit(1)

    print("Classifications:")
    for c in classifications:
        print(f"  - {c['type']}: {c['description']}")
    print()

    if args.dry_run:
        print("Dry run - not creating processor")
        return

    print(f"Creating classifier '{args.name}'...")
    response = create_classifier_processor(
        extend_key,
        args.name,
        classifications,
        args.rules,
    )

    if response:
        print()
        print("Classifier created successfully!")
        processor = response.get("processor", {})
        print(f"  ID: {processor.get('id')}")
        print(f"  Name: {processor.get('name')}")
        print(f"  Type: {processor.get('type')}")
        print(f"  Created: {processor.get('createdAt')}")
        draft_version = processor.get("draftVersion", {})
        if draft_version:
            print(f"  Draft Version: {draft_version.get('id')}")
    else:
        print("Failed to create classifier")
        sys.exit(1)


if __name__ == "__main__":
    main()
