# BMI Coding Automation

## Description

Body mass index (BMI) provides a quick and easy way to estimate body fat based on height and weight and is often used as a screening tool to identify potential health risks associated with being underweight, overweight, or obese. ICD-10 Z codes describe factors influencing a person's health status, contact with health services, and social determinants of health. These codes are used to provide additional information about an encounter with a healthcare provider, especially when the reason for visit is not a disease or injury. Z68 codes are specifically designated for BMI.

For any patient 20 years or older, the BMI Coding Automation extension will automatically add and commit the corresponding ICD-10 Z code to the patient chart based on the BMI calculated from the patient's entered height and weight.

If patient has an existing Z68 code, the extension will update existing diagnosis code, making it easy to track progress over time.

## Problem it solves

BMI Z68 codes are easy to forget and tedious to look up by hand, so they often go unrecorded even when the height and weight are already in the chart. This plugin replaces the manual step of calculating BMI and matching it to the correct Z68 code, recording the diagnosis from the vitals already entered.

## Who it's for

Prescribers and clinical staff who document vitals and want BMI Z68 codes recorded consistently for patients 20 and older, and the billing and coding staff who rely on those codes.

## How to install

```
canvas install bmi_coding_automation
```

The SDK commands for vitals, updateDiagnosis, and diagnose must be enabled on the instance.

### Important Note!

The SDK Command needs to be turned for vitals, updateDiagnosis, and diagnose
