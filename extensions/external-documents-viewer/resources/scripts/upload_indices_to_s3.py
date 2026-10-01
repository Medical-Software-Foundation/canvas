"""Upload generated patient-indices/ JSON files to S3.

Usage:
    uv run python scripts/upload_indices_to_s3.py \
        --bucket canvas-plugin-data \
        --prefix legacy_emr_documents \
        --region us-west-2 \
        --indices-dir patient-indices
"""

import argparse
import os
import sys
from pathlib import Path

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload document index files to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--prefix", required=True, help="S3 key prefix (e.g. legacy_emr_documents)")
    parser.add_argument("--region", default="us-west-2", help="AWS region")
    parser.add_argument("--indices-dir", type=Path, default=Path("patient-indices"), help="Local directory with JSON files")
    args = parser.parse_args()

    indices_dir: Path = args.indices_dir
    if not indices_dir.exists():
        print(f"ERROR: Directory not found: {indices_dir}", file=sys.stderr)
        sys.exit(1)

    json_files = sorted(indices_dir.glob("*.json"))
    if not json_files:
        print(f"ERROR: No JSON files found in {indices_dir}", file=sys.stderr)
        sys.exit(1)

    prefix = args.prefix.strip("/")
    print(f"Uploading {len(json_files)} files to s3://{args.bucket}/{prefix}/patient-indices/")

    s3 = boto3.client("s3", region_name=args.region)

    uploaded = 0
    for f in json_files:
        s3_key = f"{prefix}/patient-indices/{f.name}"
        s3.upload_file(str(f), args.bucket, s3_key, ExtraArgs={"ContentType": "application/json"})
        uploaded += 1
        if uploaded % 100 == 0:
            print(f"  Uploaded {uploaded}/{len(json_files)}...")

    print(f"Done. Uploaded {uploaded} files to s3://{args.bucket}/{prefix}/patient-indices/")


if __name__ == "__main__":
    main()
