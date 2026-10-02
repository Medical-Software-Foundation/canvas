"""Proxy models enabling ForeignKeys from CustomModels to built-in Canvas models."""

from canvas_sdk.v1.data import ModelExtension, Staff


class StaffProxy(Staff, ModelExtension):
    """Proxy so a CustomModel can ForeignKey to Staff."""

    pass
