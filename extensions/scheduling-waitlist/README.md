# Scheduling Waitlist

A shared, priority-ordered list of patients waiting to be scheduled — and a task to the
scheduling team the moment a booked slot frees up.

When an appointment is cancelled or a patient no-shows, that slot usually goes to waste because
nobody remembers who was waiting for it. This plugin keeps the waiting list in one place and
reacts to cancellations automatically.

**The plugin never books anyone.** It recommends; staff schedule from the task.

## What it does

**The roster** — a practice-wide page in the app drawer listing everyone waiting, sorted by
priority then wait time. Filter by service, provider, or location; search by patient name. Each
row can open the patient's chart, be edited, marked scheduled, or removed.

**Adding a patient** — from the roster itself: search for the patient by name, then fill in
service, provider, location, priority, preferred time, and a note.

**From the chart** — the chart carries two things, because it is asked two different questions:

- A **banner** on the chart of anyone already waiting, saying what they are waiting for and
  linking back to the roster. This answers "is this patient on the list?" without a click.
- An **"Add to waitlist" button** in the chart header, which opens the roster's add dialog with
  the patient already filled in. The label reads "On waitlist" when they are already waiting.
  This answers "put them on the list" — an action, which a passive banner cannot serve.

The button reuses the roster's add dialog rather than shipping a second form, so there is one
set of validation rules. Only the patient's key travels in the page URL; the name behind it is
fetched over the authenticated API, so no identifiable data is baked into the document.

**Cancellation matching** — when a booked slot frees up, the plugin finds waiting entries whose
requested type, provider (or "any"), and location fit it, and raises **one** task to the
scheduling team naming them in priority order. Each patient's preferred day/time is shown so
staff can judge fit.

A slot counts as freed whether staff cancelled it, the patient cancelled or rescheduled it in
the patient portal, it was no-showed, or the booking was moved to another time. For a
reschedule, the slot announced is the one the booking moved *away* from — the new booking is
occupied. Duplicate deliveries are harmless: every path fingerprints the same freed slot, so a
cancellation and a no-show for one booking raise one task between them.

**Housekeeping** — a nightly job ages out entries past their configured shelf life and logs
wait-time and fill metrics. Ageing marks entries `expired`; it never deletes them, so the backlog
report stays intact and an entry can be reinstated in one click.

## Entry lifecycle

```
waiting ⇄ offered  →  scheduled | removed | expired
```

`waiting` and `offered` are both matchable — telling a patient about a slot is not the same as
them booking it. All three terminal states can be reinstated. An entry that was auto-marked
`scheduled` returns to `waiting` on its own if that appointment is later cancelled.

## Installation

```bash
canvas install extensions/scheduling-waitlist/scheduling_waitlist
```

The plugin's Custom Data namespace (`custom_data__scheduling_waitlist`) is created on install.
Writes require the platform-supplied `namespace_read_write_access_key`.

## Configuration

Set as plugin secrets. Anything marked **required** fails closed — the plugin declines to act
rather than guessing.

| Secret | Required | Default | What it does |
|---|---|---|---|
| `WAITLIST_SCHEDULING_TEAM` | **yes** | — | Team UUID or exact name that receives slot-opened tasks. Unset ⇒ no task is raised (an unassigned task is an unread task) |
| `WAITLIST_APPOINTMENT_TYPES` | **yes** | — | Comma-separated `NoteType` **codes** offered on the form. Codes, not names, because names change across versions and installs |
| `WAITLIST_PRIORITY_LABELS` | no | `High,Medium,Low` | Comma-separated, highest priority first |
| `WAITLIST_TTL_DAYS` | **yes** | — | Days before a waiting entry ages out. Invalid ⇒ nothing expires |
| `WAITLIST_MANAGER_ROLE_CODES` | no | *(empty)* | Staff role codes allowed to edit or remove **other** people's entries. Unset ⇒ everyone still manages their own |
| `WAITLIST_ENFORCE_TIME_WINDOWS` | no | `false` | When `true`, a patient's preferred day/time filters matches instead of only being displayed |
| `WAITLIST_MAX_MATCHES_PER_TASK` | no | `10` | Cap on patients named in one task |
| `WAITLIST_MIN_LEAD_TIME_HOURS` | no | `2` | Slots starting sooner than this are ignored — nobody can fill them |
| `WAITLIST_URGENT_LEAD_HOURS` | no | `48` | Slots starting within this window raise an urgent task |
| `WAITLIST_DISPLAY_TIMEZONE` | no | `UTC` | IANA timezone for times in tasks. The abbreviation is always printed, so a wrong value is visible rather than silent |

> The manifest uses the `secrets` key. Newer CLI versions report it as deprecated in favour of
> `variables`, but the CLI notes the server may not return `variables` yet, and 80 of the 81
> plugins in this repo still use `secrets`. Revisit once server support is confirmed.

## Components

| Class | Kind | Responds to |
|---|---|---|
| `applications.waitlist_app:WaitlistApp` | Application (global) | app drawer |
| `routes.app_routes:WaitlistAppAPI` | SimpleAPI | serves the roster page and assets |
| `routes.waitlist_api:WaitlistAPI` | SimpleAPI | entry CRUD, patient search, dropdown options |
| `handlers.chart_button:AddToWaitlistButton` | ActionButton | chart patient header |
| `handlers.slot_freed:SlotFreedHandler` | Handler | `APPOINTMENT_CANCELED`, `APPOINTMENT_NO_SHOWED`, `APPOINTMENT_RESCHEDULED`, `PATIENT_PORTAL__APPOINTMENT_CANCELED`, `PATIENT_PORTAL__APPOINTMENT_RESCHEDULED` |
| `handlers.appointment_booked:AppointmentBookedHandler` | Handler | `APPOINTMENT_CREATED` |
| `handlers.waitlist_cron:WaitlistMaintenanceCron` | CronTask | `0 3 * * *` (UTC) |

## Notes for maintainers

**Filtering, search, and sorting run server-side**, unlike some plugins here that bootstrap a
whole list into the page and filter in JavaScript. Three reasons, all specific to this plugin: a
practice-wide waitlist is thousands of rows rather than dozens; the search box matches *patient
name*, so filtering in the browser would ship every waitlisted patient's name and date of birth
regardless of the filter; and priority rank comes from configuration, so ordering belongs in one
place. Please don't "fix" this back.

**"Any provider" is stored as a value, not an absent foreign key.** The plugin DDL pipeline emits
no `NOT NULL` constraints, so a null column cannot be distinguished from one that was never
filled in — and reading null as "any" would make a malformed row match every open slot. Storing
the intent explicitly makes a malformed row match nothing instead.

**Slot detection reacts to a freed *booked* slot, not to open availability.** Canvas emits no
generic "slot opened" event, so scanning arbitrary open availability is out of scope.

**The chart banner is emitted from the write paths, not from `apply_transition`.** Banner effects
have to be *returned* by a handler or route to take effect, and `services/transitions.py` writes
with `entry.save()` and returns the entry — it has no channel for an effect. So each of the five
places that change what a patient is waiting for appends `services/banner.py:banner_effects` to
what it was already returning. If you add a sixth write path, it needs the same line, or that
patient's chart will quietly go stale. The banner is keyed, so re-emitting replaces rather than
stacks.

**The nightly sweep caps how many banners it refreshes** (`MAX_BANNER_REFRESH_PER_RUN`). Expiring
one of a patient's entries does not necessarily clear their banner — they may still be waiting on
something else — so each affected patient costs a query to recompute. The remainder is logged and
corrected by the next write or the next run.

## Development

```bash
cd extensions/scheduling-waitlist
uv run --python 3.12 --with pytest --no-project pytest tests/ -q
uv run --python 3.12 --with pytest --with pytest-cov --no-project pytest tests/ --cov --cov-branch -q
uv run --python 3.12 mypy --config-file=mypy.ini .          # needs the project env
canvas validate-manifest scheduling_waitlist
```

The test suite stubs the Canvas SDK at import time, so it runs with only `pytest` installed —
no SDK, no Django, and no database. `--no-project` keeps that run from materializing a `.venv`
inside the plugin directory; `--python 3.12` matches the platform runtime, since a bare
`uv run` may pick up an older interpreter.

**Type checking is the exception and does need the project.** `canvas` is a dev dependency for
exactly one reason: without the real SDK on the path, every `canvas_sdk` import is unresolved,
and an unresolved import switches off checking for the whole file that imports it — which is
most of the plugin. With it installed, mypy checks this code properly. It still cannot verify
SDK call signatures, because `canvas_sdk` ships no `py.typed` marker; `follow_untyped_imports`
in `mypy.ini` resolves those imports as `Any` and says so.

`mypy.ini` carries per-module exemptions for framework limitations rather than global ones, each
with the reason inline: the `CustomModel` metaclass being invisible to django-stubs, the
`ModelExtension` / SDK-model `Meta` clash in `models/proxies.py`, the `StaffSessionAuthMixin`
override signature, and the protobuf-generated `EventType.Name`. The last two are covered at
runtime by `tests/test_stub_contract.py`, which checks the stubs against the real SDK.

## License

MIT
