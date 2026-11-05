# Auto Fax

Faxes a note automatically when it is locked or signed, to recipients chosen by rules the
practice sets in the plugin's settings. An opt-in **Fax orders** button on the note faxes
the note's orders to the patient's facility (or any other recipient) before the note is
signed. No code change is needed to add, change or turn off a rule.

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
| `FaxOrdersButton` | `SHOW_NOTE_HEADER_BUTTON`, `ACTION_BUTTON_CLICKED` |
| `FaxOrdersAPI` | `SIMPLE_API_REQUEST` (`POST /plugin-io/api/auto_fax/fax-orders/send`, staff session only) |

### The Fax orders button

Rules with `"trigger": "fax_orders_button"` add a **Fax orders** button to the header of
every note they cover. The note does not need to be signed; only committed orders count.

1. A click sends nothing. It opens a preview: who gets a fax, at which number, and which
   orders are in it. It says plainly when there is nothing to send, for example when the
   patient's facility has no fax number or the note has no committed orders of the rule's types.
2. The staff member clicks **Send fax**. The server rebuilds the preview from the database
   (it trusts nothing from the browser but the note id) and returns the fax effects.
3. Double sends: the preview shows when each recipient was last faxed. If a recipient
   already has everything, the server skips it, so a second click or a replayed request
   sends nothing new. The preview then offers **Send again**, which resends on purpose.
   The button also disables itself after one click.

How the orders are sent is the rule's `send_as` setting. The SDK can't fax a document made
of only some of a note's commands, so the choice is between:

- `"whole_note"`: **one fax**, the whole note as it stands now (unsigned). It carries every
  order, and also everything else in the note, including orders the rule doesn't list. Any
  order type can be sent this way. A whole-note fax counts as sent again once a newer order
  is committed.
- `"order_documents"`: **one fax per order**, each order's own document, the same one its
  **Fax** action sends in Canvas (a lab order sends its requisition). Nothing else from the
  note goes out. Only referrals, imaging orders and lab orders have a document, so DME and
  medication orders can't use this mode; the rule is rejected if it lists them.

When two rules send to the same number, their orders go out together. If either rule is
`whole_note`, the number gets one whole-note fax.

A `command_metadata` setting, such as `{"alert_facility": "Yes"}`, limits a rule to orders
marked that way. With `whole_note` it decides whether the fax is offered and what the
preview lists. The note itself still shows every order.

The note-lock rules only count faxes sent since the note was first locked or signed, so a
whole-note fax from the button before signing doesn't stop the signed note from being faxed.

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
| `trigger` | no | `note_state` (default) or `fax_orders_button` (the button). |
| `trigger_states` | no | Note rules only. Any of `LKD` (locked), `SGN` (signed), `RLK` (relocked). Defaults to `["LKD"]`. |
| `order_types` | button rules | Any of `referral`, `imaging`, `lab`, `dme`, `prescribe`, `adjust_prescription`, `refill`, `change_medication`, `stop_medication`, `medication_statement`, or `medication` for all six medication types. |
| `send_as` | button rules | `whole_note` (one fax, the whole note) or `order_documents` (one fax per referral, imaging or lab order). |
| `command_metadata` | no | Button rules only. Metadata every order must carry, e.g. `{"alert_facility": "Yes"}`. Values match case-insensitively. |
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

### Example: one orders fax to the patient's facility, before signing

Lab, DME, referral and imaging orders, plus medication orders marked
**Alert facility: Yes** (stored as command metadata by another plugin). Both rules fax the same number, so one click sends one fax.

```json
[
  {
    "name": "Orders to facility",
    "trigger": "fax_orders_button",
    "send_as": "whole_note",
    "note_type_codes": ["*"],
    "order_types": ["lab", "dme", "referral", "imaging"],
    "recipients": [{"type": "facility"}]
  },
  {
    "name": "Facility-alert meds to facility",
    "trigger": "fax_orders_button",
    "send_as": "whole_note",
    "note_type_codes": ["*"],
    "order_types": ["medication"],
    "command_metadata": {"alert_facility": "Yes"},
    "recipients": [{"type": "facility"}]
  }
]
```

`command_metadata` applies to every order type in its rule, which is why the medication
orders have their own rule here. To send only the order documents instead (no rest of the
note), use one rule with `"send_as": "order_documents"` and `["referral", "imaging", "lab"]`.

Role codes and note type codes differ between instances. Check them in the instance's
settings before you write a rule.

## Access and data

- One route, `POST /plugin-io/api/auto_fax/fax-orders/send`, for logged-in staff only
  (`StaffSessionAuthMixin`). It needs a note a button rule covers and sends only what the
  rules allow for that note. The only UI is the note header button and its preview.
- It reads the note, its committed order commands and their metadata, the order records, the patient's
  care team and directory records, and the patient's facility address. It writes nothing
  except the faxes (`FaxNoteEffect`, `FaxReferralEffect`, `FaxImagingOrderEffect`,
  `FaxLabOrderEffect`), which Canvas records on the document's fax history under Canvas Bot.
- A `whole_note` button rule faxes an unsigned note. The receiver gets the note as it
  stands, before the provider has signed it.
- Whoever can edit this plugin's settings decides where notes are faxed. Treat that
  permission like access to the charts: limit it to practice admins.
- Logs carry note ids, the clicking staff member's id, rule names, the recipient type and the fax number masked to its
  last four digits. They never carry patient, provider or facility names.

## Notes

- Only US fax numbers (10 digits, with or without a leading 1) are supported.
- A facility address counts as current through its end date in the note provider's last
  known time zone (UTC if the provider has none).
- Fax delivery status shows on the note's fax history in Canvas. This plugin doesn't retry failed faxes.
- A very fast second send, before Canvas has recorded the first fax, can't be caught by
  the "already sent" check. The disabled button covers the normal case.
