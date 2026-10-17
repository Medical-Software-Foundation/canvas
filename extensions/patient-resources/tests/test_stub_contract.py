"""Pins the test doubles to the SDK behavior they stand in for.

The suite fabricates ``canvas_sdk`` and Django in ``sys.modules`` so it can run
with only pytest installed. That buys speed and portability at one cost: if a
stub drifts from the real SDK, every test above it keeps passing while production
breaks. These tests assert the invariants the rest of the suite leans on.

They cannot compare against the real SDK in-process -- conftest has already
replaced it in ``sys.modules`` by the time any test runs. The real cross-checks
are ``mypy`` (which sees the installed ``canvas`` package) and ``canvas
validate`` (which sandbox-loads every handler with the real runner). What lives
here is the set of behaviors a future edit to conftest must not quietly relax.
"""

import pytest

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.handlers.application import Application
from canvas_sdk.handlers.simple_api import (
    PatientSessionAuthMixin,
    SimpleAPI,
    StaffSessionAuthMixin,
)
from canvas_sdk.handlers.simple_api import security as security_module
from canvas_sdk.v1.data.staff import StaffRole
from django.db import models


def test_launch_modal_refuses_url_and_content_together():
    """The real effect treats them as mutually exclusive.

    Every surface in this plugin launches by url, so a regression that also set
    content has to fail here rather than in the browser.
    """
    with pytest.raises(ValueError):
        LaunchModalEffect(url="/x", content="<p>x</p>")


def test_launch_modal_target_values_are_the_stored_strings():
    assert LaunchModalEffect.TargetType.DEFAULT_MODAL == "default_modal"
    assert LaunchModalEffect.TargetType.PAGE == "page"
    assert LaunchModalEffect.TargetType.RIGHT_CHART_PANE == "right_chart_pane"


def test_both_auth_mixins_are_importable_from_both_paths():
    """Both are real exports and both styles appear across this repo.

    Stubbing only one would make the suite silently depend on which import style
    the plugin happens to use.
    """
    assert security_module.StaffSessionAuthMixin is StaffSessionAuthMixin
    assert security_module.PatientSessionAuthMixin is PatientSessionAuthMixin


def test_the_two_auth_mixins_are_distinct():
    """The staff and portal surfaces must not be able to collapse into one class."""
    assert StaffSessionAuthMixin is not PatientSessionAuthMixin


def test_role_domain_carries_the_stored_code_not_the_member_name():
    """The permission query filters on ``domain__in`` with configured strings.

    ``str()`` of a real TextChoices member is its stored value, so a stub using
    "ADMINISTRATIVE" would pass every test here and match no row on the instance.
    """
    assert StaffRole.RoleDomain.ADMINISTRATIVE == "ADM"
    assert StaffRole.RoleDomain.CLINICAL == "CLI"
    assert StaffRole.RoleDomain.HYBRID == "HYB"


def test_application_badge_defaults_to_no_badge():
    """None means emit nothing; 0 is a real value that clears an existing badge."""

    class Bare(Application):
        def on_open(self):
            return []

    assert Bare(event=None, secrets={}).compute_notification_badge() is None


def test_action_button_location_is_available_and_stringy():
    assert ActionButton.ButtonLocation.CHART_PATIENT_HEADER == "chart_patient_header"


def test_action_button_visible_defaults_to_true_and_handle_is_abstract():
    class Bare(ActionButton):
        pass

    button = Bare(event=None, secrets={})
    assert button.visible() is True
    with pytest.raises(NotImplementedError):
        button.handle()


def test_json_response_keeps_its_data_and_status():
    response = JSONResponse({"a": 1}, status_code=418)
    assert response.data == {"a": 1}
    assert response.status_code == 418


def test_responses_accept_headers():
    """Omitting headers from the stub let a route that passes them fail only here."""
    assert Response(b"x", headers={"Cache-Control": "no-cache"}).headers["Cache-Control"]
    assert HTMLResponse("x", headers={"Cache-Control": "no-cache"}).headers["Cache-Control"]


def test_simple_api_carries_secrets_and_event():
    api = SimpleAPI(event="e", secrets={"k": "v"})
    assert api.event == "e"
    assert api.secrets == {"k": "v"}


def test_q_objects_compose_into_an_inspectable_tree():
    """The partial unique constraints carry a condition the schema tests read."""
    predicate = models.Q(a=1) | models.Q(b=2)
    assert predicate.connector == "OR"
    assert predicate.leaves() == [{"a": 1}, {"b": 2}]


def test_url_and_uuid_fields_are_not_available():
    """Neither is in the sandbox's django.db.models allowlist.

    Leaving them out of the stub means importing one fails here too, instead of
    passing the suite and stopping the plugin from loading on the instance.
    """
    assert not hasattr(models, "URLField")
    assert not hasattr(models, "UUIDField")


def test_each_plugin_model_has_its_own_manager():
    """Otherwise arranging one table's queryset silently arranges the other's."""
    from patient_resources.models import PatientResource, PatientResourceShare

    assert PatientResource.objects is not PatientResourceShare.objects
