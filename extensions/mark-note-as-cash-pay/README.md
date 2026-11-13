# Mark as cash pay

Adds **Mark as cash pay** and **Unmark as cash pay** to the note header's
three-dot menu on billable notes. Only one shows at a time.

- **Mark** adds the Cash Pay label to the note's claim. If the claim is in
  NeedsCodingReview, it moves to the Cash Pay queue right away. A claim that is
  still in Appointment or NeedsClinicianReview gets the label now and moves when
  it reaches NeedsCodingReview. A claim already past coding (queued, filed,
  adjudicated, balance, trash) gets the label only; it is not moved.
- **Unmark** removes the label. If the claim is in the Cash Pay queue, it goes
  back to NeedsCodingReview.
- Every mark and unmark adds a claim comment naming the staff member. If the
  click carries no staff member the plugin can resolve, it opens a message and
  changes nothing, rather than writing a placeholder name.

The label is the source of truth: a labeled claim that enters NeedsCodingReview
is moved to the Cash Pay queue automatically.

## Who it is for

Billing teams that take cash-pay visits and want those claims kept out of the
insurance coding queue without moving each one by hand.

## Install

From the `extensions/mark-note-as-cash-pay` folder:

```sh
canvas install mark_note_as_cash_pay --host <your-instance>
```

## Configuration

The plugin does nothing until it is turned on.

| Variable | Default | Meaning |
|---|---|---|
| `CASH_PAY_ENABLED` | `false` | Must be `true` for the menu items to show. Any other value is off. |
| `CASH_PAY_QUEUE_NAME` | (blank) | Name of an existing claim queue (the queue's `name`, not its display name). Required when on. |
| `CASH_PAY_LABEL_NAME` | `Cash Pay` | Label added to the claim. Matched case-insensitively. |

The plugin never creates a claim queue. Create it first in Canvas admin, then:

```sh
canvas config set mark_note_as_cash_pay CASH_PAY_QUEUE_NAME=<queue name> --host <instance>
canvas config set mark_note_as_cash_pay CASH_PAY_ENABLED=true --host <instance>
```

If the queue name is blank or doesn't match a queue, clicking the menu item opens
a message saying so and nothing on the claim changes. A labeled claim that enters
coding while the queue is missing stays in coding, and an error is logged.

## What access it has

- Any staff member who can open a billable note sees the menu item once the
  plugin is on. There is no extra role check.
- It reads the note, its claim and labels, claim queue names, and the clicking
  staff member's name.
- It writes only claim effects: add or remove the label, move the claim between
  NeedsCodingReview and the configured queue, and add a claim comment. It never
  touches the claim's coverage, never creates a queue and makes no outside calls.
- Logs carry setting names and ids, never patient details.

## Components

- `handlers/buttons.py`: `MarkAsCashPayButton`, `UnmarkCashPayButton` (note
  header dropdown).
- `handlers/route_claims.py`: `RouteLabeledClaims` on `CLAIM_QUEUE_MOVED`.
- `helpers/cash_pay.py`: settings, checks and effect builders.

## Development

```sh
uv run --frozen pytest
canvas validate-manifest mark_note_as_cash_pay
canvas install mark_note_as_cash_pay --host <instance>
```
