"""The plugin's own storage for its policy.

A plugin cannot write its own installation variables, there is no effect for it,
so a configuration screen that saves needs storage the plugin owns. This is that
storage.

One row per setting, name and text, rather than a column per setting. Adding a
setting is then a default in code plus a control on the screen with nothing to
migrate. Clearing a field deletes its row, which is what lets blank mean use the
shipped default rather than storing something meaningless. And every value a form
sends is text anyway, so one text column keeps the coercion in a single place
instead of spreading it across typed columns.

This file has to sit in this package's `models` directory. The runner finds
custom models by globbing `models/*.py` and requires the module to resolve under
`{plugin}.models`, so it cannot live beside the rest of the Canvas adapter even
though that is where it otherwise belongs. That is the seam, and it is here
rather than hidden behind another layer.
"""

from django.db.models import TextField, UniqueConstraint

from canvas_sdk.v1.data.base import CustomModel


class PolicySetting(CustomModel):
    """One stored policy value, by name.

    The annotations are quoted on purpose. Django's field classes are not
    subscriptable at runtime, so the SDK example's bare `TextField[str, str]`
    only works under the lazy annotations that `from __future__ import
    annotations` provides, and that import is not on the plugin sandbox's
    allowed list. A quoted annotation is never evaluated, so it satisfies the
    type checker without asking the interpreter to subscript anything.
    """

    key: "TextField[str, str]" = TextField()
    value: "TextField[str, str]" = TextField()

    class Meta:
        constraints = [
            UniqueConstraint(fields=["key"], name="unique_policy_setting_key"),
        ]
