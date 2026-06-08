# Psychiatry Questionnaires

Canvas plugin that installs three validated psychiatry screening questionnaires commonly used in behavioral health and psychiatric settings.

## Included Questionnaires

### ACE (Adverse Childhood Experiences)
- **LOINC Code**: 62378-5
- **Questions**: 10
- Screens for childhood adversity across 10 categories (abuse, neglect, household dysfunction)
- Scored 0-10; higher scores indicate greater cumulative childhood adversity

### C-SSRS (Columbia Suicide Severity Rating Scale)
- **LOINC Code**: 93373-2
- **Questions**: 17 (with conditional branching)
- Evidence-based suicide risk assessment with three sections: Suicidal Ideation, Intensity of Ideation, and Suicidal Behavior
- Uses conditional logic to show follow-up questions based on initial responses

### PCL-5 (PTSD Checklist for DSM-5)
- **LOINC Code**: 77040-1
- **Questions**: 20
- Self-report measure of PTSD symptoms mapped to DSM-5 criteria
- Scored 0-80; a score of 31-33 suggests probable PTSD diagnosis

## Installation

```
canvas install psychiatry_questionnaires
```

All three questionnaires will be available in charting after installation.
