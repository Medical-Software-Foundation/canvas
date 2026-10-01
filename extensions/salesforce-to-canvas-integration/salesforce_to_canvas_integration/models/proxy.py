"""ModelExtension proxies so foreign keys resolve to Canvas Patient and Staff.

The proxies target the dbid join key. Custom models point their foreign keys at
these rather than at Patient and Staff directly, following the established repo
pattern in rx_history and the custom data room booking example.
"""

from canvas_sdk.v1.data import ModelExtension, Patient, Staff


class PatientProxy(Patient, ModelExtension):
    pass


class StaffProxy(Staff, ModelExtension):
    pass
