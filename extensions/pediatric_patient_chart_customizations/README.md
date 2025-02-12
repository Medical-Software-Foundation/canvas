# Pediatric Patient Chart Customizations

## Description

This extension provides examples of using a patient's data to customize their
chart with the goal of creating a more focused workspace for clinical users.
Use the context of the patient to surface the right choices more often and
minimize or eliminate irrelevant options.

### Components

1. `protocols/pediatric_chart_layout.py` - Rearranges the patient summary
   section to show immunizations first for patients under the age of 18.
2. `protocols/pediatric_condition_search.py` - Suppresses search results
   containing diagnosis codes that are clinically irrelevant for patients
   under the age of 15. See: [CMS: ICD-10 Dx Edit Code Lists](https://www.cms.gov/Medicare/Coding/OutpatientCodeEdit/Downloads/ICD-10-IOCE-Code-Lists.pdf)
