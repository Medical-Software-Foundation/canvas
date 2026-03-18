#!/usr/bin/env python3
"""Debug script to run the lipid panel extractor against an intake document.

Usage:
    python scripts/debug_run_lipid_panel_extractor.py <intake_id>

Requires environment variables:
    EXTEND_AI_KEY - Extend AI API key
    EXTEND_AI_PROCESSOR_TREE - JSON string containing processor tree
    AWS_ACCESS_KEY_ID - AWS key for S3 access
    AWS_SECRET_ACCESS_KEY - AWS secret for S3 access
"""

import json
import os
import sys
from pathlib import Path

# Add parent directory to path so we can import extend_lab_intake
sys.path.insert(0, str(Path(__file__).parent.parent))

from extend_lab_intake.services.extend_client import (
    ExtendClient,
    ExtendError,
    ExtendRunStatus,
    ProcessorTree,
)
from extend_lab_intake.utils.s3_client import S3Client


# Configuration
BUCKET = "canvas-plugin-data"
REGION = "us-west-2"
INSTANCE = "plugin-testing"


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_lipid_panel_extractor.py <intake_id>")
        sys.exit(1)

    intake_id = sys.argv[1]
    print(f"Running extractor for intake: {intake_id}")

    # Load credentials from environment
    extend_api_key = os.environ["EXTEND_AI_KEY"]
    processor_tree_json = os.environ["EXTEND_AI_PROCESSOR_TREE"]
    aws_key = os.environ["AWS_ACCESS_KEY_ID"]
    aws_secret = os.environ["AWS_SECRET_ACCESS_KEY"]

    # Create clients
    s3_client = S3Client(
        aws_key=aws_key,
        aws_secret=aws_secret,
        bucket=BUCKET,
        region=REGION,
        instance=INSTANCE,
    )
    extend_client = ExtendClient(api_key=extend_api_key)
    processor_tree = ProcessorTree.from_json(processor_tree_json)

    # Step 1: Load metadata from S3
    print(f"\n[1] Loading metadata from S3...")
    metadata_key = f"intake/{intake_id}/metadata.json"
    metadata = s3_client.get_json(metadata_key)

    if not metadata:
        print(f"ERROR: Metadata not found for intake {intake_id}")
        sys.exit(1)

    print(f"Metadata loaded: {json.dumps(metadata, indent=2)}")

    file_name = metadata["file_name"]
    classification_data = metadata.get("classification", {})
    classification_id = classification_data.get("id", "")
    classification_type = classification_data.get("type", "")

    print(f"\nFile: {file_name}")
    print(f"Classification ID: {classification_id}")
    print(f"Classification type: {classification_type}")

    # Step 2: Get extractor from processor tree
    print(f"\n[2] Looking up extractor in processor tree...")
    classifier = processor_tree.get_first_classifier()
    print(f"Classifier ID: {classifier.processor_id}")
    print(f"Available extractors: {list(classifier.extractors.keys())}")

    extractor = processor_tree.get_extractor_for_classification(
        classifier.processor_id, classification_id
    )

    if not extractor:
        print(f"ERROR: No extractor found for classification_id: {classification_id}")
        sys.exit(1)

    print(f"Found extractor: {extractor.processor_id} ({extractor.name})")

    # Step 3: Generate presigned URL for PDF
    print(f"\n[3] Generating presigned URL...")
    pdf_key = f"intake/{intake_id}/{file_name}"
    presigned_url = s3_client.generate_presigned_url(pdf_key, expires_in=3600)
    print(f"Presigned URL: {presigned_url[:100]}...")

    # Step 4: Run the extractor
    print(f"\n[4] Running Extend AI extractor...")
    print(f"Processor ID: {extractor.processor_id}")
    print(f"File name: {file_name}")

    extract_result = extend_client.run_processor(
        processor_id=extractor.processor_id,
        file_name=file_name,
        file_url=presigned_url,
    )

    if isinstance(extract_result, ExtendError):
        print(f"ERROR: run_processor failed!")
        print(f"Status code: {extract_result.status_code}")
        print(f"Message: {extract_result.message}")
        sys.exit(1)

    print(f"Run started. Run ID: {extract_result.run_id}")
    print(f"Initial status: {extract_result.status}")

    # Step 5: Wait for completion
    print(f"\n[5] Waiting for extraction to complete...")
    extract_result = extend_client.wait_for_completion(extract_result.run_id)

    if isinstance(extract_result, ExtendError):
        print(f"ERROR: wait_for_completion failed!")
        print(f"Status code: {extract_result.status_code}")
        print(f"Message: {extract_result.message}")
        sys.exit(1)

    print(f"Final status: {extract_result.status}")

    if extract_result.status == ExtendRunStatus.FAILED:
        print(f"ERROR: Extraction failed!")
        print(f"Error: {extract_result.error}")
        sys.exit(1)

    # Step 6: Print extraction output
    print(f"\n[6] Extraction output:")
    print(json.dumps(extract_result.output, indent=2))


if __name__ == "__main__":
    main()
