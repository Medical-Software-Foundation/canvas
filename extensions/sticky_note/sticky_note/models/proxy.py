from canvas_sdk.v1.data import ModelExtension, Patient, Staff


class PatientProxy(Patient, ModelExtension):
    """Proxy model to allow ForeignKey from CustomModel to Patient."""

    pass


class StaffProxy(Staff, ModelExtension):
    """Proxy model to allow ForeignKey from CustomModel to Staff."""

    pass
