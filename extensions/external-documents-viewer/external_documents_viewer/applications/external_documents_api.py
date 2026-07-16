from http import HTTPStatus
from urllib.parse import unquote

from canvas_sdk.clients.aws.libraries import S3
from canvas_sdk.clients.aws.structures import Credentials as S3Credentials
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from logger import log


class ExternalDocumentsAPI(StaffSessionAuthMixin, SimpleAPI):
    """SimpleAPI providing presigned URL endpoint for external document viewing."""

    def _s3_client(self) -> S3:
        return S3(
            S3Credentials(
                key=self.secrets["S3_KEY"],
                secret=self.secrets["S3_SECRET"],
                region=self.secrets["S3_REGION"],
                bucket=self.secrets["S3_BUCKET"],
            )
        )

    @api.get("/document-url/<s3_key>")
    def get_document_url(self) -> list[Response | Effect]:
        s3_key = self.request.path_params["s3_key"]
        decoded_key = unquote(s3_key)

        prefix = self.secrets.get("S3_PREFIX", "").strip().rstrip("/")
        full_key = f"{prefix}/{decoded_key}" if prefix else decoded_key

        try:
            client = self._s3_client()
            if not client.is_ready():
                log.error("S3 client not ready for presigned URL generation")
                return [JSONResponse({"error": "S3 connection failed"}, status_code=HTTPStatus.SERVICE_UNAVAILABLE)]

            presigned_url = client.generate_presigned_url(full_key, expiration=3600)
            return [JSONResponse({"url": presigned_url}, status_code=HTTPStatus.OK)]
        except Exception as e:
            # Log full detail server-side, but return a generic message so raw
            # exception text (which may reference bucket/key names) is never
            # echoed back to the caller.
            log.error(f"Error generating presigned URL for {decoded_key}: {e}")
            return [
                JSONResponse(
                    {"error": "Unable to generate document link."},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]
