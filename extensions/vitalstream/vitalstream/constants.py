# Treatment intervals for timed vitals capture.
# Labels must match the Spravato charting app's DEFAULT_ROWS exactly
# so that vitals saved from VitalStream prepopulate the edit form.
TREATMENT_INTERVALS = ["Pre-administration", "40-min post", "Pre-discharge"]

# Standard LOINC codes for per-interval vital sign observations
LOINC_HR = "8867-4"
LOINC_BP_PANEL = "85354-9"
LOINC_BP_SYS = "8480-6"
LOINC_BP_DIA = "8462-4"
LOINC_SPO2 = "2708-6"
LOINC_RR = "9279-1"

# Mean LOINC codes for summary (averaged) vital sign observations
LOINC_HR_MEAN = "103205-1"
LOINC_BP_PANEL_MEAN = "96607-7"
LOINC_BP_SYS_MEAN = "96608-5"
LOINC_BP_DIA_MEAN = "96609-3"
LOINC_SPO2_MEAN = "103209-3"
LOINC_RR_MEAN = "103217-6"

# All LOINC codes for filtering observations
ALL_VITAL_CODES = {LOINC_HR, LOINC_BP_PANEL, LOINC_SPO2, LOINC_RR}
