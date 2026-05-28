"""`get_today` chat tool: resolve relative dates by returning today's ISO date."""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict


class GetTodayArgs(BaseModel):
    """Arguments for the `get_today` chat tool (none)."""

    model_config = ConfigDict(extra="forbid")


def get_today(instance: Any, args: GetTodayArgs) -> dict:
    """Handler for the `get_today` chat tool."""
    return {"date": date.today().isoformat()}

TOOL_SPEC = {
    "name": "get_today",
    "description": "Returns today's date in ISO format (YYYY-MM-DD). Call this when you need "
    "to resolve relative dates like 'today', 'this week', 'next month'.",
    "args_model": GetTodayArgs,
    "handler": get_today,
    "mutates": False,
}
