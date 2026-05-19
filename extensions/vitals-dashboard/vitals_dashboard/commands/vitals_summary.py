from canvas_sdk.commands.commands.custom_command import CustomCommand


class VitalsSummaryCommand(CustomCommand):
    """Read-only vitals session summary embedded in the Vitals note."""

    class Meta:
        key = "customCommand"
        schema_key = "vitalsSummary"
