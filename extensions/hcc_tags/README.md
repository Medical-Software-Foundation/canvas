# HCC Tags Extension for Canvas

This Canvas extension tags HCC diagnoses so they are visible while documenting and coding. It is an alternative to `hcc_capture` that installs only the HCC tags; `hcc_capture` also adds a protocol card for validating coding gaps.

- Annotates condition search results with an HCC tag based on a provided list, in the Diagnose, Past Medical History, Add Condition, and Assess commands.
  These tagged results guide coders to preferred codings.
- Annotates condition list items with an HCC tag based on a provided list,
  both in the patient summary and in the claim view.

## Problem it solves

Risk-adjusted HCC codes get missed because clinicians and coders cannot see which conditions carry an HCC while they document and code. The manual workaround is a separate spreadsheet or after-visit review pass to reconcile diagnoses against an HCC reference list. This plugin puts the HCC tags directly in the chart, search, and claim so they are acted on during the visit.

## Configuration options

No configuration required.

## Installation

`canvas install hcc_tags`
