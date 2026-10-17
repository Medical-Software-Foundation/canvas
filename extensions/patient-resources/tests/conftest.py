"""Shared fixtures and Django / Canvas-SDK stubs.

The plugin imports ``canvas_sdk`` and Django, neither of which is installed in
the test environment. We synthesize just enough of both for the plugin modules to
import cleanly, then mock behavior per test. The result is a suite that runs with
only ``pytest`` present -- no SDK, no Django, no database.

This is a trimmed port of ``extensions/scheduling-waitlist/tests/conftest.py``
(itself a port of ``extensions/staff_directory``). Dropped, because this plugin
has no use for them: banner alerts, task effects, cron tasks, appointment and
note data models, and the protobuf ``EventType`` shim. Added: a patient session
auth mixin, and a ``StaffRole`` whose ``RoleDomain`` carries the stored codes.

The stubs are not free-form doubles. Where the real SDK enforces an invariant --
mutually exclusive arguments, a required id, a stored enum code -- the stub
enforces it too, so a regression fails here instead of on the instance.
``tests/test_stub_contract.py`` pins the important ones against the real SDK.
"""

from __future__ import annotations

import contextlib
import sys
import types
from datetime import date
from enum import StrEnum
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
    """Stands in for any Django field; records how it was declared.

    ``tests/models/test_schema.py`` reads these recordings. They are the only
    guard this plugin has on its table shape, because the DDL pipeline is
    append-only: a field declared wrong cannot be corrected after install.
    """

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    @property
    def null(self) -> bool:
        return bool(self.kwargs.get("null", False))

    @property
    def default(self):
        return self.kwargs.get("default")

    @property
    def auto_now_add(self) -> bool:
        return bool(self.kwargs.get("auto_now_add", False))

    @property
    def auto_now(self) -> bool:
        return bool(self.kwargs.get("auto_now", False))


class Q:
    """A composable stand-in for ``django.db.models.Q``.

    staff_directory's stub collapses ``|`` and ``&`` back to ``self``, which is
    fine when nothing inspects the result. Here the partial unique constraints
    carry a ``condition`` that decides whether archiving frees a title for reuse
    and whether a revoked share blocks a re-send -- so the tree is kept and the
    schema tests assert on its shape.
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

    # Only the field types the sandbox's django.db.models allowlist actually
    # permits. URLField, UUIDField and PositiveIntegerField are deliberately
    # absent: they are absent from the allowlist too, so importing one stops the
    # plugin loading on the instance. Leaving them out of the stub means such an
    # import fails here as well, instead of passing the suite.
    for name in (
        "TextField",
        "CharField",
        "IntegerField",
        "BigIntegerField",
        "BooleanField",
        "DateField",
        "DateTimeField",
        "JSONField",
        "ForeignKey",
        "OneToOneField",
        "Index",
        "UniqueConstraint",
    ):
        setattr(models, name, type(name, (FieldStub,), {}))

    models.Q = Q
    models.DO_NOTHING = "DO_NOTHING"

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

    def __init_subclass__(cls, **kwargs):
        """Give every model its own manager.

        Inheriting one ``objects`` from this base would make
        ``PatientResource.objects`` and ``PatientResourceShare.objects`` the same
        mock: a test arranging a catalog queryset would silently also arrange the
        share queryset, and an assertion about one table could pass because of a
        call made against the other.
        """
        super().__init_subclass__(**kwargs)
        cls.objects = MagicMock()

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)

    def save(self, *args, **kwargs):
        return None


class ModelExtension:
    pass


class LaunchModalEffect:
    """Mirrors the real effect, including its mutual-exclusion rule.

    Every surface in this plugin launches by ``url`` rather than inline
    ``content``, so that the staff or patient session cookie travels with the
    page's own fetches. The real effect raises when both are supplied, so the
    stub raises too -- otherwise a regression that set both would pass here and
    fail in production.
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


def _install_canvas_sdk_stubs() -> None:
    _ensure_module("canvas_sdk")
    _ensure_module("canvas_sdk.v1")
    data = _ensure_module("canvas_sdk.v1.data")
    base_mod = _ensure_module("canvas_sdk.v1.data.base")
    staff_data_mod = _ensure_module("canvas_sdk.v1.data.staff")
    patient_data_mod = _ensure_module("canvas_sdk.v1.data.patient")
    effects_mod = _ensure_module("canvas_sdk.effects")
    launch_modal_mod = _ensure_module("canvas_sdk.effects.launch_modal")
    simple_api_effects = _ensure_module("canvas_sdk.effects.simple_api")
    _ensure_module("canvas_sdk.handlers")
    app_mod = _ensure_module("canvas_sdk.handlers.application")
    base_handler_mod = _ensure_module("canvas_sdk.handlers.base")
    action_button_handler_mod = _ensure_module("canvas_sdk.handlers.action_button")
    simple_api_mod = _ensure_module("canvas_sdk.handlers.simple_api")
    security_mod = _ensure_module("canvas_sdk.handlers.simple_api.security")
    exceptions_mod = _ensure_module("canvas_sdk.handlers.simple_api.exceptions")
    templates_mod = _ensure_module("canvas_sdk.templates")
    logger_mod = _ensure_module("logger")

    base_mod.CustomModel = CustomModel
    data.CustomModel = CustomModel
    data.ModelExtension = ModelExtension
    base_mod.ModelExtension = ModelExtension

    # Core data models the plugin reads. MagicMock managers let each test drive
    # its own queryset behavior.
    for name in ("Patient", "Staff"):
        setattr(data, name, type(name, (), {"objects": MagicMock()}))

    patient_data_mod.Patient = data.Patient
    staff_data_mod.Staff = data.Staff

    class StaffRole:
        """The role rows a staff member holds.

        ``RoleDomain`` carries the *stored codes*, not the member names. The
        permission check filters on ``domain__in=[...]`` with configured strings,
        and ``str()`` of a real ``TextChoices`` member is its stored value -- so a
        stub using ``"ADMINISTRATIVE"`` would pass every test in this suite and
        match no row on the instance.
        """

        class RoleDomain(StrEnum):
            CLINICAL = "CLI"
            ADMINISTRATIVE = "ADM"
            HYBRID = "HYB"

        objects = MagicMock()

    staff_data_mod.StaffRole = StaffRole
    data.StaffRole = StaffRole

    class Effect:
        pass

    effects_mod.Effect = Effect

    launch_modal_mod.LaunchModalEffect = LaunchModalEffect

    simple_api_effects.Response = Response
    simple_api_effects.HTMLResponse = HTMLResponse
    simple_api_effects.JSONResponse = JSONResponse

    class BaseHandler:
        def __init__(self, event=None, secrets=None):
            self.event = event
            self.secrets = secrets or {}

    base_handler_mod.BaseHandler = BaseHandler

    class Application(BaseHandler):
        """The app-drawer / portal-menu entry point.

        ``compute_notification_badge`` returning ``None`` is the real base
        class's default and means "emit no badge"; ``0`` is a valid value that
        clears an existing one. The portal app overrides it.
        """

        def on_open(self):
            raise NotImplementedError

        def compute_notification_badge(self):
            return None

        @property
        def identifier(self) -> str:
            return f"{self.__class__.__module__}:{self.__class__.__qualname__}"

    app_mod.Application = Application

    class ActionButton(BaseHandler):
        """Mirrors the real base class closely enough to test a button.

        ``visible()`` is called by the real ``compute()`` immediately before
        ``BUTTON_TITLE`` is read. The stub keeps that ordering even though this
        plugin's button has a static title, so a future title computed in
        ``visible()`` is exercised the way the platform exercises it.
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

    class SimpleAPI:
        def __init__(self, event=None, secrets=None):
            self.event = event
            self.secrets = secrets or {}

    class SimpleAPIRoute(SimpleAPI):
        PATH = ""

    class StaffSessionAuthMixin:
        """Proves a live *staff* session. Nothing more.

        It does not resolve the staff member, and it says nothing about what they
        are allowed to do -- that is services/permissions.py's job.
        """

    class PatientSessionAuthMixin:
        """Proves a live *patient* session. Nothing more.

        Specifically: it does not bind the request to a patient. Every portal
        query has to scope itself from the session header, which is why no portal
        route in this plugin accepts an identifier at all.
        """

    simple_api_mod.SimpleAPI = SimpleAPI
    simple_api_mod.SimpleAPIRoute = SimpleAPIRoute
    simple_api_mod.api = _Api()
    exceptions_mod.InvalidCredentialsError = InvalidCredentialsError

    # Registered under BOTH import paths. Both are real exports in the SDK and
    # both styles are used across this repo. Stubbing only one makes the suite
    # silently depend on which style the plugin happens to use.
    for module in (simple_api_mod, security_mod):
        module.StaffSessionAuthMixin = StaffSessionAuthMixin
        module.PatientSessionAuthMixin = PatientSessionAuthMixin

    # A MagicMock wrapper, not a plain function, so tests can assert on the
    # context dict a route passed rather than parsing it back out of rendered
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
    """Keep call-recording stubs independent between tests.

    ``side_effect=True`` and ``return_value=True`` matter: a bare ``reset_mock()``
    clears recorded calls but leaves configured side effects and return values in
    place, so a queryset arranged in one test file silently carried into the next
    one and an assertion could pass or fail for reasons in another file.
    """
    from canvas_sdk.v1.data import Patient, Staff
    from canvas_sdk.v1.data.staff import StaffRole

    from patient_resources.models import PatientResource, PatientResourceShare

    managers = (
        Patient.objects,
        Staff.objects,
        StaffRole.objects,
        PatientResource.objects,
        PatientResourceShare.objects,
    )
    for manager in managers:
        manager.reset_mock(side_effect=True, return_value=True)

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
    """A staff member with no roles configured on them by default."""
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
    # Real values, not mocks: a MagicMock birth_date has a strftime attribute
    # that returns another mock, so a formatting bug would stringify to junk and
    # still pass.
    patient.birth_date = date(1979, 4, 12)
    patient.mrn = "88213"
    return patient


@pytest.fixture
def make_request():
    """Builds the ``self.request`` a SimpleAPI handler sees."""

    def _make(headers=None, query_params=None, path_params=None, json_body=None):
        request = MagicMock()
        request.headers = headers or {}
        request.query_params = query_params or {}
        request.path_params = path_params or {}
        request.json.return_value = {} if json_body is None else json_body
        return request

    return _make


@pytest.fixture
def make_event():
    """Builds the ``self.event`` a handler sees."""

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
