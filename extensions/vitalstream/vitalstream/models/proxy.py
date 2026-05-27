from canvas_sdk.v1.data import ModelExtension
from canvas_sdk.v1.data.note import Note


class NoteProxy(Note, ModelExtension):
    """Proxy model to allow ForeignKey from CustomModel to Note."""

    pass
