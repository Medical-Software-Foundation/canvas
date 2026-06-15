"""Stable codes for the Sleep Study Result questionnaire and an existing
Epworth Sleepiness Scale questionnaire.

Per Canvas best practice, look up questionnaires by (code_system, code) — never
by name or database ID — so the plugin works across environments.
"""

# Sleep Study Result questionnaire (created by this plugin)
SLEEP_STUDY_QUESTIONNAIRE_CODE_SYSTEM = "INTERNAL"
SLEEP_STUDY_QUESTIONNAIRE_CODE = "SLEEP-STUDY-RESULT"

# Question codes within the Sleep Study Result questionnaire
Q_STUDY_DATE = "SLEEP-STUDY-DATE"
Q_AHI = "SLEEP-STUDY-AHI"
Q_RDI = "SLEEP-STUDY-RDI"
Q_ODI = "SLEEP-STUDY-ODI"
Q_SEVERITY = "SLEEP-STUDY-SEVERITY"
Q_EPWORTH = "SLEEP-STUDY-EPWORTH"

# Severity response option codes → user-facing label
SEVERITY_OPTION_TO_LABEL = {
    "SLEEP-STUDY-SEVERITY-NORMAL": "Normal",
    "SLEEP-STUDY-SEVERITY-MILD": "Mild",
    "SLEEP-STUDY-SEVERITY-MODERATE": "Moderate",
    "SLEEP-STUDY-SEVERITY-SEVERE": "Severe",
}

# Existing Epworth Sleepiness Scale questionnaire (identified by LOINC code).
# The plugin doesn't create this — it only queries responses for the trend modal.
EPWORTH_QUESTIONNAIRE_CODE_SYSTEM = "LOINC"
EPWORTH_QUESTIONNAIRE_CODE = "69732-3"
