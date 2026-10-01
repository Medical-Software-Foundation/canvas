# Admin-Managed Calendar Feeds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an authorized admin connect, view, and disconnect a personal calendar feed on behalf of any active provider, without changing the existing provider self-service flow.

**Architecture:** Add an `is_admin` authorization helper (backed by a new `ADMIN_STAFF_IDS` secret, fail closed). Extend `FeedsAPI` so its connect/disconnect routes accept an optional `staff_id` that is honored only for admins, and add an admin-only `GET /feeds/status` route. `ConfigPage` renders an extra admin section (a server-rendered active-staff dropdown) only for admins. No data-model or cron changes — an admin-created `StaffCalendarFeed` is identical to a self-created one.

**Tech Stack:** Python 3.12, Canvas Plugin SDK (`canvas_sdk`), Django ORM custom-data models, pytest, `unittest.mock`.

## Global Constraints

- Plugin package root: `extensions/external-calendar-busy-blocks/external_calendar_busy_blocks/`.
- Tests run from `extensions/external-calendar-busy-blocks/` via `.venv/bin/pytest`.
- Fail closed on missing/empty secrets — a missing `ADMIN_STAFF_IDS` grants access to nobody (never everybody).
- Staff ids are canonicalized to dashless form; `Staff.id` is stored as `uuid4().hex` (32 lowercase hex chars).
- A non-admin's body/query `staff_id` must be ignored for writes (act on self) — never a 403 that reveals behavior, never privilege escalation.
- Never echo a stored ICS URL back to any client (it is a bearer token).
- No broad `try/except Exception` around handler logic; keep existing specific error handling.
- Clinical-data `entered_in_error` filtering is N/A here (no clinical models touched).

---

### Task 1: `is_admin` authorization helper

**Files:**
- Modify: `external_calendar_busy_blocks/auth.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `is_admin(staff_id: str | None, secrets: Mapping[str, str] | None) -> bool` in `external_calendar_busy_blocks.auth`. Returns `True` only when `staff_id` (canonicalized dashless, lowercased) is a member of the comma-separated `ADMIN_STAFF_IDS` secret; `False` when `staff_id` is falsy or the secret is unset/empty/whitespace.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:

```python
from external_calendar_busy_blocks.auth import is_admin


def test_is_admin_false_when_secret_unset() -> None:
    assert is_admin("00000000000000000000000000000001", {}) is False


def test_is_admin_false_when_secret_blank() -> None:
    assert is_admin("00000000000000000000000000000001", {"ADMIN_STAFF_IDS": "   "}) is False


def test_is_admin_false_when_staff_id_none() -> None:
    assert is_admin(None, {"ADMIN_STAFF_IDS": "00000000000000000000000000000001"}) is False


def test_is_admin_true_for_member_dashless() -> None:
    secrets = {"ADMIN_STAFF_IDS": "00000000000000000000000000000001,0000000000000000000000000000ffff"}
    assert is_admin("0000000000000000000000000000ffff", secrets) is True


def test_is_admin_matches_regardless_of_dashes_and_case() -> None:
    # Secret entered with dashes and uppercase; caller id is dashless lowercase.
    secrets = {"ADMIN_STAFF_IDS": "00000000-0000-0000-0000-0000000000AB"}
    assert is_admin("000000000000000000000000000000ab", secrets) is True


def test_is_admin_false_for_non_member() -> None:
    secrets = {"ADMIN_STAFF_IDS": "00000000000000000000000000000001"}
    assert is_admin("00000000000000000000000000000002", secrets) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth.py -v -k is_admin`
Expected: FAIL with `ImportError: cannot import name 'is_admin'`.

- [ ] **Step 3: Implement the helper**

Add to the end of `external_calendar_busy_blocks/auth.py`:

```python
def _canonical(raw: str) -> str:
    """Dashless, lowercased form for case/format-insensitive UUID comparison."""
    return raw.replace("-", "").strip().lower()


def is_admin(staff_id, secrets) -> bool:
    """Return True only if ``staff_id`` is listed in the ADMIN_STAFF_IDS secret.

    Fails closed: an unset, empty, or whitespace-only secret means no one is an
    admin. Both the caller id and each configured id are canonicalized to the
    dashless, lowercased form so dashed/uppercase entries still match Staff.id
    (uuid4().hex).
    """
    if not staff_id:
        return False
    raw = (secrets or {}).get("ADMIN_STAFF_IDS") or ""
    admins = {_canonical(part) for part in raw.split(",") if part.strip()}
    if not admins:
        return False
    return _canonical(staff_id) in admins
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: PASS (all `is_admin` tests plus the existing `canonical_staff_id` tests).

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/auth.py tests/test_auth.py
git commit -m "feat(external-calendar-busy-blocks): add is_admin authorization helper"
```

---

### Task 2: Admin-targeted connect/disconnect in `FeedsAPI`

**Files:**
- Modify: `external_calendar_busy_blocks/routes/feeds.py`
- Test: `tests/routes/test_feeds.py`

**Interfaces:**
- Consumes: `is_admin` from Task 1.
- Produces: `FeedsAPI._resolve_target_staff_id(logged_in: str, body: dict) -> str` — returns the canonicalized body `staff_id` when it is present AND the caller is an admin, else `logged_in`. `create_feed`/`delete_feed` operate on this target. `create_feed` now returns `400` when the target's Admin calendar cannot be resolved (empty id from `get_admin_calendar_id`).

- [ ] **Step 1: Update the test helper and rewrite the impersonation test**

In `tests/routes/test_feeds.py`, replace `_api_with_request` so callers can pass secrets and so `query_params` exists:

```python
def _api_with_request(
    method: str,
    body: bytes,
    logged_in_staff: str | None,
    secrets: dict | None = None,
    query_params: dict | None = None,
) -> FeedsAPI:
    headers = {}
    if logged_in_staff:
        headers["canvas-logged-in-user-id"] = logged_in_staff
    request = MagicMock(
        method=method,
        body=body,
        headers=headers,
        path_params={},
        query_params=query_params or {},
    )
    api = FeedsAPI.__new__(FeedsAPI)
    api.request = request
    api.secrets = secrets or {}
    return api
```

Then replace the existing `test_post_ignores_staff_id_in_body` with the non-admin + admin pair:

```python
def test_post_non_admin_ignores_staff_id_in_body() -> None:
    """A non-admin's body staff_id is ignored; the session stays authoritative."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-1", [])),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://outlook.office365.com/owa/calendar/x/calendar.ics",'
            b'"staff_id":"00000000000000000000000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000002",
            secrets={},  # not an admin
        )
        api.create_feed()
    assert MockFeed.call_args.kwargs["staff_id"] == "00000000000000000000000000000002"


def test_post_admin_targets_other_staff() -> None:
    """An admin's body staff_id is honored: the feed is keyed to the target."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-1", [])) as mock_get_cal,
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics",'
            b'"staff_id":"00000000-0000-0000-0000-000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        )
        api.create_feed()
    assert MockFeed.call_args.kwargs["staff_id"] == "00000000000000000000000000000099"
    assert mock_get_cal.call_args.args[0] == "00000000000000000000000000000099"


def test_post_admin_returns_400_when_calendar_unresolvable() -> None:
    """If the target staff can't be resolved, no feed is written and we 400."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("", [])),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics",'
            b'"staff_id":"00000000000000000000000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        )
        responses = api.create_feed()
    assert responses[0].status_code == 400
    MockFeed.assert_not_called()


def test_delete_admin_targets_other_staff() -> None:
    feed = MagicMock(staff_id="00000000000000000000000000000099")
    with (
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.ImportedEvent") as MockImported,
    ):
        MockFeed.objects.filter.return_value.first.return_value = feed
        MockImported.objects.filter.return_value = []
        api = _api_with_request(
            "POST",
            b'{"staff_id":"00000000-0000-0000-0000-000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        )
        responses = api.delete_feed()
    # Feed and imported-event lookups were scoped to the target staff id.
    assert MockFeed.objects.filter.call_args.kwargs["staff_id"] == "00000000000000000000000000000099"
    assert responses[-1].status_code == 200
    feed.delete.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/routes/test_feeds.py -v -k "admin or non_admin"`
Expected: FAIL — `test_post_admin_targets_other_staff` asserts the target id but current code keys the feed to the session id; `_resolve_target_staff_id` / 400-guard do not yet exist.

- [ ] **Step 3: Implement target resolution and the calendar guard**

In `external_calendar_busy_blocks/routes/feeds.py`, add the `is_admin` import:

```python
from external_calendar_busy_blocks.auth import canonical_staff_id, is_admin
```

Add a helper method to `FeedsAPI`:

```python
    def _resolve_target_staff_id(self, logged_in: str, body: dict) -> str:
        """Return the staff id to act on.

        An admin may target another provider by sending ``staff_id`` in the
        body; the id is canonicalized to the dashless form used for Staff.id.
        For everyone else (and when no staff_id is sent), the logged-in staff is
        authoritative — a non-admin's body staff_id is ignored, so it can never
        escalate privilege.
        """
        requested = (body.get("staff_id") or "").strip()
        if requested and is_admin(logged_in, self.secrets):
            return requested.replace("-", "")
        return logged_in
```

Rewrite `create_feed` so the target is resolved, the calendar is provisioned
before the feed row is written, and an unresolvable calendar returns `400`
before any write. Replace the body of `create_feed` from the `existing = ...`
block onward with:

```python
        target_id = self._resolve_target_staff_id(staff_id, body)

        # Provision the target's Admin calendar first. An empty id means the
        # staff (or their name) could not be resolved — fail before writing a
        # feed row that would have no calendar to land busy blocks on.
        cal_id, cal_effects = get_admin_calendar_id(target_id)
        if not cal_id:
            return [JSONResponse(
                {"error": "Could not resolve the provider's calendar"},
                status_code=400,
            )]

        existing = StaffCalendarFeed.objects.filter(staff_id=target_id).first()
        if existing:
            existing.ics_url = url
            existing.is_active = True
            existing.last_error = None
            existing.last_etag = None
            existing.last_modified = None
            existing.save()
        else:
            StaffCalendarFeed(staff_id=target_id, ics_url=url, is_active=True).save()

        return [*cal_effects, JSONResponse({"status": "connected"}, status_code=200)]
```

Rewrite `delete_feed` to resolve the target. Replace its body (after the auth
check) with:

```python
        try:
            body = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=400)]

        target_id = self._resolve_target_staff_id(staff_id, body)

        feed = StaffCalendarFeed.objects.filter(staff_id=target_id).first()
        if feed is None:
            return [JSONResponse({"status": "no feed"}, status_code=200)]

        effects: list[Effect] = []
        for row in ImportedEvent.objects.filter(staff_id=target_id):
            effects.append(Event(event_id=row.canvas_event_id).delete())
            row.delete()

        feed.delete()
        return [*effects, JSONResponse({"status": "disconnected"}, status_code=200)]
```

- [ ] **Step 4: Run the full feeds test file**

Run: `.venv/bin/pytest tests/routes/test_feeds.py -v`
Expected: PASS — new admin/non-admin tests pass and all pre-existing tests
(SSRF allowlist, whitespace, provisioning, self-service) still pass.

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/routes/feeds.py tests/routes/test_feeds.py
git commit -m "feat(external-calendar-busy-blocks): admins can connect/disconnect feeds for any provider"
```

---

### Task 3: Admin-only `GET /feeds/status` route

**Files:**
- Modify: `external_calendar_busy_blocks/routes/feeds.py`
- Test: `tests/routes/test_feeds.py`

**Interfaces:**
- Consumes: `is_admin` (Task 1), `StaffCalendarFeed`, `_logged_in_staff_id`.
- Produces: `FeedsAPI.feed_status()` handling `GET /feeds/status?staff_id=<id>`. Admin-only. Returns JSON `{"connected": bool, "last_sync_at": str | None, "last_error": str | None}`. Never returns the ICS URL. `401` unauthenticated, `403` non-admin, `400` missing `staff_id`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/routes/test_feeds.py`:

```python
def test_status_requires_admin() -> None:
    api = _api_with_request(
        "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000002",
        secrets={},  # not an admin
        query_params={"staff_id": "00000000000000000000000000000099"},
    )
    responses = api.feed_status()
    assert responses[0].status_code == 403


def test_status_requires_staff_id() -> None:
    api = _api_with_request(
        "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000001",
        secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        query_params={},
    )
    responses = api.feed_status()
    assert responses[0].status_code == 400


def test_status_reports_connected_feed_without_url() -> None:
    feed = MagicMock(is_active=True, last_sync_at="2026-07-11T00:00:00Z", last_error=None)
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = feed
        api = _api_with_request(
            "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
            query_params={"staff_id": "00000000-0000-0000-0000-000000000099"},
        )
        responses = api.feed_status()
    assert responses[0].status_code == 200
    body = json.loads(responses[0].content)
    assert body["connected"] is True
    assert "ics_url" not in body
    # Lookup was scoped to the canonicalized target id.
    assert MockFeed.objects.filter.call_args.kwargs["staff_id"] == "00000000000000000000000000000099"


def test_status_reports_no_feed() -> None:
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
            query_params={"staff_id": "00000000000000000000000000000099"},
        )
        responses = api.feed_status()
    body = json.loads(responses[0].content)
    assert body["connected"] is False
```

Note: `responses[0].content` is the `JSONResponse` body. If `JSONResponse`
stores bytes, `json.loads` accepts bytes directly; if the attribute name
differs in this SDK build, inspect the object in a scratch REPL
(`.venv/bin/python -c "from canvas_sdk.effects.simple_api import JSONResponse; print(dir(JSONResponse(...)))"`)
and adjust the accessor — do not change the assertion intent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/routes/test_feeds.py -v -k status`
Expected: FAIL with `AttributeError: 'FeedsAPI' object has no attribute 'feed_status'`.

- [ ] **Step 3: Implement the route**

In `external_calendar_busy_blocks/routes/feeds.py`, add after `delete_feed`:

```python
    @api.get("/feeds/status")
    def feed_status(self) -> list[Response | Effect]:
        staff_id = self._logged_in_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Not authenticated"}, status_code=401)]
        if not is_admin(staff_id, self.secrets):
            return [JSONResponse({"error": "Forbidden"}, status_code=403)]

        target_id = (self.request.query_params.get("staff_id") or "").strip().replace("-", "")
        if not target_id:
            return [JSONResponse({"error": "Missing staff_id"}, status_code=400)]

        feed = StaffCalendarFeed.objects.filter(staff_id=target_id).first()
        if feed is None:
            return [JSONResponse({"connected": False}, status_code=200)]
        # Never return ics_url — it is a bearer token.
        return [JSONResponse(
            {
                "connected": bool(feed.is_active),
                "last_sync_at": str(feed.last_sync_at) if feed.last_sync_at else None,
                "last_error": feed.last_error,
            },
            status_code=200,
        )]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/routes/test_feeds.py -v -k status`
Expected: PASS (4 status tests).

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/routes/feeds.py tests/routes/test_feeds.py
git commit -m "feat(external-calendar-busy-blocks): add admin-only feed status endpoint"
```

---

### Task 4: `ConfigPage` admin context (staff dropdown data)

**Files:**
- Modify: `external_calendar_busy_blocks/ui/pages.py`
- Create: `tests/ui/__init__.py`
- Create: `tests/ui/test_pages.py`

**Interfaces:**
- Consumes: `is_admin` (Task 1), `canonical_staff_id`, SDK `Staff`.
- Produces: `ConfigPage.render` passes `is_admin` (bool), `staff_options` (list of `{"id": str, "name": str}`, only populated for admins), and `status_url` into the template context. `render_to_string` cannot execute outside plugin context, so tests patch it and assert the context.

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/__init__.py` (empty file), then create `tests/ui/test_pages.py`:

```python
from unittest.mock import MagicMock, patch

from external_calendar_busy_blocks.ui.pages import ConfigPage


def _page(logged_in_staff: str | None, secrets: dict | None = None) -> ConfigPage:
    headers = {}
    if logged_in_staff:
        headers["canvas-logged-in-user-id"] = logged_in_staff
    request = MagicMock(headers=headers)
    page = ConfigPage.__new__(ConfigPage)
    page.request = request
    page.secrets = secrets or {}
    return page


def test_render_non_admin_has_no_staff_options() -> None:
    with (
        patch("external_calendar_busy_blocks.ui.pages.render_to_string", return_value="<html></html>") as mock_render,
        patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed,
    ):
        MockFeed.objects.filter.return_value.first.return_value = None
        _page("00000000-0000-0000-0000-000000000002", secrets={}).render()
    context = mock_render.call_args.args[1]
    assert context["is_admin"] is False
    assert context["staff_options"] == []


def test_render_admin_lists_active_staff() -> None:
    staff_a = MagicMock(id="00000000000000000000000000000010", full_name="Bea Adams")
    staff_b = MagicMock(id="00000000000000000000000000000011", full_name="Cy Brown")
    with (
        patch("external_calendar_busy_blocks.ui.pages.render_to_string", return_value="<html></html>") as mock_render,
        patch("external_calendar_busy_blocks.ui.pages.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.ui.pages.Staff") as MockStaff,
    ):
        MockFeed.objects.filter.return_value.first.return_value = None
        MockStaff.objects.filter.return_value.order_by.return_value = [staff_a, staff_b]
        _page(
            "00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        ).render()
    context = mock_render.call_args.args[1]
    assert context["is_admin"] is True
    assert context["staff_options"] == [
        {"id": "00000000000000000000000000000010", "name": "Bea Adams"},
        {"id": "00000000000000000000000000000011", "name": "Cy Brown"},
    ]
    MockStaff.objects.filter.assert_called_once_with(active=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/ui/test_pages.py -v`
Expected: FAIL — `render` does not yet put `is_admin`/`staff_options` in context (KeyError), and `Staff` is not yet imported/patched in `pages`.

- [ ] **Step 3: Implement the context**

Replace `external_calendar_busy_blocks/ui/pages.py` with:

```python
from http import HTTPStatus

from canvas_sdk.effects.simple_api import HTMLResponse, PlainTextResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.staff import Staff

from external_calendar_busy_blocks.auth import canonical_staff_id, is_admin
from external_calendar_busy_blocks.data.models import StaffCalendarFeed


class ConfigPage(StaffSessionAuthMixin, SimpleAPI):
    """GET /pages/config — renders the connect/disconnect HTML page."""

    @api.get("/pages/config")
    def render(self) -> list[Response]:
        staff_id = canonical_staff_id(self.request.headers)
        feed = StaffCalendarFeed.objects.filter(staff_id=staff_id).first() if staff_id else None

        admin = is_admin(staff_id, self.secrets)
        staff_options: list[dict] = []
        if admin:
            staff_options = [
                {"id": s.id, "name": s.full_name}
                for s in Staff.objects.filter(active=True).order_by("last_name", "first_name")
            ]

        html = render_to_string(
            "templates/config.html",
            {
                "feed": feed,
                "connected": feed is not None and feed.is_active,
                "is_admin": admin,
                "staff_options": staff_options,
                "post_url": "/plugin-io/api/external_calendar_busy_blocks/feeds",
                "delete_url": "/plugin-io/api/external_calendar_busy_blocks/feeds/delete",
                "status_url": "/plugin-io/api/external_calendar_busy_blocks/feeds/status",
            },
        )
        # render_to_string is typed `str | None`. The current SDK raises
        # FileNotFoundError on a missing template rather than returning None,
        # but guard against the declared contract so a None can never reach
        # HTMLResponse (whose content.encode() would raise) — return an
        # explicit 500 instead.
        if html is None:
            return [PlainTextResponse(
                "Unable to render the configuration page.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )]
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ui/test_pages.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/ui/pages.py tests/ui/
git commit -m "feat(external-calendar-busy-blocks): pass admin staff list to config page"
```

---

### Task 5: Admin section in `config.html`

**Files:**
- Modify: `external_calendar_busy_blocks/templates/config.html`

**Interfaces:**
- Consumes: context keys `is_admin`, `staff_options`, `post_url`, `delete_url`, `status_url` from Task 4.
- Produces: no Python interface. Rendered HTML gains a "Manage another provider" section (staff `<select>`, a status line, and Connect/Disconnect controls) only when `is_admin` is truthy. Admin actions POST the same `post_url`/`delete_url` with a `staff_id` field; status is fetched from `status_url`.

This task has no unit test (the SDK forbids rendering templates outside plugin
context, and the repo does not unit-test the page JS). Verify by inspection in
Step 2 and rely on the Task 4 context tests plus Task 6's manifest.

- [ ] **Step 1: Add the admin section and its script**

In `external_calendar_busy_blocks/templates/config.html`, insert the admin
block immediately after the closing `</div>` of `#content` (before
`<p id="msg"></p>`):

```html
  {% if is_admin %}
  <hr style="margin:24px 0;" />
  <div id="admin-content">
    <h2>Manage another provider</h2>
    <p>Connect or disconnect a personal calendar on behalf of a provider. The provider never has to paste their own URL.</p>
    <label for="admin_staff">Provider</label>
    <select id="admin_staff">
      <option value="">— Select a provider —</option>
      {% for option in staff_options %}
      <option value="{{ option.id }}">{{ option.name }}</option>
      {% endfor %}
    </select>
    <p id="admin-status"></p>
    <div id="admin-actions" style="display:none;">
      <label for="admin_ics_url">Secret iCal URL</label>
      <input type="url" id="admin_ics_url" placeholder="https://calendar.google.com/calendar/ical/.../basic.ics" />
      <button type="button" id="admin-connect">Connect / Replace</button>
      <button type="button" id="admin-disconnect">Disconnect</button>
    </div>
    <p id="admin-msg"></p>
  </div>
  {% endif %}
```

- [ ] **Step 2: Add the admin script and verify markup**

Inside the existing `<script>`'s IIFE, just before the final `bindConnect();
bindDisconnect();` lines, add the admin wiring (reusing `submitJson`, `postUrl`,
`deleteUrl`):

```javascript
      var statusUrl = "{{ status_url }}";
      var adminSelect = document.getElementById("admin_staff");
      if (adminSelect) {
        var adminActions = document.getElementById("admin-actions");
        var adminStatus = document.getElementById("admin-status");
        var adminMsg = document.getElementById("admin-msg");
        var adminUrlInput = document.getElementById("admin_ics_url");

        function refreshAdminStatus(staffId) {
          adminMsg.textContent = "";
          if (!staffId) { adminActions.style.display = "none"; adminStatus.textContent = ""; return; }
          adminActions.style.display = "block";
          adminStatus.textContent = "Loading…";
          fetch(statusUrl + "?staff_id=" + encodeURIComponent(staffId), { credentials: "same-origin" })
            .then(function (r) { return r.json(); })
            .then(function (d) {
              if (d.connected) {
                adminStatus.textContent = "Connected." +
                  (d.last_sync_at ? " Last sync: " + d.last_sync_at : "") +
                  (d.last_error ? " Last error: " + d.last_error : "");
              } else {
                adminStatus.textContent = "Not connected.";
              }
            })
            .catch(function () { adminStatus.textContent = "Could not load status."; });
        }

        adminSelect.addEventListener("change", function () { refreshAdminStatus(adminSelect.value); });

        document.getElementById("admin-connect").addEventListener("click", function () {
          var staffId = adminSelect.value;
          var url = adminUrlInput.value.trim();
          if (!staffId || !url) { adminMsg.textContent = "Pick a provider and enter a URL."; adminMsg.className = "error"; return; }
          submitJson(postUrl, { ics_url: url, staff_id: staffId }, this, function () {
            adminMsg.textContent = "Connected."; adminMsg.className = "status";
            adminUrlInput.value = ""; refreshAdminStatus(staffId);
          });
        });

        document.getElementById("admin-disconnect").addEventListener("click", function () {
          var staffId = adminSelect.value;
          if (!staffId) { return; }
          submitJson(deleteUrl, { staff_id: staffId }, this, function () {
            adminMsg.textContent = "Disconnected."; adminMsg.className = "status";
            refreshAdminStatus(staffId);
          });
        });
      }
```

Note: `submitJson` disables the button it is passed and re-enables it on error;
the admin buttons are passed as `this`, so they behave like the self-service
button. Verify the inserted markup by eye: the `{% if is_admin %}` block wraps
the whole admin section, `{% for option in staff_options %}` renders one
`<option>` per provider, and no stored ICS URL is ever printed into the page.

- [ ] **Step 3: Run the full plugin test suite (nothing should regress)**

Run: `.venv/bin/pytest -q`
Expected: PASS — template changes don't touch Python; all tests from Tasks 1–4
and the pre-existing suite pass.

- [ ] **Step 4: Commit**

```bash
git add external_calendar_busy_blocks/templates/config.html
git commit -m "feat(external-calendar-busy-blocks): admin section in config page for managing provider feeds"
```

---

### Task 6: Manifest, data access, README, version bump

**Files:**
- Modify: `external_calendar_busy_blocks/CANVAS_MANIFEST.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `ADMIN_STAFF_IDS` declared as a secret; `Staff` added to the `read` data-access of `FeedsAPI` and `ConfigPage`; README documents admin setup/usage; `plugin_version` bumped.

- [ ] **Step 1: Update the manifest**

In `external_calendar_busy_blocks/CANVAS_MANIFEST.json`:

1. Bump `"plugin_version"` from `"0.2.0"` to `"0.3.0"`.
2. In the `FeedsAPI` protocol entry, change its `data_access` to:

```json
                "data_access": {"event": "", "read": ["Staff"], "write": ["Event", "Calendar"]}
```

3. In the `ConfigPage` protocol entry, change its `data_access` to:

```json
                "data_access": {"event": "", "read": ["Staff"], "write": []}
```

4. Change the `secrets` array to:

```json
    "secrets": ["LOOKAHEAD_DAYS", "ADMIN_STAFF_IDS", "namespace_read_write_access_key"],
```

- [ ] **Step 2: Update the README**

In `README.md`, add a row to the Configuration table:

```markdown
| `ADMIN_STAFF_IDS` | _(unset)_ | Comma-separated Canvas staff IDs allowed to manage other providers' feeds from the admin section. Unset means no one has admin access (the admin section is hidden). |
```

And add a subsection after "How it works":

```markdown
## Admin: connect feeds on behalf of providers

Staff whose IDs are listed in the `ADMIN_STAFF_IDS` secret see an extra
**Manage another provider** section when they open **Calendar Busy Blocks**.
There they pick any active provider, see whether that provider already has a
feed connected, and connect/replace or disconnect the provider's secret iCal
URL — so providers never have to paste their own URL. Everyone else sees only
their own self-service form; the admin section and its API are denied to
non-admins (fail closed). Admin-connected feeds sync exactly like self-service
feeds, and the stored URL is never shown back in the UI.
```

- [ ] **Step 3: Verify manifest is valid JSON and matches class paths**

Run:
```bash
.venv/bin/python -c "import json; m=json.load(open('external_calendar_busy_blocks/CANVAS_MANIFEST.json')); print(m['plugin_version']); print(m['secrets'])"
```
Expected: prints `0.3.0` and a list containing `ADMIN_STAFF_IDS`.

- [ ] **Step 4: Run the full suite once more**

Run: `.venv/bin/pytest -q`
Expected: PASS (whole suite green).

- [ ] **Step 5: Commit**

```bash
git add external_calendar_busy_blocks/CANVAS_MANIFEST.json README.md
git commit -m "docs(external-calendar-busy-blocks): declare ADMIN_STAFF_IDS and Staff read; document admin flow; bump to 0.3.0"
```

---

## Self-Review

**Spec coverage:**
- §1 Authorization (`ADMIN_STAFF_IDS`, fail closed) → Task 1.
- §2 UI admin section (server-rendered dropdown, admin-only) → Tasks 4 + 5.
- §3 API target-staff dimension + `GET /feeds/status` → Tasks 2 + 3.
- §4 Manifest & data access (secret, Staff reads) → Task 6.
- §5 Error handling (non-admin ignored, unresolvable staff → 400, 403 on status) → Tasks 2 + 3.
- §6 Testing + README + version bump → Tasks 1–4 (tests), Task 6 (README/version).

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The only
uncertainty (Task 3 Step 1 note) gives an exact fallback command rather than a
vague instruction.

**Type consistency:** `is_admin(staff_id, secrets)` signature identical across
Tasks 1–4. `_resolve_target_staff_id(logged_in, body) -> str` used consistently
in Task 2. Context keys `is_admin`/`staff_options`/`status_url` defined in Task 4
and consumed in Task 5. Route name `feed_status` consistent between Task 3 impl
and tests.
