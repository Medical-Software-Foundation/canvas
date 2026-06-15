# Psychiatry Questionnaires

Canvas plugin that installs two validated psychiatry screening questionnaires commonly used in behavioral health and psychiatric settings.

## Problem it solves

Standing up validated screening instruments like ACE and PCL-5 by hand means rebuilding each question, response option, LOINC code, and scoring rule in the questionnaire editor. This plugin ships both instruments preconfigured so they are available in charting right after install, with no manual setup.

## Configuration options

No configuration required.

## Included Questionnaires

### ACE (Adverse Childhood Experiences)
- **LOINC Code**: 62378-5
- **Questions**: 10
- Screens for childhood adversity across 10 categories (abuse, neglect, household dysfunction)
- Scored 0-10; higher scores indicate greater cumulative childhood adversity

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
