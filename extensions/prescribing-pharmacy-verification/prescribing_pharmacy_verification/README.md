# Prescribing Pharmacy Verification

Blocks Prescribe, Refill, and Adjust-Prescription commands from being committed
until a pharmacy is selected. Without a pharmacy, a prescription cannot be
electronically transmitted, so this extension fails fast at commit time with a
clear validation message rather than allowing an unroutable order to be saved.

## Handlers

### RequirePharmacyOnPrescription

Prevents committing a prescription-related command when its `pharmacy` field
is missing or empty.

**Events:**

- `PRESCRIBE_COMMAND__POST_VALIDATION`
- `REFILL_COMMAND__POST_VALIDATION`
- `ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION`

**Validation rule:** The `pharmacy` field in the event context must be a
non-empty value carrying an NCPDP identifier. The handler accepts either:

- a dict with a non-empty `ncpdp_id`, `id`, or `value` key, or
- a non-empty string (treated as the NCPDP ID directly).

Anything else — `None`, an empty dict, a dict whose ID keys are blank, an
unexpected type — is treated as "no pharmacy set" and blocks the commit.

**Error message:**

```
Select a pharmacy before recording.
```

## Demo

_TODO: add demo video link or screenshots showing the error appearing on a
Prescribe command without a pharmacy and disappearing once one is selected._

## Development

### Running tests

```bash
uv run pytest
```

### Test coverage

```bash
uv run pytest --cov=prescribing_pharmacy_verification --cov-branch --cov-report=term-missing
```

## File structure

```
prescribing_pharmacy_verification/
├── handlers/
│   ├── __init__.py
│   └── require_pharmacy.py   # RequirePharmacyOnPrescription
├── CANVAS_MANIFEST.json
└── README.md
```
