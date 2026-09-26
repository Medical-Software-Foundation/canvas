"""Policy storage over the plugin's own namespace.

Reads return every stored setting as text and writes upsert a batch. Text in both
directions on purpose, because that is what a form sends and what the coercion in
the composition root already expects, so this layer stores and returns without
interpreting anything.

Writes go through `filter().update()` and `create()` rather than assigning to a
field and calling save. Attribute assignment on a custom model is refused in the
plugin sandbox, so an upsert phrased the obvious way passes review and then fails
at runtime.

Storing into a dictionary has the same shape of trap. The sandbox rewrites
`target[key] = value` into a guarded write and names the key from the source
text, and it can only do that when the key is written as a plain name or a
literal. Any other expression, an f-string or an attribute among them, is named
`__unknown__`, which then trips the guard's own rule against keys beginning with
an underscore and refuses the assignment at runtime. Every dictionary write here
therefore names its key as a local first. The refusal never appears in a test,
because tests do not run inside the sandbox.
"""

from attendance_policy_tracker.models.policy_setting import PolicySetting


class NamespaceSettingsStore:
    """Policy settings stored in the plugin's own namespace."""

    def read(self) -> dict[str, str]:
        """Every stored setting, by name."""
        stored: dict[str, str] = {}
        for row in PolicySetting.objects.all():
            # The key is named as a plain local before the write. See the note
            # in this module's docstring about how the sandbox guards a
            # subscript assignment.
            key = f"{row.key}"
            stored[key] = f"{row.value}"
        return stored

    def write(self, values: dict[str, str]) -> None:
        """Store this batch, replacing whatever each name held before.

        A value arriving empty deletes its row rather than storing a blank. That
        is what makes clearing a field on the screen fall back to the shipped
        default, so a person who empties a field has a way back rather than a way
        to break the policy.
        """
        for key, value in values.items():
            text = f"{value}".strip()
            existing = PolicySetting.objects.filter(key=key)
            if not text:
                existing.delete()
                continue
            if existing.exists():
                existing.update(value=text)
            else:
                PolicySetting.objects.create(key=key, value=text)
