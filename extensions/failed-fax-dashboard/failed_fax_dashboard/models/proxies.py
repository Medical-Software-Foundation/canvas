"""Plugin-scoped proxies of the SDK models that the custom data tables point at."""

from canvas_sdk.v1.data import ModelExtension, Note, Staff


class StaffProxy(Staff, ModelExtension):
    """Staff, scoped to this plugin so reverse relations can't collide with other plugins."""


class NoteProxy(Note, ModelExtension):
    """Note, scoped to this plugin so reverse relations can't collide with other plugins."""
