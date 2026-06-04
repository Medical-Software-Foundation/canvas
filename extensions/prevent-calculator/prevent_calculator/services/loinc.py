"""LOINC code constants for PREVENT inputs and risk-score outputs."""

from typing import Optional

# Input codes — used to find existing observations on the chart to pre-fill.
LOINC_TOTAL_CHOLESTEROL = "2093-3"  # Cholesterol [Mass/volume] in Serum or Plasma
LOINC_HDL_CHOLESTEROL = "2085-9"  # Cholesterol in HDL [Mass/volume]
LOINC_SYSTOLIC_BP = "8480-6"  # Systolic blood pressure
LOINC_DIASTOLIC_BP = "8462-4"  # Diastolic blood pressure
LOINC_BP_PANEL = "85354-9"  # Blood pressure panel (Canvas's native BP storage)
LOINC_BMI = "39156-5"  # Body mass index
LOINC_BODY_HEIGHT = "8302-2"  # Body height
LOINC_BODY_WEIGHT = "29463-7"  # Body weight
LOINC_EGFR_2021 = "98979-8"  # GFR estimated by CKD-EPI 2021
LOINC_EGFR_LEGACY = "48642-3"  # GFR estimated by CKD-EPI 2009 (fallback)
# Canvas Tobacco questionnaire stores responses against LOINC 39240-7; the
# legacy CCDA template also references 72166-2. Both are accepted on read.
LOINC_TOBACCO_USE_STATUS = "39240-7"
LOINC_SMOKING_STATUS = "72166-2"
LOINC_HBA1C = "4548-4"  # Hemoglobin A1c/Hemoglobin.total in Blood
LOINC_UACR = "9318-7"  # Albumin/Creatinine [Mass Ratio] in Urine

INPUT_LOINCS = {
    "total_cholesterol": (LOINC_TOTAL_CHOLESTEROL,),
    "hdl_cholesterol": (LOINC_HDL_CHOLESTEROL,),
    "systolic_bp": (LOINC_SYSTOLIC_BP,),
    "bmi": (LOINC_BMI,),
    "body_height": (LOINC_BODY_HEIGHT,),
    "body_weight": (LOINC_BODY_WEIGHT,),
    "egfr": (LOINC_EGFR_2021, LOINC_EGFR_LEGACY),
    "smoking_status": (LOINC_TOBACCO_USE_STATUS, LOINC_SMOKING_STATUS),
    "hba1c": (LOINC_HBA1C,),
    "uacr": (LOINC_UACR,),
}

# Output codes — used when writing the calculated PREVENT scores back as
# Observations. LOINC has not yet published codes specific to the AHA
# PREVENT model (2024); the codes below are the closest semantic matches
# for the two outputs that have an established mapping. The remaining
# four scores are saved with display name only (no coding) so they
# still surface in the chart's lab section and can be matched by name.
LOINC_10YR_TOTAL_CVD_RISK: Optional[str] = "97506-9"  # Cardiovascular disease 10Y risk [%] (AHA-ACC ASCVD)
LOINC_10YR_ASCVD_RISK: Optional[str] = "79423-0"  # ASCVD 10-year risk score predicted
LOINC_10YR_HF_RISK: Optional[str] = None  # No widely-adopted LOINC mapping yet
LOINC_30YR_TOTAL_CVD_RISK: Optional[str] = None  # No widely-adopted LOINC mapping yet
LOINC_30YR_ASCVD_RISK: Optional[str] = None  # No widely-adopted LOINC mapping yet
LOINC_30YR_HF_RISK: Optional[str] = None  # No widely-adopted LOINC mapping yet
