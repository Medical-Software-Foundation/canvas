# HCC Capture Extension for Canvas

This Canvas extension facilitates the capture of HCC codes.

- Presents Care Gaps in the patient chart, with recommendations for CDI
  reviewers to validate them. Validation moves them to the Coding Gaps section
  in the patient summary for clinician review.
- Annotates diagnosis search results with an HCC tag based on a provided list.
  These tagged results guide coders to preferred codings.
- Annotates condition list items with an HCC tag based on a provided list,
  both in the patient summary and in the claim view.

## Problem it solves

Risk-adjusted HCC codes get missed because clinicians and coders cannot see which conditions carry an HCC while they document and code, and care gaps sit unvalidated until someone audits the chart. The manual workaround is a separate spreadsheet or after-visit review pass to reconcile diagnoses against an HCC reference list. This plugin puts the HCC tags and the open coding gaps directly in the chart, search, and claim so they are acted on during the visit.

## Configuration options

No configuration required.

## Installation

`canvas install hcc_capture`
