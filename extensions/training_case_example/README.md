Training Case Example
=====================

## Description

The `training_case_example` extension shows how to define a clinical case programmatically so it can be replicated consistently, effortlessly, and with time-dynamic values.

## Usage

There are many different ways to trigger creation of a new patient case. For this example, we're going respond to new patient creation event created manually by a user, and the patient's last name will define the case that will be generated. Currently implemented cases are:
- Afib: Generated when the patient's last name starts with "Case-Afib"
