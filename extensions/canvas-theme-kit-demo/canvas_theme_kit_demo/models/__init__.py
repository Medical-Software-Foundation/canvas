"""Mirror of canvas_theme_kit's models, required to read the shared namespace.

**This file must stay byte-identical in substance to
`canvas_theme_kit/models/__init__.py`.** The Canvas SDK requires every plugin
sharing custom tables to declare identical model definitions; the `read_write`
plugin creates the tables and `read` plugins query them. A field that drifts
here does not fail loudly — it silently reads the wrong shape.

This plugin holds `access: "read"` on the namespace, so these models are
queried and never written. Any write would be rejected by the namespace
permission, which is the intended safety net rather than something to rely on.
"""


# Required: the field annotations below use django-stubs' generic forms
# (`TextField[str, str]`), which exist only in the stubs. Django's real field
# classes are not subscriptable, so without postponed evaluation these
# annotations raise `TypeError: type 'TextField' is not subscriptable` at import
# time and the plugin fails to load.
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import (
    CASCADE,
    BooleanField,
    DateTimeField,
    ForeignKey,
    Index,
    IntegerField,
    JSONField,
    TextField,
    UniqueConstraint,
)

from canvas_sdk.v1.data.base import CustomModel

# Fields carry explicit generic annotations because django-stubs makes Field
# generic while this project does not run the django-stubs mypy plugin (a Canvas
# plugin has no Django settings module of its own to point it at). Without the
# annotations mypy cannot infer the type parameters and reports every field as
# `var-annotated`.


class Theme(CustomModel):
    """A named theme: the editable draft plus pointers to its published history.

    The draft lives here and is mutable. Published content never does — it is
    snapshotted into `ThemeRevision` so a bad edit can be rolled back, which
    matters because one stylesheet is shared by every consuming plugin at once.
    """

    slug: TextField[str, str] = TextField(default="")
    title: TextField[str, str] = TextField(default="")
    is_default: BooleanField[bool, bool] = BooleanField(default=False)

    draft_css: TextField[str, str] = TextField(default="")
    draft_tokens: JSONField[Any, Any] = JSONField(default=dict)

    updated_at: DateTimeField[datetime, datetime] = DateTimeField(auto_now=True)
    updated_by: TextField[str, str] = TextField(default="")

    class Meta:
        constraints = [UniqueConstraint(fields=["slug"], name="uq_ctk_theme_slug")]
        indexes = [Index(fields=["is_default"])]

    def __str__(self) -> str:
        return self.slug


class ThemeRevision(CustomModel):
    """An immutable published snapshot of a `Theme`.

    Rollback republishes an earlier revision as a *new* revision rather than
    mutating or deleting one, so the audit trail of who published what stays
    complete.

    `is_active` marks the revision currently served for a theme. Exactly one
    revision per theme should carry it; that is enforced in `publish()` rather
    than by a database constraint, since the SDK's supported constraint set does
    not cover a conditional unique index.
    """

    theme: ForeignKey[Theme, Theme] = ForeignKey(
        Theme, on_delete=CASCADE, related_name="revisions"
    )
    revision: IntegerField[int, int] = IntegerField(default=1)

    css: TextField[str, str] = TextField(default="")
    tokens: JSONField[Any, Any] = JSONField(default=dict)
    content_hash: TextField[str, str] = TextField(default="")

    is_active: BooleanField[bool, bool] = BooleanField(default=False)
    published_at: DateTimeField[datetime, datetime] = DateTimeField(auto_now_add=True)
    published_by: TextField[str, str] = TextField(default="")
    note: TextField[str, str] = TextField(default="")

    class Meta:
        constraints = [
            UniqueConstraint(fields=["theme", "revision"], name="uq_ctk_theme_revision"),
        ]
        indexes = [Index(fields=["-published_at"])]

    def __str__(self) -> str:
        return f"{self.theme.slug}@{self.revision}"
