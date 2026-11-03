# Tellescope Banner

Shows a banner on the patient chart (and the patient profile) that links to the
patient's profile in [Tellescope](https://tellescope.com). It replaces the old
"Tellescope banner" protocol that was loaded by hand for practices with a
Tellescope integration.

## How it works

The plugin builds the link from a URL template you set in the plugin settings.
The template can use two placeholders:

| Placeholder | Filled with |
|---|---|
| `{patient_id}` | The Canvas patient id (patient key). |
| `{external_id}` | The value of the patient's external identifier whose system equals `TELLESCOPE_IDENTIFIER_SYSTEM`. |

The patient value is URL-encoded before it goes into the link, so a value with
`/`, `?`, `&` or spaces can't change the link's path or query.

The banner is added or refreshed when:

- a patient is created or updated (`PATIENT_CREATED`, `PATIENT_UPDATED`)
- a patient external identifier is created, updated or deleted
  (`PATIENT_EXTERNAL_IDENTIFIER_*`)

### Fails closed

The plugin shows no banner, and removes one it showed before, when:

- `TELLESCOPE_PROFILE_URL_TEMPLATE` is not set
- the template is not an `https://` URL, has no placeholder, uses a placeholder
  other than the two above, or has stray `{` / `}`
- the template uses `{external_id}` and `TELLESCOPE_IDENTIFIER_SYSTEM` is not
  set, or the patient has no non-blank identifier in that system

### Existing patients

The plugin does not loop over every patient on install. An existing patient
gets the banner the next time their record or external identifiers change.

## Configuration

| Variable | Required | Example |
|---|---|---|
| `TELLESCOPE_PROFILE_URL_TEMPLATE` | Yes | `https://app.tellescope.com/endusers/{external_id}` |
| `TELLESCOPE_IDENTIFIER_SYSTEM` | Only with `{external_id}` | The `system` your Tellescope sync writes on the patient's external identifier |

Use the profile URL format your Tellescope workspace uses; the examples above
are placeholders.

## Install

```bash
canvas install tellescope_banner --host <instance> \
  --variable TELLESCOPE_PROFILE_URL_TEMPLATE='https://app.tellescope.com/endusers/{external_id}' \
  --variable TELLESCOPE_IDENTIFIER_SYSTEM='<identifier system>'
```

Run it from the `extensions/tellescope_banner` folder.

## Tests

```bash
uv run --frozen pytest
```
