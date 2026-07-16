"""Tests for patient_panel.api.panel_api.

Policy (per project rule):
    * canvas_sdk methods/classes are NEVER mocked or patched.
    * Database-touching tests use real factories from
      `canvas_sdk.test_utils.factories` and the real ORM.
    * Pure-helper tests use `build_api` from `tests._helpers` with real
      `secrets` dicts and a `FakeRequest` (a plain Python class).
    * External boundaries (HTTP via `canvas_sdk.utils.Http`, the FHIR API)
      are stubbed at the network boundary, NOT inside canvas_sdk.

Some tests in the previous version asserted on mock call signatures
(`Coverage.objects.filter was called with X`). Those have been replaced
with behavioral assertions on the real returned data, which is more
meaningful and exercises the actual ORM query.
"""

__is_plugin__ = True

from http import HTTPStatus
from unittest.mock import MagicMock, patch

import arrow
import pytest

from canvas_sdk.handlers.simple_api.security import StaffSessionAuthMixin
from canvas_sdk.test_utils.factories import (
    FacilityFactory,
    PatientFacilityAddressFactory,
    PatientFactory,
    StaffFactory,
    StaffPhotoFactory,
    TaskFactory,
)
from canvas_sdk.v1.data.care_team import (
    CareTeamMembership,
    CareTeamMembershipStatus,
    CareTeamRole,
)
from canvas_sdk.v1.data.patient import PatientMetadata as PatientMetadataRecord
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.staff import Staff

from api.panel_api import PatientPanelAPI

from tests._helpers import build_api, cache_delete, cache_set


pytestmark = pytest.mark.django_db


# ── Direct-ORM helpers for models without factories ───────────────────────

def _make_membership(patient: Patient, staff: Staff, role: CareTeamRole | None = None) -> CareTeamMembership:
    return CareTeamMembership.objects.create(
        patient=patient,
        staff=staff,
        role=role,
        status=CareTeamMembershipStatus.ACTIVE,
        lead=False,
        role_code=role.code if role else "",
        role_system=role.system if role else "",
        role_display=role.display if role else "",
    )


# ── Configuration / Auth ───────────────────────────────────────────────────

class TestPatientPanelAPIAuthentication:
    def test_api_uses_staff_session_auth(self) -> None:
        assert issubclass(PatientPanelAPI, StaffSessionAuthMixin)


class TestPatientPanelAPIConfiguration:
    def test_base_path(self) -> None:
        assert PatientPanelAPI.BASE_PATH == "/plugin-io/api/patient_panel"

    def test_prefix(self) -> None:
        assert PatientPanelAPI.PREFIX == "/app"

    def test_default_page_size(self) -> None:
        assert PatientPanelAPI.DEFAULT_PAGE_SIZE == 10

    def test_default_highlight_thresholds(self) -> None:
        assert PatientPanelAPI.DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_GREEN == 1
        assert PatientPanelAPI.DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_YELLOW == 3
        assert PatientPanelAPI.DEFAULT_HIGHLIGHT_THRESHOLD_DAYS_RED == 7


# ── Pure logic helpers ────────────────────────────────────────────────────

class TestRenderConfig:
    def test_defaults_when_empty(self) -> None:
        cfg = build_api()._render_config()
        assert cfg["page_size"] == 10
        assert cfg["highlight_green"] == 1
        assert cfg["highlight_yellow"] == 3
        assert cfg["highlight_red"] == 7

    def test_custom_values(self) -> None:
        api = build_api(secrets={
            "PAGE_SIZE": "25",
            "HIGHLIGHT_THRESHOLD_DAYS_GREEN": "2",
            "HIGHLIGHT_THRESHOLD_DAYS_YELLOW": "5",
            "HIGHLIGHT_THRESHOLD_DAYS_RED": "10",
        })
        cfg = api._render_config()
        assert cfg["page_size"] == 25
        assert cfg["highlight_green"] == 2
        assert cfg["highlight_yellow"] == 5
        assert cfg["highlight_red"] == 10

    def test_invalid_page_size_falls_back_to_default(self) -> None:
        cfg = build_api(secrets={"PAGE_SIZE": "invalid"})._render_config()
        assert cfg["page_size"] == 10

    def test_render_config_omits_raw_secret_keys(self) -> None:
        # Regression: _render_config() is a DERIVED dict (page_size, thresholds,
        # logos) — it does NOT carry raw secrets like METADATA_FIELDS. Anything
        # needing a raw secret (e.g. inline-edit enrichment) must use the RAW
        # self.secrets. Passing this dict made every cell render read-only.
        import json

        from patient_panel.services.columns import enrich_columns_for_render

        raw = {
            "METADATA_FIELDS": json.dumps([
                {"key": "risk_score", "type": "SELECT",
                 "options": ["Low", "High"], "editable": True}
            ])
        }
        api = build_api(secrets=raw)
        risk_col = [{"type": "metadata", "key": "risk_score"}]

        assert "METADATA_FIELDS" not in api._render_config()
        # Wrong source → no inline_edit (the bug).
        assert "inline_edit" not in enrich_columns_for_render(risk_col, api._render_config())[0]
        # Correct source → inline_edit present (the fix).
        assert enrich_columns_for_render(risk_col, api.secrets)[0]["inline_edit"] == {
            "type": "SELECT", "options": ["Low", "High"]
        }


class TestPageSize:
    def test_configured(self) -> None:
        assert build_api(secrets={"PAGE_SIZE": "25"})._page_size == 25

    def test_default_for_invalid(self) -> None:
        assert build_api(secrets={"PAGE_SIZE": "invalid"})._page_size == 10


# ── ORM-backed tests ──────────────────────────────────────────────────────

class TestCurrentLoggedStaff:
    def test_returns_name_dict(self) -> None:
        staff = StaffFactory.create(first_name="Dr.", last_name="Smith")
        api = build_api(headers={"canvas-logged-in-user-id": str(staff.id)})
        result = api._current_logged_staff
        assert result == {"first_name": "Dr.", "last_name": "Smith"}


class TestGetAllCareTeamMembers:
    def test_returns_list_with_initials_and_role(self) -> None:
        patient = PatientFactory.create()
        staff = StaffFactory.create(first_name="John", last_name="Doe")
        role = CareTeamRole.objects.create(
            code="nurse", display="Nurse", system="canvas", active=True,
        )
        _make_membership(patient, staff, role)
        result = build_api()._get_all_care_team_members(patient)
        assert len(result) == 1
        assert result[0]["initials"] == "JD"
        assert result[0]["role"] == "Nurse"

    def test_empty_when_no_members(self) -> None:
        patient = PatientFactory.create()
        assert build_api()._get_all_care_team_members(patient) == []

    def test_uses_staff_photo_url_when_present(self) -> None:
        patient = PatientFactory.create()
        staff = StaffFactory.create()
        # StaffFactory adds a default photo with url=""; replace it.
        staff.photos.all().delete()
        StaffPhotoFactory.create(staff=staff, url="https://cdn.example.com/foo.png")
        _make_membership(patient, staff)
        cache_delete(f"staff_photo_url_{staff.id}")
        result = build_api()._get_all_care_team_members(patient)
        urls = [m["photo_url"] for m in result]
        assert "https://cdn.example.com/foo.png" in urls, urls

    def test_falls_back_to_default_avatar(self) -> None:
        patient = PatientFactory.create()
        staff = StaffFactory.create()
        # StaffFactory creates a photo by default — remove it.
        staff.photos.all().delete()
        _make_membership(patient, staff)
        cache_delete(f"staff_photo_url_{staff.id}")
        result = build_api()._get_all_care_team_members(patient)
        assert result[0]["photo_url"] == PatientPanelAPI.DEFAULT_AVATAR


# ── FHIR token (HTTP boundary — stub the network) ─────────────────────────

class TestGetFhirToken:
    """`Http` is canvas_sdk's thin wrapper for outbound HTTP — patching it
    stubs the external network call, NOT a canvas_sdk domain method.
    """

    def test_missing_credentials_returns_none(self) -> None:
        assert build_api()._get_fhir_token() is None

    def test_success_returns_token(self) -> None:
        api = build_api(secrets={
            "FHIR_CLIENT_ID": "client-id",
            "FHIR_CLIENT_SECRET": "client-secret",
            "CANVAS_INSTANCE_URL": "https://test.canvasmedical.com",
        })
        PatientPanelAPI._fhir_token_cache = {}
        with patch("api.panel_api.Http") as mock_http_class:
            mock_http = MagicMock()
            mock_http_class.return_value = mock_http
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"access_token": "test-token"}
            mock_http.post.return_value = mock_response

            assert api._get_fhir_token() == "test-token"

    def test_error_response_returns_none(self) -> None:
        api = build_api(secrets={
            "FHIR_CLIENT_ID": "client-id",
            "FHIR_CLIENT_SECRET": "client-secret",
            "CANVAS_INSTANCE_URL": "https://test.canvasmedical.com",
        })
        PatientPanelAPI._fhir_token_cache = {}
        with patch("api.panel_api.Http") as mock_http_class:
            mock_http = MagicMock()
            mock_http_class.return_value = mock_http
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = "Unauthorized"
            mock_http.post.return_value = mock_response

            assert api._get_fhir_token() is None


# ── Endpoint smoke tests (real ORM, real templates) ───────────────────────

class TestStaticAndIndexEndpoints:
    def test_index_returns_ok(self) -> None:
        staff = StaffFactory.create()
        api = build_api(headers={"canvas-logged-in-user-id": str(staff.id)})
        result = api.index()
        assert result[0].status_code == HTTPStatus.OK

    def test_index_embeds_logged_in_staff_id(self) -> None:
        """The dashboard shell must carry the logged-in staff id so the
        frontend can scope persisted filter state per-user (so a shared
        workstation does not leak one user's filters into another's view)."""
        staff = StaffFactory.create()
        api = build_api(headers={"canvas-logged-in-user-id": str(staff.id)})
        html = api.index()[0].content.decode()
        assert f'data-staff-id="{staff.id}"' in html

    def test_get_css_returns_no_cache_header(self) -> None:
        result = build_api().get_css()
        assert result[0].status_code == 200
        assert result[0].headers["Cache-Control"] == "no-cache"

    def test_get_scripts_returns_no_cache_header(self) -> None:
        result = build_api().get_scripts()
        assert result[0].status_code == 200
        assert result[0].headers["Cache-Control"] == "no-cache"


class TestPatientAccordionEndpoints:
    """Each accordion endpoint loads the patient by id and renders a panel."""

    def _api_for_patient(self, patient_id: str) -> PatientPanelAPI:
        return build_api(path_params={"patient_id": patient_id})

    def test_get_tasks(self) -> None:
        patient = PatientFactory.create()
        result = self._api_for_patient(str(patient.id)).get_tasks()
        assert result[0].status_code == HTTPStatus.OK

    def test_get_gaps(self) -> None:
        patient = PatientFactory.create()
        result = self._api_for_patient(str(patient.id)).get_gaps()
        assert result[0].status_code == HTTPStatus.OK

    def test_get_conditions(self) -> None:
        patient = PatientFactory.create()
        result = self._api_for_patient(str(patient.id)).get_conditions()
        assert result[0].status_code == HTTPStatus.OK

    def test_get_medications(self) -> None:
        patient = PatientFactory.create()
        result = self._api_for_patient(str(patient.id)).get_medications()
        assert result[0].status_code == HTTPStatus.OK

    def test_get_allergies(self) -> None:
        patient = PatientFactory.create()
        result = self._api_for_patient(str(patient.id)).get_allergies()
        assert result[0].status_code == HTTPStatus.OK

    def test_get_referrals(self) -> None:
        patient = PatientFactory.create()
        result = self._api_for_patient(str(patient.id)).get_referrals()
        assert result[0].status_code == HTTPStatus.OK


class TestTaskCommentEndpoints:
    def test_get_task_comments(self) -> None:
        patient = PatientFactory.create()
        task = TaskFactory.create(patient=patient)
        api = build_api(path_params={"task_id": str(task.id)})
        result = api.get_task_comments()
        assert result[0].status_code == HTTPStatus.OK

    def test_post_task_comment_missing_content_returns_400(self) -> None:
        patient = PatientFactory.create()
        task = TaskFactory.create(patient=patient)
        api = build_api(path_params={"task_id": str(task.id)})
        result = api.post_task_comment()
        assert result[0].status_code == HTTPStatus.BAD_REQUEST

    def test_post_task_comment_with_content_succeeds(self) -> None:
        patient = PatientFactory.create()
        task = TaskFactory.create(patient=patient)
        staff = StaffFactory.create()
        api = build_api(
            path_params={"task_id": str(task.id)},
            headers={"canvas-logged-in-user-id": str(staff.id)},
            form_data={"comment_content": "Test comment"},
        )
        result = api.post_task_comment()
        # Two effects: an AddTaskComment effect + a re-render Response.
        assert any(getattr(r, "status_code", None) == HTTPStatus.OK for r in result)


class TestClinicalNoteEndpoints:
    def test_get_clinical_notes_edit(self) -> None:
        patient = PatientFactory.create()
        api = build_api(path_params={"patient_id": str(patient.id)})
        result = api.get_clinical_notes()
        assert result[0].status_code == HTTPStatus.OK

    def test_save_clinical_notes(self) -> None:
        patient = PatientFactory.create()
        api = build_api(
            path_params={"patient_id": str(patient.id)},
            form_data={"clinical_note": "New clinical note"},
        )
        result = api.save_clinical_notes()
        assert len(result) == 2

    def test_save_clinical_notes_empty_clears(self) -> None:
        patient = PatientFactory.create()
        api = build_api(path_params={"patient_id": str(patient.id)})
        result = api.save_clinical_notes()
        assert len(result) == 2

    def test_view_clinical_notes(self) -> None:
        patient = PatientFactory.create()
        api = build_api(path_params={"patient_id": str(patient.id)})
        result = api.view_clinical_notes()
        assert result[0].status_code == HTTPStatus.OK


class TestGetPatientPhotoEndpoint:
    def test_no_token_redirects_to_default_avatar(self) -> None:
        patient = PatientFactory.create()
        pid = str(patient.id)
        api = build_api(path_params={"patient_id": pid})
        cache_delete(f"patient_photo_{pid}")
        result = api.get_patient_photo()
        assert result[0].status_code == 302
        assert "Location" in result[0].headers

    def test_cached_photo_served_without_fhir_call(self) -> None:
        patient = PatientFactory.create()
        pid = str(patient.id)
        cache_set(
            f"patient_photo_{pid}",
            {"content_type": "image/jpeg", "data": b"cached-bytes"},
        )
        api = build_api(path_params={"patient_id": pid})
        result = api.get_patient_photo()
        assert result[0].status_code == 200
        assert result[0].content == b"cached-bytes"


class TestFlagEndpoints:
    def test_set_flag_creates_metadata(self) -> None:
        patient = PatientFactory.create()
        api = build_api(
            path_params={"patient_id": str(patient.id)},
            form_data={"color": "red"},
        )
        result = api.set_flag()
        assert len(result) >= 1

    def test_clear_all_flags(self) -> None:
        # Seed a flag on a fresh patient
        patient = PatientFactory.create()
        today = arrow.now().format("YYYY-MM-DD")
        PatientMetadataRecord.objects.create(
            patient=patient, key="daily_flag", value=f"{today}:red",
        )
        result = build_api().clear_all_flags()
        # Returns at least one effect (clearing the flag)
        assert isinstance(result, list)


class TestGetTableEndpoint:
    """Smoke tests against the real ORM. The endpoint runs the full panel
    pipeline (filter -> sort -> paginate -> render) end-to-end.
    """

    def _api(self, **query: str | int) -> PatientPanelAPI:
        query.setdefault("page", "1")
        staff = StaffFactory.create()
        return build_api(
            query_params={k: str(v) for k, v in query.items()},
            headers={"canvas-logged-in-user-id": str(staff.id)},
        )

    def test_basic_table_renders(self) -> None:
        result = self._api().get_table()
        assert result[0].status_code == HTTPStatus.OK

    def test_with_patient_search(self) -> None:
        PatientFactory.create(first_name="John", last_name="Doe")
        result = self._api(patient_search="John").get_table()
        assert result[0].status_code == HTTPStatus.OK

    def test_with_facility_filter(self) -> None:
        # The frontend dropdown sends the Facility UUID (Facility.id), not the
        # integer dbid. Filtering must traverse the FK to the UUID.
        facility = FacilityFactory.create()
        patient = PatientFactory.create()
        PatientFacilityAddressFactory.create(patient=patient, facility=facility)
        result = self._api(facility_ids=str(facility.id)).get_table()
        assert result[0].status_code == HTTPStatus.OK
        assert str(patient.id) in result[0].content.decode()

    def test_with_sort_by_patient(self) -> None:
        PatientFactory.create_batch(3)
        result = self._api(sort_by="patient", sort_dir="asc").get_table()
        assert result[0].status_code == HTTPStatus.OK

    def test_with_sort_by_last_visit(self) -> None:
        result = self._api(sort_by="last_visit", sort_dir="desc").get_table()
        assert result[0].status_code == HTTPStatus.OK

    def test_with_pagination_page_size(self) -> None:
        PatientFactory.create_batch(5)
        result = self._api(page="1", page_size="2").get_table()
        assert result[0].status_code == HTTPStatus.OK

    def test_no_auto_filter_flag_respected(self) -> None:
        result = self._api(no_auto_filter="1").get_table()
        assert result[0].status_code == HTTPStatus.OK

    def test_count_query_does_not_evaluate_column_subqueries(self) -> None:
        """Regression: the total-count query must not embed the per-column
        correlated subqueries (facility/tasks/gaps/conditions/...). A
        `.distinct()` over the annotated queryset forces all of them to run
        across the entire patient population, which made /table take >10s.
        The count must collapse to a single cheap COUNT(*).
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        PatientFactory.create_batch(3)
        api = self._api(no_auto_filter="1")
        with CaptureQueriesContext(connection) as ctx:
            result = api.get_table()
        assert result[0].status_code == HTTPStatus.OK

        count_queries = [
            q["sql"] for q in ctx.captured_queries if "COUNT(*)" in q["sql"].upper()
        ]
        assert count_queries, "expected a COUNT(*) query for pagination total"
        # The cheap form is `SELECT COUNT(*) ... FROM patient`; the pathological
        # form wraps a `SELECT DISTINCT <38 cols + 11 subqueries>`.
        for sql in count_queries:
            assert sql.upper().count("SELECT") == 1, (
                f"count query embeds correlated subqueries (got "
                f"{sql.upper().count('SELECT')} SELECTs): {sql[:300]}"
            )

    def test_filters_do_not_duplicate_rows_without_distinct(self) -> None:
        """Safety net for dropping `.distinct()`: a patient with multiple
        active care-team memberships must still appear exactly once when
        filtered by staff.
        """
        from patient_panel.services.patient_query import (
            apply_patient_filters,
            build_base_queryset,
        )

        staff = StaffFactory.create()
        patient = PatientFactory.create()
        PatientFactory.create_batch(2)  # noise
        _make_membership(patient, staff)
        _make_membership(patient, staff)  # second active membership

        qs = apply_patient_filters(
            build_base_queryset(), staff_ids=[str(staff.id)]
        )
        ids = [p.id for p in qs]
        assert ids.count(patient.id) == 1
        assert len(ids) == 1

