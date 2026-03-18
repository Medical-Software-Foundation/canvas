"""AWS S3 client for storing lab report PDFs."""

from datetime import UTC, datetime
from hashlib import sha256
from hmac import new as hmac_new
from http import HTTPStatus
from urllib.parse import quote, urlencode

import requests


class S3Client:
    """AWS S3 client using AWS Signature Version 4 authentication.

    Provides methods to upload PDFs and generate presigned URLs for Extend AI access.
    """

    ALGORITHM = "AWS4-HMAC-SHA256"

    def __init__(
        self,
        aws_key: str,
        aws_secret: str,
        bucket: str,
        region: str,
        instance: str,
    ) -> None:
        self.aws_key = aws_key
        self.aws_secret = aws_secret
        self.bucket = bucket
        self.region = region
        self.instance = instance

    def is_ready(self) -> bool:
        """Check if all required credentials are configured."""
        return bool(
            self.aws_key and self.aws_secret and self.bucket and self.region and self.instance
        )

    def _prefixed_key(self, object_key: str) -> str:
        """Add instance and plugin prefix to object key for isolation.

        S3 bucket policy requires objects to start with {instance}-plugins/
        """
        return f"{self.instance}-plugins/extend_lab_intake/{object_key}"

    def get_host(self) -> str:
        """Get the S3 bucket endpoint hostname."""
        return f"{self.bucket}.s3.{self.region}.amazonaws.com"

    def _get_signature_key(self, date_stamp: str) -> bytes:
        """Generate AWS Signature Version 4 signing key."""
        k_date = hmac_new(
            ("AWS4" + self.aws_secret).encode("utf-8"),
            date_stamp.encode("utf-8"),
            sha256,
        ).digest()
        k_region = hmac_new(k_date, self.region.encode("utf-8"), sha256).digest()
        k_service = hmac_new(k_region, b"s3", sha256).digest()
        k_signing = hmac_new(k_service, b"aws4_request", sha256).digest()
        return k_signing

    def _sign_request(
        self, amz_date: str, canonical_request: str
    ) -> tuple[str, str]:
        """Sign a canonical request and return credential scope and signature."""
        date_stamp = amz_date[:8]
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"

        k_signing = self._get_signature_key(date_stamp)

        string_to_sign = (
            f"{self.ALGORITHM}\n{amz_date}\n{credential_scope}\n"
            f"{sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )
        signature = hmac_new(
            k_signing, string_to_sign.encode("utf-8"), sha256
        ).hexdigest()

        return credential_scope, signature

    def _build_headers(
        self,
        object_key: str,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str = "",
    ) -> dict[str, str]:
        """Build authenticated headers for S3 requests."""
        host = self.get_host()
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        payload_hash = sha256(data or b"").hexdigest()
        canonical_uri = f"/{quote(object_key, safe='/')}"

        canonical_headers = (
            f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"

        if content_type:
            canonical_headers = f"content-type:{content_type}\n{canonical_headers}"
            signed_headers = f"content-type;{signed_headers}"

        canonical_request = (
            f"{method}\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        credential_scope, signature = self._sign_request(amz_date, canonical_request)
        authorization_header = (
            f"{self.ALGORITHM} Credential={self.aws_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization_header,
        }

        if content_type:
            headers["Content-Type"] = content_type

        return headers

    def upload_pdf(self, object_key: str, pdf_data: bytes) -> requests.Response:
        """Upload a PDF file to S3.

        Args:
            object_key: The key for the S3 object (will be prefixed automatically)
            pdf_data: The raw PDF bytes

        Returns:
            The response from S3
        """
        if not self.is_ready():
            response = requests.Response()
            response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
            response._content = b"S3 credentials not configured"
            return response

        prefixed_key = self._prefixed_key(object_key)
        content_type = "application/pdf"
        headers = self._build_headers(
            prefixed_key, method="PUT", data=pdf_data, content_type=content_type
        )
        headers["Content-Length"] = str(len(pdf_data))

        endpoint = f"https://{self.get_host()}/{quote(prefixed_key, safe='/')}"
        return requests.put(endpoint, headers=headers, data=pdf_data, timeout=60)

    def generate_presigned_url(self, object_key: str, expires_in: int = 3600) -> str:
        """Generate a presigned URL for downloading an object.

        Args:
            object_key: The key for the S3 object (will be prefixed automatically)
            expires_in: URL expiration time in seconds (default 1 hour)

        Returns:
            A presigned URL string
        """
        prefixed_key = self._prefixed_key(object_key)
        host = self.get_host()
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        credential = f"{self.aws_key}/{credential_scope}"

        canonical_uri = f"/{quote(prefixed_key, safe='/')}"

        query_params = {
            "X-Amz-Algorithm": self.ALGORITHM,
            "X-Amz-Credential": credential,
            "X-Amz-Date": amz_date,
            "X-Amz-Expires": str(expires_in),
            "X-Amz-SignedHeaders": "host",
        }
        canonical_querystring = urlencode(sorted(query_params.items()))

        canonical_headers = f"host:{host}\n"
        signed_headers = "host"
        payload_hash = "UNSIGNED-PAYLOAD"

        canonical_request = (
            f"GET\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        string_to_sign = (
            f"{self.ALGORITHM}\n{amz_date}\n{credential_scope}\n"
            f"{sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        k_signing = self._get_signature_key(date_stamp)
        signature = hmac_new(
            k_signing, string_to_sign.encode("utf-8"), sha256
        ).hexdigest()

        presigned_url = (
            f"https://{host}{canonical_uri}?"
            f"{canonical_querystring}&X-Amz-Signature={signature}"
        )

        return presigned_url

    def delete_object(self, object_key: str) -> requests.Response:
        """Delete an object from S3.

        Args:
            object_key: The key for the S3 object (will be prefixed automatically)

        Returns:
            The response from S3
        """
        if not self.is_ready():
            response = requests.Response()
            response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
            response._content = b"S3 credentials not configured"
            return response

        prefixed_key = self._prefixed_key(object_key)
        headers = self._build_headers(prefixed_key, method="DELETE")

        endpoint = f"https://{self.get_host()}/{quote(prefixed_key, safe='/')}"
        return requests.delete(endpoint, headers=headers, timeout=30)

    def list_objects(self, prefix: str = "", max_keys: int = 1000) -> list[dict]:
        """List objects in the S3 bucket with the given prefix.

        Args:
            prefix: Object key prefix to filter by (will be prefixed automatically)
            max_keys: Maximum number of objects to return

        Returns:
            List of object metadata dicts with keys: Key, Size, LastModified
        """
        import xml.etree.ElementTree as ET

        if not self.is_ready():
            return []

        prefixed_prefix = self._prefixed_key(prefix)
        host = self.get_host()
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        # Build query parameters
        query_params = {
            "list-type": "2",
            "prefix": prefixed_prefix,
            "max-keys": str(max_keys),
        }
        canonical_querystring = urlencode(sorted(query_params.items()))

        # Build canonical request for signing
        canonical_uri = "/"
        canonical_headers = f"host:{host}\nx-amz-content-sha256:UNSIGNED-PAYLOAD\nx-amz-date:{amz_date}\n"
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        payload_hash = "UNSIGNED-PAYLOAD"

        canonical_request = (
            f"GET\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )

        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = (
            f"{self.ALGORITHM}\n{amz_date}\n{credential_scope}\n"
            f"{sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        k_signing = self._get_signature_key(date_stamp)
        signature = hmac_new(
            k_signing, string_to_sign.encode("utf-8"), sha256
        ).hexdigest()

        authorization_header = (
            f"{self.ALGORITHM} Credential={self.aws_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Host": host,
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": authorization_header,
        }

        endpoint = f"https://{host}/?{canonical_querystring}"

        try:
            response = requests.get(endpoint, headers=headers, timeout=30)

            if response.status_code != HTTPStatus.OK:
                return []

            # Parse XML response
            root = ET.fromstring(response.content)
            # Handle XML namespace
            ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

            objects = []
            for content in root.findall(".//s3:Contents", ns):
                key_elem = content.find("s3:Key", ns)
                size_elem = content.find("s3:Size", ns)
                modified_elem = content.find("s3:LastModified", ns)

                if key_elem is not None:
                    # Strip the instance prefix from the key for cleaner display
                    full_key = key_elem.text or ""
                    instance_prefix = f"{self.instance}-plugins/extend_lab_intake/"
                    display_key = (
                        full_key[len(instance_prefix):]
                        if full_key.startswith(instance_prefix)
                        else full_key
                    )

                    objects.append({
                        "Key": display_key,
                        "Size": int(size_elem.text) if size_elem is not None and size_elem.text else 0,
                        "LastModified": modified_elem.text if modified_elem is not None else "",
                    })

            return objects

        except Exception:
            return []

    def upload_json(self, object_key: str, data: dict) -> requests.Response:
        """Upload a JSON object to S3.

        Args:
            object_key: The key for the S3 object (will be prefixed automatically)
            data: The dict to serialize and upload as JSON

        Returns:
            The response from S3
        """
        import json

        if not self.is_ready():
            response = requests.Response()
            response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
            response._content = b"S3 credentials not configured"
            return response

        json_bytes = json.dumps(data, indent=2).encode("utf-8")
        prefixed_key = self._prefixed_key(object_key)
        content_type = "application/json"
        headers = self._build_headers(
            prefixed_key, method="PUT", data=json_bytes, content_type=content_type
        )
        headers["Content-Length"] = str(len(json_bytes))

        endpoint = f"https://{self.get_host()}/{quote(prefixed_key, safe='/')}"
        return requests.put(endpoint, headers=headers, data=json_bytes, timeout=30)

    def get_json(self, object_key: str) -> dict | None:
        """Get a JSON object from S3.

        Args:
            object_key: The key for the S3 object (will be prefixed automatically)

        Returns:
            The parsed JSON dict, or None if not found or error
        """
        import json

        if not self.is_ready():
            return None

        prefixed_key = self._prefixed_key(object_key)
        headers = self._build_headers(prefixed_key, method="GET")

        endpoint = f"https://{self.get_host()}/{quote(prefixed_key, safe='/')}"

        try:
            response = requests.get(endpoint, headers=headers, timeout=30)

            if response.status_code == HTTPStatus.OK:
                return response.json()
        except Exception:
            pass

        return None

    def get_object(self, object_key: str) -> bytes | None:
        """Get an object's raw bytes from S3.

        Args:
            object_key: The key for the S3 object (will be prefixed automatically)

        Returns:
            The raw bytes, or None if not found or error
        """
        if not self.is_ready():
            return None

        prefixed_key = self._prefixed_key(object_key)
        headers = self._build_headers(prefixed_key, method="GET")

        endpoint = f"https://{self.get_host()}/{quote(prefixed_key, safe='/')}"

        try:
            response = requests.get(endpoint, headers=headers, timeout=60)

            if response.status_code == HTTPStatus.OK:
                return response.content
        except Exception:
            pass

        return None

    # Index management methods for document queue optimization

    def get_index(self) -> dict:
        """Get the document index from S3.

        Returns:
            The index dict with 'documents' list, or empty structure if not found
        """
        index = self.get_json("intake/index.json")
        if not index:
            return {"documents": []}
        return index

    def save_index(self, index: dict) -> bool:
        """Save the document index to S3.

        Args:
            index: The index dict to save

        Returns:
            True if successful, False otherwise
        """
        response = self.upload_json("intake/index.json", index)
        return response.status_code in (200, 201)

    def add_to_index(
        self,
        intake_id: str,
        filename: str,
        status: str,
        classification_type: str,
        received_at: str,
        size_bytes: int,
    ) -> bool:
        """Add a document to the index.

        Args:
            intake_id: Unique document identifier
            filename: Original filename
            status: Document status (classified, processed, no_extractor, saved)
            classification_type: Type from classification (e.g., lipid_panel)
            received_at: ISO timestamp of receipt
            size_bytes: File size in bytes

        Returns:
            True if successful, False otherwise
        """
        index = self.get_index()

        # Remove existing entry if present (for updates)
        index["documents"] = [
            d for d in index["documents"] if d.get("intake_id") != intake_id
        ]

        # Add new entry
        index["documents"].append({
            "intake_id": intake_id,
            "filename": filename,
            "status": status,
            "classification_type": classification_type,
            "received_at": received_at,
            "size_bytes": size_bytes,
        })

        return self.save_index(index)

    def update_index_status(self, intake_id: str, status: str) -> bool:
        """Update the status of a document in the index.

        Args:
            intake_id: Document identifier
            status: New status value

        Returns:
            True if successful, False otherwise
        """
        index = self.get_index()

        for doc in index["documents"]:
            if doc.get("intake_id") == intake_id:
                doc["status"] = status
                return self.save_index(index)

        return False

    def remove_from_index(self, intake_id: str) -> bool:
        """Remove a document from the index.

        Args:
            intake_id: Document identifier to remove

        Returns:
            True if successful, False otherwise
        """
        index = self.get_index()
        original_count = len(index["documents"])

        index["documents"] = [
            d for d in index["documents"] if d.get("intake_id") != intake_id
        ]

        if len(index["documents"]) < original_count:
            return self.save_index(index)

        return True  # Already not in index
