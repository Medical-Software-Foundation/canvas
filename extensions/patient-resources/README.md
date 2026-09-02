# Patient Resources

A configurable library of patient-facing resources that staff can share with a
patient through the patient portal.

Administrators curate a list of links — a title, a public web address, an
internal label, and a note for patients. Any staff member can then open a
patient's chart, search that list, pick one or several, adjust the note for the
person in front of them, and send. The patient signs into the portal and finds
them under **My Resources**, with the note and the date they were shared.

The plugin ships with an empty library. Every practice fills in its own
resources after install; nothing here is specific to any clinic.

## Why it exists

Most practices hand out the same handful of educational links over and over —
a diabetes primer, a pre-operative instruction page, a local support group. Sent
ad hoc, they end up pasted into messages with typos, out-of-date URLs, and no
record of who was given what. Curating them once means the link a patient
receives is the one the practice reviewed.

## Who it's for

- **Administrators** curate the library.
- **Any clinical or front-desk staff member** can share from it. They cannot
  change it.
- **Patients** read what they were given, in the portal, whenever they like.

## Install

```
canvas install extensions/patient-resources/patient_resources
```

Install the **inner** `patient_resources` directory, not the container directory
above it. The plugin runner takes a plugin's name from the folder it was
installed from and routes API requests by matching that name against the URL, so
installing `patient-resources/` makes every endpoint return 404 while the
manifest still validates.

After install, three things appear:

| Surface | Where | Who sees it |
|---|---|---|
| **Patient Resources** | Provider menu (the ☰ menu, top group) | All staff (read-only for non-administrators) |
| **Resources** | Button in the patient chart header | All staff |
| **My Resources** | Patient portal menu | Patients |

## Configuration

All optional. The plugin works unconfigured.

| Variable | Default | What it does |
|---|---|---|
| `PATIENT_RESOURCES_ADMIN_ROLE_DOMAINS` | `ADM` | Comma-separated `StaffRole` domains allowed to curate the library. Valid values: `ADM` (administrative), `CLI` (clinical), `HYB` (hybrid), or `NONE` to allow nobody. |
| `PATIENT_RESOURCES_ADMIN_STAFF_IDS` | empty | Comma-separated staff keys. When set, **replaces** the role rule — only these people may curate. |
| `namespace_read_write_access_key` | supplied by the platform | Required for the plugin to write to its own Custom Data tables. |

Leaving `PATIENT_RESOURCES_ADMIN_ROLE_DOMAINS` empty means "not configured" and
falls back to `ADM`. That is not a quirk worth working around: a variable
declared in the manifest and never given a value reaches the plugin as an empty
string rather than a missing key, so blank and unset are indistinguishable. An
earlier version read blank as "switched off", which left every fresh install with
no administrator and no way to add a first resource.

To switch curation off for everybody, set the value to `NONE` explicitly. A value
that parses to no recognised domain also denies everyone, and logs why — a wrong
value was clearly meant to mean something, so it is not quietly replaced with the
default.

## How it behaves

**The library is a real table, not a setting.** Resources live in this plugin's
own Custom Data namespace, so they survive plugin upgrades and can be searched
and paged rather than parsed out of a configuration string.

**Both staff lists are paged.** The library page shows 50 rows at a time and the
chart picker 25, each with a range ("Showing 51–100 of 137 resources.") and
Previous/Next. The listing endpoint takes `limit` and `offset` and caps a page at
200. Search and the label filter always return to the first page, because the
result set changes underneath the offset.

Selecting in the picker survives a page change, and anything selected that is no
longer on screen is named in the footer, so a resource picked on page one cannot
go out unnoticed. One send carries at most 25 resources — the API enforces it,
and the picker holds the same limit so the feedback arrives before the click.

**Labels are internal; notes are patient-facing.** A label is how staff file and
filter a growing library — "Diabetes", "Post-op", "Spanish" — and it is never
sent to a patient. The note is the opposite: it is written for them, and it is
what they read under the title in the portal.

**A note has a default, and a per-patient copy.** The library entry carries the
blurb the resource usually goes out with. The picker pre-fills it, the sender can
rewrite it for the person in front of them, and what they send is stored on that
patient's own share. Editing the library default afterwards changes what the next
send starts from — never what somebody already received.

**Correcting a title reaches patients who already have it.** The portal reads the
resource's current title, so fixing a typo fixes it for everyone, including people
who received it last month.

That is safe because **a shared resource's link cannot be changed.** Once anyone
has received it, the link is frozen and an edit is refused, with a prompt to add a
replacement and archive the original. The link is the identity of what a patient
was given, so with it immutable a title edit can only ever redescribe the same
resource — never quietly swap it for a different one.

The title and note behave in deliberately opposite ways, because they say
different things. A title describes the resource, so one correction should reach
everyone. A note describes what *this* patient should do with it, so nothing in
the library may reach back and rewrite it.

Each share also stores the title and link as they were when it was sent. Those
are the fallback when a catalog row is missing, and the title is what a withdrawn
notice shows, since a withdrawn resource may since have been edited and the
patient cannot open it anyway.

Two consequences of the same rule are worth knowing:

- **Archiving hides a resource for everyone, immediately.** That is how a wrong
  or harmful link is pulled from the picker and from every portal at once.
- **There is no hard delete for anything a patient received.** The foreign keys
  carry no cascade, so removing the catalog row would orphan the share records.

**A resource nobody received can be deleted outright.** Archiving is the right
answer for something you used to offer, but it is the wrong record to leave for a
row added by mistake — a typo, a duplicate, or test data on a trial instance. So
a resource that has never been shared with anyone offers **Delete** where a
shared one offers **Withdraw**: one slot in the row, and which control appears
tells you whether that resource ever reached a patient. Deletion is refused for
anything a patient ever received, including shares that were later withdrawn,
because the foreign keys carry no cascade and removing the catalog row would
leave those records pointing at nothing.

**A resource already taken back offers nothing to take back.** The row's
destructive control follows what is actually possible: Delete only where no
patient ever received it, and Withdraw for anything with share history — shown
disabled, with the reason on hover, when every share has already been withdrawn.
The server refuses such a withdrawal with a 409 as well, so a direct request
cannot succeed at doing nothing.

**An inactive resource says why it is inactive.** Withdrawing archives the
resource as part of taking it back, so the library marks the row **Withdrawn**
rather than **Archived** when patients actually lost something. Restoring it
makes it offerable again but does not un-withdraw: patients who had it taken back
do not get it returned, though it can be sent to them afresh.

**Withdrawing is louder than archiving.** *Withdraw* marks every patient's copy
as withdrawn and archives the resource. The patient's portal then says the item
was withdrawn by their care team, with the date, rather than the row silently
disappearing from a list they had already read. It asks for typed confirmation.

**Sharing twice is not an error.** A resource a patient already has is reported
as already shared and not duplicated. The response distinguishes what was newly
sent, what was already there, and what has since been archived.

**The picker closes itself once it has done what was asked.** Sharing is the only
thing that window does, so a send that went out cleanly ends the task rather than
leaving a summary to dismiss. The summary stays for a send that needs explaining
— something already in the patient's list, or something archived since the page
was drawn.

**Nothing is emailed or texted.** Delivery is the portal, only. The portal menu
entry carries a count of resources the patient has not looked at yet, which is
how they notice new ones.

## Deliberately not built

Each of these was considered and left out. They are decisions, not omissions.

- **PDF attachments.** Links only. The sandbox has no filesystem and there is no
  SDK effect that attaches a document to a chart or a message, so hosting a PDF
  would mean an external store. Adding it later means one more field and a
  storage integration; nothing here has to change.
- **Email and SMS.** There is no generic outbound-message effect in the SDK, and
  wiring in a third-party provider would put the practice's name on wording this
  plugin invented. The portal is the channel.
- **A message when resources are shared.** The badge on the portal menu tells the
  patient without this plugin composing a clinical message on the practice's
  behalf. Adding a message later is additive; retracting one patients have
  already read is not.
- **Letting providers edit the library.** Curation is an administrator task by
  design, so one bad link cannot reach every patient.
- **Per-patient retraction.** Withdrawal is library-wide. Un-sharing one item
  from one patient is a plausible next request, and it needs a UI for finding
  that share; nothing in the data model prevents it.
- **Send reporting.** Every share is dated and attributed in the table, so a
  report is queryable — but no report surface ships here.

## Components

| Class | Kind | Purpose |
|---|---|---|
| `applications.library_app:PatientResourcesAdminApp` | Application (provider menu) | Opens the library as a full page |
| `applications.portal_app:MyResourcesPortalApp` | Application (portal menu) | Opens the patient's list, and carries the unread badge |
| `handlers.chart_button:ShareResourcesButton` | ActionButton (chart patient header) | Opens the picker for the open chart |
| `routes.staff_pages:StaffPagesAPI` | SimpleAPI (staff) | Serves the library and picker pages and their assets |
| `routes.library_api:LibraryAPI` | SimpleAPI (staff) | Reading and curating the library |
| `routes.share_api:ShareAPI` | SimpleAPI (staff) | Patient lookup and sending |
| `routes.portal_pages:PortalPagesAPI` | SimpleAPI (patient) | Serves the portal page and its assets |
| `routes.portal_api:PortalAPI` | SimpleAPI (patient) | Returns the signed-in patient's resources |

No event handlers and no scheduled work: everything happens in response to
somebody clicking something.

### Data

Two tables in the `custom_data__patient_resources` namespace:

- `PatientResource` — the catalog. Title, link, internal label, the default
  patient-facing note, status, and who last changed it.
- `PatientResourceShare` — one row per resource given to one patient, holding the
  snapshot of what was sent, the note written for that patient, who sent it, and
  when it was withdrawn or first viewed.

## Security notes

- **A patient can only ever read their own list.** The portal endpoint takes no
  identifier of any kind — not a patient key, not a share id — and scopes its
  query from the session header alone. There is nothing in the request for a
  patient to change in order to see somebody else's resources.
- **The admin app icon cannot be hidden from non-administrators.** Canvas has no
  role scoping for application visibility, so every staff member can open it. It
  renders read-only with an explanation, and every write endpoint re-checks
  permission server-side.
- **Links are validated on write and again on render.** Only absolute `http://`
  and `https://` addresses are accepted; `javascript:`, `data:`,
  protocol-relative and same-origin relative links are refused. The check runs
  again when a resource is serialized, so a row stored before a validation change
  cannot render as a live link.
- **Outbound links carry `rel="noopener noreferrer"`** and the portal page sets a
  no-referrer policy. That is a privacy control here: without it, a third-party
  health site would receive the portal URL and learn that a patient viewed a
  resource about a particular condition.
- **No outbound HTTP.** The plugin never fetches a resource itself; the browser
  opens the link.

## Development

```bash
cd extensions/patient-resources

# tests -- the suite fabricates canvas_sdk and Django, so no SDK is needed
uv run --python 3.12 --with pytest --no-project pytest tests -q

# branch coverage; the repo gate is >=90%
uv run --python 3.12 --with pytest --with pytest-cov --no-project \
  pytest tests --cov --cov-branch --cov-report=term-missing -q

# types -- the one step that needs the real SDK
uv sync && uv run --python 3.12 mypy --config-file=mypy.ini .

# manifest, static lint, and a sandbox load of every declared handler
canvas validate patient_resources

# front-end syntax
node --check patient_resources/static/js/library.js
node --check patient_resources/static/js/picker.js
node --check patient_resources/static/js/portal.js
```

`canvas validate` is the one that catches what the test suite cannot. pytest runs
under CPython; the plugin runs inside RestrictedPython, where `setattr`, `x.attr
+= 1` and most of `urllib.parse` are unavailable. A green suite says nothing
about whether the plugin loads. Requires a CLI at 0.200 or newer.

Bump `CACHE_BUST` in `patient_resources/__init__.py` whenever a template, script
or stylesheet changes; it versions every asset URL, and it is asserted to match
`plugin_version`.

Two things about the tables are worth knowing before changing them. The DDL
pipeline emits no NOT NULL constraints and no column defaults, so every reader
has to tolerate `None` in every column. And it is append-only — `ADD COLUMN IF
NOT EXISTS` is the only statement it produces — so a renamed or retyped column
cannot be corrected after the first install. `tests/models/test_schema.py` is the
guard on that.

## License

MIT.
