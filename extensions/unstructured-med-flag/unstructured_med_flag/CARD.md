# Unstructured Medication Flag

Surface free-text medications that can't be prescribed electronically, so clinicians catch and fix them before they cause problems.

![Medications section showing coded medications on top and a flagged "Unstructured Medications (free text)" group below](https://raw.githubusercontent.com/Medical-Software-Foundation/canvas/main/extensions/unstructured-med-flag/unstructured_med_flag/screenshots/medication-list.png)

## The problem

Some medications get entered as free text with no drug code behind them, often carried over from a data migration out of another EMR. Those entries can't be sent to a pharmacy electronically, they break drug-interaction checking, and they don't report correctly. Today the only cue is lighter-grey text and a hover tooltip, which is easy to miss in a long list. Clinicians often find out only when an e-prescribe attempt fails in the middle of a visit.

## What it does

Pulls every free-text medication into its own clearly labeled group in the patient chart, right under the properly coded ones, with a "⚠️ Unstructured Medications (free text)" heading. The gap becomes obvious at a glance, prompting the clinician to re-enter the medication with a real drug code. If every medication is already coded, the list looks exactly as it does today.

## Who it's for

Care teams that depend on accurate medication data - anyone using e-prescribing, drug-interaction checking, or medication reporting. It is especially useful for organizations migrating patient records from another EMR.

## Good to know

- No setup or configuration. Install it and it works.
- It only reorganizes how medications display. It never changes, hides, or deletes a medication.
