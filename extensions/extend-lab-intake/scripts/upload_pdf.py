#!/usr/bin/env python3
"""Test client for uploading PDFs to the lab intake endpoint.

Usage:
    python scripts/test_upload.py path/to/lab_report.pdf

Environment variables:
    CANVAS_HOST: Canvas instance hostname (default: plugin-testing)
    INBOUND_FAX_TOKEN: API token for authentication (required)
"""

import argparse
import os
import sys
from pathlib import Path

import requests


def upload_pdf(pdf_path: str, host: str, token: str) -> dict:
    """Upload a PDF file to the lab intake endpoint.

    Args:
        pdf_path: Path to the PDF file
        host: Canvas instance hostname
        token: API authentication token

    Returns:
        Response JSON from the API
    """
    url = f"https://{host}.canvasmedical.com/plugin-io/api/extend_lab_intake/lab-intake/inbound-fax"

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if not pdf_file.suffix.lower() == ".pdf":
        print(f"Warning: File does not have .pdf extension: {pdf_path}")

    print(f"Uploading: {pdf_file.name}")
    print(f"Target: {url}")
    print()

    with open(pdf_file, "rb") as f:
        files = {"file": (pdf_file.name, f, "application/pdf")}
        headers = {"Authorization": token}

        response = requests.post(url, files=files, headers=headers, timeout=120)

    print(f"Status: {response.status_code}")
    print()

    try:
        result = response.json()
        print("Response:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        return result
    except Exception:
        print(f"Response text: {response.text}")
        return {"status_code": response.status_code, "text": response.text}


def main():
    parser = argparse.ArgumentParser(
        description="Upload a PDF to the lab intake endpoint for testing"
    )
    parser.add_argument(
        "pdf_path",
        help="Path to the PDF file to upload"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("CANVAS_HOST", "plugin-testing"),
        help="Canvas instance hostname (default: plugin-testing or CANVAS_HOST env)"
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("INBOUND_FAX_TOKEN"),
        help="API token (default: INBOUND_FAX_TOKEN env)"
    )

    args = parser.parse_args()

    if not args.token:
        print("Error: API token required. Set INBOUND_FAX_TOKEN env or use --token")
        sys.exit(1)

    try:
        upload_pdf(args.pdf_path, args.host, args.token)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"Request error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
