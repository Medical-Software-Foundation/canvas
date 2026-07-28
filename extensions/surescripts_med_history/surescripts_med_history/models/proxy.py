from canvas_sdk.v1.data import ModelExtension, Patient


class PatientProxy(Patient, ModelExtension):
    """Proxy model so CustomModel ForeignKey can target Patient.dbid."""

    pass
