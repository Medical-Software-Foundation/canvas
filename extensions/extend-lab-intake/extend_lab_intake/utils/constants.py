"""Secret key names and constants for the lab intake plugin."""


class Secrets:
    """Plugin secret key names."""

    EXTEND_AI_KEY = "EXTEND_AI_KEY"
    EXTEND_AI_PROCESSOR_TREE = "EXTEND_AI_PROCESSOR_TREE"
    ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
    AWS_ACCESS_KEY_ID = "AWS_ACCESS_KEY_ID"
    AWS_SECRET_ACCESS_KEY = "AWS_SECRET_ACCESS_KEY"
    FHIR_CLIENT_ID = "FHIR_CLIENT_ID"
    FHIR_CLIENT_SECRET = "FHIR_CLIENT_SECRET"
    INBOUND_FAX_TOKEN = "INBOUND_FAX_TOKEN"
    CALLBACK_URL = "CALLBACK_URL"


class S3Config:
    """S3 configuration constants."""

    BUCKET = "canvas-plugin-data"
    REGION = "us-west-2"


class Labels:
    """Task label constants."""

    LAB_INTAKE = "Lab Intake"


