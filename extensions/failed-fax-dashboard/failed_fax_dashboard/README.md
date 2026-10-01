# Failed Faxes

A dashboard that lists every fax that failed across the practice, with one-click follow-up.

## What it does

Adds a "Failed Faxes" app to the app drawer. It opens a table of faxes sent from Canvas that were not delivered, and faxes received only in part, from the last 90 days, newest first. From each row, staff can open the faxed item, create a follow-up task, or dismiss the row. Failed note faxes can also be resent.

## Problem it solves

Canvas shows a fax's status (Pending, Success, Error) only on the item that was faxed: the note menu, a command's Audit History, a letter's heading, or a Data Integration document's Fax Event History. Staff have to open each item to find out a fax failed, so failures go unnoticed. Received faxes that only partly arrived still become Data Integration documents, so a partial document can be filed without anyone noticing. This plugin puts every failure in one list. See Canvas's [Fax Migration & Event History](https://help.canvasmedical.com/articles/4882014801-fax-migration-event-history) article for the native behavior.

## Who it's for

- Front desk staff and referral coordinators who send faxes
- Clinical staff who fax notes, orders, and letters
- Staff who work the Data Integration queue

## What it lists

Sent faxes that were not delivered, for all six faxable item types:

| Item type | Row actions |
|---|---|
| Note | Open note, Resend, Create task, Dismiss |
| Referral | Open note, Create task (linked to the referral), Dismiss |
| Imaging order | Open note, Create task (linked to the imaging order), Dismiss |
| Lab order | Open note, Create task, Dismiss |
| Letter | Open letter, Create task, Dismiss |
| Data Integration document | Open Data Integration, Create task, Dismiss |

A sent fax counts as failed when its delivery result is "not delivered". A fax still waiting on a result is pending and is not shown.

Received faxes that failed (inbound, not received successfully) are also listed, with a link to the Data Integration queue. Only the sender can resend, so there is no resend action for these.

Each row shows the item type, patient (when the item has one), fax number, who sent it, when, page count, and the reason the fax service gave (sent faxes only).

## How rows clear

- A sent fax row clears when a later fax of the same item to the same number is delivered. A resend from the dashboard counts.
- Any row can be dismissed. The dismissal records who dismissed it and when.
- A received fax row clears only by dismissal.

## Resend (notes only)

Resend opens a short form prefilled with the failed number. The recipient name is filled in from the contact directory when exactly one active contact has that fax number, otherwise it is blank and required. The resent fax is sent as Canvas Bot, and its outcome shows in the note's fax history like any other fax.

## Create task

Every row has a Create task button. Choose a staff member or a team, edit the title (prefilled as "Failed fax: {item type} to {fax number}"), and optionally set a due date and priority. The task is authored by the staff member who clicked, carries the patient when the item has one, and links to the referral or imaging order for those two item types. Creating a task does not clear the row.

## How to install

```
canvas install failed_fax_dashboard --host <instance>
```

The instance must run a Canvas SDK release that includes the fax delivery data models (0.237.0 or later).

## Configuration options

| Variable | Purpose |
|---|---|
| `FAX_DASHBOARD_STAFF_IDS` | Comma-separated staff ids allowed to use the dashboard. |

Access behavior:

- When `FAX_DASHBOARD_STAFF_IDS` is set, only the listed staff can open the app or call its API. Everyone else gets a "Not authorized" page or a 403.
- When it is empty or unset, every logged-in staff member can use the dashboard. This is deliberate and differs from the fail-closed guidance for admin checks: the dashboard shows nothing a staff member cannot already see on each faxed item.
- Every endpoint requires a logged-in staff session, so patient portal sessions are always rejected.

The plugin stores dismissals in a custom data namespace, `canvas_medical__failed_fax_dashboard`. Canvas generates the `namespace_read_write_access_key` variable on first install; leave it as generated.

## Data used

Read: `Fax` and the six fax action event models (note, referral, imaging order, lab order, letter, Data Integration document) with their items, patients, and the sending staff member; `Staff`, `Team`, and `ServiceProvider` for the task and resend forms. Written: dismissals (custom data), plus the resend fax and follow-up task effects.
