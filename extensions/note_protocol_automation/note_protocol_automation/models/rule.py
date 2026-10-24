"""Config storage: one Rule per note-type protocol. Predicates and commands are
stored as JSON strings in TextFields (CustomModel JSONField is unproven in the
sandbox; TextField + json keeps migrations trivial)."""

import json

from django.db.models import BooleanField, IntegerField, TextField

from canvas_sdk.v1.data.base import CustomModel


class Rule(CustomModel):
    """A note-type protocol rule. `predicates`/`commands` hold JSON strings."""

    name: TextField = TextField()
    note_type_id: TextField = TextField()  # NoteType.unique_identifier (string)
    enabled: BooleanField = BooleanField(default=True)
    match: TextField = TextField(default="all")  # "all" (AND) or "any" (OR)
    predicates: TextField = TextField(default="[]")
    commands: TextField = TextField(default="[]")
    priority: IntegerField = IntegerField(default=0)

    def predicate_list(self) -> list[dict]:
        """Parse the predicates JSON string into a list of predicate dicts."""
        parsed: list[dict] = json.loads(self.predicates or "[]")
        return parsed

    def command_list(self) -> list[str]:
        """Parse the commands JSON string into a list of catalog keys."""
        parsed: list[str] = json.loads(self.commands or "[]")
        return parsed

    def set_predicates(self, value: list[dict]) -> None:
        """Serialize a list of predicate dicts into the predicates field."""
        self.predicates = json.dumps(value)

    def set_commands(self, value: list[str]) -> None:
        """Serialize a list of command catalog keys into the commands field."""
        self.commands = json.dumps(value)
