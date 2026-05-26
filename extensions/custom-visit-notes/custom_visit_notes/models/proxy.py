from canvas_sdk.v1.data import ModelExtension, Note


class NoteProxy(Note, ModelExtension):
    """Proxy model to link CustomModels to Note via OneToOneField."""

    ...
