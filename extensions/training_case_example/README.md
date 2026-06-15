Training Case Example
=====================

## Description

The `training_case_example` extension shows how to define a clinical case programmatically so it can be replicated consistently, effortlessly, and with time-dynamic values.

## What it does

When a new patient is created, this extension checks the patient's last name. If it matches a known training case, the extension creates a note for that patient and fills it with predefined chart data. The included Afib case adds a reason for visit, a history of present illness, and abnormal vitals so the chart looks like a real atrial fibrillation presentation.

## Problem it solves

Building realistic practice charts by hand is slow and inconsistent. Each person doing a training or demo setup enters slightly different data, and the values do not stay current over time. This extension generates the same case the same way every time from code, removing the manual data entry.

## Who it's for

Teams building training environments and demo instances - implementation staff, sales engineers, and anyone preparing Canvas instances who needs repeatable example patient charts.

## How to install

```bash
canvas install training_case_example
```

This extension reads secrets to call the Note API and related services. Set them before use (see Configuration options).

## Configuration options

This extension declares these secrets in its manifest:

- `CLIENT_ID` and `CLIENT_SECRET` - credentials used to authenticate to the Note API when creating the case note.
- `FHIR_BASE_URL` and `FHIR_API_KEY` - base URL and key for FHIR access.
- `OPENAI_API_KEY` - key for OpenAI access.

## Usage

There are many different ways to trigger creation of a new patient case. For this example, we're going respond to new patient creation event created manually by a user, and the patient's last name will define the case that will be generated. Currently implemented cases are:
- Afib: Generated when the patient's last name starts with "Case-Afib"
