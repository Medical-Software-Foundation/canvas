# External Calendar Busy Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Canvas plugin that subscribes to a provider's personal calendar via an ICS URL and writes busy times to their Canvas Admin calendar every 15 minutes.

**Architecture:** Four components — a global-scope Application (config UI), a SimpleAPI (`POST /feeds`, `DELETE /feeds`), two CustomModels (`StaffCalendarFeed`, `ImportedEvent`), and a CronTask. The cron fetches each active feed with conditional headers, runs it through a plugin-internal ICS parser + RRULE expander, diffs against `ImportedEvent` rows, and emits `Event.create/update/delete` effects.

**Tech Stack:** Python 3.12, `canvas_sdk` (Application, SimpleAPI, CronTask, CustomModel, Event effect, Http), stdlib (`datetime`, `zoneinfo`, `re`), `dateutil.relativedelta`, `arrow.get`. **No `icalendar` library** — sandbox does not allowlist it; the plugin implements ICS parsing and RRULE expansion itself.

**Spec:** `docs/superpowers/specs/2026-06-01-external-calendar-busy-blocks-design.md`

---

## File Structure

```
extensions/external-calendar-busy-blocks/
├── README.md
├── pyproject.toml
└── external_calendar_busy_blocks/
    ├── CANVAS_MANIFEST.json
    ├── __init__.py
    ├── assets/
    │   └── calendar-icon.png
    ├── data/
    │   ├── __init__.py
    │   └── models.py                  # StaffCalendarFeed, ImportedEvent
    ├── ics/
    │   ├── __init__.py
    │   ├── parser.py                  # ICS line unfolding + property/VEVENT extraction
    │   ├── datetimes.py               # DTSTART/DTEND parsing + tz resolution
    │   ├── rrule.py                   # RRULE parse + expand DAILY/WEEKLY/MONTHLY/YEARLY
    │   └── types.py                   # ParsedEvent dataclass, IcsParseError
    ├── http/
    │   ├── __init__.py
    │   └── fetcher.py                 # Conditional-header fetch + URL redaction
    ├── calendars/
    │   ├── __init__.py
    │   └── admin_lookup.py            # find_admin_calendar(staff)
    ├── sync/
    │   ├── __init__.py
    │   └── cron.py                    # SyncCron orchestrator
    ├── routes/
    │   ├── __init__.py
    │   └── feeds.py                   # POST /feeds, DELETE /feeds
    ├── apps/
    │   ├── __init__.py
    │   └── busy_blocks_app.py         # Application + on_open returning LaunchModalEffect
    ├── ui/
    │   ├── __init__.py
    │   └── pages.py                   # GET /pages/config — HTML config page
    └── templates/
        └── config.html

tests/
├── __init__.py
├── conftest.py
├── fixtures/
│   └── ics/                            # Static .ics files for parser tests
│       ├── simple_confirmed.ics
│       ├── tentative_event.ics
│       ├── transparent_event.ics
│       ├── cancelled_event.ics
│       ├── all_day_event.ics
│       ├── multi_timezone.ics
│       ├── floating_time.ics
│       ├── weekly_recurring.ics
│       ├── monthly_byday.ics
│       ├── rrule_with_exdate.ics
│       ├── recurrence_id_override.ics
│       ├── unbounded_rrule.ics
│       ├── oversized_rrule.ics
│       └── malformed.ics
├── data/test_models.py
├── ics/test_parser.py
├── ics/test_datetimes.py
├── ics/test_rrule.py
├── http/test_fetcher.py
├── calendars/test_admin_lookup.py
├── sync/test_cron.py
├── routes/test_feeds.py
└── apps/test_busy_blocks_app.py
```

Each Python file has one responsibility; tests live in mirrored directories.

---

## Task 1: Plugin scaffolding

Create the on-disk skeleton. No application logic yet — just the structure subsequent tasks build into. This task has no tests; it is pure scaffolding and ends with a commit.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/README.md`
- Create: `extensions/external-calendar-busy-blocks/pyproject.toml`
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/CANVAS_MANIFEST.json`
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/__init__.py` (empty)
- Create: all subdirectory `__init__.py` files (empty)
- Create: `tests/__init__.py` (empty) and mirrored test subdirs

- [ ] **Step 1: Create the directory skeleton**

```bash
cd /Users/amandap-canvas/Code/msf-canvas/extensions
mkdir -p external-calendar-busy-blocks/external_calendar_busy_blocks/{assets,data,ics,http,calendars,sync,routes,apps,ui,templates}
mkdir -p external-calendar-busy-blocks/tests/{fixtures/ics,data,ics,http,calendars,sync,routes,apps}
cd external-calendar-busy-blocks
touch external_calendar_busy_blocks/__init__.py
touch external_calendar_busy_blocks/{data,ics,http,calendars,sync,routes,apps,ui}/__init__.py
touch tests/__init__.py
touch tests/{data,ics,http,calendars,sync,routes,apps}/__init__.py
```

- [ ] **Step 2: Write the outer `pyproject.toml`**

Create `extensions/external-calendar-busy-blocks/pyproject.toml`:

```toml
[project]
authors = [
  {email = "engineering@canvasmedical.com", name = "Canvas Team"},
]
dependencies = [
  "canvas[test-utils]",
]
description = "Subscribe Canvas to a provider's personal calendar via ICS and mirror busy times as Admin events."
license = "MIT"
name = "external_calendar_busy_blocks"
readme = "README.md"
requires-python = ">=3.12"
version = "0.1.0"

[tool.pytest.ini_options]
python_files = ["*_tests.py", "test_*.py", "tests.py"]

[tool.coverage.run]
source = ["external_calendar_busy_blocks"]
omit = ["tests/*", "*/__pycache__/*", "*/.venv/*"]

[tool.coverage.report]
exclude_lines = [
  "pragma: no cover",
  "def __repr__",
  "raise AssertionError",
  "raise NotImplementedError",
  "if __name__ == .__main__.:",
  "if TYPE_CHECKING:",
]

[dependency-groups]
dev = [
  "pytest-cov>=7.0.0",
]
```

- [ ] **Step 3: Write `CANVAS_MANIFEST.json` stub**

Create `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/CANVAS_MANIFEST.json`:

```json
{
    "sdk_version": "0.1.4",
    "plugin_version": "0.1.0",
    "name": "external_calendar_busy_blocks",
    "description": "Subscribe Canvas to a provider's personal calendar via ICS and mirror busy times as Admin events.",
    "components": {
        "protocols": [],
        "applications": [],
        "commands": [],
        "content": [],
        "effects": [],
        "views": []
    },
    "secrets": ["LOOKAHEAD_DAYS"],
    "tags": {},
    "references": [],
    "license": "MIT",
    "diagram": false,
    "readme": "../README.md"
}
```

Task 14 fills in `protocols` and `applications` once the classes exist.

- [ ] **Step 4: Write the README**

Create `extensions/external-calendar-busy-blocks/README.md`:

```markdown
# External Calendar Busy Blocks

Subscribe Canvas to a provider's personal calendar (Google Calendar, Outlook, Apple iCloud) via the calendar's secret iCal/ICS URL. Every 15 minutes, the plugin fetches each connected feed and writes the busy times as "Busy" events on the provider's Canvas Admin calendar.

## How it works

Each provider opens the **Calendar Busy Blocks** application from the Canvas global menu, pastes their personal calendar's secret iCal URL, and clicks Save. A scheduled task runs every 15 minutes:

1. Fetches each provider's ICS feed (sending `If-None-Match` / `If-Modified-Since` so unchanged feeds return `304 Not Modified` and skip work).
2. Parses the feed, filters to confirmed busy events, expands recurring events within a 90-day window, and converts everything to UTC.
3. Diffs the parsed events against the events the plugin previously imported and emits `Event.create`, `Event.update`, or `Event.delete` effects.

Canvas users see only "Busy" — the original event titles never leave the personal calendar.

## Configuration

| Plugin secret | Default | Notes |
|---|---|---|
| `LOOKAHEAD_DAYS` | `90` | How far in advance to expand recurring events. |

## Privacy & security

- The secret ICS URL **is** a bearer token. Store it as the provider's personal calendar's *secret* iCal URL, not a shared one.
- The plugin imports only event start/end times. Titles, descriptions, and attendees are discarded.
- URLs are never logged in full — tokens are redacted.

## Limitations

- Tentative events (`STATUS=TENTATIVE`) and transparent events (`TRANSP=TRANSPARENT`) are not imported.
- Recurring events use a subset of RFC 5545: `FREQ=DAILY|WEEKLY|MONTHLY|YEARLY` with `INTERVAL`, `BYDAY`, `BYMONTHDAY`, `BYMONTH`, `UNTIL`, `COUNT`, `EXDATE`, `RECURRENCE-ID`. Unsupported rule features (`BYSETPOS`, `BYWEEKNO`, `BYYEARDAY`, `WKST`, sub-daily `BY*`) cause the VEVENT to be dropped with a warning log.
- One feed per provider in v1.
- Source-side lag dominates: Google and Outlook regenerate their public ICS feeds on a 30–60 min cycle; Canvas-side polling is 15 min.
```

- [ ] **Step 5: Generate a 48x48 placeholder calendar icon**

Run:

```bash
cd /Users/amandap-canvas/Code/msf-canvas/extensions/external-calendar-busy-blocks
python -c "
from struct import pack
import zlib
w=h=48
raw=b''
for y in range(h):
    raw+=b'\x00'
    for x in range(w):
        raw+=bytes([1,164,255])
def chunk(t,d):
    c=zlib.crc32(t+d)
    return pack('>I',len(d))+t+d+pack('>I',c)
png=b'\x89PNG\r\n\x1a\n'
png+=chunk(b'IHDR',pack('>IIBBBBB',w,h,8,2,0,0,0))
png+=chunk(b'IDAT',zlib.compress(raw,9))
png+=chunk(b'IEND',b'')
open('external_calendar_busy_blocks/assets/calendar-icon.png','wb').write(png)
"
```

Replace later with a real icon if available. The Canvas icon-generation skill (`cpa:icon-generation`) can be used for a proper version.

- [ ] **Step 6: Verify the structure**

```bash
cd /Users/amandap-canvas/Code/msf-canvas
find extensions/external-calendar-busy-blocks -type f | sort
```

Expected: README.md, pyproject.toml, CANVAS_MANIFEST.json, the icon, and all the empty `__init__.py` and `tests/__init__.py` files.

- [ ] **Step 7: Commit**

```bash
git add extensions/external-calendar-busy-blocks
git commit -m "$(cat <<'EOF'
Scaffold external-calendar-busy-blocks plugin

Directory layout, pyproject.toml, manifest stub, README, placeholder
icon. No application logic yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Verify CustomModel works in deployed SDK

The spec identifies this as a load-bearing assumption. Confirm the plugin can define and use a `CustomModel`-derived class before building anything that depends on it. If `CustomModel` is not usable in the deployed SDK version (no namespace declaration in manifest schema, or runtime errors), STOP and revisit storage design with the user before continuing.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/data/_spike.py`
- Create: `extensions/external-calendar-busy-blocks/tests/data/test_spike.py`

- [ ] **Step 1: Write the spike test**

Create `tests/data/test_spike.py`:

```python
"""
Spike test: confirm CustomModel can be defined and used in this SDK version.

If this test fails to even import the module, the spec's storage approach is
not viable — STOP and consult with the SDK team before proceeding.
"""
import pytest
from django.db import models

from canvas_sdk.v1.data.base import CustomModel


def test_custom_model_class_can_be_defined() -> None:
    class SpikeModel(CustomModel):
        class Meta:
            app_label = "external_calendar_busy_blocks"
            managed = False
        name = models.CharField(max_length=64)

    instance = SpikeModel(name="hello")
    assert instance.name == "hello"


def test_custom_model_save_blocked_in_read_only_context() -> None:
    from canvas_sdk.v1.plugin_database_context import plugin_database_context
    from canvas_sdk.v1.data.base import NamespaceWriteDenied

    class SpikeModel(CustomModel):
        class Meta:
            app_label = "external_calendar_busy_blocks"
            managed = False
        name = models.CharField(max_length=64)

    with plugin_database_context(
        "external_calendar_busy_blocks",
        namespace="external_calendar_busy_blocks",
        access_level="read",
    ):
        with pytest.raises(NamespaceWriteDenied):
            SpikeModel(name="x").save()
```

- [ ] **Step 2: Run the test**

```bash
cd extensions/external-calendar-busy-blocks
uv sync
uv run pytest tests/data/test_spike.py -v
```

Expected: both tests PASS. If they fail with import errors or unexpected behavior, STOP and report to user.

- [ ] **Step 3: Delete the spike**

The spike confirmed feasibility; we don't keep it. Remove the file:

```bash
rm tests/data/test_spike.py
```

- [ ] **Step 4: Commit a no-op marker**

No code change to commit — the spike was verification only. Move on to Task 3.

---

## Task 3: Data models

Define `StaffCalendarFeed` and `ImportedEvent` as `CustomModel`s with their full field set and tests for save/uniqueness/query.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/data/models.py`
- Create: `extensions/external-calendar-busy-blocks/tests/data/test_models.py`

- [ ] **Step 1: Write failing tests for `StaffCalendarFeed`**

Create `tests/data/test_models.py`:

```python
import uuid

import pytest
from django.db import IntegrityError

from external_calendar_busy_blocks.data.models import (
    ImportedEvent,
    StaffCalendarFeed,
)


@pytest.mark.django_db
def test_staff_calendar_feed_can_be_saved() -> None:
    feed = StaffCalendarFeed(
        staff_id="staff-abc",
        ics_url="https://calendar.google.com/calendar/ical/.../basic.ics",
        is_active=True,
    )
    feed.save()
    assert feed.id is not None


@pytest.mark.django_db
def test_staff_calendar_feed_staff_id_is_unique() -> None:
    StaffCalendarFeed(
        staff_id="staff-abc",
        ics_url="https://example.com/a.ics",
    ).save()
    with pytest.raises(IntegrityError):
        StaffCalendarFeed(
            staff_id="staff-abc",
            ics_url="https://example.com/b.ics",
        ).save()


@pytest.mark.django_db
def test_imported_event_can_be_saved() -> None:
    from datetime import datetime, timezone
    canvas_event_id = str(uuid.uuid4())
    record = ImportedEvent(
        staff_id="staff-abc",
        ics_uid="event-uid-1@google.com",
        recurrence_id=None,
        canvas_event_id=canvas_event_id,
        sequence=0,
        starts_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        is_all_day=False,
        last_seen=datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc),
    )
    record.save()
    assert record.id is not None


@pytest.mark.django_db
def test_imported_event_unique_per_staff_uid_recurrence() -> None:
    from datetime import datetime, timezone
    common = dict(
        staff_id="staff-abc",
        ics_uid="event-1@google.com",
        recurrence_id="20260601T140000Z",
        canvas_event_id=str(uuid.uuid4()),
        sequence=0,
        starts_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        is_all_day=False,
        last_seen=datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc),
    )
    ImportedEvent(**common).save()
    with pytest.raises(IntegrityError):
        ImportedEvent(**{**common, "canvas_event_id": str(uuid.uuid4())}).save()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/data/test_models.py -v
```

Expected: `ImportError` (the module doesn't exist yet).

- [ ] **Step 3: Write `data/models.py`**

Create `external_calendar_busy_blocks/data/models.py`:

```python
import uuid

from django.db import models

from canvas_sdk.v1.data.base import CustomModel


class StaffCalendarFeed(CustomModel):
    """One row per provider that has connected a personal calendar feed."""

    class Meta:
        app_label = "external_calendar_busy_blocks"
        db_table = "external_calendar_busy_blocks_staff_calendar_feed"
        managed = False
        constraints = [
            models.UniqueConstraint(
                fields=["staff_id"],
                name="external_calendar_busy_blocks_feed_staff_unique",
            )
        ]

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    staff_id = models.CharField(max_length=32)
    ics_url = models.TextField()
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_etag = models.CharField(max_length=256, null=True, blank=True)
    last_modified = models.CharField(max_length=64, null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ImportedEvent(CustomModel):
    """One row per (ICS UID, recurrence-id) -> Canvas Event id mapping."""

    class Meta:
        app_label = "external_calendar_busy_blocks"
        db_table = "external_calendar_busy_blocks_imported_event"
        managed = False
        constraints = [
            models.UniqueConstraint(
                fields=["staff_id", "ics_uid", "recurrence_id"],
                name="external_calendar_busy_blocks_event_unique",
            )
        ]

    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    staff_id = models.CharField(max_length=32)
    ics_uid = models.CharField(max_length=512)
    recurrence_id = models.CharField(max_length=64, null=True, blank=True)
    canvas_event_id = models.CharField(max_length=64)
    sequence = models.IntegerField(default=0)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_all_day = models.BooleanField(default=False)
    last_seen = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/data/test_models.py -v
```

Expected: all 4 PASS. If `IntegrityError` doesn't fire as expected, check whether the test runner created the table — `managed = False` plus pytest-django typically needs `--create-db` on first run.

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/data/ tests/data/
git commit -m "$(cat <<'EOF'
Add StaffCalendarFeed and ImportedEvent CustomModels

StaffCalendarFeed: one row per connected provider, holds the ICS URL,
sync state, and last error. Unique on staff_id.

ImportedEvent: ICS-UID -> Canvas-Event-ID mapping. Unique on
(staff_id, ics_uid, recurrence_id) so recurring-event instance
overrides get their own row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

<!-- END-OF-TASK-3 -->
---

## Task 4: ICS parser — types and line unfolding

Set up shared parser types (`ParsedEvent`, `IcsParseError`) and implement RFC 5545 line unfolding (lines continued by CRLF + space/tab).

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/types.py`
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/parser.py`
- Create: `extensions/external-calendar-busy-blocks/tests/ics/test_parser.py`

- [ ] **Step 1: Write failing tests for line unfolding**

Create `tests/ics/test_parser.py`:

```python
import pytest

from external_calendar_busy_blocks.ics.parser import unfold_lines
from external_calendar_busy_blocks.ics.types import IcsParseError


def test_unfold_lines_no_folding() -> None:
    body = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    assert unfold_lines(body) == ["BEGIN:VCALENDAR", "VERSION:2.0", "END:VCALENDAR"]


def test_unfold_lines_folded_with_space() -> None:
    body = b"DESCRIPTION:This is a long\r\n description that wraps\r\n"
    assert unfold_lines(body) == ["DESCRIPTION:This is a long description that wraps"]


def test_unfold_lines_folded_with_tab() -> None:
    body = b"SUMMARY:Multi\r\n\tline\r\n"
    assert unfold_lines(body) == ["SUMMARY:Multiline"]


def test_unfold_lines_accepts_lf_only() -> None:
    body = b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"
    assert unfold_lines(body) == ["BEGIN:VCALENDAR", "END:VCALENDAR"]


def test_unfold_lines_strips_blank_lines() -> None:
    body = b"BEGIN:VCALENDAR\r\n\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    assert unfold_lines(body) == ["BEGIN:VCALENDAR", "VERSION:2.0", "END:VCALENDAR"]


def test_unfold_lines_rejects_non_utf8() -> None:
    with pytest.raises(IcsParseError):
        unfold_lines(b"\xff\xfeBEGIN:VCALENDAR\r\n")
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd extensions/external-calendar-busy-blocks
uv run pytest tests/ics/test_parser.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create the types module**

Create `external_calendar_busy_blocks/ics/types.py`:

```python
from dataclasses import dataclass
from datetime import datetime


class IcsParseError(Exception):
    """Raised when an ICS body cannot be parsed."""


@dataclass(frozen=True)
class ParsedEvent:
    """A single VEVENT occurrence ready to be written to Canvas as an Admin block."""

    uid: str
    recurrence_id: str | None
    starts_at: datetime
    ends_at: datetime
    is_all_day: bool
    sequence: int
```

- [ ] **Step 4: Implement `unfold_lines`**

Create `external_calendar_busy_blocks/ics/parser.py`:

```python
from external_calendar_busy_blocks.ics.types import IcsParseError


def unfold_lines(body: bytes) -> list[str]:
    """Decode and unfold an ICS body into logical lines."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IcsParseError(f"feed is not valid UTF-8: {exc}") from exc

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")

    folded: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        if line[0] in (" ", "\t") and folded:
            folded[-1] += line[1:]
        else:
            folded.append(line)
    return folded
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/ics/test_parser.py -v
```

Expected: all 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add external_calendar_busy_blocks/ics/ tests/ics/test_parser.py
git commit -m "Add ICS line unfolding + shared parser types"
```

---

## Task 5: ICS parser — property parsing and VEVENT extraction

Parse `KEY[;PARAM=VAL]*:VALUE` lines and group them into VEVENT blocks.

**Files:**
- Modify: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/parser.py`
- Modify: `extensions/external-calendar-busy-blocks/tests/ics/test_parser.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/ics/test_parser.py`:

```python
from external_calendar_busy_blocks.ics.parser import (
    parse_property_line,
    extract_vevents,
)


def test_parse_property_simple() -> None:
    name, params, value = parse_property_line("SUMMARY:Hello world")
    assert name == "SUMMARY"
    assert params == {}
    assert value == "Hello world"


def test_parse_property_with_one_param() -> None:
    name, params, value = parse_property_line(
        "DTSTART;TZID=America/New_York:20260601T090000"
    )
    assert name == "DTSTART"
    assert params == {"TZID": "America/New_York"}
    assert value == "20260601T090000"


def test_parse_property_with_multiple_params() -> None:
    name, params, value = parse_property_line(
        "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED:mailto:x@y.com"
    )
    assert name == "ATTENDEE"
    assert params == {"ROLE": "REQ-PARTICIPANT", "PARTSTAT": "ACCEPTED"}
    assert value == "mailto:x@y.com"


def test_parse_property_value_contains_colon() -> None:
    name, params, value = parse_property_line("ORGANIZER:mailto:foo@bar.com")
    assert name == "ORGANIZER"
    assert value == "mailto:foo@bar.com"


def test_extract_vevents_groups_lines() -> None:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        "UID:a@x",
        "SUMMARY:A",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:b@x",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    events = extract_vevents(lines)
    assert len(events) == 2
    assert events[0][0] == ("UID", {}, "a@x")
    assert events[1][0] == ("UID", {}, "b@x")


def test_extract_vevents_ignores_other_components() -> None:
    lines = [
        "BEGIN:VCALENDAR",
        "BEGIN:VTIMEZONE",
        "TZID:UTC",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        "UID:a@x",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    assert len(extract_vevents(lines)) == 1


def test_extract_vevents_raises_on_missing_vcalendar() -> None:
    with pytest.raises(IcsParseError):
        extract_vevents(["BEGIN:VEVENT", "UID:x", "END:VEVENT"])
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/ics/test_parser.py -v
```

Expected: `ImportError` on the new functions.

- [ ] **Step 3: Implement property parser + VEVENT extractor**

Append to `external_calendar_busy_blocks/ics/parser.py`:

```python
Property = tuple[str, dict[str, str], str]


def parse_property_line(line: str) -> Property:
    """Parse one content line into (name, params, value)."""
    colon_idx = -1
    in_quotes = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            colon_idx = i
            break
    if colon_idx == -1:
        raise IcsParseError(f"malformed property line (no colon): {line!r}")

    head = line[:colon_idx]
    value = line[colon_idx + 1 :]

    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        params[k.upper()] = v.strip('"')
    return name, params, value


def extract_vevents(lines: list[str]) -> list[list[Property]]:
    """Return one list of properties per VEVENT block."""
    if not lines or lines[0].upper() != "BEGIN:VCALENDAR":
        raise IcsParseError("body does not begin with BEGIN:VCALENDAR")

    events: list[list[Property]] = []
    current: list[Property] | None = None
    in_vevent = False

    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            in_vevent = True
            current = []
            continue
        if upper == "END:VEVENT":
            in_vevent = False
            if current is not None:
                events.append(current)
            current = None
            continue
        if in_vevent and current is not None:
            current.append(parse_property_line(line))

    return events
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/ics/test_parser.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/ics/parser.py tests/ics/test_parser.py
git commit -m "Parse ICS property lines and extract VEVENT blocks"
```

---

## Task 6: ICS parser — DTSTART/DTEND parsing with timezone resolution

Convert ICS date/datetime values into tz-aware UTC `datetime` objects. Handles three forms: UTC (`20260601T140000Z`), TZID-tagged (`DTSTART;TZID=America/New_York:20260601T090000`), and DATE-only all-day (`DTSTART;VALUE=DATE:20260601`). Plus VCALENDAR-level `X-WR-TIMEZONE` fallback for floating times.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/datetimes.py`
- Create: `extensions/external-calendar-busy-blocks/tests/ics/test_datetimes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/ics/test_datetimes.py`:

```python
from datetime import datetime, timezone

import pytest

from external_calendar_busy_blocks.ics.datetimes import (
    parse_ics_datetime,
    DateValue,
)
from external_calendar_busy_blocks.ics.types import IcsParseError


def test_parse_utc_zulu() -> None:
    result = parse_ics_datetime("20260601T140000Z", params={}, default_tz="UTC")
    assert result == DateValue(
        moment=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        is_all_day=False,
    )


def test_parse_tzid_converts_to_utc() -> None:
    # 09:00 in America/New_York on 2026-06-01 (EDT, UTC-4) == 13:00 UTC
    result = parse_ics_datetime(
        "20260601T090000",
        params={"TZID": "America/New_York"},
        default_tz="UTC",
    )
    assert result.moment == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
    assert result.is_all_day is False


def test_parse_floating_uses_default_tz() -> None:
    # No TZID and no Z suffix -> floating; resolve via default_tz
    result = parse_ics_datetime(
        "20260601T090000",
        params={},
        default_tz="America/New_York",
    )
    assert result.moment == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)


def test_parse_date_only_all_day() -> None:
    result = parse_ics_datetime("20260601", params={"VALUE": "DATE"}, default_tz="UTC")
    assert result.is_all_day is True
    assert result.moment == datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


def test_parse_unknown_tzid_raises() -> None:
    with pytest.raises(IcsParseError):
        parse_ics_datetime(
            "20260601T090000",
            params={"TZID": "Bogus/Made_Up"},
            default_tz="UTC",
        )


def test_parse_malformed_value_raises() -> None:
    with pytest.raises(IcsParseError):
        parse_ics_datetime("not-a-date", params={}, default_tz="UTC")
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/ics/test_datetimes.py -v
```

- [ ] **Step 3: Implement `parse_ics_datetime`**

Create `external_calendar_busy_blocks/ics/datetimes.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from external_calendar_busy_blocks.ics.types import IcsParseError


@dataclass(frozen=True)
class DateValue:
    """A parsed ICS date or datetime value, always tz-aware UTC."""

    moment: datetime
    is_all_day: bool


def parse_ics_datetime(
    value: str,
    params: dict[str, str],
    default_tz: str,
) -> DateValue:
    """Parse an ICS DTSTART/DTEND/EXDATE/etc. value to a UTC datetime.

    Args:
        value: the property value, e.g. "20260601T090000", "20260601T140000Z",
               or "20260601".
        params: the property parameters dict. Honors VALUE=DATE and TZID.
        default_tz: fallback IANA timezone for floating times (no TZID, no Z).
                    Typically the calendar's X-WR-TIMEZONE or "UTC".
    """
    if params.get("VALUE", "").upper() == "DATE":
        if len(value) != 8 or not value.isdigit():
            raise IcsParseError(f"malformed DATE value: {value!r}")
        try:
            return DateValue(
                moment=datetime(
                    int(value[0:4]),
                    int(value[4:6]),
                    int(value[6:8]),
                    tzinfo=timezone.utc,
                ),
                is_all_day=True,
            )
        except ValueError as exc:
            raise IcsParseError(f"invalid DATE: {value!r}") from exc

    is_utc = value.endswith("Z")
    body = value[:-1] if is_utc else value

    if len(body) != 15 or body[8] != "T":
        raise IcsParseError(f"malformed DATE-TIME value: {value!r}")

    try:
        naive = datetime(
            int(body[0:4]),
            int(body[4:6]),
            int(body[6:8]),
            int(body[9:11]),
            int(body[11:13]),
            int(body[13:15]),
        )
    except ValueError as exc:
        raise IcsParseError(f"invalid DATE-TIME: {value!r}") from exc

    if is_utc:
        return DateValue(moment=naive.replace(tzinfo=timezone.utc), is_all_day=False)

    tzid = params.get("TZID", default_tz)
    try:
        zone = ZoneInfo(tzid)
    except ZoneInfoNotFoundError as exc:
        raise IcsParseError(f"unknown TZID: {tzid!r}") from exc

    return DateValue(
        moment=naive.replace(tzinfo=zone).astimezone(timezone.utc),
        is_all_day=False,
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/ics/test_datetimes.py -v
```

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/ics/datetimes.py tests/ics/test_datetimes.py
git commit -m "Parse ICS DTSTART/DTEND with TZID and DATE-only support"
```

---

## Task 7: ICS parser — filter and assemble non-recurring events

Combine VEVENT extraction + datetime parsing into the top-level `parse_ics(body, now, lookahead_days) -> list[ParsedEvent]` function. Applies STATUS/TRANSP filters. RRULE expansion is left to Tasks 8–9; non-recurring VEVENTs emit one `ParsedEvent` each.

**Files:**
- Modify: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/parser.py`
- Modify: `extensions/external-calendar-busy-blocks/tests/ics/test_parser.py`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/simple_confirmed.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/transparent_event.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/tentative_event.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/cancelled_event.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/all_day_event.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/multi_timezone.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/floating_time.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/malformed.ics`

- [ ] **Step 1: Create fixtures**

Create `tests/fixtures/ics/simple_confirmed.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:simple-1@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
SUMMARY:Dentist
STATUS:CONFIRMED
TRANSP:OPAQUE
SEQUENCE:0
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/transparent_event.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:transp-1@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
STATUS:CONFIRMED
TRANSP:TRANSPARENT
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/tentative_event.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:tent-1@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
STATUS:TENTATIVE
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/cancelled_event.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:canc-1@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
STATUS:CANCELLED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/all_day_event.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:allday-1@test
DTSTAMP:20260601T120000Z
DTSTART;VALUE=DATE:20260615
DTEND;VALUE=DATE:20260616
SUMMARY:Vacation day
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/multi_timezone.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:tz-pst@test
DTSTAMP:20260601T120000Z
DTSTART;TZID=America/Los_Angeles:20260601T090000
DTEND;TZID=America/Los_Angeles:20260601T100000
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
BEGIN:VEVENT
UID:tz-utc@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T200000Z
DTEND:20260601T210000Z
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/floating_time.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
X-WR-TIMEZONE:America/New_York
BEGIN:VEVENT
UID:float-1@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T090000
DTEND:20260601T100000
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/malformed.ics`:

```
not an ics file
just random text
```

- [ ] **Step 2: Add a fixture helper to `conftest.py`**

Create `tests/conftest.py`:

```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "ics"


@pytest.fixture
def ics_fixture():
    def _load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()
    return _load
```

- [ ] **Step 3: Write failing tests for `parse_ics`**

Append to `tests/ics/test_parser.py`:

```python
from datetime import datetime, timezone

from external_calendar_busy_blocks.ics.parser import parse_ics


def test_parse_simple_confirmed(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("simple_confirmed.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert len(events) == 1
    e = events[0]
    assert e.uid == "simple-1@test"
    assert e.recurrence_id is None
    assert e.starts_at == datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    assert e.ends_at == datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    assert e.is_all_day is False
    assert e.sequence == 0


def test_parse_skips_transparent(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("transparent_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert events == []


def test_parse_skips_tentative(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("tentative_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert events == []


def test_parse_skips_cancelled(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("cancelled_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert events == []


def test_parse_all_day(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("all_day_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert len(events) == 1
    assert events[0].is_all_day is True
    assert events[0].starts_at == datetime(2026, 6, 15, tzinfo=timezone.utc)


def test_parse_multi_timezone(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("multi_timezone.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert len(events) == 2
    # PST 09:00 -> UTC 16:00 (PDT, UTC-7 in June)
    pst = next(e for e in events if e.uid == "tz-pst@test")
    assert pst.starts_at == datetime(2026, 6, 1, 16, 0, tzinfo=timezone.utc)
    utc = next(e for e in events if e.uid == "tz-utc@test")
    assert utc.starts_at == datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)


def test_parse_floating_uses_x_wr_timezone(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("floating_time.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # NY 09:00 (EDT, UTC-4) -> 13:00 UTC
    assert events[0].starts_at == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)


def test_parse_malformed_raises(ics_fixture) -> None:
    with pytest.raises(IcsParseError):
        parse_ics(
            ics_fixture("malformed.ics"),
            now=datetime(2026, 6, 1, tzinfo=timezone.utc),
            lookahead_days=90,
        )
```

- [ ] **Step 4: Run to verify failure**

```bash
uv run pytest tests/ics/test_parser.py -v
```

- [ ] **Step 5: Implement `parse_ics`**

Append to `external_calendar_busy_blocks/ics/parser.py`:

```python
from datetime import datetime, timedelta

from external_calendar_busy_blocks.ics.datetimes import parse_ics_datetime
from external_calendar_busy_blocks.ics.types import ParsedEvent


def _find_property(props: list[Property], name: str) -> Property | None:
    name = name.upper()
    for prop in props:
        if prop[0] == name:
            return prop
    return None


def _calendar_default_tz(lines: list[str]) -> str:
    for line in lines:
        if line.upper().startswith("X-WR-TIMEZONE:"):
            return line.split(":", 1)[1].strip()
    return "UTC"


def _should_skip(props: list[Property]) -> bool:
    status_prop = _find_property(props, "STATUS")
    if status_prop and status_prop[2].upper() in ("CANCELLED", "TENTATIVE"):
        return True
    transp_prop = _find_property(props, "TRANSP")
    if transp_prop and transp_prop[2].upper() == "TRANSPARENT":
        return True
    return False


def parse_ics(
    body: bytes,
    now: datetime,
    lookahead_days: int,
) -> list[ParsedEvent]:
    """Parse an ICS body to ParsedEvents within [now, now+lookahead_days].

    Non-recurring events are emitted directly. RRULE expansion is added in
    later tasks; for now, recurring events are emitted only as their base
    DTSTART instance.
    """
    lines = unfold_lines(body)
    default_tz = _calendar_default_tz(lines)
    vevents = extract_vevents(lines)

    out: list[ParsedEvent] = []
    window_end = now + timedelta(days=lookahead_days)

    for props in vevents:
        if _should_skip(props):
            continue

        uid_prop = _find_property(props, "UID")
        dtstart_prop = _find_property(props, "DTSTART")
        dtend_prop = _find_property(props, "DTEND")
        if not uid_prop or not dtstart_prop or not dtend_prop:
            continue

        starts = parse_ics_datetime(dtstart_prop[2], dtstart_prop[1], default_tz)
        ends = parse_ics_datetime(dtend_prop[2], dtend_prop[1], default_tz)

        if ends.moment <= now or starts.moment >= window_end:
            continue

        seq_prop = _find_property(props, "SEQUENCE")
        sequence = int(seq_prop[2]) if seq_prop else 0

        out.append(
            ParsedEvent(
                uid=uid_prop[2],
                recurrence_id=None,
                starts_at=starts.moment,
                ends_at=ends.moment,
                is_all_day=starts.is_all_day,
                sequence=sequence,
            )
        )

    return out
```

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/ics/test_parser.py tests/ics/test_datetimes.py -v
```

- [ ] **Step 7: Commit**

```bash
git add external_calendar_busy_blocks/ics/parser.py tests/ics/ tests/conftest.py tests/fixtures/
git commit -m "Implement parse_ics for non-recurring events with filters and tz"
```

---

## Task 8: RRULE parse + DAILY/WEEKLY expansion

Parse the `RRULE:FREQ=...;...` property into a structured form and expand DAILY and WEEKLY frequencies within a window. Supports `INTERVAL`, `BYDAY` (non-positional), `UNTIL`, `COUNT`. The expander is bounded by both the window and a 1000-instance hard cap per VEVENT.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/rrule.py`
- Create: `extensions/external-calendar-busy-blocks/tests/ics/test_rrule.py`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/weekly_recurring.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/unbounded_rrule.ics`

- [ ] **Step 1: Create fixtures**

Create `tests/fixtures/ics/weekly_recurring.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-1@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/unbounded_rrule.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:daily-forever@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T143000Z
RRULE:FREQ=DAILY
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

- [ ] **Step 2: Write failing tests**

Create `tests/ics/test_rrule.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from external_calendar_busy_blocks.ics.rrule import (
    RRule,
    parse_rrule,
    expand_rrule,
    RRuleUnsupported,
)


def test_parse_freq_weekly_byday() -> None:
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR;INTERVAL=2;COUNT=10")
    assert rule.freq == "WEEKLY"
    assert rule.interval == 2
    assert rule.byday == [(0, "MO"), (0, "WE"), (0, "FR")]
    assert rule.count == 10
    assert rule.until is None


def test_parse_until_parses_utc_datetime() -> None:
    rule = parse_rrule("FREQ=DAILY;UNTIL=20261231T235959Z")
    assert rule.until == datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def test_parse_rejects_unsupported_bysetpos() -> None:
    with pytest.raises(RRuleUnsupported):
        parse_rrule("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1")


def test_parse_rejects_unsupported_byweekno() -> None:
    with pytest.raises(RRuleUnsupported):
        parse_rrule("FREQ=YEARLY;BYWEEKNO=20")


def test_expand_daily_with_count() -> None:
    rule = parse_rrule("FREQ=DAILY;COUNT=5")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 6, 30, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    assert len(occurrences) == 5
    assert occurrences[0] == dtstart
    assert occurrences[4] == dtstart + timedelta(days=4)


def test_expand_weekly_byday_with_count() -> None:
    # 2026-06-01 is a Monday. FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4 should produce
    # MO 6/1, WE 6/3, MO 6/8, WE 6/10.
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    assert [o.date().day for o in occurrences] == [1, 3, 8, 10]


def test_expand_daily_until() -> None:
    rule = parse_rrule("FREQ=DAILY;UNTIL=20260605T000000Z")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    # UNTIL is inclusive but 6/5 00:00 < 6/5 14:00 -> last occurrence 6/4
    assert [o.date().day for o in occurrences] == [1, 2, 3, 4]


def test_expand_respects_window_end() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 6, 5, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    assert len(occurrences) == 4  # 6/1, 6/2, 6/3, 6/4


def test_expand_respects_cap() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=10))
    assert len(occurrences) == 10
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/ics/test_rrule.py -v
```

- [ ] **Step 4: Implement RRule parse + DAILY/WEEKLY expansion**

Create `external_calendar_busy_blocks/ics/rrule.py`:

```python
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from external_calendar_busy_blocks.ics.types import IcsParseError


class RRuleUnsupported(Exception):
    """Raised when an RRULE uses a feature this plugin does not support."""


SUPPORTED_FREQS = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
UNSUPPORTED_PARTS = {"BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYHOUR", "BYMINUTE", "BYSECOND"}

WEEKDAY_TO_NUM = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


@dataclass
class RRule:
    freq: str
    interval: int = 1
    count: int | None = None
    until: datetime | None = None
    byday: list[tuple[int, str]] = field(default_factory=list)  # [(0,"MO"), (1,"TU"), ...]; first int is positional (0 = any)
    bymonthday: list[int] = field(default_factory=list)
    bymonth: list[int] = field(default_factory=list)


def parse_rrule(value: str) -> RRule:
    parts = {p.split("=", 1)[0].upper(): p.split("=", 1)[1] for p in value.split(";") if "=" in p}

    for k in parts:
        if k in UNSUPPORTED_PARTS:
            raise RRuleUnsupported(f"RRULE uses unsupported part {k}")

    freq = parts.get("FREQ", "").upper()
    if freq not in SUPPORTED_FREQS:
        raise RRuleUnsupported(f"RRULE FREQ={freq!r} is not supported")

    rule = RRule(freq=freq)

    if "INTERVAL" in parts:
        try:
            rule.interval = int(parts["INTERVAL"])
        except ValueError as exc:
            raise IcsParseError(f"INTERVAL is not an integer: {parts['INTERVAL']!r}") from exc

    if "COUNT" in parts:
        try:
            rule.count = int(parts["COUNT"])
        except ValueError as exc:
            raise IcsParseError(f"COUNT is not an integer: {parts['COUNT']!r}") from exc

    if "UNTIL" in parts:
        u = parts["UNTIL"]
        # Spec allows UTC (Z suffix) or date-only. Treat naive as UTC.
        if u.endswith("Z"):
            u = u[:-1]
        if len(u) == 8 and u.isdigit():
            rule.until = datetime(int(u[0:4]), int(u[4:6]), int(u[6:8]), tzinfo=timezone.utc)
        elif len(u) == 15 and u[8] == "T":
            rule.until = datetime(
                int(u[0:4]), int(u[4:6]), int(u[6:8]),
                int(u[9:11]), int(u[11:13]), int(u[13:15]),
                tzinfo=timezone.utc,
            )
        else:
            raise IcsParseError(f"malformed UNTIL: {parts['UNTIL']!r}")

    if "BYDAY" in parts:
        for tok in parts["BYDAY"].split(","):
            tok = tok.strip().upper()
            # Positional prefix like "1MO", "-1FR", "2TU"
            i = 0
            while i < len(tok) and (tok[i].isdigit() or tok[i] in ("+", "-")):
                i += 1
            pos = int(tok[:i]) if i > 0 else 0
            day = tok[i:]
            if day not in WEEKDAY_TO_NUM:
                raise IcsParseError(f"invalid BYDAY weekday: {tok!r}")
            rule.byday.append((pos, day))

    if "BYMONTHDAY" in parts:
        try:
            rule.bymonthday = [int(x) for x in parts["BYMONTHDAY"].split(",")]
        except ValueError as exc:
            raise IcsParseError(f"invalid BYMONTHDAY: {parts['BYMONTHDAY']!r}") from exc

    if "BYMONTH" in parts:
        try:
            rule.bymonth = [int(x) for x in parts["BYMONTH"].split(",")]
        except ValueError as exc:
            raise IcsParseError(f"invalid BYMONTH: {parts['BYMONTH']!r}") from exc

    return rule


def expand_rrule(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
) -> Iterator[datetime]:
    """Yield occurrences of dtstart within [window_start, window_end).

    DAILY/WEEKLY implemented here; MONTHLY/YEARLY added in Task 9.
    Always stops at min(rule.count, cap, end-of-window, rule.until).
    """
    if rule.freq == "DAILY":
        yield from _expand_daily(rule, dtstart, window_start, window_end, cap)
    elif rule.freq == "WEEKLY":
        yield from _expand_weekly(rule, dtstart, window_start, window_end, cap)
    else:
        # MONTHLY/YEARLY handled in Task 9. Until that lands, yield nothing.
        return


def _emit_if_in_window(
    moment: datetime,
    window_start: datetime,
    window_end: datetime,
    rule: RRule,
) -> bool:
    if rule.until is not None and moment > rule.until:
        return False
    if moment >= window_end:
        return False
    return moment >= window_start


def _expand_daily(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
) -> Iterator[datetime]:
    cur = dtstart
    produced = 0
    while produced < cap:
        if rule.count is not None and produced >= rule.count:
            return
        if rule.until is not None and cur > rule.until:
            return
        if cur >= window_end:
            return
        if cur >= window_start:
            yield cur
            produced += 1
        elif rule.count is not None:
            # Still consume against the COUNT even when below window
            produced += 1
        cur = cur + timedelta(days=rule.interval)


def _expand_weekly(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
) -> Iterator[datetime]:
    # If no BYDAY, the rule recurs only on the DTSTART weekday.
    weekdays = [WEEKDAY_TO_NUM[d] for _, d in rule.byday] if rule.byday else [dtstart.weekday()]
    weekdays = sorted(set(weekdays))

    # Anchor to the Monday of the dtstart week (WKST default).
    week_start = dtstart - timedelta(days=dtstart.weekday())
    week_start = week_start.replace(
        hour=dtstart.hour,
        minute=dtstart.minute,
        second=dtstart.second,
        microsecond=0,
    )

    produced = 0
    week_no = 0
    while produced < cap:
        for wd in weekdays:
            moment = week_start + timedelta(weeks=week_no, days=wd)
            if moment < dtstart:
                continue
            if rule.count is not None and produced >= rule.count:
                return
            if rule.until is not None and moment > rule.until:
                return
            if moment >= window_end:
                return
            if moment >= window_start:
                yield moment
            produced += 1
            if produced >= cap:
                return
        week_no += rule.interval
        # Safety: stop if the next week is entirely outside the window
        next_week = week_start + timedelta(weeks=week_no)
        if next_week >= window_end:
            return
```

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/ics/test_rrule.py -v
```

- [ ] **Step 6: Commit**

```bash
git add external_calendar_busy_blocks/ics/rrule.py tests/ics/test_rrule.py tests/fixtures/ics/weekly_recurring.ics tests/fixtures/ics/unbounded_rrule.ics
git commit -m "Parse RRULE and expand DAILY/WEEKLY frequencies"
```

---

## Task 9: RRULE MONTHLY/YEARLY expansion + EXDATE + RECURRENCE-ID + parser integration

Add MONTHLY/YEARLY expansion (with positional BYDAY like `1MO`, BYMONTHDAY, BYMONTH), wire EXDATE exclusions and RECURRENCE-ID overrides into the main parser, and integrate RRULE expansion into `parse_ics`.

**Files:**
- Modify: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/rrule.py`
- Modify: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ics/parser.py`
- Modify: `extensions/external-calendar-busy-blocks/tests/ics/test_rrule.py`
- Modify: `extensions/external-calendar-busy-blocks/tests/ics/test_parser.py`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/monthly_byday.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/rrule_with_exdate.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/recurrence_id_override.ics`
- Create: `extensions/external-calendar-busy-blocks/tests/fixtures/ics/oversized_rrule.ics`

- [ ] **Step 1: Create new fixtures**

Create `tests/fixtures/ics/monthly_byday.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:monthly-1st-mon@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
RRULE:FREQ=MONTHLY;BYDAY=1MO;COUNT=3
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/rrule_with_exdate.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-exdate@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4
EXDATE:20260615T140000Z
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/recurrence_id_override.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-override@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T150000Z
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=3
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
BEGIN:VEVENT
UID:weekly-override@test
DTSTAMP:20260601T120000Z
RECURRENCE-ID:20260608T140000Z
DTSTART:20260608T160000Z
DTEND:20260608T170000Z
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

Create `tests/fixtures/ics/oversized_rrule.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:huge@test
DTSTAMP:20260601T120000Z
DTSTART:20260601T140000Z
DTEND:20260601T141000Z
RRULE:FREQ=DAILY;COUNT=5000
STATUS:CONFIRMED
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
```

- [ ] **Step 2: Append failing tests for MONTHLY**

Append to `tests/ics/test_rrule.py`:

```python
def test_expand_monthly_first_monday() -> None:
    rule = parse_rrule("FREQ=MONTHLY;BYDAY=1MO;COUNT=3")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)  # 1st Monday of June
    window_end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, dtstart, window_end, cap=1000))
    # 1st Mondays: Jun 1 2026, Jul 6 2026, Aug 3 2026
    assert [(o.year, o.month, o.day) for o in occurrences] == [
        (2026, 6, 1), (2026, 7, 6), (2026, 8, 3),
    ]


def test_expand_monthly_bymonthday() -> None:
    rule = parse_rrule("FREQ=MONTHLY;BYMONTHDAY=15;COUNT=2")
    dtstart = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
    window_end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, dtstart, window_end, cap=1000))
    assert [(o.year, o.month, o.day) for o in occurrences] == [
        (2026, 6, 15), (2026, 7, 15),
    ]


def test_expand_yearly_bymonth_bymonthday() -> None:
    rule = parse_rrule("FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25;COUNT=2")
    dtstart = datetime(2026, 12, 25, 14, 0, tzinfo=timezone.utc)
    window_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, dtstart, window_end, cap=1000))
    assert [(o.year, o.month, o.day) for o in occurrences] == [
        (2026, 12, 25), (2027, 12, 25),
    ]
```

- [ ] **Step 3: Implement MONTHLY/YEARLY in `rrule.py`**

Replace the `expand_rrule` stub branches in `external_calendar_busy_blocks/ics/rrule.py` with full implementations. Update the file by replacing the `else: return` clause:

```python
def expand_rrule(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
) -> Iterator[datetime]:
    if rule.freq == "DAILY":
        yield from _expand_daily(rule, dtstart, window_start, window_end, cap)
    elif rule.freq == "WEEKLY":
        yield from _expand_weekly(rule, dtstart, window_start, window_end, cap)
    elif rule.freq == "MONTHLY":
        yield from _expand_monthly(rule, dtstart, window_start, window_end, cap)
    elif rule.freq == "YEARLY":
        yield from _expand_yearly(rule, dtstart, window_start, window_end, cap)
```

Append the new helpers:

```python
from calendar import monthrange
from dateutil.relativedelta import relativedelta


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> int | None:
    """Return the day-of-month for the Nth (1-based) weekday in (year, month)."""
    _, last_day = monthrange(year, month)
    if n > 0:
        first_match = ((weekday - datetime(year, month, 1).weekday()) % 7) + 1
        day = first_match + 7 * (n - 1)
        return day if day <= last_day else None
    if n < 0:
        last_match = last_day - ((datetime(year, month, last_day).weekday() - weekday) % 7)
        day = last_match - 7 * (-n - 1)
        return day if day >= 1 else None
    return None


def _candidate_days_in_month(rule: RRule, year: int, month: int, dtstart: datetime) -> list[int]:
    days: set[int] = set()
    if rule.byday:
        for pos, day in rule.byday:
            weekday = WEEKDAY_TO_NUM[day]
            if pos == 0:
                _, last = monthrange(year, month)
                for d in range(1, last + 1):
                    if datetime(year, month, d).weekday() == weekday:
                        days.add(d)
            else:
                d = _nth_weekday_of_month(year, month, weekday, pos)
                if d is not None:
                    days.add(d)
    if rule.bymonthday:
        _, last = monthrange(year, month)
        for d in rule.bymonthday:
            if d > 0 and d <= last:
                days.add(d)
            elif d < 0 and (last + d + 1) >= 1:
                days.add(last + d + 1)
    if not rule.byday and not rule.bymonthday:
        days.add(dtstart.day if dtstart.day <= monthrange(year, month)[1] else monthrange(year, month)[1])
    return sorted(days)


def _expand_monthly(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
) -> Iterator[datetime]:
    cursor_year, cursor_month = dtstart.year, dtstart.month
    produced = 0
    while produced < cap:
        if rule.bymonth and cursor_month not in rule.bymonth:
            cursor_year, cursor_month = _next_month(cursor_year, cursor_month, rule.interval)
            continue
        for d in _candidate_days_in_month(rule, cursor_year, cursor_month, dtstart):
            moment = datetime(
                cursor_year, cursor_month, d,
                dtstart.hour, dtstart.minute, dtstart.second,
                tzinfo=dtstart.tzinfo,
            )
            if moment < dtstart:
                continue
            if rule.count is not None and produced >= rule.count:
                return
            if rule.until is not None and moment > rule.until:
                return
            if moment >= window_end:
                return
            if moment >= window_start:
                yield moment
            produced += 1
            if produced >= cap:
                return
        cursor_year, cursor_month = _next_month(cursor_year, cursor_month, rule.interval)
        if datetime(cursor_year, cursor_month, 1, tzinfo=dtstart.tzinfo) >= window_end:
            return


def _next_month(year: int, month: int, interval: int) -> tuple[int, int]:
    new = datetime(year, month, 1) + relativedelta(months=interval)
    return new.year, new.month


def _expand_yearly(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
) -> Iterator[datetime]:
    cursor_year = dtstart.year
    produced = 0
    while produced < cap:
        months = rule.bymonth if rule.bymonth else [dtstart.month]
        for m in sorted(set(months)):
            days = _candidate_days_in_month(rule, cursor_year, m, dtstart) or [dtstart.day]
            for d in days:
                try:
                    moment = datetime(
                        cursor_year, m, d,
                        dtstart.hour, dtstart.minute, dtstart.second,
                        tzinfo=dtstart.tzinfo,
                    )
                except ValueError:
                    continue
                if moment < dtstart:
                    continue
                if rule.count is not None and produced >= rule.count:
                    return
                if rule.until is not None and moment > rule.until:
                    return
                if moment >= window_end:
                    return
                if moment >= window_start:
                    yield moment
                produced += 1
                if produced >= cap:
                    return
        cursor_year += rule.interval
        if datetime(cursor_year, 1, 1, tzinfo=dtstart.tzinfo) >= window_end:
            return
```

- [ ] **Step 4: Verify MONTHLY/YEARLY tests pass**

```bash
uv run pytest tests/ics/test_rrule.py -v
```

- [ ] **Step 5: Append failing tests for full parse_ics with RRULE/EXDATE/RECURRENCE-ID**

Append to `tests/ics/test_parser.py`:

```python
def test_parse_weekly_recurring(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("weekly_recurring.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # MO 6/1, WE 6/3, MO 6/8, WE 6/10
    assert len(events) == 4
    days = sorted(e.starts_at.day for e in events)
    assert days == [1, 3, 8, 10]
    assert all(e.uid == "weekly-1@test" for e in events)


def test_parse_rrule_with_exdate(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("rrule_with_exdate.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # 4 Mondays: 6/1, 6/8, 6/15, 6/22. EXDATE excludes 6/15.
    days = sorted(e.starts_at.day for e in events)
    assert days == [1, 8, 22]


def test_parse_recurrence_id_override(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("recurrence_id_override.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # 3 occurrences: 6/1, 6/8 (overridden), 6/15
    by_day = {e.starts_at.day: e for e in events}
    assert set(by_day.keys()) == {1, 8, 15}
    # The 6/8 instance was overridden to start at 16:00 instead of 14:00
    assert by_day[8].starts_at == datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    assert by_day[8].recurrence_id == "20260608T140000Z"


def test_parse_oversized_rrule_capped_at_1000(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("oversized_rrule.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=3650,  # huge window to remove that constraint
    )
    assert len(events) == 1000
```

- [ ] **Step 6: Replace `parse_ics` with RRULE-aware version**

Replace the `parse_ics` body in `external_calendar_busy_blocks/ics/parser.py`:

```python
import logging

from external_calendar_busy_blocks.ics.rrule import (
    expand_rrule,
    parse_rrule,
    RRuleUnsupported,
)

log = logging.getLogger(__name__)

RRULE_CAP_PER_VEVENT = 1000


def _collect_exdates(props: list[Property], default_tz: str) -> set[datetime]:
    out: set[datetime] = set()
    for name, params, value in props:
        if name != "EXDATE":
            continue
        for piece in value.split(","):
            dv = parse_ics_datetime(piece, params, default_tz)
            out.add(dv.moment)
    return out


def parse_ics(
    body: bytes,
    now: datetime,
    lookahead_days: int,
) -> list[ParsedEvent]:
    lines = unfold_lines(body)
    default_tz = _calendar_default_tz(lines)
    vevents = extract_vevents(lines)

    window_end = now + timedelta(days=lookahead_days)

    # First pass: index overrides by (uid, recurrence_id) so we can apply them
    # while expanding the base RRULE in the second pass.
    overrides: dict[tuple[str, str], list[Property]] = {}
    base_events: list[list[Property]] = []
    for props in vevents:
        uid_prop = _find_property(props, "UID")
        rid_prop = _find_property(props, "RECURRENCE-ID")
        if uid_prop and rid_prop:
            overrides[(uid_prop[2], rid_prop[2])] = props
        else:
            base_events.append(props)

    out: list[ParsedEvent] = []
    for props in base_events:
        if _should_skip(props):
            continue
        uid_prop = _find_property(props, "UID")
        dtstart_prop = _find_property(props, "DTSTART")
        dtend_prop = _find_property(props, "DTEND")
        if not uid_prop or not dtstart_prop or not dtend_prop:
            continue

        starts = parse_ics_datetime(dtstart_prop[2], dtstart_prop[1], default_tz)
        ends = parse_ics_datetime(dtend_prop[2], dtend_prop[1], default_tz)
        duration = ends.moment - starts.moment

        seq_prop = _find_property(props, "SEQUENCE")
        sequence = int(seq_prop[2]) if seq_prop else 0

        rrule_prop = _find_property(props, "RRULE")
        if rrule_prop is None:
            if ends.moment <= now or starts.moment >= window_end:
                continue
            out.append(
                ParsedEvent(
                    uid=uid_prop[2],
                    recurrence_id=None,
                    starts_at=starts.moment,
                    ends_at=ends.moment,
                    is_all_day=starts.is_all_day,
                    sequence=sequence,
                )
            )
            continue

        try:
            rule = parse_rrule(rrule_prop[2])
        except RRuleUnsupported as exc:
            log.warning("Dropping VEVENT uid=%s: %s", uid_prop[2], exc)
            continue

        exdates = _collect_exdates(props, default_tz)

        for moment in expand_rrule(
            rule, starts.moment, now, window_end, cap=RRULE_CAP_PER_VEVENT,
        ):
            if moment in exdates:
                continue
            rid_key = _format_recurrence_id(moment, starts.is_all_day)
            override_props = overrides.get((uid_prop[2], rid_key))
            if override_props is not None:
                if _should_skip(override_props):
                    continue
                ovs_prop = _find_property(override_props, "DTSTART")
                ove_prop = _find_property(override_props, "DTEND")
                if ovs_prop is None or ove_prop is None:
                    continue
                ovs = parse_ics_datetime(ovs_prop[2], ovs_prop[1], default_tz)
                ove = parse_ics_datetime(ove_prop[2], ove_prop[1], default_tz)
                out.append(
                    ParsedEvent(
                        uid=uid_prop[2],
                        recurrence_id=rid_key,
                        starts_at=ovs.moment,
                        ends_at=ove.moment,
                        is_all_day=ovs.is_all_day,
                        sequence=sequence,
                    )
                )
                continue
            out.append(
                ParsedEvent(
                    uid=uid_prop[2],
                    recurrence_id=rid_key,
                    starts_at=moment,
                    ends_at=moment + duration,
                    is_all_day=starts.is_all_day,
                    sequence=sequence,
                )
            )
    return out


def _format_recurrence_id(moment: datetime, is_all_day: bool) -> str:
    if is_all_day:
        return moment.strftime("%Y%m%d")
    return moment.strftime("%Y%m%dT%H%M%SZ")
```

- [ ] **Step 7: Run all parser tests**

```bash
uv run pytest tests/ics/ -v
```

Expected: all PASS. If the RECURRENCE-ID test fails, check that `_format_recurrence_id` matches the fixture's `RECURRENCE-ID:20260608T140000Z` exactly.

- [ ] **Step 8: Commit**

```bash
git add external_calendar_busy_blocks/ics/ tests/ics/ tests/fixtures/ics/
git commit -m "Expand MONTHLY/YEARLY RRULEs; honor EXDATE and RECURRENCE-ID"
```

---

## Task 10: HTTP fetcher with conditional headers + URL redaction

Wrap `canvas_sdk.utils.http.Http` with a `fetch_feed(url, etag, last_modified) -> FetchResult` function. Returns a discriminated result: `NotModified`, `Ok(body, etag, last_modified)`, `Unauthorized`, `NotFound`, or `TransientError`. Includes a `redact_url(url) -> str` helper so URLs with secret tokens never appear in logs verbatim.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/http/fetcher.py`
- Create: `extensions/external-calendar-busy-blocks/tests/http/test_fetcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/http/test_fetcher.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from external_calendar_busy_blocks.http.fetcher import (
    FetchOk,
    NotModified,
    Unauthorized,
    NotFound,
    TransientError,
    fetch_feed,
    redact_url,
)


def test_redact_strips_query_token() -> None:
    url = "https://calendar.google.com/calendar/ical/me%40example.com/private-abc123def456/basic.ics"
    redacted = redact_url(url)
    assert "abc123def456" not in redacted
    assert "calendar.google.com" in redacted
    assert "***" in redacted


def test_redact_strips_query_string_secret() -> None:
    url = "https://outlook.live.com/owa/calendar/ics?path=/calendar&secret=verylongsecretstring1234567890"
    redacted = redact_url(url)
    assert "verylongsecretstring" not in redacted
    assert "outlook.live.com" in redacted


def test_fetch_200_returns_ok() -> None:
    response = MagicMock(
        status_code=200,
        content=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
        headers={"ETag": '"abc"', "Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT"},
    )
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, FetchOk)
    assert result.body.startswith(b"BEGIN:VCALENDAR")
    assert result.etag == '"abc"'
    assert result.last_modified == "Mon, 01 Jun 2026 00:00:00 GMT"


def test_fetch_304_returns_not_modified() -> None:
    response = MagicMock(status_code=304, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag='"abc"', last_modified=None)
    assert isinstance(result, NotModified)


def test_fetch_401_returns_unauthorized() -> None:
    response = MagicMock(status_code=401, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, Unauthorized)


def test_fetch_404_returns_not_found() -> None:
    response = MagicMock(status_code=404, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, NotFound)


def test_fetch_500_returns_transient() -> None:
    response = MagicMock(status_code=503, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, TransientError)


def test_fetch_exception_returns_transient() -> None:
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.side_effect = RuntimeError("network down")
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, TransientError)
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/http/test_fetcher.py -v
```

- [ ] **Step 3: Implement the fetcher**

Create `external_calendar_busy_blocks/http/fetcher.py`:

```python
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from canvas_sdk.utils.http import Http


@dataclass(frozen=True)
class FetchOk:
    body: bytes
    etag: str | None
    last_modified: str | None


class NotModified:
    pass


class Unauthorized:
    pass


class NotFound:
    pass


@dataclass(frozen=True)
class TransientError:
    reason: str


FetchResult = FetchOk | NotModified | Unauthorized | NotFound | TransientError


_SECRET_LIKE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{16,}$")


def redact_url(url: str) -> str:
    """Mask probable secret tokens in a URL so it's safe to log."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "***"
    new_path_parts = []
    for segment in parsed.path.split("/"):
        if _SECRET_LIKE_PATH_SEGMENT.fullmatch(segment):
            new_path_parts.append("***")
        else:
            new_path_parts.append(segment)
    new_path = "/".join(new_path_parts)

    new_query_pairs = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        if len(v) >= 16 or k.lower() in ("token", "key", "secret", "auth"):
            new_query_pairs.append((k, "***"))
        else:
            new_query_pairs.append((k, v))
    new_query = urlencode(new_query_pairs)

    return urlunparse(
        (parsed.scheme, parsed.netloc, new_path, parsed.params, new_query, parsed.fragment)
    )


def fetch_feed(
    url: str,
    etag: str | None,
    last_modified: str | None,
) -> FetchResult:
    """Fetch an ICS feed with conditional headers."""
    headers: dict[str, str] = {"User-Agent": "Canvas External Calendar Busy Blocks/0.1"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    try:
        response = Http().get(url, headers=headers, timeout=30)
    except Exception as exc:  # noqa: BLE001 — surface all transient errors uniformly
        return TransientError(reason=f"{type(exc).__name__}: {exc}")

    code = response.status_code
    if code == 304:
        return NotModified()
    if code == 401 or code == 403:
        return Unauthorized()
    if code == 404:
        return NotFound()
    if 200 <= code < 300:
        return FetchOk(
            body=response.content,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
    return TransientError(reason=f"HTTP {code}")
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/http/test_fetcher.py -v
```

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/http/ tests/http/
git commit -m "Add HTTP fetcher with conditional headers and URL redaction"
```

---

## Task 11: Admin Calendar lookup

A small helper that finds a staff's Admin Calendar via `Calendar.objects.for_calendar_name(provider_name=..., calendar_type=CalendarType.Administrative, location=None).last()`. Returns the calendar id (UUID/str) or None.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/calendars/admin_lookup.py`
- Create: `extensions/external-calendar-busy-blocks/tests/calendars/test_admin_lookup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/calendars/test_admin_lookup.py`:

```python
from unittest.mock import MagicMock, patch

from external_calendar_busy_blocks.calendars.admin_lookup import find_admin_calendar_id


def test_returns_id_when_calendar_exists() -> None:
    staff = MagicMock(full_name="Jane Doe")
    queryset = MagicMock()
    queryset.values_list.return_value.last.return_value = "calendar-123"
    with patch(
        "external_calendar_busy_blocks.calendars.admin_lookup.Calendar"
    ) as MockCalendar:
        MockCalendar.objects.for_calendar_name.return_value = queryset
        result = find_admin_calendar_id(staff)
    assert result == "calendar-123"
    MockCalendar.objects.for_calendar_name.assert_called_once()
    args, kwargs = MockCalendar.objects.for_calendar_name.call_args
    assert kwargs["provider_name"] == "Jane Doe"
    assert str(kwargs["calendar_type"]) == "Admin"
    assert kwargs["location"] is None


def test_returns_none_when_no_calendar() -> None:
    staff = MagicMock(full_name="Jane Doe")
    queryset = MagicMock()
    queryset.values_list.return_value.last.return_value = None
    with patch(
        "external_calendar_busy_blocks.calendars.admin_lookup.Calendar"
    ) as MockCalendar:
        MockCalendar.objects.for_calendar_name.return_value = queryset
        result = find_admin_calendar_id(staff)
    assert result is None
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/calendars/test_admin_lookup.py -v
```

- [ ] **Step 3: Implement**

Create `external_calendar_busy_blocks/calendars/admin_lookup.py`:

```python
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.v1.data.calendar import Calendar
from canvas_sdk.v1.data.staff import Staff


def find_admin_calendar_id(staff: Staff) -> str | None:
    """Return the id of the staff's Administrative calendar, or None."""
    return (
        Calendar.objects.for_calendar_name(
            provider_name=staff.full_name,
            calendar_type=CalendarType.Administrative,
            location=None,
        )
        .values_list("id", flat=True)
        .last()
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/calendars/test_admin_lookup.py -v
```

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/calendars/ tests/calendars/
git commit -m "Add Admin calendar lookup helper for staff"
```

---

## Task 12: SyncCron — the sync engine

The orchestrator. Per spec section "C. Cron sync": for each active feed, fetch → parse → diff → emit Event effects. Implements the safety guard, 304/401/4xx/5xx handling, the no-Admin-calendar branch, and the per-VEVENT 1000-instance cap (already enforced inside the parser).

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/sync/cron.py`
- Create: `extensions/external-calendar-busy-blocks/tests/sync/test_cron.py`

- [ ] **Step 1: Write failing tests (12a — new event creates)**

Create `tests/sync/test_cron.py`:

```python
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from canvas_generated.messages.effects_pb2 import Effect
from external_calendar_busy_blocks.sync.cron import SyncCron


def _new_cron(timestamp: datetime) -> SyncCron:
    """Construct SyncCron with a CRON event keyed to `timestamp`."""
    event = MagicMock()
    event.target.id = timestamp.isoformat()
    cron = SyncCron(event=event)
    cron.SCHEDULE = "*/15 * * * *"
    return cron


def _stub_feed(staff_id: str = "staff-abc", ics_url: str = "https://x.com/x.ics", **kw):
    feed = MagicMock(
        id="feed-1",
        staff_id=staff_id,
        ics_url=ics_url,
        is_active=True,
        last_etag=None,
        last_modified=None,
        **kw,
    )
    return feed


def _ok_body(uid: str, start_z: str, end_z: str) -> bytes:
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        "DTSTAMP:20260601T120000Z\r\n"
        f"DTSTART:{start_z}\r\n"
        f"DTEND:{end_z}\r\n"
        "STATUS:CONFIRMED\r\n"
        "TRANSP:OPAQUE\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode()


@pytest.fixture
def patch_sync_deps():
    """Patch SyncCron's external dependencies in a single place."""
    with (
        patch("external_calendar_busy_blocks.sync.cron.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.sync.cron.ImportedEvent") as MockImported,
        patch("external_calendar_busy_blocks.sync.cron.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.sync.cron.Staff") as MockStaff,
        patch(
            "external_calendar_busy_blocks.sync.cron.find_admin_calendar_id"
        ) as mock_find_cal,
    ):
        MockStaff.objects.get.return_value = MagicMock(full_name="Jane Doe")
        mock_find_cal.return_value = "cal-1"
        yield {
            "feed_model": MockFeed,
            "imported_model": MockImported,
            "fetch": mock_fetch,
            "staff": MockStaff,
            "find_cal": mock_find_cal,
        }


def test_new_event_emits_create_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", "20260615T140000Z", "20260615T150000Z"),
        etag='"abc"',
        last_modified="Mon, 01 Jun 2026",
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    create_effects = [e for e in effects if e.type.endswith("CALENDAR__EVENT__CREATE")]
    assert len(create_effects) == 1
    payload = json.loads(create_effects[0].payload)["data"]
    assert payload["title"] == "Busy"
    assert payload["calendar_id"] == "cal-1"
```

- [ ] **Step 2: Add tests for diff cases, 304, 401, 5xx, safety guard, etc.**

Continue appending to `tests/sync/test_cron.py`:

```python
def test_unchanged_event_emits_no_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-1@x",
        recurrence_id=None,
        canvas_event_id="canvas-1",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", "20260615T140000Z", "20260615T150000Z"),
        etag='"abc"',
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    calendar_effects = [e for e in effects if "CALENDAR__EVENT" in e.type]
    assert calendar_effects == []


def test_time_changed_emits_update_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-1@x",
        recurrence_id=None,
        canvas_event_id="canvas-1",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-1@x", "20260615T160000Z", "20260615T170000Z"),  # moved 2h later
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    update_effects = [e for e in effects if e.type.endswith("CALENDAR__EVENT__UPDATE")]
    assert len(update_effects) == 1
    payload = json.loads(update_effects[0].payload)["data"]
    assert payload["event_id"] == "canvas-1"


def test_removed_event_emits_delete_effect(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-old@x",
        recurrence_id=None,
        canvas_event_id="canvas-old",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    # ICS now has a different event
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=_ok_body("ev-new@x", "20260615T140000Z", "20260615T150000Z"),
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type.endswith("CALENDAR__EVENT__DELETE")]
    create_effects = [e for e in effects if e.type.endswith("CALENDAR__EVENT__CREATE")]
    assert len(delete_effects) == 1
    assert len(create_effects) == 1
    delete_payload = json.loads(delete_effects[0].payload)["data"]
    assert delete_payload["event_id"] == "canvas-old"


def test_safety_guard_skips_deletes_on_empty_feed(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import FetchOk

    feed = _stub_feed()
    existing = MagicMock(
        ics_uid="ev-1@x",
        recurrence_id=None,
        canvas_event_id="canvas-1",
        sequence=0,
        starts_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
    )
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = [existing]
    # Valid ICS but no VEVENTs
    patch_sync_deps["fetch"].return_value = FetchOk(
        body=b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
        etag=None,
        last_modified=None,
    )

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    delete_effects = [e for e in effects if e.type.endswith("CALENDAR__EVENT__DELETE")]
    assert delete_effects == []


def test_304_emits_no_effects(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import NotModified

    feed = _stub_feed(last_etag='"abc"')
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = NotModified()

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    calendar_effects = [e for e in effects if "CALENDAR__EVENT" in e.type]
    assert calendar_effects == []


def test_401_deactivates_feed(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import Unauthorized

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = Unauthorized()

    _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    # The cron should have set is_active to False and saved.
    assert feed.is_active is False
    assert feed.save.called


def test_5xx_keeps_feed_active(patch_sync_deps) -> None:
    from external_calendar_busy_blocks.http.fetcher import TransientError

    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["fetch"].return_value = TransientError(reason="HTTP 503")

    _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert feed.is_active is True
    assert feed.last_error == "HTTP 503"


def test_no_admin_calendar_records_error_and_skips(patch_sync_deps) -> None:
    feed = _stub_feed()
    patch_sync_deps["feed_model"].objects.filter.return_value = [feed]
    patch_sync_deps["imported_model"].objects.filter.return_value = []
    patch_sync_deps["find_cal"].return_value = None

    effects = _new_cron(datetime(2026, 6, 1, 14, 15, tzinfo=timezone.utc)).execute()
    assert effects == []
    assert feed.last_error and "no admin calendar" in feed.last_error.lower()
```

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/sync/test_cron.py -v
```

- [ ] **Step 4: Implement `SyncCron`**

Create `external_calendar_busy_blocks/sync/cron.py`:

```python
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event
from canvas_sdk.handlers.cron_task import CronTask
from canvas_sdk.v1.data.staff import Staff

from external_calendar_busy_blocks.calendars.admin_lookup import find_admin_calendar_id
from external_calendar_busy_blocks.data.models import (
    ImportedEvent,
    StaffCalendarFeed,
)
from external_calendar_busy_blocks.http.fetcher import (
    FetchOk,
    NotFound,
    NotModified,
    TransientError,
    Unauthorized,
    fetch_feed,
    redact_url,
)
from external_calendar_busy_blocks.ics.parser import parse_ics
from external_calendar_busy_blocks.ics.types import IcsParseError, ParsedEvent

log = logging.getLogger(__name__)

LOOKAHEAD_DAYS_DEFAULT = 90


class SyncCron(CronTask):
    """Polls every 15 minutes and reconciles ICS feeds to Canvas Admin events."""

    SCHEDULE = "*/15 * * * *"

    def execute(self) -> list[Effect]:
        now = datetime.now(timezone.utc)
        lookahead = self._lookahead_days()
        effects: list[Effect] = []

        for feed in StaffCalendarFeed.objects.filter(is_active=True):
            effects.extend(self._sync_feed(feed, now, lookahead))
        return effects

    def _lookahead_days(self) -> int:
        try:
            return int(self.secrets.get("LOOKAHEAD_DAYS", str(LOOKAHEAD_DAYS_DEFAULT)))
        except (TypeError, ValueError):
            log.warning("LOOKAHEAD_DAYS not parseable; using default %d", LOOKAHEAD_DAYS_DEFAULT)
            return LOOKAHEAD_DAYS_DEFAULT

    def _sync_feed(
        self,
        feed: StaffCalendarFeed,
        now: datetime,
        lookahead_days: int,
    ) -> list[Effect]:
        try:
            staff = Staff.objects.get(id=feed.staff_id)
        except Exception:
            log.warning("Skipping feed %s: staff %s not found", feed.id, feed.staff_id)
            feed.last_error = f"staff {feed.staff_id} not found"
            feed.save()
            return []

        calendar_id = find_admin_calendar_id(staff)
        if calendar_id is None:
            feed.last_error = "no Admin calendar for this provider"
            feed.save()
            return []

        result = fetch_feed(feed.ics_url, etag=feed.last_etag, last_modified=feed.last_modified)
        log.info("Synced feed %s url=%s result=%s", feed.id, redact_url(feed.ics_url), type(result).__name__)

        if isinstance(result, NotModified):
            feed.last_sync_at = now
            feed.last_error = None
            feed.save()
            return []
        if isinstance(result, Unauthorized) or isinstance(result, NotFound):
            feed.is_active = False
            feed.last_error = type(result).__name__
            feed.save()
            return []
        if isinstance(result, TransientError):
            feed.last_error = result.reason
            feed.save()
            return []

        assert isinstance(result, FetchOk)

        try:
            parsed = parse_ics(result.body, now=now, lookahead_days=lookahead_days)
        except IcsParseError as exc:
            log.warning("Parse failure feed=%s err=%s", feed.id, exc)
            feed.last_error = f"parse failure: {type(exc).__name__}"
            feed.save()
            return []

        existing = list(
            ImportedEvent.objects.filter(staff_id=feed.staff_id)
        )

        if not parsed and existing:
            feed.last_error = "feed parsed but empty; deletions skipped"
            feed.save()
            return []

        effects = self._diff_and_emit(feed, calendar_id, parsed, existing, now)

        feed.last_sync_at = now
        feed.last_etag = result.etag
        feed.last_modified = result.last_modified
        feed.last_error = None
        feed.save()
        return effects

    def _diff_and_emit(
        self,
        feed: StaffCalendarFeed,
        calendar_id: str,
        parsed: list[ParsedEvent],
        existing: list[Any],
        now: datetime,
    ) -> list[Effect]:
        by_key_existing = {
            (e.ics_uid, e.recurrence_id): e for e in existing
        }
        seen_keys: set[tuple[str, str | None]] = set()
        effects: list[Effect] = []

        for ev in parsed:
            key = (ev.uid, ev.recurrence_id)
            seen_keys.add(key)
            prior = by_key_existing.get(key)
            if prior is None:
                new_event_id = str(uuid.uuid4())
                effects.append(
                    Event(
                        event_id=new_event_id,
                        calendar_id=calendar_id,
                        title="Busy",
                        starts_at=ev.starts_at,
                        ends_at=ev.ends_at,
                    ).create()
                )
                ImportedEvent(
                    staff_id=feed.staff_id,
                    ics_uid=ev.uid,
                    recurrence_id=ev.recurrence_id,
                    canvas_event_id=new_event_id,
                    sequence=ev.sequence,
                    starts_at=ev.starts_at,
                    ends_at=ev.ends_at,
                    is_all_day=ev.is_all_day,
                    last_seen=now,
                ).save()
                continue

            if (
                prior.starts_at == ev.starts_at
                and prior.ends_at == ev.ends_at
                and prior.sequence == ev.sequence
            ):
                prior.last_seen = now
                prior.save()
                continue

            effects.append(
                Event(
                    event_id=prior.canvas_event_id,
                    title="Busy",
                    starts_at=ev.starts_at,
                    ends_at=ev.ends_at,
                ).update()
            )
            prior.starts_at = ev.starts_at
            prior.ends_at = ev.ends_at
            prior.sequence = ev.sequence
            prior.last_seen = now
            prior.save()

        for key, row in by_key_existing.items():
            if key in seen_keys:
                continue
            effects.append(Event(event_id=row.canvas_event_id).delete())
            row.delete()

        return effects
```

The plugin pre-allocates Canvas Event UUIDs on the client side (`uuid.uuid4()`) and passes them as the `event_id` field of `Event.create()`. This avoids needing a return path from the platform — `ImportedEvent.canvas_event_id` is the same id Canvas stores, so subsequent `update`/`delete` calls reference the right event.

- [ ] **Step 5: Run to verify pass**

```bash
uv run pytest tests/sync/test_cron.py -v
```

If `test_unchanged_event_emits_no_effect` fails because the parser emits something the test didn't expect, recheck that the fixture's `now` is correctly before the event's start (otherwise the parser drops it as past).

- [ ] **Step 6: Commit**

```bash
git add external_calendar_busy_blocks/sync/ tests/sync/
git commit -m "Add SyncCron with diff/emit, conditional headers, safety guard"
```

> **Note on Canvas event ids:** the plugin generates a UUID client-side and passes it as the `event_id` field of `Event.create()`. The SDK's `Event` effect accepts `event_id` on create. This guarantees `ImportedEvent.canvas_event_id` matches what Canvas stores, so subsequent `update`/`delete` effects reference the right event. **Implementation kickoff item:** confirm Canvas actually uses the supplied `event_id` rather than overriding it; if not, switch to a return-id pattern.

---

## Task 13: SimpleAPI — POST /feeds and DELETE /feeds

The form handler endpoints. Reads logged-in staff from the session, validates the URL (HTTPS only, must probe as ICS), and upserts `StaffCalendarFeed`. Disconnect emits `Event.delete` effects for every `ImportedEvent` row and deletes them.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/routes/feeds.py`
- Create: `extensions/external-calendar-busy-blocks/tests/routes/test_feeds.py`

- [ ] **Step 1: Write failing tests**

Create `tests/routes/test_feeds.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from external_calendar_busy_blocks.routes.feeds import FeedsAPI


def _api_with_request(method: str, body: bytes, logged_in_staff: str | None) -> FeedsAPI:
    headers = {}
    if logged_in_staff:
        headers["canvas-logged-in-user-id"] = logged_in_staff
    request = MagicMock(
        method=method,
        body=body,
        headers=headers,
        path_params={},
    )
    api = FeedsAPI.__new__(FeedsAPI)
    api.request = request
    api.context = {}
    api.secrets = {}
    return api


def test_post_rejects_when_unauthenticated() -> None:
    api = _api_with_request("POST", b'{"ics_url":"https://x.com/x.ics"}', logged_in_staff=None)
    responses = api.create_feed()
    assert responses[0].status_code == 401


def test_post_rejects_non_https() -> None:
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed"):
        api = _api_with_request(
            "POST", b'{"ics_url":"http://insecure.example.com/cal.ics"}',
            logged_in_staff="staff-abc",
        )
        responses = api.create_feed()
    assert responses[0].status_code == 400


def test_post_rejects_javascript_scheme() -> None:
    api = _api_with_request(
        "POST", b'{"ics_url":"javascript:alert(1)"}',
        logged_in_staff="staff-abc",
    )
    responses = api.create_feed()
    assert responses[0].status_code == 400


def test_post_rejects_non_ics_body() -> None:
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed"),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(body=b"<html>not ics</html>", etag=None, last_modified=None)
        api = _api_with_request(
            "POST", b'{"ics_url":"https://x.com/x.ics"}',
            logged_in_staff="staff-abc",
        )
        responses = api.create_feed()
    assert responses[0].status_code == 400


def test_post_creates_feed_when_valid() -> None:
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(
            body=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            etag=None, last_modified=None,
        )
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST", b'{"ics_url":"https://x.com/x.ics"}',
            logged_in_staff="staff-abc",
        )
        responses = api.create_feed()

    assert responses[0].status_code == 200
    MockFeed.assert_called_once()
    kwargs = MockFeed.call_args.kwargs
    assert kwargs["staff_id"] == "staff-abc"
    assert kwargs["ics_url"] == "https://x.com/x.ics"


def test_post_ignores_staff_id_in_body() -> None:
    """Even if the body claims a different staff_id, the session is authoritative."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://x.com/x.ics","staff_id":"impersonated"}',
            logged_in_staff="staff-real",
        )
        api.create_feed()
    assert MockFeed.call_args.kwargs["staff_id"] == "staff-real"


def test_delete_idempotent_when_no_feed() -> None:
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request("POST", b"{}", logged_in_staff="staff-abc")
        responses = api.delete_feed()
    assert responses[0].status_code == 200


def test_delete_removes_feed_and_emits_delete_effects() -> None:
    feed = MagicMock(staff_id="staff-abc")
    imported = [
        MagicMock(canvas_event_id="evt-1"),
        MagicMock(canvas_event_id="evt-2"),
    ]
    with (
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.ImportedEvent") as MockImported,
    ):
        MockFeed.objects.filter.return_value.first.return_value = feed
        MockImported.objects.filter.return_value = imported
        api = _api_with_request("POST", b"{}", logged_in_staff="staff-abc")
        responses = api.delete_feed()
    effects_emitted = [r for r in responses if hasattr(r, "type") and "DELETE" in str(r.type)]
    assert len(effects_emitted) == 2
    feed.delete.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/routes/test_feeds.py -v
```

- [ ] **Step 3: Implement `FeedsAPI`**

Create `external_calendar_busy_blocks/routes/feeds.py`:

```python
import json
from urllib.parse import urlparse

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from external_calendar_busy_blocks.data.models import (
    ImportedEvent,
    StaffCalendarFeed,
)
from external_calendar_busy_blocks.http.fetcher import FetchOk, fetch_feed


class FeedsAPI(StaffSessionAuthMixin, SimpleAPI):
    """POST /feeds to connect, POST /feeds/delete to disconnect."""

    @api.post("/feeds")
    def create_feed(self) -> list[Response | Effect]:
        staff_id = self._logged_in_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Not authenticated"}, status_code=401)]

        try:
            body = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=400)]

        url = (body.get("ics_url") or "").strip()
        if not self._is_https_url(url):
            return [JSONResponse({"error": "ICS URL must be HTTPS"}, status_code=400)]

        # Probe: must respond with something that starts with BEGIN:VCALENDAR
        result = fetch_feed(url, etag=None, last_modified=None)
        if not isinstance(result, FetchOk) or not result.body.lstrip().startswith(b"BEGIN:VCALENDAR"):
            return [JSONResponse(
                {"error": "URL does not return a valid iCalendar feed"},
                status_code=400,
            )]

        existing = StaffCalendarFeed.objects.filter(staff_id=staff_id).first()
        if existing:
            existing.ics_url = url
            existing.is_active = True
            existing.last_error = None
            existing.last_etag = None
            existing.last_modified = None
            existing.save()
        else:
            StaffCalendarFeed(staff_id=staff_id, ics_url=url, is_active=True).save()

        return [JSONResponse({"status": "connected"}, status_code=200)]

    @api.post("/feeds/delete")
    def delete_feed(self) -> list[Response | Effect]:
        staff_id = self._logged_in_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Not authenticated"}, status_code=401)]

        feed = StaffCalendarFeed.objects.filter(staff_id=staff_id).first()
        if feed is None:
            return [JSONResponse({"status": "no feed"}, status_code=200)]

        effects: list[Effect] = []
        for row in ImportedEvent.objects.filter(staff_id=staff_id):
            effects.append(Event(event_id=row.canvas_event_id).delete())
            row.delete()

        feed.delete()
        return [*effects, JSONResponse({"status": "disconnected"}, status_code=200)]

    def _logged_in_staff_id(self) -> str | None:
        return self.request.headers.get("canvas-logged-in-user-id")

    @staticmethod
    def _is_https_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        return parsed.scheme == "https" and bool(parsed.netloc)
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/routes/test_feeds.py -v
```

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/routes/ tests/routes/
git commit -m "Add FeedsAPI POST/DELETE handlers with session auth and probe"
```

---

## Task 14: Application UI

The global-scope Application that launches the config page in a modal. `on_open()` returns a `LaunchModalEffect` pointing at a SimpleAPI route that renders the HTML.

**Files:**
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/apps/busy_blocks_app.py`
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/ui/pages.py`
- Create: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/templates/config.html`
- Create: `extensions/external-calendar-busy-blocks/tests/apps/test_busy_blocks_app.py`

- [ ] **Step 1: Write failing tests**

Create `tests/apps/test_busy_blocks_app.py`:

```python
from unittest.mock import MagicMock, patch

from external_calendar_busy_blocks.apps.busy_blocks_app import BusyBlocksApplication


def test_on_open_launches_modal_to_config_page() -> None:
    event = MagicMock()
    event.target.id = "external_calendar_busy_blocks.apps.busy_blocks_app:BusyBlocksApplication"
    app = BusyBlocksApplication(event=event)
    effect = app.on_open()
    assert "external_calendar_busy_blocks" in effect.payload.decode() or "external_calendar_busy_blocks" in str(effect)


def test_config_page_renders_disconnected_state() -> None:
    from external_calendar_busy_blocks.ui.pages import ConfigPage

    request = MagicMock(headers={"canvas-logged-in-user-id": "staff-abc"})
    page = ConfigPage.__new__(ConfigPage)
    page.request = request
    page.context = {}
    page.secrets = {}

    with patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = None
        responses = page.render()
    html = responses[0].content.decode()
    assert "Paste" in html or "iCal" in html.lower()


def test_config_page_renders_connected_state() -> None:
    from datetime import datetime, timezone
    from external_calendar_busy_blocks.ui.pages import ConfigPage

    request = MagicMock(headers={"canvas-logged-in-user-id": "staff-abc"})
    page = ConfigPage.__new__(ConfigPage)
    page.request = request
    page.context = {}
    page.secrets = {}

    feed = MagicMock(
        last_sync_at=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        last_error=None,
        is_active=True,
    )
    with patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = feed
        responses = page.render()
    html = responses[0].content.decode()
    assert "Disconnect" in html
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/apps/test_busy_blocks_app.py -v
```

- [ ] **Step 3: Implement the Application**

Create `external_calendar_busy_blocks/apps/busy_blocks_app.py`:

```python
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class BusyBlocksApplication(Application):
    """Global-scope app that launches the config modal."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/external_calendar_busy_blocks/pages/config",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
```

- [ ] **Step 4: Implement the config page**

Create `external_calendar_busy_blocks/ui/pages.py`:

```python
from http import HTTPStatus

from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from external_calendar_busy_blocks.data.models import StaffCalendarFeed


class ConfigPage(StaffSessionAuthMixin, SimpleAPI):
    """GET /pages/config — renders the connect/disconnect HTML page."""

    @api.get("/pages/config")
    def render(self) -> list[Response]:
        staff_id = self.request.headers.get("canvas-logged-in-user-id")
        feed = StaffCalendarFeed.objects.filter(staff_id=staff_id).first() if staff_id else None
        html = render_to_string(
            "templates/config.html",
            {
                "feed": feed,
                "connected": feed is not None and feed.is_active,
                "post_url": "/plugin-io/api/external_calendar_busy_blocks/feeds",
                "delete_url": "/plugin-io/api/external_calendar_busy_blocks/feeds/delete",
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]
```

- [ ] **Step 5: Create the config template**

Create `external_calendar_busy_blocks/templates/config.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Calendar Busy Blocks</title>
  <style>
    body { font-family: system-ui, sans-serif; padding: 24px; max-width: 600px; }
    label { display: block; margin: 12px 0 4px; font-weight: 600; }
    input[type="url"] { width: 100%; padding: 8px; font-size: 14px; box-sizing: border-box; }
    button { padding: 8px 16px; font-size: 14px; cursor: pointer; margin-top: 12px; }
    .error { color: #b00; }
    .status { color: #060; }
  </style>
</head>
<body>
  <h1>Calendar Busy Blocks</h1>
  {% if connected %}
    <p class="status">Connected.</p>
    {% if feed.last_sync_at %}<p>Last sync: {{ feed.last_sync_at }}</p>{% endif %}
    {% if feed.last_error %}<p class="error">Last error: {{ feed.last_error }}</p>{% endif %}
    <form method="post" action="{{ delete_url }}">
      <button type="submit">Disconnect</button>
    </form>
  {% else %}
    <p>Paste your personal calendar's secret iCal URL below. Canvas will fetch your busy times every 15 minutes and add them to your schedule as "Busy" blocks.</p>
    <form method="post" action="{{ post_url }}">
      <label for="ics_url">Secret iCal URL</label>
      <input type="url" id="ics_url" name="ics_url" placeholder="https://calendar.google.com/calendar/ical/.../basic.ics" required />
      <button type="submit">Connect</button>
    </form>
  {% endif %}
</body>
</html>
```

- [ ] **Step 6: Run to verify pass**

```bash
uv run pytest tests/apps/test_busy_blocks_app.py -v
```

If the template renderer fails to find the template, confirm the path is resolved relative to the package root. The existing `ical` plugin uses `templates/index.html` as a relative path — match that pattern.

- [ ] **Step 7: Commit**

```bash
git add external_calendar_busy_blocks/apps/ external_calendar_busy_blocks/ui/ external_calendar_busy_blocks/templates/ tests/apps/
git commit -m "Add Application + config page UI"
```

---

## Task 15: Wire everything into CANVAS_MANIFEST.json

Register the Application, both SimpleAPI routes, and the CronTask. Run the whole test suite. Final commit.

**Files:**
- Modify: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/CANVAS_MANIFEST.json`

- [ ] **Step 1: Update the manifest**

Replace the contents of `external_calendar_busy_blocks/CANVAS_MANIFEST.json`:

```json
{
    "sdk_version": "0.1.4",
    "plugin_version": "0.1.0",
    "name": "external_calendar_busy_blocks",
    "description": "Subscribe Canvas to a provider's personal calendar via ICS and mirror busy times as Admin events.",
    "components": {
        "protocols": [
            {
                "class": "external_calendar_busy_blocks.routes.feeds:FeedsAPI",
                "description": "POST /feeds to connect; POST /feeds/delete to disconnect.",
                "data_access": {"event": "", "read": [], "write": []}
            },
            {
                "class": "external_calendar_busy_blocks.ui.pages:ConfigPage",
                "description": "GET /pages/config — renders the connect/disconnect HTML page.",
                "data_access": {"event": "", "read": [], "write": []}
            },
            {
                "class": "external_calendar_busy_blocks.sync.cron:SyncCron",
                "description": "Every 15 minutes: fetch each active feed, parse, diff, and emit Event effects.",
                "data_access": {"event": "", "read": [], "write": []}
            }
        ],
        "applications": [
            {
                "class": "external_calendar_busy_blocks.apps.busy_blocks_app:BusyBlocksApplication",
                "name": "Calendar Busy Blocks",
                "description": "Connect a personal calendar so its busy times block your Canvas schedule.",
                "icon": "assets/calendar-icon.png",
                "scope": "global"
            }
        ],
        "commands": [],
        "content": [],
        "effects": [],
        "views": []
    },
    "secrets": ["LOOKAHEAD_DAYS"],
    "tags": {},
    "references": [],
    "license": "MIT",
    "diagram": false,
    "readme": "../README.md"
}
```

- [ ] **Step 2: Validate the manifest**

The Canvas CLI validates manifests against the schema:

```bash
cd extensions/external-calendar-busy-blocks
uv run canvas validate-manifest external_calendar_busy_blocks/
```

If `validate-manifest` is not a recognized subcommand, this MSF SDK version uses a different command name — try `canvas plugins lint` or skip and rely on manual JSON parse validation:

```bash
python -c "import json; json.load(open('external_calendar_busy_blocks/CANVAS_MANIFEST.json')); print('OK')"
```

- [ ] **Step 3: Run the full test suite with coverage**

```bash
uv run pytest tests/ -v --cov=external_calendar_busy_blocks --cov-report=term-missing
```

Coverage target per the spec:

- 100% on `ics/parser.py`, `ics/rrule.py`, `ics/datetimes.py`, `sync/cron.py`
- ~80% on `routes/feeds.py`
- `apps/busy_blocks_app.py`, `ui/pages.py` only need smoke coverage

If any module falls below target, add tests that cover the missing branches before merging.

- [ ] **Step 4: Manual smoke test plan (run before opening PR)**

Document and execute the manual checks:

1. Install the plugin against a development Canvas instance.
2. Set the `LOOKAHEAD_DAYS` secret (or leave default).
3. Log in as a provider; open the "Calendar Busy Blocks" app from the global menu.
4. Paste a known-good Google Calendar secret iCal URL; click Connect.
5. Confirm the page now shows "Connected" with no last error.
6. Manually trigger the cron (via `canvas trigger-cron` if available, or wait up to 15 min).
7. Open the provider's Canvas schedule — confirm Admin "Busy" events appear matching the personal calendar.
8. Modify a personal calendar event, wait for next sync, confirm Canvas event updates.
9. Delete a personal calendar event, wait, confirm Canvas event is removed.
10. Click Disconnect — confirm all Busy blocks are removed.

- [ ] **Step 5: Commit and push**

```bash
git add external_calendar_busy_blocks/CANVAS_MANIFEST.json
git commit -m "$(cat <<'EOF'
Wire FeedsAPI, ConfigPage, SyncCron, and BusyBlocksApplication into manifest

Plugin is now feature-complete per the design spec:
- Self-service config UI (global-scope Application + modal)
- POST /feeds and /feeds/delete with session-authoritative staff_id
- 15-minute CronTask that fetches with conditional headers, parses ICS,
  expands the supported RRULE subset, and reconciles Canvas Admin events
- Hand-rolled ICS parser (sandbox does not allow icalendar library)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push
```

---

## Self-review against spec

The following spec sections should each map to at least one task. If any are missing, add a task before execution begins.

| Spec section | Covered by |
|---|---|
| Architecture: 4 components (Application, SimpleAPI, CustomModels, CronTask) | Tasks 3, 12, 13, 14, 15 |
| `StaffCalendarFeed` + `ImportedEvent` schema | Task 3 |
| ICS parsing (filters, all-day, timezones) | Tasks 4–7 |
| RRULE subset + EXDATE + RECURRENCE-ID + 1000-cap | Tasks 8–9 |
| HTTP conditional fetch + URL redaction | Task 10 |
| Admin calendar lookup | Task 11 |
| Sync diff, safety guard, 304/401/4xx/5xx handling, no-Admin-calendar branch | Task 12 |
| Session-authoritative POST/DELETE feeds, idempotent disconnect | Task 13 |
| Application + config HTML (connected/disconnected states) | Task 14 |
| Manifest registration + full coverage + manual smoke | Task 15 |
| Sandbox-imposed parser scope | Documented in plan header; implemented across Tasks 4–9 |

## Known kickoff items to verify (carried over from spec)

1. **Canvas `Event.create()` id return path** (called out in Task 12). The current implementation stores `""` for the new `ImportedEvent.canvas_event_id`. Confirm whether the SDK assigns ids returnable to the plugin, or whether we must pre-allocate UUIDs on the plugin side and pass them in the create payload.
2. **`CustomModel` migration mechanism** (called out in spec). Task 2's spike confirms the class works at the Python level; what creates the actual database tables? If migrations are required, Task 3 needs an additional step.
3. **Manifest namespace declaration** for read/write access to the plugin's CustomModel tables — Task 2 may surface that the manifest needs a field we haven't added.
4. **Manifest validator command name** in Task 15 step 2 — try variants if the one shown doesn't exist.


