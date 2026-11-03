# Auto Fax

Faxes a note automatically when it is locked or signed, to recipients chosen by rules the
practice sets in the plugin's settings. No code change is needed to add, change or turn off
a rule.

## Problem it solves

Many practices fax every visit note to someone outside Canvas: the patient's primary care
provider, the referring provider, or the facility where the patient lives. Done by hand, this
gets forgotten or sent to the wrong number. Several customer plugins already did it, each
with its own hard-coded logic. This plugin is a generic version you configure for each practice.

## Who it's for

Practices that need visit notes faxed to external care team members (PCP, referring
provider) or to a patient's facility (assisted living, skilled nursing) as soon as the note
is final.

## How it works

1. Canvas fires `NOTE_STATE_CHANGE_EVENT_CREATED` on every note state change.
2. If the plugin is off, or no rule fires on this state, the handler stops before it runs any query.
3. It loads the note and keeps only the rules that match its note type and location.
4. It resolves the recipients with a fixed number of queries:
   - care team: one query for the memberships and one for their directory records
   - facility: one query
   - fixed numbers: no query
5. It skips any number this note was already faxed to by a plugin, unless the note was relocked.
6. It returns one `FaxNoteEffect` per fax number. Anything it can't fax is logged, never guessed.

| Handler | Event |
| --- | --- |
| `AutoFaxOnNoteLock` | `NOTE_STATE_CHANGE_EVENT_CREATED` |

## Install

```bash
canvas install auto_fax --host <your-instance>
```

Then open **Settings → Plugins → auto_fax** and set the variables below.

## Configuration

| Variable | Values | Default |
| --- | --- | --- |
| `AUTO_FAX_MODE` | `off`, `dry_run` or `live` | `off`. Blank or unknown values also mean off. |
| `AUTO_FAX_RULES` | A JSON list of rules (see below) | None. Nothing is sent. |
| `AUTO_FAX_TEST_FAX_NUMBER` | A US fax number | Optional. When set, every fax goes here instead. |

Suggested rollout:

1. Set `dry_run` and lock a test note. The logs show
   `[auto_fax] dry run, would fax …` for each fax, with the number masked to its last four digits.
2. Set `live` with `AUTO_FAX_TEST_FAX_NUMBER` pointed at the practice's own fax line.
3. Clear the test number.

If the test number can't be read, the plugin turns itself off. It never falls back to the real recipients.

### Rule fields

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | no | Shown in logs. Defaults to `rule N`. |
| `enabled` | no | `false` turns the rule off without deleting it. |
| `note_type_codes` | yes | Note type codes, or `["*"]` for every type. |
| `trigger_states` | no | Any of `LKD` (locked), `SGN` (signed), `RLK` (relocked). Defaults to `["LKD"]`. |
| `location_ids` | no | Only notes at these practice locations. Leave it out for every location. |
| `recipients` | yes | One or more recipients (see below). |
| `cover_sheet` | no | `{"subject": "...", "comment": "..."}`. Needs the note to have a practice location. Without one, the fax is sent with no coversheet. |

Recipient types:

- `{"type": "care_team_role", "role_codes": ["446050000"]}`: every active external care team
  member (a directory provider, not staff) with one of these role codes. The fax goes to the
  business fax on their directory record.
- `{"type": "facility"}`: the fax number of the facility on the patient's current facility address.
- `{"type": "fixed", "name": "Records office", "fax": "555-234-0100"}`: a fixed number.

If a rule has an error, the plugin logs it (`[auto_fax] config: …`) and skips the whole rule.
Other rules still run.

### Example: visit notes to the PCP and referring provider on lock

```json
[
  {
    "name": "Visit notes to PCP and referring provider",
    "note_type_codes": ["office_visit", "telehealth_visit"],
    "trigger_states": ["LKD", "RLK"],
    "recipients": [
      {"type": "care_team_role", "role_codes": ["446050000", "3842006"]}
    ],
    "cover_sheet": {
      "subject": "Visit note",
      "comment": "Please file this visit note in the patient's chart."
    }
  }
]
```

### Example: visit notes to the patient's facility on signature

```json
[
  {
    "name": "Signed visit notes to facility",
    "note_type_codes": ["*"],
    "trigger_states": ["SGN"],
    "recipients": [{"type": "facility"}]
  }
]
```

Role codes and note type codes differ between instances. Check them in the instance's
settings before you write a rule.

## Access and data

- No routes or UI. The only trigger is a note state change inside the instance.
- It reads the note, the patient's care team and directory records, and the patient's
  facility address. It writes nothing except the faxes (`FaxNoteEffect`), which Canvas
  records on the note's fax history under Canvas Bot.
- Whoever can edit this plugin's settings decides where notes are faxed. Treat that
  permission like access to the charts: limit it to practice admins.
- Logs carry note ids, rule names, the recipient type and the fax number masked to its
  last four digits. They never carry patient, provider or facility names.

## Notes

- Only US fax numbers (10 digits, with or without a leading 1) are supported.
- A facility address counts as current through its end date in the note provider's last
  known time zone (UTC if the provider has none).
- Fax delivery status shows on the note's fax history in Canvas. This plugin doesn't retry failed faxes.
- Screenshot: this plugin has no UI of its own. A screenshot of a sent fax in the note's history still needs to be added.
