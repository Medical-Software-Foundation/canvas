# Recent Labs

Patient-scoped chart-drawer app that displays a patient's recent lab results **grouped by
test** — up to the 3 most recent results for each test — with a **Print** button and a
**Create fax summary** action.

## Problem it solves

Reviewing a patient's recent labs in a standard chart often means scrolling through a flat,
chronological list and mentally regrouping results by test. When a clinician needs to share
those results with an outside provider, they typically copy values by hand into a note or a
cover sheet. This plugin groups results by test, surfaces only the most recent values with
trend context, and turns them into a fax-ready summary note in one click — removing manual
transcription and the errors that come with it.

## Who it's for

Clinicians and clinical staff who review lab results at the point of care and need to
quickly share a concise lab summary with referring or consulting providers via fax.

## What it does

- Opens from the patient app drawer into the right chart pane.
- Groups the patient's `LabValue` records by test and shows, per test, its **up to 3 most
  recent results** (newest first): value + units, abnormal-flag badge, reference range, and
  date. Test groups are ordered by most-recent-result date (the test resulted most recently
  appears first).
- Each test with **2+ numeric results** shows a small inline **sparkline** (oldest→newest)
  next to its name. Qualitative tests (e.g. POSITIVE/NEGATIVE) show no line.
- **Print** uses the browser print dialog (print stylesheet hides the buttons).
- **Create fax summary** creates a visit note containing a **"Recent Labs" custom command**
  (declared in the manifest, `schema_key: recentLabsSummary`) whose HTML content is a
  readable, fax-ready summary: a patient header (name + DOB), then one block per test with
  dated result lines, friendly dates, spelled-out abnormal flags (High/Low/Abnormal), and
  placeholder values (`-`, `None`, `N/A`) and unidentified tests omitted. The user then
  faxes that note through Canvas's native note-fax flow — recipient chosen from the
  contact/fax directory at send time. The plugin does not store fax numbers. The note's
  provider is the logged-in staff member.

## How to install

```bash
canvas install recent-labs
```

## Configuration

Set the following secrets after installing:

| Secret | Purpose |
|---|---|
| `RECENT_LABS_NOTE_TYPE_ID` | The visit note type used for the generated fax-summary note. Accepts the note type's **code** (e.g. `faxedlabs`), its **name** (e.g. `Faxed Labs`), or its UUID — code is tried first. Must be a visit note type (not letter/message/appointment). |
| `RECENT_LABS_PRACTICE_LOCATION_ID` | *(Optional)* Practice location UUID used on the summary note. If unset, the first active practice location is used. Set this for multi-location practices. |

The created note's provider is the logged-in staff member.

## Screenshots

_Screenshots / a short screen recording of the chart-drawer app and the generated fax
summary note will be added here._

## Notes

- Results are grouped by **LOINC code** (falling back to the test's display name when a
  result has no code), so the same test under slightly different names still groups
  together. Each group keeps its 3 most recent results, newest first.
- "Top-N most recent per test" is not expressible cheaply in the ORM, so the plugin scans
  the patient's lab values and buckets them in Python. Fine for typical patients; revisit
  with prefetching if a patient accumulates very many results.
- Faxing is intentionally delegated to Canvas's native note-fax flow (the plugin only
  builds the note).

## Running Tests

```bash
uv run pytest tests/
```
