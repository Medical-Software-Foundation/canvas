# LOINC codes for averaged vital signs
VITAL_SIGNS = {
    "hr": {"code": "103205-1", "display": "Mean heart rate", "units": "{beats}/min"},
    "resp": {"code": "103217-6", "display": "Mean respiratory rate", "units": "/min"},
    "spo2": {"code": "103209-3", "display": "Mean oxygen saturation", "units": "%"},
}

# Blood pressure panel with components
BP_PANEL = {
    "code": "96607-7",
    "display": "Blood pressure panel mean systolic and mean diastolic",
}
BP_COMPONENTS = {
    "sys": {"code": "96608-5", "display": "Systolic blood pressure mean", "units": "mm[Hg]"},
    "dia": {"code": "96609-3", "display": "Diastolic blood pressure mean", "units": "mm[Hg]"},
}

# All LOINC codes for filtering observations
ALL_VITAL_CODES = (
    {info["code"] for info in VITAL_SIGNS.values()} |
    {BP_PANEL["code"]}
)
