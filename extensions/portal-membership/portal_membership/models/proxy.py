from canvas_sdk.v1.data import ModelExtension, Patient


class PatientProxy(Patient, ModelExtension):
    """Proxy model so CustomModels can declare a ForeignKey to Patient."""

    pass
