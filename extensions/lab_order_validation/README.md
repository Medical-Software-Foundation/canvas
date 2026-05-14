# Lab Order Validation

Pre-flight validation for lab orders bound for electronic transmission (Health Gorilla).

## What it does

When a clinician clicks **Sign and Send** on a lab order whose selected lab partner has `electronic_ordering_enabled = True`, this plugin runs five data-state checks. If any fail, the commit is blocked with a clear, fixable error message naming the field that needs attention. Manual or paper labs are skipped - the plugin only fires for electronic orders.

## Problem it solves

Health Gorilla rejects orders when a patient's insurance, payer, or address data is missing or malformed. Today the rejection happens silently downstream, after the order has already left the chart. The clinician believes the order was sent; the lab partner has dropped it. Patients wait for results that will never arrive, and front-desk staff get pulled in to reconcile orphaned orders days later.

This plugin moves the rejection forward in time - to the moment of Sign-and-Send, in the chart, while the clinician can still fix the underlying data in seconds.

## Who it's for

Canvas customers who route lab orders through Health Gorilla, or any electronic lab partner with `electronic_ordering_enabled = True`. Highest value for high-volume ordering specialties - primary care, chronic care management, weight-loss programs, longevity practices - where even a small rejection rate adds up to a meaningful operational drag.

## How to install

From a clone of the [`Medical-Software-Foundation/canvas`](https://github.com/Medical-Software-Foundation/canvas) repo:

```
canvas install --host <your-instance> extensions/lab_order_validation
```

The plugin activates immediately on `LAB_ORDER_COMMAND__POST_VALIDATION` events for any electronic-enabled lab partner. No restart, no further setup.

## Configuration options

None. The plugin reads the `electronic_ordering_enabled` flag from the lab partner field at runtime. No secrets, environment variables, or plugin settings are required.

## Screenshots or screen recordings

> _Screenshot pending - the Sign-and-Send block message shown in the Canvas UI when one of the five rules fails. To be added._

## Important: hard block, no override

If any of the five checks below fails on an electronic-vendor order, the clinician **cannot save or send the order** until the underlying data is fixed. There is no override or bypass - for electronic labs, missing or malformed insurance, payer, or address data always produces a broken order downstream at Health Gorilla, so the only safe path is to fix the data first.

For paper or manual labs, the plugin does nothing and the order behaves normally.

## Rules

1. **Coverage sequence** - when coverages exist, exactly one must be primary (rank 1) with no duplicate ranks. Self-pay patients (zero active coverages) pass this rule.
2. **Update registration** - flags the legacy duplicate-coverage state.
3. **Payer completeness** - every payer on an active coverage must have an address and phone.
4. **Patient address** - at least one home address must be marked `Postal` or `Both` with a complete street address.
5. **Coverage subscriber address** - when the coverage subscriber is someone other than the patient, the coverage subscriber's patient chart must have a complete address on file.

## Files

```
lab_order_validation/
├── CANVAS_MANIFEST.json
├── README.md
├── handlers/
│   └── preflight_validator.py
└── rules/
    ├── coverage_sequence.py
    ├── registration_update.py
    ├── payer_completeness.py
    ├── patient_address.py
    └── subscriber_address.py
```

## Tests

```
uv run pytest
```
