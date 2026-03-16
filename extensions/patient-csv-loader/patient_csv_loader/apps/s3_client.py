"""S3 upload client using canvas_sdk.utils.Http with AWS Signature V4.

Uploads CSV files to S3 for audit trail purposes. Uses the Canvas SDK's
built-in Http utility since boto3 is not available in the plugin sandbox.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from canvas_sdk.utils import Http
from logger import log


_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _percent_encode(s: str) -> str:
    """Percent-encode a URI path segment (RFC 3986 unreserved chars kept)."""
    encoded: list[str] = []
    for ch in s:
        if ch in _UNRESERVED:
            encoded.append(ch)
        else:
            for byte in ch.encode("utf-8"):
                encoded.append(f"%{byte:02X}")
    return "".join(encoded)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "aws4_request")
    return k_signing


def upload_csv_to_s3(
    csv_content: str,
    filename: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    region: str = "us-east-1",
) -> bool:
    """Upload CSV content to S3 using HTTP PUT with AWS Signature V4.

    The file is stored at: s3://{bucket}/patient-csv-uploads/{timestamp}_{filename}

    Args:
        csv_content: The raw CSV text to upload.
        filename: Original filename from the upload.
        bucket: S3 bucket name.
        access_key_id: AWS access key ID.
        secret_access_key: AWS secret access key.
        region: AWS region (default us-east-1).

    Returns:
        True if upload succeeded, False otherwise.
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    # Build the S3 object key
    safe_filename = filename.replace(" ", "_")
    object_key = f"patient-csv-uploads/{date_stamp}/{timestamp}_{safe_filename}"

    # Encode the body
    body = csv_content.encode("utf-8")
    payload_hash = _sha256(body)

    # S3 host
    host = f"{bucket}.s3.{region}.amazonaws.com"
    encoded_key = "/".join(_percent_encode(part) for part in object_key.split("/"))
    url = f"https://{host}/{encoded_key}"

    # Canonical request components
    method = "PUT"
    canonical_uri = "/" + encoded_key
    canonical_querystring = ""

    headers_to_sign = {
        "content-type": "text/csv",
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": timestamp,
    }

    canonical_headers = ""
    for key in sorted(headers_to_sign):
        canonical_headers = canonical_headers + f"{key}:{headers_to_sign[key]}\n"

    signed_headers = ";".join(sorted(headers_to_sign))

    canonical_request = "\n".join([
        method,
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    # String to sign
    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        algorithm,
        timestamp,
        credential_scope,
        _sha256(canonical_request.encode("utf-8")),
    ])

    # Signing key and signature
    signing_key = _get_signing_key(secret_access_key, date_stamp, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    # Authorization header
    authorization = (
        f"{algorithm} Credential={access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    request_headers = {
        "Authorization": authorization,
        "Content-Type": "text/csv",
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": timestamp,
    }

    try:
        http = Http()
        response = http.put(url, headers=request_headers, data=body)
        if response.ok:
            log.info(f"Patient CSV Loader: uploaded CSV to s3://{bucket}/{object_key}")
            return True
        else:
            log.error(
                f"Patient CSV Loader: S3 upload failed — "
                f"status={response.status_code} body={response.text[:200]}"
            )
            return False
    except Exception as exc:
        log.error(f"Patient CSV Loader: S3 upload error — {exc}")
        return False
