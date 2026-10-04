"""Tests for the admin app and admin API: fail-closed access, status, and backfill."""

import json
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.conftest import make_patient
from patient_numbering.applications.numbering_admin import PatientNumberingAdmin
from patient_numbering.handlers.admin_api import BATCH_SIZE, PatientNumberingAdminAPI
from patient_numbering.models import PatientNumber
from patient_numbering.numbering import backfill_complete



def _api(admin_ids: str = "", staff_id: str = "") -> PatientNumberingAdminAPI:
    api = PatientNumberingAdminAPI.__new__(PatientNumberingAdminAPI)
    api.secrets = {"ADMIN_STAFF_IDS": admin_ids}
    api.request = SimpleNamespace(headers={"canvas-logged-in-user-id": staff_id})
    return api


def _admin() -> PatientNumberingAdminAPI:
    return _api(admin_ids="admin1, admin2", staff_id="admin2")


def _json(response: object) -> dict[str, object]:
    body: dict[str, object] = json.loads(response.content)  # type: ignore[attr-defined]
    return body


class TestAccess:
    def test_denies_when_admin_list_unset(self) -> None:
        assert _api(admin_ids="", staff_id="admin1")._is_admin() is False

    def test_denies_unlisted_staff(self) -> None:
        assert _api(admin_ids="admin1", staff_id="other")._is_admin() is False

    def test_allows_listed_staff(self) -> None:
        assert _admin()._is_admin() is True

    def test_status_forbidden_for_non_admin(self) -> None:
        assert _api().status()[0].status_code == HTTPStatus.FORBIDDEN

    def test_backfill_forbidden_for_non_admin(self) -> None:
        assert _api().backfill()[0].status_code == HTTPStatus.FORBIDDEN

    def test_admin_page_shows_notice_to_non_admin(self) -> None:
        with patch("patient_numbering.handlers.admin_api.render_to_string") as render:
            render.return_value = "<html>notice</html>"
            (response,) = _api().admin_page()
        assert response.status_code == HTTPStatus.OK
        render.assert_called_once_with("templates/admin.html", {"authorized": False})


@pytest.mark.django_db
class TestAdminRoutes:
    def test_admin_page_includes_status_for_admin(self) -> None:
        make_patient()
        with patch("patient_numbering.handlers.admin_api.render_to_string") as render:
            render.return_value = "<html></html>"
            _admin().admin_page()
        context = render.call_args.args[1]
        assert context == {
            "authorized": True,
            "patients": 1,
            "numbered": 0,
            "remaining": 1,
            "backfill_complete": False,
        }

    def test_status_reports_counts(self) -> None:
        make_patient()
        make_patient()
        assert _json(_admin().status()[0]) == {
            "patients": 2,
            "numbered": 0,
            "remaining": 2,
            "backfill_complete": False,
        }

    def test_backfill_numbers_in_creation_order_and_completes(self) -> None:
        patients = [make_patient() for _ in range(3)]
        with patch("patient_numbering.handlers.admin_api.number_effects") as effects:
            effects.side_effect = lambda key, number: [f"effect-{number}"]
            response, *returned = _admin().backfill()

        assert _json(response) == {
            "assigned": 3,
            "first": 1,
            "last": 3,
            "remaining": 0,
            "backfill_complete": True,
        }
        assert returned == ["effect-1", "effect-2", "effect-3"]
        numbers = {n.patient_id: n.number for n in PatientNumber.objects.all()}
        assert [numbers[p.dbid] for p in patients] == [1, 2, 3]
        assert backfill_complete() is True

    def test_backfill_stops_at_batch_size(self) -> None:
        for _ in range(BATCH_SIZE + 1):
            make_patient()
        with patch("patient_numbering.handlers.admin_api.number_effects", return_value=[]):
            body = _json(_admin().backfill()[0])
        assert (body["assigned"], body["remaining"], body["backfill_complete"]) == (
            BATCH_SIZE,
            1,
            False,
        )
        assert backfill_complete() is False

    def test_backfill_with_nothing_left(self) -> None:
        body = _json(_admin().backfill()[0])
        assert body == {
            "assigned": 0,
            "first": None,
            "last": None,
            "remaining": 0,
            "backfill_complete": True,
        }


class TestApplication:
    def test_on_open_launches_admin_page(self) -> None:
        app = PatientNumberingAdmin.__new__(PatientNumberingAdmin)
        effect = app.on_open()
        assert "/plugin-io/api/patient_numbering/admin?v=" in effect.payload
