# Expired ICD-10 Code Alert

Tags conditions in the patient chart with an **EXPIRED** annotation whenever
their ICD-10 code has been deleted from the current CMS code set. This helps
providers see at a glance that a condition needs to be re-coded.

## How it works

The plugin subscribes to the `PATIENT_CHART__CONDITIONS` event. For each
condition rendered in the patient summary, it:

1. Reads the condition's ICD-10 code (accepts either `"ICD-10"` or the FHIR
   URI `"http://hl7.org/fhir/sid/icd-10"` as the system value).
2. Skips conditions flagged as `entered_in_error`.
3. Normalizes the code (uppercase, periods removed) and checks it against the
   expired set.
4. Emits a single `ANNOTATE_PATIENT_CHART_CONDITION_RESULTS` effect with the
   `EXPIRED` tag for every matching condition.

## Expired code list

The default list lives in
[`expired_icd10_alert/data/expired_icd10_codes.json`](./expired_icd10_alert/data/expired_icd10_codes.json),
along with its CMS effective date and source URL.

The plugin ships with the codes deleted in **2026 ICD-10-CM**, effective
**October 1, 2025**.

### Updating for a new CMS release

CMS publishes ICD-10-CM updates twice per year (April 1 and October 1). To
adopt a new set:

1. Get the official deleted-codes list from
   <https://www.cms.gov/medicare/coding-billing/icd-10-codes>.
2. Replace the contents of `expired_icd10_alert/data/expired_icd10_codes.json`,
   updating `code_set_version`, `effective_date`, and the `expired_codes`
   array.
3. Bump `plugin_version` in `CANVAS_MANIFEST.json`.
4. Run `uv run pytest` to confirm tests still pass.
5. Reinstall on each instance.

### Overriding the list per-instance

If you need to patch the list without releasing a new plugin version — for
example, to handle a mid-cycle CMS errata, or to flag a code your organization
has locally deprecated — set the `EXPIRED_ICD10_CODES_OVERRIDE` secret to a
comma-separated string of codes:

```
EXPIRED_ICD10_CODES_OVERRIDE = "G35, E78.01, I25.10"
```

Codes may be written with or without periods. When the secret is set and
non-empty, it **replaces** the bundled list rather than extending it. When the
secret is unset, empty, or whitespace-only, the bundled list is used.

## Installation

From the plugin directory:

```bash
uv run canvas install .
```

## Tests

```bash
uv sync
uv run pytest -v
uv run mypy expired_icd10_alert/
```

## Manual UAT

1. **Expired code tags as EXPIRED.** Open a patient chart, add a condition for
   `G35` (Multiple Sclerosis) via Diagnose. The condition row in the summary
   shows the `EXPIRED` tag.
2. **Valid code is not tagged.** Add a condition for `I10` (Essential
   Hypertension). No tag appears.
3. **Override secret takes effect.** Set
   `EXPIRED_ICD10_CODES_OVERRIDE = "I10"` and reload. The `I10` condition now
   shows `EXPIRED`; `G35` does not.
4. **Encounter-type suffixes.** Add `S30.1XXA` (Contusion of abdominal wall,
   initial). The condition is tagged.

## Future work

- A `CronTask` that pulls the CMS deleted-codes list automatically would remove
  the twice-yearly manual update. CMS does not currently publish a stable
  machine-readable delta, so this is deferred until that's available.
