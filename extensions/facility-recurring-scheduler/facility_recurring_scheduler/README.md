# Facility & Recurring Scheduling

> Recurring, facility-aware scheduling for practices that round at facilities and care for long-term residents.

A Canvas plugin that adds **recurrence** to any scheduled item and **facility selection + automatic naming** to Other Events, so a clinician's standing cadence at a facility can be entered once and maintained automatically.

---

## Why this matters

Practices that deliver care **at facilities** — skilled nursing, assisted living, memory care, group homes, hospice — schedule differently than a single-location clinic. Rounding is a *standing commitment to a place*, not a one-off patient visit, and stock scheduling tools model it poorly.

| Practice need | How this plugin helps |
|---|---|
| Rounding follows a **cadence**, not a single date | Enter the pattern once (weekly, biweekly, "3rd Tuesday"); future visits are generated and kept topped up automatically. |
| A facility round is a **provider/location commitment**, not one patient's appointment | Model it as an **Other Event**, reserving the clinician's time at the site without forcing a single patient onto the block. |
| The calendar should read **by place** | Selecting a facility renames the block to the facility name, so the week shows *where* each clinician is at a glance. |
| Long-term residents need a **dependable return interval** | A rolling horizon of future visits always exists on the calendar instead of relying on someone to rebook. |
| A monthly round must fall on a **staffable weekday** | Monthly recurs on the same *ordinal weekday* (e.g. the 3rd Tuesday), never a fixed date that drifts onto a weekend. |

The result: a practice can express *which clinician is at which facility, on what cadence, seeing which long-term residents* — directly in the Canvas calendar.

---

## Features

### Recurrence — all event types

Available on both appointments and Other Events.

**Patterns:** None · Daily · Weekly · Every 2 Weeks · Every 3 Weeks · Monthly

- **Monthly is ordinal-weekday based.** An event on the 3rd Tuesday recurs on the 3rd Tuesday of each following month — stable weekday, no month-length drift, never lands on a weekend. An anchor on the *5th* occurrence of its weekday recurs on the **last** such weekday in months that have no 5th.
- **Wall-clock time is preserved across DST** — a 9:00 AM visit stays 9:00 AM local through spring-forward and fall-back.
- **Initial creation** generates ~2 months of visits up front.
- **A daily CronTask** extends every active series to maintain a **90-day horizon**.
- **Stopping a series:** cancel the parent event, or cancel every child — the daily task will not regenerate a fully-cancelled series.

### Facility selection — Other Events only

- Dropdown populated with all **active** `Facility` records in Canvas.
- Selecting a facility renames the event's description to the facility name.
- Recurring child events inherit the facility name from their parent.

---

## How it works

The plugin is a small set of event handlers; no UI beyond the two dropdowns it injects into the scheduling modal.

| Handler | Trigger | Responsibility |
|---|---|---|
| `OtherEventFormFields` | `APPOINTMENT__FORM__GET_ADDITIONAL_FIELDS` | Adds the Recurrence dropdown (all events) and the Facility dropdown (Other Events only). |
| `FacilityRename` | `APPOINTMENT_CREATED` | Renames Other Events to the selected facility name; children inherit the parent's facility. |
| `RecurrenceInitialHandler` | `APPOINTMENT_CREATED` | Creates the initial batch of recurring child events (~2 months). |
| `RecurrenceExtender` | CronTask, daily at midnight | Extends every active recurring series out to the 90-day horizon. |

**Anchoring:** interval patterns (daily/weekly/every-N-weeks) extend from the latest existing child; monthly extends from the parent's original start so its ordinal weekday can never drift.

---

## Configuration

No secrets or environment configuration required.

**Prerequisites for facility features:** at least one **active** `Facility` configured in Canvas.

---

## Development

```bash
uv sync           # install dependencies
uv run pytest     # run the test suite
uv run mypy facility_recurring_scheduler   # type-check
```

> The included `pyproject.toml` and `uv.lock` are for local development and testing only. Canvas packages the plugin through its own process.

---

## UAT

> **Prerequisites:** plugin installed on the target instance, at least one active Facility, and access to the Schedule page.

| # | Scenario | Steps | Expected |
|---|---|---|---|
| 1 | Recurrence on appointments | On the **Appointments** tab, open the scheduling modal | A **Recurrence** dropdown appears; **no** Facility dropdown |
| 2 | Both dropdowns on Other Events | On the **Other Events** tab, open the scheduling modal | Both **Facility** and **Recurrence** dropdowns appear |
| 3 | Facility naming | Create an Other Event with a facility selected | The event is named after the facility |
| 4 | Weekly recurrence | Create a weekly Other Event | Child events created weekly, all named after the facility |
| 5 | Every 2 Weeks | Create an Other Event with **Every 2 Weeks** | ~4 child events (~2 months) |
| 6 | Every 3 Weeks | Create an Other Event with **Every 3 Weeks** | ~3 child events (~2 months) |
| 7 | Monthly ordinal weekday | Create a monthly Other Event on, e.g., the 3rd Tuesday | Children land on the 3rd Tuesday of each following month |
| 8 | Appointments are not renamed | Create a recurring **appointment** (not an Other Event) | Children created but **not** renamed to a facility |
| 9 | Cancelled series stays cancelled | Cancel every child of a recurring series | The daily task does **not** regenerate the series |
