# Lab Order Validation

Pre-flight validation for lab orders bound for electronic transmission (Health Gorilla).

When a clinician clicks **Sign and Send** on a lab order whose selected lab partner has `electronic_ordering_enabled = True`, this plugin runs five data-state checks. If any fail, the commit is blocked with a clear, fixable error message. Manual or paper labs are skipped - the plugin only fires for electronic orders.

## Important: hard block, no override

If any of the five checks below fails on an electronic-vendor order, the clinician **cannot save or send the order** until the underlying data is fixed. There is no override or bypass - for electronic labs, missing or malformed insurance, payer, or address data always produces a broken order downstream at Health Gorilla, so the only safe path is to fix the data first.

For paper or manual labs, the plugin does nothing and the order behaves normally.

## Rules

1. **Coverage sequence** - patient must have one primary coverage with no duplicate ranks.
2. **Update registration** - flags the legacy duplicate-coverage state.
3. **Payer completeness** - every payer on an active coverage must have an address and phone.
4. **Patient address** - at least one home address must be marked `Postal` or `Both` with a complete street address.
5. **Subscriber address** - when the coverage subscriber is someone other than the patient, the subscriber's record must have a complete address on file.

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
