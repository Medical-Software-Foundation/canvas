"""Coverage for read-only data endpoints: list_sets, providers, lab partners,
lab tests, CPT search, note-provider, UI/static routes."""
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest

from order_sets.api import endpoints
from order_sets.api.endpoints import OrderSetsAPI


def make_handler(query_params=None, headers=None, path_params=None):
    handler = OrderSetsAPI.__new__(OrderSetsAPI)
    handler.request = MagicMock()
    handler.request.query_params = query_params or {}
    handler.request.headers = headers or {}
    handler.request.path_params = path_params or {}
    return handler


def staff(id_="staff-1"):
    s = MagicMock()
    s.id = id_
    s.first_name = "Ada"
    s.last_name = "Lovelace"
    s.active = True
    s.top_role_abbreviation = "MD"
    return s


# ── list_sets ────────────────────────────────────────────────────────────────

class TestListSets:
    def test_returns_serialized_sets(self, monkeypatch):
        row1 = MagicMock(
            set_id="s-1", name="A", description="", order_type="lab",
            is_shared=True, created_by="x", created_by_name="X",
            diagnosis_codes=[], lab_partner="", lab_partner_name="",
            items=[], fasting_required=False, comment="",
            created_at=None, updated_at=None,
        )

        qs = MagicMock()
        qs.order_by.return_value = [row1]
        objects = MagicMock()
        objects.filter.return_value = qs
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = staff("u-1")
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(headers={"canvas-logged-in-user-id": "u-1"})
        [resp] = handler.list_sets()

        assert resp.status_code == HTTPStatus.OK
        assert isinstance(resp.body, list)
        assert resp.body[0]["id"] == "s-1"

    def test_db_error_propagates(self, monkeypatch):
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = staff("u-1")
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        objects = MagicMock()
        objects.filter.side_effect = RuntimeError("private detail")
        monkeypatch.setattr(endpoints.OrderSet, "objects", objects)

        handler = make_handler(headers={"canvas-logged-in-user-id": "u-1"})
        with pytest.raises(RuntimeError):
            handler.list_sets()

    def test_unauthorized_when_no_staff(self, monkeypatch):
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler()
        [resp] = handler.list_sets()
        assert resp.status_code == HTTPStatus.UNAUTHORIZED


# ── list_providers ───────────────────────────────────────────────────────────

class TestListProviders:
    def test_returns_active_providers_sorted(self, monkeypatch):
        provider_a = staff("p-1")
        provider_a.first_name = "Alice"
        provider_b = staff("p-2")
        provider_b.first_name = "Bob"

        qs = MagicMock()
        qs.distinct.return_value.order_by.return_value = [provider_a, provider_b]
        objects = MagicMock()
        objects.filter.return_value = qs
        monkeypatch.setattr(endpoints.Staff, "objects", objects)

        handler = make_handler()
        [resp] = handler.list_providers()

        assert resp.status_code == HTTPStatus.OK
        assert len(resp.body) == 2
        assert resp.body[0]["name"] == "Alice Lovelace"

    def test_exception_propagates(self, monkeypatch):
        objects = MagicMock()
        objects.filter.side_effect = RuntimeError("db error")
        monkeypatch.setattr(endpoints.Staff, "objects", objects)

        handler = make_handler()
        with pytest.raises(RuntimeError):
            handler.list_providers()


# ── list_lab_partners ────────────────────────────────────────────────────────

class TestListLabPartners:
    def test_returns_partner_list(self, monkeypatch):
        partner = MagicMock(id="lab-1", electronic_ordering_enabled=True)
        partner.name = "LabCorp"  # `name` is special on MagicMock; set explicitly
        objects = MagicMock()
        objects.all.return_value = [partner]
        monkeypatch.setattr(endpoints.LabPartner, "objects", objects)

        handler = make_handler()
        [resp] = handler.list_lab_partners()

        assert resp.status_code == HTTPStatus.OK
        assert resp.body[0]["name"] == "LabCorp"
        assert resp.body[0]["electronic_ordering"] is True

    def test_exception_propagates(self, monkeypatch):
        objects = MagicMock()
        objects.all.side_effect = RuntimeError("oh no")
        monkeypatch.setattr(endpoints.LabPartner, "objects", objects)

        handler = make_handler()
        with pytest.raises(RuntimeError):
            handler.list_lab_partners()


# ── list_lab_tests ───────────────────────────────────────────────────────────

class TestListLabTests:
    def _make_partner(self, tests):
        partner = MagicMock()
        available = MagicMock()
        available.all.return_value.filter.return_value.order_by.return_value = tests
        available.all.return_value.order_by.return_value = tests
        partner.available_tests = available
        return partner

    def test_returns_empty_when_partner_missing(self, monkeypatch):
        objects = MagicMock()
        objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.LabPartner, "objects", objects)

        handler = make_handler(path_params={"partner_id": "x"})
        [resp] = handler.list_lab_tests()
        assert resp.body == []

    def test_search_param_filters_tests(self, monkeypatch):
        test_row = MagicMock(order_code="CBC", order_name="Blood Count", cpt_code="85025")
        partner = self._make_partner([test_row])
        objects = MagicMock()
        objects.filter.return_value.first.return_value = partner
        monkeypatch.setattr(endpoints.LabPartner, "objects", objects)

        handler = make_handler(
            path_params={"partner_id": "lab-1"},
            query_params={"search": "blood"},
        )
        [resp] = handler.list_lab_tests()
        assert resp.body[0]["code"] == "CBC"

    def test_exception_propagates(self, monkeypatch):
        objects = MagicMock()
        objects.filter.side_effect = RuntimeError("boom")
        monkeypatch.setattr(endpoints.LabPartner, "objects", objects)

        handler = make_handler(path_params={"partner_id": "x"})
        with pytest.raises(RuntimeError):
            handler.list_lab_tests()


# ── cpt_search ───────────────────────────────────────────────────────────────

class TestCptSearch:
    def test_returns_empty_when_cdm_unavailable(self, monkeypatch):
        monkeypatch.setattr(endpoints, "ChargeDescriptionMaster", None)
        handler = make_handler()
        [resp] = handler.cpt_search()
        assert resp.body == []

    def test_with_query_filters_and_returns_codes(self, monkeypatch):
        cdm_row = MagicMock(cpt_code="87880", name="Rapid Strep")
        cdm = MagicMock()
        qs = MagicMock()
        qs.filter.return_value.order_by.return_value = [cdm_row]
        qs.order_by.return_value = [cdm_row]
        cdm.objects.all.return_value = qs
        monkeypatch.setattr(endpoints, "ChargeDescriptionMaster", cdm)

        handler = make_handler(query_params={"q": "strep"})
        [resp] = handler.cpt_search()
        assert resp.body[0]["code"] == "87880"

    def test_skips_rows_without_cpt_code(self, monkeypatch):
        good = MagicMock(cpt_code="99999", name="Good")
        bad = MagicMock(cpt_code="", name="Bad")
        cdm = MagicMock()
        cdm.objects.all.return_value.order_by.return_value = [good, bad]
        monkeypatch.setattr(endpoints, "ChargeDescriptionMaster", cdm)

        handler = make_handler()
        [resp] = handler.cpt_search()
        codes = [r["code"] for r in resp.body]
        assert "99999" in codes
        assert "" not in codes

    def test_exception_propagates(self, monkeypatch):
        cdm = MagicMock()
        cdm.objects.all.side_effect = RuntimeError("boom")
        monkeypatch.setattr(endpoints, "ChargeDescriptionMaster", cdm)

        handler = make_handler()
        with pytest.raises(RuntimeError):
            handler.cpt_search()


# ── get_note_provider ────────────────────────────────────────────────────────

class TestGetNoteProvider:
    def test_no_open_note_returns_nulls(self, monkeypatch):
        handler = make_handler(query_params={"patient_id": "p-1"})
        handler._find_open_note = lambda patient_id: (None, "")
        [resp] = handler.get_note_provider()
        assert resp.body["note_uuid"] is None
        assert resp.body["provider_id"] is None

    def test_returns_provider_when_active_provider(self, monkeypatch):
        s = staff("provider-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(query_params={"patient_id": "p-1"})
        handler._find_open_note = lambda patient_id: ("note-1", "provider-1")
        [resp] = handler.get_note_provider()
        assert resp.body["provider_id"] == "provider-1"
        assert resp.body["provider_name"] == "Ada Lovelace"

    def test_note_without_provider_returns_nulls(self):
        handler = make_handler(query_params={"patient_id": "p-1"})
        handler._find_open_note = lambda patient_id: ("note-1", "")
        [resp] = handler.get_note_provider()
        assert resp.body["note_uuid"] == "note-1"
        assert resp.body["provider_id"] is None

    def test_exception_propagates(self):
        handler = make_handler(query_params={"patient_id": "p-1"})

        def boom(_):
            raise RuntimeError("internal")

        handler._find_open_note = boom
        with pytest.raises(RuntimeError):
            handler.get_note_provider()


# ── UI + static endpoints (smoke tests) ──────────────────────────────────────

class TestUIRoutes:
    def test_get_ui_renders(self, monkeypatch):
        s = staff("u-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler(
            query_params={"patient_id": "p-1"},
            headers={"canvas-logged-in-user-id": "u-1"},
        )
        [resp] = handler.get_ui()
        assert resp.status_code == HTTPStatus.OK

    def test_get_admin_ui_renders(self, monkeypatch):
        s = staff("u-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = False
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(headers={"canvas-logged-in-user-id": "u-1"})
        [resp] = handler.get_admin_ui()
        assert resp.status_code == HTTPStatus.OK

    def test_get_admin_ui_passes_is_admin_context_var(self, monkeypatch):
        """The admin template needs is_admin to gate the Shared option.

        Verify the handler computes is_admin via the StaffRole admin lookup
        and passes it into render_to_string. Captures the context dict and
        asserts both branches.
        """
        # Spy on render_to_string to capture the context dict
        captured = {}

        def fake_render(template, context):
            captured["ctx"] = context
            return "<html></html>"

        monkeypatch.setattr(endpoints, "render_to_string", fake_render)

        s = staff("u-1")
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = s
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        # Admin case
        role_objects = MagicMock()
        role_objects.filter.return_value.exists.return_value = True
        monkeypatch.setattr(endpoints.StaffRole, "objects", role_objects)

        handler = make_handler(headers={"canvas-logged-in-user-id": "u-1"})
        handler.get_admin_ui()
        assert captured["ctx"]["is_admin"] is True

        # Non-admin case
        role_objects.filter.return_value.exists.return_value = False
        handler.get_admin_ui()
        assert captured["ctx"]["is_admin"] is False

    def test_get_admin_ui_anonymous_renders_empty_strings(self, monkeypatch):
        staff_objects = MagicMock()
        staff_objects.filter.return_value.first.return_value = None
        monkeypatch.setattr(endpoints.Staff, "objects", staff_objects)

        handler = make_handler()
        [resp] = handler.get_admin_ui()
        assert resp.status_code == HTTPStatus.OK

    def test_static_css(self):
        handler = make_handler()
        [resp] = handler.get_css()
        assert resp.status_code == HTTPStatus.OK

    def test_static_main_js(self):
        handler = make_handler()
        [resp] = handler.get_main_js()
        assert resp.status_code == HTTPStatus.OK

    def test_static_admin_js(self):
        handler = make_handler()
        [resp] = handler.get_admin_js()
        assert resp.status_code == HTTPStatus.OK
