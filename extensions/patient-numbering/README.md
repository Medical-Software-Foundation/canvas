# Patient Numbering

## What it does

Gives every patient a simple Patient ID (1, 2, 3...) in addition to the Canvas MRN. The Patient ID appears in the Patient demographics section of the patient profile, and staff can find a patient by it from the patient search bar. Existing patients are numbered in the order they were added to Canvas, starting at 1, and every new patient gets the next number automatically.

A practice moving from another system can keep the patient numbers it already uses. When patients are imported with an ID from the previous system (for example a Charm ID such as `ABC0042`), each one keeps that number, and new patients continue after the highest one (`ABC0349`, `ABC0350`...).

![Patient ID shown in the patient demographics section of the profile](docs/profile-patient-id.png)

## Problem it solves

Canvas assigns each patient a 9-digit random MRN. Some practices also need a short, sequential number: to label paper charts and forms, to say over the phone, or to match a numbering scheme the practice already uses. Without this plugin, staff keep that number in a separate spreadsheet or type it into a free-text field by hand, which leads to duplicates and skipped numbers. This plugin assigns the numbers itself and guarantees that no two patients share one.

## Who it's for

Front desk, intake, and practice administrators who register patients and look them up, and practice owners who want a simple running patient count. An administrator runs the one-time numbering of existing patients from the admin app.

## How it works

- **New patients:** when a patient is created, they get the next Patient ID.
- **Existing patients:** an administrator opens the **Patient Numbering** app and clicks **Number existing patients**. Patients are numbered in the order they were added to Canvas, in batches of 100, with progress shown on the page. New patients are not numbered until this finishes, so existing patients keep the lowest numbers.
- **Keeping IDs from a previous system:** when `SOURCE_IDENTIFIER_SYSTEM` is set, the same button first gives each patient the number in their ID from that system, then numbers everyone else after the highest number in use. If two patients carry the same source ID, the second gets a new number and the plugin logs it, and the admin page says how many.
- **Profile:** the number shows as a read-only **Patient ID** field in Patient demographics.
- **Search:** type `!` followed by the number in the patient search bar, for example `!42`. The `!` tells Canvas search to look up patient identifiers.
- **Numbers are never reused.** If a patient record is removed, its number is skipped.

![Admin app after numbering existing patients](docs/admin-after.png)

### Where the number is stored

| Where | Purpose |
|---|---|
| Custom data table `patientnumber` in namespace `canvas__patient_numbering` | Source of truth. A unique constraint guarantees no two patients share a number. |
| Patient external identifier, system `https://schemas.canvasmedical.com/patient-number` | Makes `!<number>` search work and includes the number on the FHIR Patient resource. |
| Patient metadata, key `patient_number` | The value the profile field displays. |

## How to install

```bash
canvas install patient_numbering --variable "ADMIN_STAFF_IDS=<staff_id>,<staff_id>"

# To keep IDs from a previous system:
canvas install patient_numbering \
  --variable "ADMIN_STAFF_IDS=<staff_id>" \
  --variable "SOURCE_IDENTIFIER_SYSTEM=Charm" \
  --variable "NUMBER_PREFIX=ABC" \
  --variable "NUMBER_WIDTH=4"
```

Then:

1. Copy the generated `namespace_read_write_access_key` and `namespace_read_access_key` from the plugin's secrets and store them somewhere safe. Canvas generates them only when the namespace is first created, and a reinstall after an uninstall needs them.
2. As one of the listed administrators, open the **Patient Numbering** app and click **Number existing patients**. When it reports "Done", new patients are numbered automatically.

![Admin app before numbering existing patients](docs/admin-before.png)

## Configuration options

| Setting | Required | Description |
|---|---|---|
| `ADMIN_STAFF_IDS` | Yes | Comma-separated staff IDs allowed to use the admin app. If it is empty, nobody can open it. |
| `SOURCE_IDENTIFIER_SYSTEM` | No | System of the patient external identifier that carries the previous system's ID, for example `Charm`. Leave unset to number every patient from 1. |
| `NUMBER_PREFIX` | No | Letters shown before the number, for example `ABC`. Source IDs must start with it to be kept. |
| `NUMBER_WIDTH` | No | Pad the number with zeros to this many digits, for example `4` gives `ABC0042`. |
| `namespace_read_write_access_key` | Generated | Created on first install. Pass it back with `--secret` on any reinstall. |

Set these before clicking **Number existing patients**. The stored number never changes, but the displayed Patient ID is written when a patient is numbered, so changing the prefix or width later does not update patients who already have one.

The profile label (`Patient ID`) and the identifier system are set in code (`handlers/profile_field.py` and `numbering.py`).
