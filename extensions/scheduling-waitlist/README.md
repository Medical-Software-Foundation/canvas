# Scheduling Waitlist

A shared, priority-ordered list of patients waiting to be scheduled — and a task to the
scheduling team the moment a booked slot frees up.

When an appointment is cancelled or a patient no-shows, that slot usually goes to waste because
nobody remembers who was waiting for it. This plugin keeps the waiting list in one place and
reacts to cancellations automatically.

**The plugin never books anyone.** It recommends; staff schedule from the task.

## What it does

**The roster** — a practice-wide page in the **provider (hamburger) menu** listing everyone
waiting, sorted by priority then wait time. Filter by service, provider, or location; search by
patient name. Each row can open the patient's chart, be edited, marked scheduled, or removed.

Filtering asks "who could take a slot like this?", so choosing a provider **also** lists the
patients who said they would see anybody — they are the likeliest candidates for that provider's
next cancellation, and hiding them contradicted the task the plugin would go on to raise. Same for
service and location. The roster and the freed-slot matcher share one implementation of that rule
(`services/preferences.py`) so they cannot drift apart again.

**Adding a patient** — three ways, and only two of them involve a form:

- **From the patient chart header**, in one click. The **"Waitlist"** button adds them on the
  broadest terms — any appointment type, any provider, any location, the configured default
  priority, no time preference — with no modal in between. It reads **"On waitlist"** once they
  are listed, and a second click on it opens that entry's own form, which is where the broad
  entry gets narrowed to "only Dr Chen, Tuesday mornings". A patient with *several* live entries
  has no single entry to open, so that opens the roster with their name already typed into the
  search box.
- **From the roster**, searching for the patient by name. This is the full form, and the way to
  state a *specific* want: this service, that provider, Tuesday mornings.
- **From a no-showed appointment's note**, pre-filled with the service, provider and location
  of the slot that just freed up. A **cancelled** appointment has no equivalent surface — its
  note is tombstoned in the timeline with nothing but `Restore`, so use the chart-header button.
  See the maintainer note below.

**Why the chart writes immediately.** Every field on that form already defaulted to its broadest
setting, so the modal and the second click were confirming answers that were correct on arrival.
Reviewers asked for the clicks back. Offering the shortcut as a *second* button beside the form
was tried and was worse than either: a chart header truncates labels at roughly twelve
characters, so "Add to waitlist" and "Waitlist: any" both rendered as an ellipsis and became
impossible to tell apart. (That truncation had been mangling "Add to waitlist" all along —
"On waitlist" is eleven characters and always fitted, which is why it is unchanged.)

The write goes through the same `validate_entry` the forms post to (`services/quick_add.py`), so
the shelf life, the priority default and the shape of a preferred window have exactly one
implementation.

**Stating a specific want from the chart is the second click.** The first click is deliberately
not the one that asks questions: the patient is on the list before anything can go wrong, and the
detail is optional. Clicking "On waitlist" opens `/app/edit?entry=<dbid>` — the same compact form
the add uses, in edit mode, loaded from `GET /waitlist/entries/<dbid>`. It is a form about one
entry, not the roster: a full-width table is not a dialog, which is the same reason the add form
has its own page.

The form is the roster's own dialog: it links `roster.css` and uses the dialog's classes rather
than inlining a copy of them, so the two cannot look like two different forms. The only field it
leaves out is the patient picker — the chart already knows who this is about, and an edit cannot
reassign the patient.

**A patient with several live entries opens the roster, searched for their name.** There is no
single entry to edit, and guessing one would edit the wrong want — but "open the roster" used to
mean searching a table that can run to thousands for the patient whose chart was already on
screen. So the URL carries `?q=<name>`, which lands in the search box the roster already has.

That is **not** the patient-scoped roster reverted in `cf94418`, and the difference is what that
revert asked for: no filter the UI does not show, no `patient_id` key, no "Show everyone" control
to escape it. It is the keyword search from the ticket's own acceptance criteria, pre-typed — the
term is visible in the box, `Reset` clears it, and the count line says "2 matching patients."
rather than reporting a filtered total as the practice-wide one, which is the misreading that sank
the earlier attempt.

One consequence worth naming: a patient's **display name travels in that query string**, so it
lands in browser history where a dbid would not. Judged acceptable because the page it opens lists
that name and every other waiting patient's anyway, and the URL is same-origin and
staff-authenticated. If that stops being acceptable, the fix is for the button to pass a key and
the roster route to resolve the name — which means `WaitlistAppAPI` starts reading patients and its
manifest `data_access` stops being empty.

The **"On waitlist"** button on a freed appointment's note does the same thing, opening the entry
for *that slot's service* — the one `visible()` checked before it chose the label. Two buttons
wearing one label had to behave one way.

If the clicking staff member cannot be resolved from the event, the click **opens the old form
instead of writing**. An entry attributed to nobody can be edited or removed only by a configured
manager, never by the person who added it, so degrading to two clicks is the cheaper failure. See
the maintainer note on button actors.

**From the chart** — the chart carries two things, because it is asked two different questions:

- A **banner** on the chart of anyone already waiting, saying what they are waiting for and
  linking back to the roster. This answers "is this patient on the list?" without a click.
- The **button** above, which answers "put them on the list" — an action, which a passive banner
  cannot serve.

Both waitlist buttons are **filled in the listed state** and left on the platform's own styling
otherwise. The two labels do different jobs — "Waitlist" is an action, "On waitlist" is a
statement of fact — and drawn identically the second read as an action too, which reviewers
reported as confusing. Colouring only the exception means a plain button always means "there is
something to do here". Both colours live in `constants.py`; `ShowButtonEffect` validates them as
exactly `#RRGGBB`, so names, shorthand and `rgba()` are refused at the effect.

Where a form *is* shown, it is the roster's own rather than a second implementation, so there is
one set of validation rules. Only the patient's key travels in the page URL; the name behind it is
fetched over the authenticated API, so no identifiable data is baked into the document.

**Cancellation matching** — when a booked slot frees up, the plugin finds waiting entries whose
requested type, provider, and location fit it, and raises **one** task to the scheduling team
naming them in priority order. Each patient's preferred day/time is shown so staff can judge fit.

All three of those fields accept "any", and all three **default** to it. That default is
deliberate: the alternative is defaulting to whichever value happens to sort first, which is a
choice the patient never made and which matches no slot unless the practice happens to book that
exact thing. An entry that matches too widely is visible and correctable; one that matches nothing
looks perfectly well-formed on the roster and simply never fires.

A slot counts as freed whether staff cancelled it, the patient cancelled or rescheduled it in
the patient portal, it was no-showed, or the booking was moved to another time. For a
reschedule, the slot announced is the one the booking moved *away* from — the new booking is
occupied. Duplicate deliveries are harmless: every path fingerprints the same freed slot, so a
cancellation and a no-show for one booking raise one task between them.

**Next appointment** — each roster row shows what that patient already has booked, and a row for
somebody who has **already been seen** is tinted so it can be found while scanning.

This is the visible half of a deliberate decision made elsewhere. `AppointmentBookedHandler`
closes an entry only when a booking satisfies what the entry actually asked for, because a patient
waiting for Dr Chen who gets booked with somebody else still wants Dr Chen. The cost of that
strictness is that the entry stays open with nothing to show anything happened — which is how a
waitlist fills up with people who no longer need the call. The column supplies the missing signal
and **changes nothing**: a visit for a different service does not satisfy the request, so the
judgement stays with the person reading the row.

Two states, meaning opposite things. *Booked* is reassurance and is drawn quietly. *Seen* is the
warning, and is the only one coloured. Only real patient visits count — the same
`is_patient_visit` exclusion the appointment-type dropdown uses, so a calendar block on a chart is
not mistaken for an appointment somebody attended — and only appointments that were actually
attended (`arrived`, `roomed`, `exited`), because one still sitting at `unconfirmed` a week later
says nothing about whether the patient turned up. History is bounded to
`RECENT_VISIT_WINDOW_DAYS`; the whole page is answered in one query
(`services/appointments.py`).

**Housekeeping** — a nightly job ages out entries past their configured shelf life and logs
wait-time and fill metrics. Ageing marks entries `expired`; it never deletes them, so the backlog
report stays intact and an entry can be reinstated in one click.

The same job **closes slot-opened tasks whose slot has already started**. A freed slot is only
fillable until it begins, so after that the task is dead work — and nothing else would ever close
it, leaving the scheduling team's queue growing by one per cancellation until the live call-lists
were lost among finished ones. This runs whether or not `WAITLIST_TTL_DAYS` is set: the two are
unrelated, and an unconfigured instance is still a working one.

A task is *not* closed when someone actually books the freed slot — that would mean matching a new
appointment back to a freed one, and it is not implemented yet. Until then a filled slot's task is
closed by the nightly sweep once the slot time passes, or by the scheduler marking it Done.

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

| Variable | Required | Default | What it does |
|---|---|---|---|
| `WAITLIST_SCHEDULING_TEAM` | **yes** | — | Team UUID or exact name that receives slot-opened tasks. Unset ⇒ no task is raised (an unassigned task is an unread task) |
| `WAITLIST_APPOINTMENT_TYPES` | no | *(every bookable type)* | Comma-separated `NoteType` **codes** to narrow what the form offers. Codes, not names, because names change across versions and installs. Unset ⇒ every bookable type is offered, so the plugin works on a fresh install. A list matching nothing bookable falls back to all of them and logs an error, because a typo should not empty the form |
| `WAITLIST_PRIORITY_LABELS` | no | `High,Medium,Low` | Comma-separated, highest priority first |
| `WAITLIST_TTL_DAYS` | **yes** | — | Days before a waiting entry ages out. Invalid ⇒ nothing expires |
| `WAITLIST_MANAGER_ROLE_CODES` | no | *(empty)* | Staff role codes allowed to edit or remove **other** people's entries. Unset ⇒ everyone still manages their own |
| `WAITLIST_ENFORCE_TIME_WINDOWS` | no | `false` | When `true`, a patient's preferred day/time filters matches instead of only being displayed |
| `WAITLIST_MAX_MATCHES_PER_TASK` | no | `10` | Cap on patients named in one task |
| `WAITLIST_MIN_LEAD_TIME_HOURS` | no | `2` | Slots starting sooner than this are ignored — nobody can fill them |
| `WAITLIST_URGENT_LEAD_HOURS` | no | `48` | Slots starting within this window raise an urgent task |
| `WAITLIST_DISPLAY_TIMEZONE` | no | `UTC` | IANA timezone for times in tasks. The abbreviation is always printed, so a wrong value is visible rather than silent |

> The manifest declares these under `variables`, the key newer CLI versions expect; the older
> `secrets` key is reported as deprecated. They are still read through `self.secrets` in handler
> code, which is the SDK's accessor regardless of which manifest key declares them.

## Components

| Class | Kind | Responds to |
|---|---|---|
| `applications.waitlist_app:WaitlistApp` | Application (`provider_menu_item`) | provider (hamburger) menu, pinned to the top |
| `routes.app_routes:WaitlistAppAPI` | SimpleAPI | serves the roster page and assets |
| `routes.waitlist_api:WaitlistAPI` | SimpleAPI | entry CRUD, patient search, dropdown options |
| `handlers.chart_button:AddToWaitlistButton` | ActionButton | chart patient header — one-click add on the broadest terms, or the roster once they are listed |
| `handlers.appointment_button:AddToWaitlistAppointmentButton` | ActionButton | note header, cancelled/no-showed appointments only — so in practice the no-show, which is the only one of the two whose note still has a header |
| `handlers.slot_freed:SlotFreedHandler` | Handler | `APPOINTMENT_CANCELED`, `APPOINTMENT_NO_SHOWED`, `APPOINTMENT_RESCHEDULED`, `PATIENT_PORTAL__APPOINTMENT_CANCELED`, `PATIENT_PORTAL__APPOINTMENT_RESCHEDULED` |
| `handlers.appointment_booked:AppointmentBookedHandler` | Handler | `APPOINTMENT_CREATED` |
| `handlers.note_buttons:NoteButtonsRefreshHandler` | Handler | `NOTE_STATE_CHANGE_EVENT_CREATED` |
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

**A button click has no request, so its actor comes off the event.** Every other write in this
plugin arrives on an authenticated request and resolves the acting staff member from the
`canvas-logged-in-user-id` header. A button click has no such header: the identity is
`event.actor.id`, which is a **`CanvasUser` dbid**, not a staff key — `Actor.instance` looks it up
as one — so `services/permissions.py:staff_from_actor` goes through `Staff.user` rather than
matching `Staff.id`.

Whether that field is populated for `ACTION_BUTTON_CLICKED` is server behaviour a plugin cannot
see from the SDK source, which is why `AddToWaitlistButton.handle()` treats an unresolved actor
as a reason to open the form instead of writing. Do not "simplify" that fallback into
`created_by=None`: `can_modify_entry` keys on the creator, so such an entry becomes untouchable by
the very scheduler who added it. If the fallback turns out to fire on the instance, the fix is to
find where the actor really lives — not to write the entry anyway.

**The application's scope decides where its icon lives, not how it opens.** Moving the roster from
the app drawer to the hamburger menu was a one-word manifest change, `"scope": "global"` →
`"provider_menu_item"` (plus `menu_position`), with no change to `WaitlistApp`. Note that the other
`provider_menu_item` apps in this repo launch with `TargetType.PAGE` or `NEW_WINDOW` while this one
uses `DEFAULT_MODAL`; if the modal ever misbehaves from the menu, `PAGE` is a reasonable swap for a
full-width table — but the roster's Close button talks to the host modal's `MessagePort`, so it
would need hiding in that case.

**Being scheduleable does not make a note type an appointment.** Canvas marks calendar blocks —
"Generic event" and friends, category `schedule_event` — as scheduleable, because staff schedule
*time* with them. There is no patient, so a waitlist entry for one can never be filled. It was
also alphabetically first on the test instance, and therefore the form's default, which is how
entries got created that matched nothing while looking perfectly well-formed.
`services/options.py:NON_VISIT_CATEGORIES` excludes it along with messages, letters, tasks, data,
C-CDA and chart reviews. Stated as an exclusion rather than an allow-list of visit categories, so
an instance that classifies a real visit type unusually still offers it; if the exclusion would
empty the list entirely it falls back to everything scheduleable and logs an error, because an
empty form teaches a scheduler nothing.

**A UI no-show emits no `APPOINTMENT_NO_SHOWED` event, so button refreshes hang off the note
state instead.** Observed on `vicert-testing`: clicking No show moved the note to `NSW` and
`SlotFreedHandler` — which does subscribe to `APPOINTMENT_NO_SHOWED` — never ran at all. Whether
the platform writes `Appointment.status` for a UI no-show is server behaviour a plugin cannot see,
which is why `handlers/appointment_button.py` consults both records and treats either as enough.

An ActionButton also decides visibility only as the note renders, and nothing redraws it, so the
button appeared on a no-show only after a page reload. `handlers/note_buttons.py` closes that by
subscribing to `NOTE_STATE_CHANGE_EVENT_CREATED` and emitting `ReloadNoteActionButtonsEffect`.
Two things about it are deliberate:

- **It does not filter on which state was entered.** The button's answer changes both entering
  cancelled/no-showed and leaving it — reverted, restored, undeleted, and whatever is added next.
  Enumerating the second half is a list that goes stale without anything failing, and the two
  errors are not symmetric: a spare redraw is an idempotent re-render, a missing one leaves a
  button that lies. It gates on the note having an appointment instead, since no other note can
  carry the button.
- **It addresses the note by UUID, not dbid.** `ReloadNoteActionButtonsEffect` validates against
  `Note.id`, while a note-header button receives the note's *dbid*. Mixing them up passes a test
  suite and fails on the instance.

**A cancelled appointment has nowhere to put a button, and this is not fixable here.** Please
don't spend an afternoon on it. Cancelling an appointment tombstones its note: the chart timeline
shows a greyed strip — `[CANCELED] Office visit 2 - On Wednesday, 8/19/26 …` — with a trash icon
and a `Restore` link, and that is the entire surface. The note does not open, so it has no header,
no footer and no body.

Every note-related `ActionButton.ButtonLocation` the SDK offers requires an **open** note
(`NOTE_HEADER`, `NOTE_FOOTER`, `NOTE_BODY`, `NOTE_HEADER_DROPDOWN`); the other twelve are chart
surfaces. There is no appointment-card, calendar-grid or timeline-row location. So no plugin can
render anything on that strip.

`visible()` is not the problem and does not need changing — it already accepts either
`Appointment.status ∈ {cancelled, noshowed}` or note state `∈ {CLD, NSW}`, and both signals are
still needed, because only one of the two records is guaranteed to move on a no-show. The
condition is right; there is simply nowhere to draw.

The workflow this costs is worth naming, because it is easy to assume the freed-slot task already
covers it. It does not: the **task** names *other* waiting patients and deliberately excludes the
one who cancelled, whereas the **button** exists to put *that* patient on the list — someone who
cancels usually wants a different time rather than nothing at all. The chart-header button serves
that, and is one click away since you are already in the patient's chart. The only thing lost
against the note button is the pre-fill of the freed slot's service, provider and location — and
since the chart button's second click now opens the entry's own form, re-entering it is a
correction rather than a re-add.

If the manual re-entry becomes annoying, the fix is to pre-fill the chart-header button from the
patient's most recent cancelled or no-showed appointment — which needs no note surface at all.
That is a behaviour change and deliberately not done yet.

**One template serves both the add and the edit form, and wears the roster's stylesheet.**
`templates/entry_form.html` (formerly `add_patient.html`) chooses its verb from `config.mode`:
`add` fetches the patient and POSTs to `/waitlist/entries`, `edit` fetches the entry from
`GET /waitlist/entries/<dbid>` and PUTs back to it.

It links `roster.css` and uses the roster dialog's own classes — `wl-dialog-body`, `wl-form-grid`,
`wl-field`, `wl-dialog-actions` — rather than the inline copy it used to carry. The copy had its
own spacing, its own sentence-case labels and no action bar, so the form opened from a chart and
the form opened from the roster were visibly two different dialogs; reviewers compared them side by
side and rejected it. `.wl-modal-page` in `roster.css` supplies the two things the dialog got from
being a `<dialog>`: the white ground and an action bar at the bottom of the viewport. Because
`.wl-dialog h2` and `.wl-dialog textarea` only match inside a `<dialog>`, both selectors name
`.wl-modal-page` too — `TestTheFormLooksLikeTheRostersOwnDialog` fails if either is dropped.

While doing that: `[hidden] { display: none !important; }` is now in `roster.css`. The browser's
own rule for the attribute is `display: none`, which any author `display` outranks — so
`.wl-pager { display: flex }` had been keeping the pager on screen with `hidden` set, and the form
page would have flashed before its options loaded. They ask for the same six fields against the same validator, so a second template would be the
same form twice — and the last pair that drifted disagreed about whether "any appointment type" was
on offer at all, which is how entries got created for services nobody books. Anything other than
the literal `"edit"` is treated as `add`, so a mistyped URL cannot leave the form PUTting to an
entry key it never read.

The one duplication left is `WINDOW_SHAPES`, the table that matches a stored window (days plus a
start time) back to the named option it was chosen under. It exists in both the template and
`roster.js` because the two forms share no script, and `test_the_window_shapes_agree_with_the_rosters_own`
fails if the copies drift. Without that reconstruction an edit silently clears a time preference
the patient gave, which is the kind of bug nobody reports because nothing looks broken.

`GET /waitlist/entries/<dbid>` is gated by the **write** check, not by read access: it is a form's
own load, and refusing someone after they have retyped an entry is worse than refusing them now.
That is why it sits in the write section of `routes/waitlist_api.py` alongside the routes it shares
`_entry_for_write` with, and why `TestWriteAuthorization` iterates over it.

**The roster's search requires every word, not the whole term.** `build_queryset` filters once per
whitespace-separated word, each matching `patient__first_name` or `patient__last_name`. Before that
a full name typed into the box — which is what the box's own placeholder invites — matched nothing,
because no single column holds both words. One word behaves exactly as it did. The term is capped
at `SEARCH_TERM_WORD_LIMIT` words, since each one is another predicate on the patient join and the
value arrives from a query string.

The count line distinguishes the two cases: unfiltered it says "128 patients waiting", filtered it
says "3 matching patients". Reporting a filtered total as a statement about the practice is what
made a narrowed roster look like a waitlist holding one person, and the honest wording needs no
second query to be true.

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
