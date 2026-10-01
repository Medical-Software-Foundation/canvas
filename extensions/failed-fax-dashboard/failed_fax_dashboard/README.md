# Failed Faxes

A dashboard that lists every fax that failed across the practice, with one-click follow-up.

## What it does

Adds a "Failed Faxes" app to the app drawer. It opens a dashboard with two tabs from the last 90 days:

- Sent: faxes that were not delivered, one row per item and fax number across notes, referrals, imaging orders, lab orders, letters, and Data Integration documents.
- Received: faxes that only partly arrived.

Each row shows the recipient or sender (click the name for a contact card), the fax service's reason, who sent it, when, pages, and the attempt count. Expanding a row shows every attempt and the row's automatic task, with its comments.

## How rows clear

- A sent row clears when a later fax of the same item to the same number is delivered. A resend from the dashboard counts.
- Any row can be dismissed. The dismissal records who and when.
- A received row clears only by dismissal.

## Automatic tasks

A scheduled job runs every 5 minutes and reads only failures recorded since its previous run (with a 15-minute overlap). For each new failure it makes one task per item and fax number, assigned to the sender and labeled "Failed fax". A later failure moves the same task to that attempt's sender, reopens it, and adds a comment. A later delivered attempt closes it. Failures from before the job first ran get no task.

- Sent fax with no staff sender (for example one sent by another plugin): the team named in `FAILED_FAX_FALLBACK_TEAM`. Empty: no task.
- Received fax that only partly arrived: the team named in `RECEIVED_FAX_TASK_TEAM`. Empty: no task.
- Team settings hold the team's name, matched exactly.

From the expanded row, staff can click the assignee to reassign the task and add comments. Both are written under their own name.

## Resend (notes only)

Resend opens a short form prefilled with the failed number and, when exactly one directory contact has that number, the recipient name. The fax is sent as Canvas Bot. The plugin remembers who clicked, so the row, the history, and the task comments show "Resent by {name}".

## Sorting, filtering, sections

Click a column header to sort (people sort by last name). Filter by search text, item type, and person. Rows assigned to you or your teams appear under "Assigned to you"; everything else is under "Everything else", and each section collapses. Search, filters, sort, and collapsed sections are saved per staff member and restored on any computer. Reset view clears them. Filtering, sorting, and paging cover all 90 days.

## How to install

```
canvas install failed_fax_dashboard --host <instance>
```

The instance must run a Canvas SDK release that includes the fax delivery data models (0.237.0 or later).

## Configuration options

| Variable | Purpose |
|---|---|
| `FAX_DASHBOARD_STAFF_IDS` | Comma-separated staff ids allowed to use the dashboard. |
| `FAILED_FAX_FALLBACK_TEAM` | Team name that gets the task when a failed sent fax has no staff sender. |
| `RECEIVED_FAX_TASK_TEAM` | Team name that gets the task for a received fax that only partly arrived. |

Access behavior:

- When `FAX_DASHBOARD_STAFF_IDS` is set, only the listed staff can open the app or call its API. Everyone else gets a "Not authorized" page or a 403.
- When it is empty or unset, every logged-in staff member can use the dashboard. This is deliberate and differs from the fail-closed guidance for admin checks: the dashboard shows nothing a staff member cannot already see on each faxed item.
- Every endpoint requires a logged-in staff session, so patient portal sessions are always rejected.

The plugin stores dismissals, task alerts, resend clicks, and saved settings in a custom data namespace, `canvas_medical__failed_fax_dashboard`. Canvas generates the `namespace_read_write_access_key` variable on first install; leave it as generated.

## Data used

Read: `Fax`, the six fax action event models with their items, patients, and sending staff; `Staff`, `Team`, `Task`, `TaskComment`, `IntegrationTask`, and `ServiceProvider`. Written: custom data, plus the resend fax, task, and task comment effects.
