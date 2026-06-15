"""Read-only custom command holding one questionnaire's frozen trend."""

from __future__ import annotations

from canvas_sdk.commands.commands.custom_command import CustomCommand


class ScoringTrendCommand(CustomCommand):
    """One questionnaire's static chart + metrics, inserted into a note."""

    class Meta:
        schema_key = "scoringTrend"
