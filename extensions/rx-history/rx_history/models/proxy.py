from canvas_sdk.v1.data import ModelExtension, Patient, Staff


class PatientProxy(Patient, ModelExtension):
    pass


class StaffProxy(Staff, ModelExtension):
    pass
