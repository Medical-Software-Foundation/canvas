"""Document queue application for viewing received lab report PDFs."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string

from extend_lab_intake.utils.constants import Secrets, S3Config
from extend_lab_intake.utils.hmac_auth import generate_session_token
from extend_lab_intake.utils.s3_client import S3Client


class DocumentQueueApplication(Application):
    """Application to view and manage received lab report PDFs.

    Displays a table of documents received via the inbound-fax endpoint,
    with classification info and actions to extract or discard each document.
    """

    def on_open(self) -> Effect:
        """Handle the on_open event - launch the document queue modal."""
        # Get list of documents from S3 with metadata
        documents = self._get_documents()

        # Generate a time-limited session token for frontend authentication
        # The token is signed with HMAC-SHA256 and expires after 5 minutes
        # This is more secure than passing the raw API token because:
        # 1. The token has a built-in expiry timestamp
        # 2. The signature prevents tampering
        # 3. Even if captured, it cannot be used after expiry
        api_secret = self.secrets.get(Secrets.INBOUND_FAX_TOKEN, "")
        session_token = generate_session_token(api_secret) if api_secret else ""
        instance = self.environment.get("CUSTOMER_IDENTIFIER", "unknown")

        # Render the HTML template with document data
        html_content = render_to_string(
            "templates/document_queue.html",
            {
                "documents": documents,
                "session_token": session_token,
                "instance": instance,
            },
        )

        return LaunchModalEffect(
            content=html_content,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Lab Parser",
        ).apply()

    def _get_documents(self) -> list[dict]:
        """Retrieve list of documents from S3 index.

        Reads only the index file for fast initial load. Full document details
        (classification, extraction, presigned URL) are fetched on-demand when
        a row is expanded.

        Returns:
            List of document summary dicts with keys:
            - intake_id: Unique document identifier
            - filename: Original filename
            - status: classified | processed | no_extractor | saved
            - classification_type: Type from classification (e.g., lipid_panel)
            - received_at: Upload timestamp (ISO format)
            - size_bytes: File size in bytes
            - size_display: Human-readable size
        """
        try:
            s3_client = S3Client(
                aws_key=self.secrets.get(Secrets.AWS_ACCESS_KEY_ID, ""),
                aws_secret=self.secrets.get(Secrets.AWS_SECRET_ACCESS_KEY, ""),
                bucket=S3Config.BUCKET,
                region=S3Config.REGION,
                instance=self.environment.get("CUSTOMER_IDENTIFIER", "unknown"),
            )

            # Read the index file - single S3 request
            index = s3_client.get_index()

            documents = []
            for doc in index.get("documents", []):
                size_bytes = doc.get("size_bytes", 0)
                documents.append({
                    "intake_id": doc.get("intake_id", ""),
                    "filename": doc.get("filename", ""),
                    "status": doc.get("status", "unknown"),
                    "classification_type": doc.get("classification_type", "unknown"),
                    "received_at": doc.get("received_at", ""),
                    "size_bytes": size_bytes,
                    "size_display": self._format_size(size_bytes),
                })

            # Sort by received_at descending (most recent first)
            documents.sort(key=lambda d: d["received_at"], reverse=True)

            return documents

        except Exception as e:
            from logger import log
            log.error(f"Failed to get document index from S3: {e}")
            return []

    def _format_size(self, size_bytes: int) -> str:
        """Format byte size as human-readable string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
