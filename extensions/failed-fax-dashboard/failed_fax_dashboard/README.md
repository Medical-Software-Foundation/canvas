# Failed Faxes

A dashboard that lists every fax that failed across the practice, with one-click follow-up.

## What it does

Adds a "Failed Faxes" app to the app drawer. It opens a dashboard with two tabs from the last 90 days:

- Sent: faxes that were not delivered, one row per item and fax number across notes, referrals, imaging orders, lab orders, letters, and Data Integration documents.
- Received: faxes that only partly arrived.

Each row shows the recipient or sender (click the name for a contact card), the fax service's reason, who sent it, when, pages, and the attempt count. Expanding a row shows every attempt and the row's automatic task, with its comments.

The contact card comes from the item when it names one (referrals, imaging orders). Otherwise it comes from the one contact with that fax number, looked up first in the instance's contact list and then in the Saved Directory, the list the fax pop-up searches. Lab cards show the lab name from the order only when no contact matches, since a lab like "Generic Lab" is a placeholder for the contact picked in the fax pop-up. Saved Directory answers are kept for a day, and a number shared by two contacts shows as the number only.

## How rows clear

- A sent row clears when a later fax of the same item to the same number is delivered. A resend from the dashboard counts.
- Any row can be dismissed, after a confirm. Dismissing closes the row's open task with the comment "Dismissed from the Failed Faxes dashboard by {name}." The dismissal records who and when.
- Several rows can be dismissed at once: tick them (or a section header to tick the whole section) and use Dismiss in the bar above the table, with one confirm for the batch. While rows are ticked, the row ✕ buttons are hidden.
- After a dismiss, an Undo button shows for 10 seconds.
- Show dismissed lists rows dismissed in the last 30 days, with who dismissed each and when. Restore (one row, or several ticked at once) brings rows back and reopens the task the dismissal closed, with the comment "Task reopened by {name}." A task that was already closed before the dismissal stays closed, and so does one from a dismissal made before version 0.1.9.
- A newer failure of a dismissed item and number brings the row back on its own.
- A received row clears only by dismissal.

## Automatic tasks

A scheduled job runs every 5 minutes and reads only failures recorded since its previous run (with a 15-minute overlap). For each new failure it makes one task per item and fax number, assigned to the sender and labeled "Failed fax". A later failure moves the same task to that attempt's sender, reopens it, and adds a comment. A later delivered attempt closes it. Failures from before the job first ran get no task.

- Sent fax with no staff sender (for example one sent by another plugin): the team named in `FAILED_FAX_FALLBACK_TEAM`. Empty: no task.
- Received fax that only partly arrived: the team named in `RECEIVED_FAX_TASK_TEAM`. Empty: no task.
- Team settings hold the team's name, matched exactly.
- Sent by a provider: the patient's care team member in the role named in `PROVIDER_FAX_TASK_ROLE`, when the sender holds a role listed in `PROVIDER_ROLES`. See "Provider faxes" below.

From the expanded row, staff can click the assignee to reassign the task and add comments. Both are written under their own name.

## Provider faxes

A failed fax sent by a provider can go to someone on the patient's care team instead of back to the provider.

- A provider is a sender holding a staff role listed in `PROVIDER_ROLES`, matched on the role's code, abbreviation, or name.
- The task goes to the patient's active care team member in the role named in `PROVIDER_FAX_TASK_ROLE`. Canvas allows one active member per role per patient.
- No one in that role, no care team, or a sender who isn't a provider: the task goes to the sender as usual.
- The task comment names the provider who sent it and the care team member it went to.
- Either setting empty turns this off. A role name that matches no care team role is logged as a warning.

## Reassigning to a team

The SDK can't remove a person from a task. When a task held by a person moves to a team (from the dashboard, or by the scheduled job's fallback team), the plugin closes the person's task and opens a new one for the team. The new task points back to the old one. The dashboard shows each earlier task's comments under a divider ("Earlier task 1, assigned to Dana Whitfield") with a link to that task, then the current task's comments. The task title links to the current task. Moves to a person, and team-to-team moves, update the same task.

## Resend (notes only)

Resend opens a short form prefilled with the failed number and, when exactly one contact (instance list or Saved Directory) has that number, the recipient name. The fax is sent as Canvas Bot. The plugin remembers who clicked, so the row and the attempt list name that person as the sender.

## Sorting, filtering, sections

Click a column header to sort (people sort by last name). Filter by search text, item type, and person. Rows assigned to you or your teams appear under "Assigned to you"; everything else is under "Everything else", and each section collapses. Search, filters, sort, and collapsed sections are saved per staff member and restored on any computer. Reset view clears them. Filtering, sorting, and paging cover all 90 days.

## How to install

```
canvas install failed_fax_dashboard --host <instance>
```

The instance must run a Canvas SDK release that includes the fax delivery data models (0.237.0 or later).

## Configuration options

Set these on the plugin's configuration page. Canvas's settings page has no room for help text, so this table is the reference.

| Setting | What it does | Format | Empty means |
|---|---|---|---|
| `FAX_DASHBOARD_STAFF_IDS` | Limits who can open the dashboard. | Staff ids separated by commas, for example `0a1b2c3d4e5f60718293a4b5c6d7e8f9, 1b2c3d4e5f60718293a4b5c6d7e8f90a`. A staff id is the staff member's 32-character key. Dashes and spaces are ignored. | Every staff member can open it. |
| `FAILED_FAX_FALLBACK_TEAM` | Gets the task when a failed sent fax has no staff sender, for example one another plugin sent. | A team's name, spelled exactly as in Canvas, for example `Front Desk`. | No task for those faxes. |
| `RECEIVED_FAX_TASK_TEAM` | Gets a task for each received fax that only partly arrived. | A team's name, spelled exactly as in Canvas, for example `Medical Records`. | No task for received faxes. |
| `PROVIDER_ROLES` | Which senders count as providers for provider fax routing. | Staff role codes or names separated by commas, for example `MD, NP, RN, DO, PA`. Capitals and spaces are ignored. | No rerouting. Tasks go to the sender. |
| `PROVIDER_FAX_TASK_ROLE` | The care team role that gets a provider's failed fax task. | A care team role's name as it appears in Canvas, for example `Care Coordinator`. Capitals are ignored. | No rerouting. Tasks go to the sender. |
| `namespace_read_write_access_key` | Lets the plugin read and write its own stored data. | Generated by Canvas on first install. | Leave it as generated. Don't change or clear it. |

A team name that matches no team, or more than one, is treated as empty and logged as a warning.

Access behavior:

- When `FAX_DASHBOARD_STAFF_IDS` is set, only the listed staff can open the app or call its API. Everyone else gets a "Not authorized" page or a 403.
- When it is empty or unset, every logged-in staff member can use the dashboard. This is deliberate and differs from the fail-closed guidance for admin checks: the dashboard shows nothing a staff member cannot already see on each faxed item.
- Every endpoint requires a logged-in staff session, so patient portal sessions are always rejected.

The plugin stores dismissals, task alerts, resend clicks, and saved settings in a custom data namespace, `canvas_medical__failed_fax_dashboard`. Canvas generates the `namespace_read_write_access_key` variable on first install; leave it as generated.

## Data used

Read: `Fax`, the six fax action event models with their items, patients, and sending staff; `Staff`, `StaffRole`, `CareTeamMembership`, `CareTeamRole`, `Team`, `Task`, `TaskComment`, `IntegrationTask`, and `ServiceProvider`; Saved Directory contacts by fax number, read-only through the SDK's `science_http` client. Written: custom data, plus the resend fax, task, and task comment effects.
