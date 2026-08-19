"""Shared fixtures and Django / Canvas-SDK stubs.

The plugin imports ``canvas_sdk`` and Django, neither of which is installed in
the test environment. We synthesize just enough of both for the plugin modules
to import cleanly, then mock behavior per test. The result is a suite that runs
with only ``pytest`` present -- no SDK, no Django, no database.

This is a port of the pattern in ``extensions/staff_directory/tests/conftest.py``
with the pieces this plugin needs that that one has no use for: banner alerts,
task effects, cron tasks, events, and a ``Q`` object that actually composes so
the matching predicate can be asserted on structurally.
"""

from __future__ import annotations

import contextlib
import sys
import types
from enum import Enum, StrEnum
from unittest.mock import MagicMock

import pytest


def _ensure_module(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


# ---------------------------------------------------------------------------
# Django
# ---------------------------------------------------------------------------


class FieldStub:
    """Stands in for any Django field; records how it was declared."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    @property
    def null(self) -> bool:
        return bool(self.kwargs.get("null", False))

    @property
    def default(self):
        return self.kwargs.get("default")


class Q:
    """A composable stand-in for ``django.db.models.Q``.

    staff_directory's stub collapses ``|`` and ``&`` back to ``self``, which is
    fine when nothing inspects the result. The waitlist's match predicate *is*
    the feature, so this version keeps the tree: every combination produces a
    new node recording its connector and children. Tests can then assert on the
    shape of the predicate without a database.
    """

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        self.children: list[Q] = []
        self.connector: str | None = None
        self.negated = False

    @classmethod
    def _combine(cls, left: Q, right: Q, connector: str) -> Q:
        node = cls()
        node.connector = connector
        node.children = [left, right]
        return node

    def __or__(self, other: Q) -> Q:
        return Q._combine(self, other, "OR")

    def __and__(self, other: Q) -> Q:
        return Q._combine(self, other, "AND")

    def __invert__(self) -> Q:
        node = Q(**self.kwargs)
        node.children = list(self.children)
        node.connector = self.connector
        node.negated = not self.negated
        return node

    def leaves(self) -> list[dict]:
        """Every leaf condition in this tree, flattened. Order-preserving."""
        if not self.children:
            return [dict(self.kwargs)] if self.kwargs else []
        found: list[dict] = []
        for child in self.children:
            found.extend(child.leaves())
        return found

    def __repr__(self) -> str:
        if not self.children:
            return f"Q({self.kwargs})"
        joiner = f" {self.connector} "
        return "(" + joiner.join(repr(child) for child in self.children) + ")"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Q):
            return NotImplemented
        return (
            self.kwargs == other.kwargs
            and self.connector == other.connector
            and self.negated == other.negated
            and self.children == other.children
        )


def _install_django_stubs() -> None:
    _ensure_module("django")
    django_db = _ensure_module("django.db")
    models = _ensure_module("django.db.models")

    for name in (
        "TextField",
        "CharField",
        "IntegerField",
        "PositiveIntegerField",
        "BooleanField",
        "DateField",
        "DateTimeField",
        "JSONField",
        "UUIDField",
        "ForeignKey",
        "OneToOneField",
        "ManyToManyField",
        "Index",
        "UniqueConstraint",
    ):
        setattr(models, name, type(name, (FieldStub,), {}))

    models.Q = Q
    models.DO_NOTHING = "DO_NOTHING"
    models.CASCADE = "CASCADE"
    models.PROTECT = "PROTECT"
    models.SET_NULL = "SET_NULL"

    class Model:
        objects = MagicMock()

    models.Model = Model

    class IntegrityError(Exception):
        pass

    django_db.IntegrityError = IntegrityError
    models.IntegrityError = IntegrityError

    class _Transaction:
        @staticmethod
        def atomic():
            @contextlib.contextmanager
            def _cm():
                yield

            return _cm()

    django_db.transaction = _Transaction()


# ---------------------------------------------------------------------------
# Canvas SDK
# ---------------------------------------------------------------------------


class CustomModel:
    """Plugin-owned table stub. Assigns whatever kwargs it is given."""

    objects = MagicMock()

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def save(self, *args, **kwargs):
        return None


class ModelExtension:
    pass


BANNER_NARRATIVE_MAX = 90


class AddBannerAlert:
    """Mirrors the real effect, including its 90-character narrative cap.

    The cap is the reason this is a hand-written stub rather than a MagicMock:
    the chart banner composes its text from a patient's entries, so a summary
    that grows past the limit has to fail here rather than in production.
    """

    class Placement(Enum):
        CHART = "chart"
        TIMELINE = "timeline"
        APPOINTMENT_CARD = "appointment_card"
        SCHEDULING_CARD = "scheduling_card"
        PROFILE = "profile"

    class Intent(Enum):
        INFO = "info"
        WARNING = "warning"
        ALERT = "alert"

    def __init__(
        self, patient_id=None, key=None, narrative=None, placement=None, intent=None, href=None
    ):
        if narrative is not None and len(narrative) > BANNER_NARRATIVE_MAX:
            raise ValueError(
                f"narrative must be at most {BANNER_NARRATIVE_MAX} characters"
            )
        self.patient_id = patient_id
        self.key = key
        self.narrative = narrative
        self.placement = placement
        self.intent = intent
        self.href = href

    def apply(self):
        return self


class RemoveBannerAlert:
    """Clears a banner by the same key that created it."""

    def __init__(self, patient_id=None, key=None):
        self.patient_id = patient_id
        self.key = key

    def apply(self):
        return self


class LaunchModalEffect:
    """Mirrors the real effect, including its mutual-exclusion rule.

    staff_directory's stub accepts only ``url``. This plugin launches the roster
    by ``url``, and the real effect raises when ``url`` and ``content`` are both
    supplied -- so the stub raises too. Without that, a regression that set both
    would pass the suite and fail in production.
    """

    class TargetType:
        DEFAULT_MODAL = "default_modal"
        NEW_WINDOW = "new_window"
        RIGHT_CHART_PANE = "right_chart_pane"
        RIGHT_CHART_PANE_LARGE = "right_chart_pane_large"
        PAGE = "page"
        NOTE = "note"

    def __init__(self, url=None, content=None, target=TargetType.DEFAULT_MODAL, title="Untitled"):
        if url is not None and content is not None:
            raise ValueError("'url' and 'content' are mutually exclusive")
        self.url = url
        self.content = content
        self.target = target
        self.title = title

    def apply(self):
        return self


class Response:
    def __init__(self, body=b"", status_code=200, content_type="text/plain", headers=None):
        self.body = body
        self.status_code = status_code
        self.content_type = content_type
        self.headers = headers or {}


class HTMLResponse(Response):
    # ``headers`` mirrors the real effect. Omitting it here let a route that
    # passes headers -- which the SDK accepts -- fail only in the test suite.
    def __init__(self, body, status_code=200, headers=None):
        super().__init__(
            body=body, status_code=status_code, content_type="text/html", headers=headers
        )


class JSONResponse(Response):
    def __init__(self, data, status_code=200, headers=None):
        self.data = data
        super().__init__(
            body=b"",
            status_code=status_code,
            content_type="application/json",
            headers=headers,
        )


class InvalidCredentialsError(Exception):
    pass


class _RouteDecorator:
    def __init__(self, method: str, path: str):
        self.method = method
        self.path = path

    def __call__(self, func):
        func.__api_route__ = (self.method, self.path)
        return func


class _Api:
    def get(self, path):
        return _RouteDecorator("GET", path)

    def post(self, path):
        return _RouteDecorator("POST", path)

    def put(self, path):
        return _RouteDecorator("PUT", path)

    def patch(self, path):
        return _RouteDecorator("PATCH", path)

    def delete(self, path):
        return _RouteDecorator("DELETE", path)


class _EventType:
    """Enough of the protobuf enum for ``EventType.Name(EventType.X)``."""

    # Kept in step with the real enum for the events this plugin subscribes to;
    # tests/test_stub_contract.py checks each one still round-trips there.
    _NAMES = (
        "APPOINTMENT_CANCELED",
        "APPOINTMENT_CREATED",
        "APPOINTMENT_NO_SHOWED",
        "APPOINTMENT_RESCHEDULED",
        "APPOINTMENT_RESTORED",
        "APPOINTMENT_UPDATED",
        "PATIENT_PORTAL__APPOINTMENT_CANCELED",
        "PATIENT_PORTAL__APPOINTMENT_RESCHEDULED",
        "NOTE_STATE_CHANGE_EVENT_CREATED",
        "CRON",
    )

    def __init__(self):
        self._by_value = {}
        for index, name in enumerate(self._NAMES, start=1):
            setattr(self, name, index)
            self._by_value[index] = name

    def Name(self, value):  # noqa: N802 - matches the protobuf API
        return self._by_value[value]


def _install_canvas_sdk_stubs() -> None:
    _ensure_module("canvas_sdk")
    _ensure_module("canvas_sdk.v1")
    data = _ensure_module("canvas_sdk.v1.data")
    base_mod = _ensure_module("canvas_sdk.v1.data.base")
    note_data_mod = _ensure_module("canvas_sdk.v1.data.note")
    appointment_data_mod = _ensure_module("canvas_sdk.v1.data.appointment")
    task_data_mod = _ensure_module("canvas_sdk.v1.data.task")
    effects_mod = _ensure_module("canvas_sdk.effects")
    launch_modal_mod = _ensure_module("canvas_sdk.effects.launch_modal")
    banner_mod = _ensure_module("canvas_sdk.effects.banner_alert")
    add_banner_mod = _ensure_module("canvas_sdk.effects.banner_alert.add_banner_alert")
    remove_banner_mod = _ensure_module("canvas_sdk.effects.banner_alert.remove_banner_alert")
    simple_api_effects = _ensure_module("canvas_sdk.effects.simple_api")
    task_effects_mod = _ensure_module("canvas_sdk.effects.task")
    task_effects_task_mod = _ensure_module("canvas_sdk.effects.task.task")
    _ensure_module("canvas_sdk.handlers")
    app_mod = _ensure_module("canvas_sdk.handlers.application")
    base_handler_mod = _ensure_module("canvas_sdk.handlers.base")
    cron_mod = _ensure_module("canvas_sdk.handlers.cron_task")
    action_button_handler_mod = _ensure_module("canvas_sdk.handlers.action_button")
    action_button_effects_mod = _ensure_module("canvas_sdk.effects.action_button")
    simple_api_mod = _ensure_module("canvas_sdk.handlers.simple_api")
    security_mod = _ensure_module("canvas_sdk.handlers.simple_api.security")
    exceptions_mod = _ensure_module("canvas_sdk.handlers.simple_api.exceptions")
    events_mod = _ensure_module("canvas_sdk.events")
    templates_mod = _ensure_module("canvas_sdk.templates")
    logger_mod = _ensure_module("logger")

    base_mod.CustomModel = CustomModel
    data.CustomModel = CustomModel
    data.ModelExtension = ModelExtension
    base_mod.ModelExtension = ModelExtension

    # Core data models the plugin reads. MagicMock managers let each test drive
    # its own queryset behavior.
    for name in (
        "Patient",
        "Staff",
        "StaffRole",
        "NoteType",
        "PracticeLocation",
        "Appointment",
        "Team",
        "Note",
        "NoteStateChangeEvent",
    ):
        setattr(data, name, type(name, (), {"objects": MagicMock()}))

    note_data_mod.Note = data.Note
    note_data_mod.NoteType = data.NoteType
    note_data_mod.NoteStateChangeEvent = data.NoteStateChangeEvent

    class NoteStates:
        """The stored codes, not the member names.

        The handler compares strings, and ``str()`` of a real ``TextChoices``
        member is its stored value -- so a stub using readable names would pass
        the suite and fail on the instance.
        """

        NEW = "NEW"
        SCHEDULING = "SCH"
        BOOKED = "BKD"
        CONVERTED = "CVD"
        CANCELLED = "CLD"
        NOSHOW = "NSW"
        REVERTED = "RVT"
        LOCKED = "LKD"
        SIGNED = "SGN"

    note_data_mod.NoteStates = NoteStates
    data.NoteStates = NoteStates

    class AppointmentProgressStatus:
        """Only the values this plugin reads, as their stored strings.

        ``str()`` of the real ``TextChoices`` member yields the stored value, so
        the plugin compares against these strings and the stub has to be them.
        """

        UNCONFIRMED = "unconfirmed"
        ATTEMPTED = "attempted"
        CONFIRMED = "confirmed"
        ARRIVED = "arrived"
        ROOMED = "roomed"
        EXITED = "exited"
        NOSHOWED = "noshowed"
        CANCELLED = "cancelled"

    appointment_data_mod.AppointmentProgressStatus = AppointmentProgressStatus

    class TaskPriority:
        URGENT = "urgent"
        HIGH = "high"
        MEDIUM = "medium"
        LOW = "low"

    task_data_mod.TaskPriority = TaskPriority

    class Effect:
        pass

    effects_mod.Effect = Effect

    launch_modal_mod.LaunchModalEffect = LaunchModalEffect

    banner_mod.AddBannerAlert = AddBannerAlert
    banner_mod.RemoveBannerAlert = RemoveBannerAlert
    add_banner_mod.AddBannerAlert = AddBannerAlert
    remove_banner_mod.RemoveBannerAlert = RemoveBannerAlert

    simple_api_effects.Response = Response
    simple_api_effects.HTMLResponse = HTMLResponse
    simple_api_effects.JSONResponse = JSONResponse

    class TaskStatus:
        OPEN = "OPEN"
        CLOSED = "CLOSED"
        COMPLETED = "COMPLETED"

    class AddTask:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)

        def apply(self):
            return self

    class AddTaskComment:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)

        def apply(self):
            return self

    class UpdateTask:
        """Requires an id, like the real effect: it addresses an existing task."""

        def __init__(self, **kwargs):
            if not kwargs.get("id"):
                raise ValueError("UpdateTask requires the id of the task to update")
            self.kwargs = kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)

        def apply(self):
            return self

    for module in (task_effects_mod, task_effects_task_mod):
        module.AddTask = AddTask
        module.AddTaskComment = AddTaskComment
        module.UpdateTask = UpdateTask
        module.TaskStatus = TaskStatus

    class Application:
        def __init__(self, event=None, secrets=None):
            self.event = event
            self.secrets = secrets or {}

    app_mod.Application = Application

    class BaseHandler:
        def __init__(self, event=None, secrets=None):
            self.event = event
            self.secrets = secrets or {}

    base_handler_mod.BaseHandler = BaseHandler

    class CronTask(BaseHandler):
        SCHEDULE = ""

    cron_mod.CronTask = CronTask

    class ActionButton(BaseHandler):
        """Mirrors the real base class closely enough to test a button.

        ``visible()`` is called by the real ``compute()`` immediately before
        ``BUTTON_TITLE`` is read, which is what lets a button decide its own
        label from live data. The stub keeps that ordering so a title computed
        in ``visible()`` is exercised the way the platform exercises it.
        """

        class ButtonLocation(StrEnum):
            NOTE_HEADER = "note_header"
            NOTE_FOOTER = "note_footer"
            NOTE_BODY = "note_body"
            NOTE_HEADER_DROPDOWN = "note_header_dropdown"
            CHART_PATIENT_HEADER = "chart_patient_header"

        BUTTON_TITLE = ""
        BUTTON_KEY = ""
        BUTTON_LOCATION = None
        PRIORITY = 0

        def handle(self):
            raise NotImplementedError

        def visible(self):
            return True

    action_button_handler_mod.ActionButton = ActionButton

    class ReloadPatientActionButtonsEffect:
        """Tells the chart to redraw its buttons so a stale label is corrected."""

        def __init__(self, id=None):  # noqa: A002 - matches the real signature
            self.id = id

        def apply(self):
            return self

    action_button_effects_mod.ReloadPatientActionButtonsEffect = (
        ReloadPatientActionButtonsEffect
    )

    class ReloadNoteActionButtonsEffect:
        """The note-header counterpart, addressed by note rather than patient.

        A separate effect in the SDK, which is why emitting only the patient one
        left a note's button label stale until the page was reloaded.
        """

        def __init__(self, id=None):  # noqa: A002 - matches the real signature
            self.id = id

        def apply(self):
            return self

    action_button_effects_mod.ReloadNoteActionButtonsEffect = (
        ReloadNoteActionButtonsEffect
    )

    class SimpleAPI:
        def __init__(self, event=None, secrets=None):
            self.event = event
            self.secrets = secrets or {}

    class SimpleAPIRoute(SimpleAPI):
        PATH = ""

    class StaffSessionAuthMixin:
        pass

    simple_api_mod.SimpleAPI = SimpleAPI
    simple_api_mod.SimpleAPIRoute = SimpleAPIRoute
    simple_api_mod.api = _Api()
    exceptions_mod.InvalidCredentialsError = InvalidCredentialsError

    # Registered under BOTH import paths. Both are real exports in the SDK and
    # both are used in this repo (28 files import from the package, 2 from
    # .security). Stubbing only one makes the suite silently depend on which
    # style the plugin happens to use.
    simple_api_mod.StaffSessionAuthMixin = StaffSessionAuthMixin
    security_mod.StaffSessionAuthMixin = StaffSessionAuthMixin

    events_mod.EventType = _EventType()

    # A MagicMock wrapper, not a plain function, so tests can assert on the
    # context dict a handler passed rather than parsing it back out of rendered
    # text. The returned marker still names the template, which is what the
    # response-level assertions look for.
    def _render(template_name, context=None):
        return f"RENDERED::{template_name}"

    templates_mod.render_to_string = MagicMock(side_effect=_render)

    logger_mod.log = MagicMock()


_install_django_stubs()
_install_canvas_sdk_stubs()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_shared_mocks():
    """Keep call-recording stubs independent between tests."""
    sys.modules["logger"].log.reset_mock()
    sys.modules["canvas_sdk.templates"].render_to_string.reset_mock()
    yield


@pytest.fixture
def rendered_context():
    """The context dict passed to the most recent ``render_to_string`` call."""

    def _context():
        render = sys.modules["canvas_sdk.templates"].render_to_string
        assert render.call_args is not None, "render_to_string was never called"
        args, kwargs = render.call_args
        if "context" in kwargs:
            return kwargs["context"]
        return args[1] if len(args) > 1 else {}

    return _context


@pytest.fixture
def mock_staff():
    staff = MagicMock()
    staff.dbid = 101
    staff.id = "00000000000000000000000000000101"
    staff.first_name = "Alice"
    staff.last_name = "Chen"
    staff.active = True
    return staff


@pytest.fixture
def mock_patient():
    patient = MagicMock()
    patient.dbid = 55
    patient.id = "00000000000000000000000000000055"
    patient.first_name = "Jordan"
    patient.last_name = "Lee"
    patient.birth_date = None
    return patient


@pytest.fixture
def mock_note_type():
    note_type = MagicMock()
    note_type.dbid = 7
    note_type.id = "00000000-0000-0000-0000-000000000007"
    note_type.name = "Established Patient Visit"
    note_type.code = "estab"
    note_type.is_scheduleable = True
    note_type.is_active = True
    note_type.is_visible = True
    note_type.deprecated_at = None
    return note_type


@pytest.fixture
def mock_location():
    location = MagicMock()
    location.dbid = 3
    location.id = "00000000-0000-0000-0000-000000000003"
    location.full_name = "Riverside Clinic"
    location.short_name = "Riverside"
    location.active = True
    return location


@pytest.fixture
def make_request():
    """Builds the ``self.request`` a SimpleAPI handler sees."""

    def _make(headers=None, query_params=None, path_params=None, json_body=None):
        request = MagicMock()
        request.headers = headers or {}
        request.query_params = query_params or {}
        request.path_params = path_params or {}
        request.json.return_value = json_body or {}
        return request

    return _make


@pytest.fixture
def make_event():
    """Builds the ``self.event`` a handler sees.

    Appointment events carry the id on ``target`` and ship an empty context, so
    that is the default shape here.
    """

    def _make(target_id=None, context=None, event_type=None):
        event = MagicMock()
        event.target = MagicMock()
        event.target.id = target_id
        event.context = context if context is not None else {}
        event.type = event_type
        if event_type is not None:
            event.name = event_type
        return event

    return _make
