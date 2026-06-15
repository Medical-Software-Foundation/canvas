# Pediatric Patient Chart Customizations

## Description

This extension provides examples of using a patient's data to customize their
chart with the goal of creating a more focused workspace for clinical users.
Use the context of the patient to surface the right choices more often and
minimize or eliminate irrelevant options.

## Who it's for

Pediatricians and pediatric clinic staff who chart on patients under 18, and plugin developers who want a worked example of tailoring chart layout and search results to a patient's age.

## How to install

```
canvas install pediatric_patient_chart_customizations
```

## Configuration options

No configuration required.

### Components

1. `protocols/pediatric_chart_layout.py` - Rearranges the patient summary
   section to show immunizations first for patients under the age of 18.
2. `protocols/pediatric_condition_search.py` - Suppresses search results
   containing diagnosis codes that are clinically irrelevant for patients
   under the age of 15. See: [CMS: ICD-10 Dx Edit Code Lists](https://www.cms.gov/Medicare/Coding/OutpatientCodeEdit/Downloads/ICD-10-IOCE-Code-Lists.pdf)
