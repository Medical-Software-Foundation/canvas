develop_health_ai_prior_auth
============================

## What it does

This plugin connects Canvas to Develop Health to verify medication benefits and run prior authorizations. It watches for questionnaire command activity and coverage changes in a patient chart and uses the Develop Health service to check what a medication will cost under the patient's plan and to handle the prior authorization paperwork for medications that require approval.

## Problem it solves

Checking a medication's coverage and getting prior authorization is slow manual work: staff call payers, fill out forms, and wait on hold to learn whether a drug is covered and what the patient will owe. This plugin moves that checking and form handling to the Develop Health service so the work happens against the chart instead of over the phone.

## Who it's for

Prescribers and the pharmacy or prior authorization staff who handle medication coverage and approvals for patients.

## How to install

```
canvas install develop_health_ai_prior_auth
```

This plugin requires secrets to function. Set the values described under Configuration options before use.

## Configuration options

Set these secrets in the plugin settings:

- `DEVELOP_HEALTH_API_BASE_URL`: base URL of the Develop Health API.
- `DEVELOP_HEALTH_API_KEY`: API key for authenticating to Develop Health.
- `DEVELOP_HEALTH_DRUG_LIST`: the drug list that scopes which medications are checked.

## Description

A description of this plugin

### Important Note!

The CANVAS_MANIFEST.json is used when installing your plugin. Please ensure it
gets updated if you add, remove, or rename protocols.
