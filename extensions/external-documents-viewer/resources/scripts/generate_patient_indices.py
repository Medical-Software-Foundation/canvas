"""
Generate per-patient JSON document index files from a document-index CSV.

This is a reference data-prep script. It converts a flat CSV describing legacy
documents (one row per document) into the per-patient JSON index files the
plugin reads from S3. Adapt the column mapping to match your own export.

Input:
    A CSV file with the following columns:
        patient_directory     - S3 directory for the patient (e.g. "PATIENT_DIR_12345")
        canvas_patient_key    - Canvas patient UUID
        pdf_filename          - PDF file name within the patient directory
        ai_generated_title    - Human-readable document title
        ai_extracted_date     - Document date (YYYY-MM-DD or similar)
        category              - Document category (Order, Lab, Admin, etc.)

Output:
    patient-indices/{canvas_patient_key}.json  (one file per patient)

    JSON structure:
    {
      "documents": [
        {
          "title":    "Sample Lab Result",
          "category": "Lab",
          "date":     "2025-02-10",
          "s3_key":   "PATIENT_DIR_12345/sample_lab_result.pdf"
        },
        ...
      ]
    }

    Documents within each file are sorted by date descending.

Usage:
    uv run python generate_patient_indices.py --csv PATH [--out-dir PATH]

    Defaults:
        --csv     document_index.csv
        --out-dir patient-indices
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


DEFAULT_CSV = Path("document_index.csv")
DEFAULT_OUT_DIR = Path("patient-indices")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate per-patient JSON document index files from a document-index CSV."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Path to a document-index CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for per-patient JSON files (default: {DEFAULT_OUT_DIR})",
    )
    return parser.parse_args()


def normalize_date(raw: str) -> str:
    """Return a YYYY-MM-DD string, or the raw value if it cannot be parsed."""
    raw = raw.strip()
    # Already ISO format
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw
    # Try common formats
    from datetime import datetime

    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%m-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw  # Return as-is if unparseable


def main() -> None:
    args = parse_args()

    csv_path: Path = args.csv
    out_dir: Path = args.out_dir

    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    # Group documents by canvas_patient_key
    patients: dict[str, list[dict]] = defaultdict(list)

    required_columns = {
        "patient_directory",
        "canvas_patient_key",
        "pdf_filename",
        "ai_generated_title",
        "ai_extracted_date",
        "category",
    }

    row_count = 0
    skipped = 0

    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            print("ERROR: CSV has no header row.", file=sys.stderr)
            sys.exit(1)

        actual_columns = set(reader.fieldnames)
        missing = required_columns - actual_columns
        if missing:
            print(
                f"ERROR: CSV is missing required columns: {sorted(missing)}", file=sys.stderr
            )
            print(f"       Found columns: {sorted(actual_columns)}", file=sys.stderr)
            sys.exit(1)

        for row in reader:
            row_count += 1
            patient_key = row["canvas_patient_key"].strip()
            patient_dir = row["patient_directory"].strip()
            pdf_filename = row["pdf_filename"].strip()

            if not patient_key or not patient_dir or not pdf_filename:
                skipped += 1
                continue

            doc = {
                "title": row["ai_generated_title"].strip() or pdf_filename,
                "category": row["category"].strip() or "Admin",
                "date": normalize_date(row["ai_extracted_date"]),
                "s3_key": f"patient_data/{patient_dir}/{pdf_filename}",
            }
            patients[patient_key].append(doc)

    print(f"Read {row_count} rows, skipped {skipped} incomplete rows.")
    print(f"Found {len(patients)} unique patients.")

    written = 0
    for patient_key, docs in patients.items():
        # Sort by date descending (ISO strings sort lexicographically)
        docs.sort(key=lambda d: d["date"], reverse=True)

        out_path = out_dir / f"{patient_key}.json"
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump({"documents": docs}, fh, indent=2, ensure_ascii=False)
        written += 1

    print(f"Wrote {written} patient index files to {out_dir}/")


if __name__ == "__main__":
    main()
