from canvas_sdk.v1.data import ModelExtension, Staff
from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    BooleanField,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    TextField,
    UniqueConstraint,
)


class CustomStaff(Staff, ModelExtension):
    """This plugin's handle on Staff, so reverse lookups stay private to the plugin."""


class Phrase(CustomModel):
    """A saved phrase a provider inserts by typing its code (for example .metf500).

    scope is "personal" (only the owner sees and edits it) or "practice" (everyone uses it; only
    members of the ADMIN_TEAM team change it). A personal phrase with the same code as a
    practice phrase is used instead of it, for that provider only.

    use_in is None for "all commands", or a list of command keys from catalog.NOTE_COMMANDS.
    Prescription fields are opt-in through rx_sig and rx_note_to_pharmacist, and are never
    included in "all commands".
    """

    code = TextField()
    text = TextField()
    scope = TextField(default="personal")
    owner = ForeignKey(CustomStaff, to_field="dbid", on_delete=DO_NOTHING, related_name="dot_phrases")
    use_in = JSONField(default=None, null=True)
    rx_sig = BooleanField(default=False)
    rx_note_to_pharmacist = BooleanField(default=False)
    archived = BooleanField(default=False)  # No longer set: phrases are deleted. Kept so existing tables still match.
    uses = IntegerField(default=0)
    last_used_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["code"]),
            Index(fields=["scope", "archived"]),
        ]


class PhraseFavorite(CustomModel):
    """A phrase a staff member starred. Starred phrases sort to the top of their chart panel."""

    staff = ForeignKey(CustomStaff, to_field="dbid", on_delete=DO_NOTHING, related_name="dot_phrase_favorites")
    phrase = ForeignKey(Phrase, to_field="dbid", on_delete=CASCADE, related_name="favorites")

    class Meta:
        constraints = [
            UniqueConstraint(fields=["staff", "phrase"], name="uq_dot_phrase_favorite"),
        ]


class PhraseHidden(CustomModel):
    """A practice phrase a staff member hid from their own chart panel list. Its code still works."""

    staff = ForeignKey(CustomStaff, to_field="dbid", on_delete=DO_NOTHING, related_name="dot_phrase_hidden")
    phrase = ForeignKey(Phrase, to_field="dbid", on_delete=CASCADE, related_name="hidden_by")

    class Meta:
        constraints = [
            UniqueConstraint(fields=["staff", "phrase"], name="uq_dot_phrase_hidden"),
        ]


class PracticeValue(CustomModel):
    """Practice info used as a placeholder in any phrase, like {after_hours_line}."""

    name = TextField()
    value = TextField(default="")
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["name"], name="uq_dot_phrase_practice_value"),
        ]


class PracticeSetting(CustomModel):
    """A practice-wide setting, like whether providers can copy phrase text."""

    key = TextField()
    value = JSONField(default=None, null=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["key"], name="uq_dot_phrase_setting"),
        ]
