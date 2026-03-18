#!/usr/bin/env python3
"""Create an Extend AI processor from a text file specification.

This script reads a text file containing a description of fields to extract,
uses an LLM to convert it to the Extend AI processor schema format,
and creates the processor via the Extend API.

Usage:
    python scripts/create_processor.py processor_spec.txt --name "My Processor"

Environment variables:
    EXTEND_AI_KEY: Extend AI API key (required)
    ANTHROPIC_API_KEY: Anthropic API key for LLM conversion (required)
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from extend_ai import Extend


SYSTEM_PROMPT = """You are an expert at converting document extraction specifications into Extend AI processor configurations.

Given a text description of fields to extract from documents, you must generate a valid JSON Schema for the Extend AI extraction processor.

## Extend AI JSON Schema Requirements:

1. The schema must be a valid JSON Schema with "type": "object" and "properties"
2. All primitive fields (string, number, boolean, integer) MUST be nullable using array type: "type": ["string", "null"]
3. Arrays must use "type": "array" (NOT ["array", "null"] - only primitives can be combined with null)
4. Maximum nesting level is 3 (each non-root object counts as 1 level)
5. Property keys can contain letters, numbers, underscores, and hyphens
6. Array items can be objects or primitive types

## Special Extend Types (use via "extend:type" property):
- "date" - For dates, ensures ISO format (yyyy-mm-dd). Use with "type": ["string", "null"]
- "currency" - For monetary values with currency code. Use with "type": ["object", "null"]
- "signature" - For signature detection. Use with "type": ["object", "null"]

## Example Schema:

```json
{
  "type": "object",
  "properties": {
    "patient_name": {
      "type": ["string", "null"],
      "description": "Full name of the patient"
    },
    "date_of_birth": {
      "type": ["string", "null"],
      "extend:type": "date",
      "description": "Patient's date of birth"
    },
    "test_results": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "test_name": {
            "type": ["string", "null"],
            "description": "Name of the lab test"
          },
          "value": {
            "type": ["number", "null"],
            "description": "Numeric result value"
          },
          "unit": {
            "type": ["string", "null"],
            "description": "Unit of measurement"
          },
          "reference_range": {
            "type": ["string", "null"],
            "description": "Normal reference range"
          },
          "is_abnormal": {
            "type": ["boolean", "null"],
            "description": "Whether the result is outside normal range"
          }
        }
      },
      "description": "Array of individual test results"
    }
  }
}
```

Output ONLY the JSON schema, no explanation or markdown formatting."""


def call_anthropic(api_key: str, user_prompt: str) -> dict | None:
    """Call Anthropic API to convert text spec to JSON schema."""
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "messages": [
                {"role": "user", "content": user_prompt}
            ],
            "system": SYSTEM_PROMPT,
        },
        timeout=60,
    )

    if response.status_code != 200:
        print(f"Anthropic API error: {response.status_code}")
        print(response.text)
        return None

    data = response.json()
    content = data.get("content", [])
    if content and content[0].get("type") == "text":
        text = content[0].get("text", "")
        # Try to parse as JSON
        try:
            # Handle potential markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text.strip())
        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response as JSON: {e}")
            print(f"Raw response: {text}")
            return None
    return None


def create_extend_processor(
    api_key: str,
    name: str,
    schema: dict,
    extraction_rules: str | None = None,
) -> dict | None:
    """Create a processor in Extend AI using direct API call."""
    # Build the config with correct field names for the API
    config = {
        "type": "EXTRACT",
        "schema": schema,
    }
    if extraction_rules:
        config["extractionRules"] = extraction_rules

    payload = {
        "name": name,
        "type": "EXTRACT",
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


def list_processors(client: Extend) -> None:
    """List all processors."""
    try:
        response = client.processor.list(type="EXTRACT")
        if response.processors:
            print("Existing EXTRACT processors:")
            for p in response.processors:
                print(f"  - {p.name} (ID: {p.id})")
        else:
            print("No EXTRACT processors found.")
    except Exception as e:
        print(f"Error listing processors: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Create an Extend AI processor from a text specification"
    )
    parser.add_argument(
        "spec_file",
        nargs="?",
        help="Path to text file containing the extraction specification"
    )
    parser.add_argument(
        "--name",
        help="Name for the processor"
    )
    parser.add_argument(
        "--rules",
        help="Optional extraction rules in natural language"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate schema but don't create processor"
    )
    parser.add_argument(
        "--output-schema",
        help="Save generated schema to this file"
    )
    parser.add_argument(
        "--input-schema",
        help="Use schema from this JSON file instead of generating with LLM"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing processors"
    )

    args = parser.parse_args()

    # Check required environment variables
    extend_key = os.environ.get("EXTEND_AI_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    # Handle --list command
    if args.list:
        if not extend_key:
            print("Error: EXTEND_AI_KEY environment variable required")
            sys.exit(1)
        client = Extend(token=extend_key)
        list_processors(client)
        return

    # Require --name for creation
    if not args.name and not args.list:
        print("Error: --name is required")
        sys.exit(1)

    if not args.dry_run and not extend_key and not args.list:
        print("Error: EXTEND_AI_KEY environment variable required")
        sys.exit(1)

    # Handle --input-schema (skip LLM call)
    if args.input_schema:
        schema_path = Path(args.input_schema)
        if not schema_path.exists():
            print(f"Error: Schema file not found: {args.input_schema}")
            sys.exit(1)
        schema = json.loads(schema_path.read_text())
        print(f"Loaded schema from: {schema_path.name}")
    else:
        # Need spec_file and anthropic key for LLM generation
        if not args.spec_file:
            print("Error: spec_file is required (unless using --list or --input-schema)")
            parser.print_help()
            sys.exit(1)

        if not anthropic_key:
            print("Error: ANTHROPIC_API_KEY environment variable required")
            sys.exit(1)

        # Read the spec file
        spec_path = Path(args.spec_file)
        if not spec_path.exists():
            print(f"Error: Spec file not found: {args.spec_file}")
            sys.exit(1)

        spec_text = spec_path.read_text()
        print(f"Read specification from: {spec_path.name}")
        print(f"Specification length: {len(spec_text)} characters")
        print()

        # Convert to JSON schema using LLM
        print("Converting specification to JSON schema using LLM...")
        user_prompt = f"""Convert the following document extraction specification into a valid Extend AI JSON Schema:

---
{spec_text}
---

Generate a JSON Schema that extracts all the fields described above. Use appropriate types (string, number, date, boolean, array, object) and include helpful descriptions."""

        schema = call_anthropic(anthropic_key, user_prompt)
        if not schema:
            print("Failed to generate schema")
            sys.exit(1)

    print("Generated schema:")
    print(json.dumps(schema, indent=2))
    print()

    # Save schema if requested
    if args.output_schema:
        output_path = Path(args.output_schema)
        output_path.write_text(json.dumps(schema, indent=2))
        print(f"Schema saved to: {output_path}")

    # Create processor unless dry run
    if args.dry_run:
        print("Dry run - not creating processor")
        return

    print(f"Creating processor '{args.name}'...")
    response = create_extend_processor(
        extend_key,
        args.name,
        schema,
        args.rules,
    )

    if response:
        print()
        print("Processor created successfully!")
        processor = response.get("processor", {})
        print(f"  ID: {processor.get('id')}")
        print(f"  Name: {processor.get('name')}")
        print(f"  Type: {processor.get('type')}")
        print(f"  Created: {processor.get('createdAt')}")
        draft_version = processor.get("draftVersion", {})
        if draft_version:
            print(f"  Draft Version: {draft_version.get('id')}")
    else:
        print("Failed to create processor")
        sys.exit(1)


if __name__ == "__main__":
    main()
