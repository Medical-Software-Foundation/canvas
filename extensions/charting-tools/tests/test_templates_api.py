import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest

from charting_tools.api.templates_api import NoteTemplatesAPI, validate_payload
from tests.conftest import make_request, make_template

MODULE = "charting_tools.api.templates_api"


def _api(request: MagicMock, secrets: dict | None = None) -> NoteTemplatesAPI:
    api = object.__new__(NoteTemplatesAPI)
    api.request = request
    api.secrets = secrets or {}
    api.environment = {}
    return api


def _body(response: Any) -> dict:
    return json.loads(response.content)


@pytest.fixture
def admin(mocker: MagicMock) -> MagicMock:
    return mocker.patch(f"{MODULE}.staff_can_manage_templates", return_value=True)


@pytest.fixture
def not_admin(mocker: MagicMock) -> MagicMock:
    return mocker.patch(f"{MODULE}.staff_can_manage_templates", return_value=False)


class TestValidatePayload:
    def test_valid_payload_is_normalized(self) -> None:
        fields, error = validate_payload(
            {
                "name": "  Annual visit ",
                "commands": [
                    {"schema_key": "hpi", "carry_forward": True, "scribe_prompt": " onset "},
                    {"schema_key": "prescribe", "carry_forward": True},
                ],
            }
        )
        assert error is None
        assert fields == {
            "kind": "template",
            "name": "Annual visit",
            "active": True,
            "show_in_menu": True,
            "show_in_panel": False,
            "note_types": [],
            "diagnosis_sources": [],
            "tags": [],
            "commands": [
                {"schema_key": "hpi", "carry_forward": True, "scribe_prompt": "onset"},
                # prescribe has no carry-forward mapper, so the flag is dropped
                {"schema_key": "prescribe", "carry_forward": False, "scribe_prompt": ""},
            ],
        }

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ([], "Body must be a JSON object"),
            ({"name": " ", "commands": [{"schema_key": "hpi"}]}, "Note template name is required"),
            ({"name": "x" * 81, "commands": [{"schema_key": "hpi"}]}, "80 characters"),
            ({"name": "A", "commands": []}, "Add at least one command"),
            ({"name": "A", "commands": [{"schema_key": "hpi"}] * 31}, "at most 30"),
            ({"name": "A", "commands": ["hpi"]}, "Command 1 is malformed"),
            ({"name": "A", "commands": [{"schema_key": "customCommand"}]}, "unsupported type"),
            ({"name": "A", "commands": [{"schema_key": "hpi", "scribe_prompt": "x" * 2001}]}, "2000"),
        ],
    )
    def test_invalid_payloads(self, body: Any, message: str) -> None:
        fields, error = validate_payload(body)
        assert fields is None
        assert error is not None and message in error

    def test_questionnaire_commands_require_a_questionnaire(self) -> None:
        fields, error = validate_payload({"name": "A", "commands": [{"schema_key": "ros"}]})
        assert fields is None
        assert error == "Command 1 needs a questionnaire"

    def test_questionnaire_choice_is_stored_by_code(self) -> None:
        fields, error = validate_payload(
            {
                "name": "A",
                "commands": [
                    {
                        "schema_key": "questionnaire",
                        "questionnaire": {"code_system": "LOINC", "code": "69737-5", "name": "GAD-7", "id": "x"},
                    }
                ],
            }
        )
        assert error is None
        assert fields is not None
        assert fields["commands"][0]["questionnaire"] == {
            "code_system": "LOINC",
            "code": "69737-5",
            "name": "GAD-7",
        }

    def test_active_false_is_kept(self) -> None:
        fields, _ = validate_payload({"name": "A", "active": False, "commands": [{"schema_key": "hpi"}]})
        assert fields is not None and fields["active"] is False


class TestUsage:
    def test_needs_menu_or_note_types(self) -> None:
        fields, error = validate_payload(
            {"name": "A", "show_in_menu": False, "note_types": [], "commands": [{"schema_key": "hpi"}]}
        )
        assert fields is None
        assert error is not None and "new notes of a type" in error

    def test_note_types_deduplicated(self) -> None:
        fields, _ = validate_payload(
            {
                "name": "A",
                "show_in_menu": False,
                "note_types": [{"unique_identifier": "u1", "name": "Office"}, {"unique_identifier": "u1"}],
                "commands": [{"schema_key": "hpi"}],
            }
        )
        assert fields is not None
        assert fields["note_types"] == [{"unique_identifier": "u1", "name": "Office"}]

    def test_note_type_without_identifier_rejected(self) -> None:
        fields, error = validate_payload(
            {"name": "A", "note_types": [{"name": "Office"}], "commands": [{"schema_key": "hpi"}]}
        )
        assert fields is None and error == "Each note type needs a unique_identifier"

    def _body(self, **extra: Any) -> dict:
        return {
            "name": "A",
            "commands": [{"schema_key": "hpi"}],
            "note_types": [{"unique_identifier": "u1", "name": "Office visit"}],
            **extra,
        }

    def test_note_type_already_used_conflicts(self, admin: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(f"{MODULE}.note_type_options", return_value=[{"unique_identifier": "u1", "name": "Office visit"}])
        query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        query.return_value = [make_template(name="Annual", note_types=[{"unique_identifier": "u1", "name": "Office visit"}])]
        [response] = _api(make_request(self._body())).create_template()
        assert response.status_code == HTTPStatus.CONFLICT
        assert _body(response)["error"] == "'Office visit' is already assigned to template 'Annual'"

    def test_inactive_note_type_rejected(self, admin: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(f"{MODULE}.note_type_options", return_value=[])
        [response] = _api(make_request(self._body())).create_template()
        assert response.status_code == HTTPStatus.CONFLICT
        assert _body(response)["error"] == "Note type 'Office visit' is not active"

    def test_update_ignores_its_own_note_types(self, admin: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(f"{MODULE}.note_type_options", return_value=[{"unique_identifier": "u1", "name": "Office visit"}])
        template = make_template(template_id="t1", note_types=[{"unique_identifier": "u1"}])
        template.save = MagicMock()
        query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        query.return_value.first.return_value = template
        query.return_value.exclude.return_value = MagicMock(__iter__=lambda s: iter([]), exists=lambda: False)

        request = make_request(self._body(show_in_menu=False), path_params={"template_id": "t1"})
        [response] = _api(request).update_template()

        assert response.status_code == HTTPStatus.OK
        assert template.show_in_menu is False
        assert template.note_types == [{"unique_identifier": "u1", "name": "Office visit"}]

    def test_inactive_template_skips_conflict_check(self, admin: MagicMock, mocker: MagicMock) -> None:
        problem = mocker.patch(f"{MODULE}.note_type_problem")
        model = mocker.patch(f"{MODULE}.NoteTemplate")
        model.objects.filter.return_value.exists.return_value = False
        model.return_value = make_template()
        model.return_value.save = MagicMock()
        [response] = _api(make_request(self._body(active=False))).create_template()
        assert response.status_code == HTTPStatus.CREATED
        problem.assert_not_called()


class TestAccess:
    @pytest.mark.parametrize(
        "method", ["config", "list_templates", "create_template", "update_template", "delete_template"]
    )
    def test_json_endpoints_forbid_non_admins(self, not_admin: MagicMock, method: str) -> None:
        [response] = getattr(_api(make_request({})), method)()
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_admin_page_shows_notice_to_non_admins(self, not_admin: MagicMock, mocker: MagicMock) -> None:
        render = mocker.patch(f"{MODULE}.render_to_string", return_value="<p>notice</p>")
        [response] = _api(make_request()).admin_page()
        assert response.status_code == HTTPStatus.FORBIDDEN
        render.assert_called_with(
            "templates/forbidden.html", {"setting_name": "TEMPLATE_ADMIN_ROLES", "styles_version": mocker.ANY}
        )

    def test_admin_page_serves_builder_to_admins(self, admin: MagicMock, mocker: MagicMock) -> None:
        render = mocker.patch(f"{MODULE}.render_to_string", return_value="<p>builder</p>")
        [response] = _api(make_request()).admin_page()
        assert response.status_code == HTTPStatus.OK
        render.assert_called_with("templates/admin.html", {"styles_version": mocker.ANY})

    def test_stylesheet_url_changes_with_its_contents(self, mocker: MagicMock) -> None:
        # A new install's styles load at once rather than after the browser cache expires.
        from charting_tools.api.templates_api import styles_version

        render = mocker.patch(f"{MODULE}.render_to_string", return_value=".a{color:red}")
        first = styles_version()
        render.return_value = ".a{color:blue}"
        assert styles_version() != first and len(first) == 12

    def test_admin_check_uses_logged_in_staff(self, not_admin: MagicMock) -> None:
        _api(make_request(), secrets={"TEMPLATE_ADMIN_ROLES": "ADMIN"}).list_templates()
        not_admin.assert_called_once_with("staff1", {"TEMPLATE_ADMIN_ROLES": "ADMIN"})


class TestConfig:
    def test_returns_catalog_and_scribe_flag(self, admin: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(f"{MODULE}.options_by_command", return_value={"ros": [{"name": "ROS"}]})
        [response] = _api(make_request(), secrets={"SCRIBE_ENABLED": "true"}).config()
        body = _body(response)
        assert body["scribe_enabled"] is True
        by_key = {c["schema_key"]: c for c in body["commands"]}
        assert by_key["hpi"] == {
            "schema_key": "hpi",
            "label": "History of present illness",
            "carry_forward_supported": True,
            "questionnaire_use_case": None,
            "section": "subjective",
            "form": [],
        }
        assert by_key["exam"]["questionnaire_use_case"] == "EXAM"
        assert body["questionnaires"] == {"ros": [{"name": "ROS"}]}
        assert by_key["prescribe"]["carry_forward_supported"] is False
        assert "customCommand" not in by_key


class TestCreate:
    def test_creates_template(self, admin: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(f"{MODULE}.NoteTemplate.objects.filter").return_value.exists.return_value = False
        model = mocker.patch(f"{MODULE}.NoteTemplate")
        model.objects.filter.return_value.exists.return_value = False
        model.return_value = make_template(template_id="new", name="Annual visit", commands=[])
        model.return_value.save = MagicMock()

        request = make_request({"name": "Annual visit", "commands": [{"schema_key": "hpi"}]})
        [response] = _api(request).create_template()

        assert response.status_code == HTTPStatus.CREATED
        kwargs = model.call_args.kwargs
        assert kwargs["name"] == "Annual visit"
        assert kwargs["created_by"] == "staff1"
        assert len(kwargs["template_id"]) == 32
        model.return_value.save.assert_called_once()

    def test_duplicate_name_conflicts(self, admin: MagicMock, mocker: MagicMock) -> None:
        query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        query.return_value.exists.return_value = True
        request = make_request({"name": "Annual visit", "commands": [{"schema_key": "hpi"}]})
        [response] = _api(request).create_template()
        assert response.status_code == HTTPStatus.CONFLICT
        query.assert_called_once_with(name__iexact="Annual visit")

    def test_inactive_questionnaire_is_rejected(self, admin: MagicMock, mocker: MagicMock) -> None:
        resolve = mocker.patch(f"{MODULE}.resolve", return_value={})
        request = make_request(
            {
                "name": "A",
                "commands": [
                    {"schema_key": "exam", "questionnaire": {"code_system": "S", "code": "E1", "name": "Full exam"}}
                ],
            }
        )
        [response] = _api(request).create_template()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _body(response)["error"] == "Command 1: questionnaire 'Full exam' is not active"
        resolve.assert_called_once_with({("EXAM", "S", "E1")})

    def test_bad_json(self, admin: MagicMock) -> None:
        [response] = _api(make_request(ValueError("bad"))).create_template()
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_body(self, admin: MagicMock) -> None:
        [response] = _api(make_request({"name": "A", "commands": []})).create_template()
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _body(response)["error"] == "Add at least one command"


class TestUpdateDelete:
    def test_update_replaces_fields(self, admin: MagicMock, mocker: MagicMock) -> None:
        template = make_template(template_id="t1", name="Old")
        template.save = MagicMock()
        query = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        query.return_value.first.return_value = template
        query.return_value.exclude.return_value.exists.return_value = False

        request = make_request(
            {"name": "New", "active": False, "commands": [{"schema_key": "plan"}]},
            path_params={"template_id": "t1"},
        )
        [response] = _api(request).update_template()

        assert response.status_code == HTTPStatus.OK
        assert template.name == "New"
        assert template.active is False
        assert template.commands == [{"schema_key": "plan", "carry_forward": False, "scribe_prompt": ""}]
        assert template.updated_by == "staff1"
        template.save.assert_called_once()
        query.return_value.exclude.assert_called_once_with(template_id="t1")

    def test_update_missing_template(self, admin: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(f"{MODULE}.NoteTemplate.objects.filter").return_value.first.return_value = None
        request = make_request({"name": "A", "commands": [{"schema_key": "hpi"}]}, {"template_id": "x"})
        [response] = _api(request).update_template()
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_delete(self, admin: MagicMock, mocker: MagicMock) -> None:
        template = make_template()
        template.delete = MagicMock()
        mocker.patch(f"{MODULE}.NoteTemplate.objects.filter").return_value.first.return_value = template
        [response] = _api(make_request(path_params={"template_id": "tmpl1"})).delete_template()
        assert response.status_code == HTTPStatus.OK
        template.delete.assert_called_once()

    def test_delete_missing_template(self, admin: MagicMock, mocker: MagicMock) -> None:
        mocker.patch(f"{MODULE}.NoteTemplate.objects.filter").return_value.first.return_value = None
        [response] = _api(make_request(path_params={"template_id": "x"})).delete_template()
        assert response.status_code == HTTPStatus.NOT_FOUND


class TestStyles:
    @pytest.mark.parametrize(
        ("method", "template"),
        [
            ("semantic_css", "templates/static/semantic.min.css"),
            ("overrides_css", "templates/static/canvas-overrides.css"),
        ],
    )
    def test_serves_css_to_any_staff(
        self, not_admin: MagicMock, mocker: MagicMock, method: str, template: str
    ) -> None:
        render = mocker.patch(f"{MODULE}.render_to_string", return_value=".ui{}")
        [response] = getattr(_api(make_request()), method)()
        assert response.status_code == HTTPStatus.OK
        assert response.content == b".ui{}"
        assert response.headers["Content-Type"] == "text/css"
        render.assert_called_once_with(template)
        not_admin.assert_not_called()


def test_filter_tags_are_cleaned_and_only_for_quickpicks_and_order_sets() -> None:
    from charting_tools.api.templates_api import clean_tags

    assert clean_tags(["  Annual   visit ", "annual visit", "", "HF clinic", None, "x" * 60]) == [
        "Annual visit", "HF clinic", "x" * 40
    ]
    assert clean_tags("Annual") == []
    fields, _ = validate_payload({"kind": "quickpick", "name": "A", "show_in_panel": True,
                                  "commands": [{"schema_key": "plan"}], "tags": ["Peds"]})
    assert fields is not None and fields["tags"] == ["Peds"]
    fields, _ = validate_payload({"name": "A", "commands": [{"schema_key": "plan"}], "tags": ["Peds"]})
    assert fields is not None and fields["tags"] == []


class TestCrossSiteChanges:
    """Another site can submit a form as a logged-in admin; only JSON changes are accepted."""

    @pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None])
    @pytest.mark.parametrize("route", ["create_template", "update_template", "delete_template"])
    def test_non_json_changes_are_refused(
        self, admin: MagicMock, mocker: MagicMock, route: str, content_type: str | None
    ) -> None:
        save = mocker.patch(f"{MODULE}.NoteTemplate.objects.create")
        lookup = mocker.patch(f"{MODULE}.NoteTemplate.objects.filter")
        request = make_request({"name": "Planted rule", "commands": [{"schema_key": "plan"}]}, {"template_id": "t1"})
        request.content_type = content_type
        [response] = getattr(_api(request), route)()
        assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        save.assert_not_called()
        lookup.assert_not_called()

    def test_non_admins_are_refused_before_the_content_check(self, not_admin: MagicMock) -> None:
        request = make_request({})
        request.content_type = "text/plain"
        [response] = _api(request).create_template()
        assert response.status_code == HTTPStatus.FORBIDDEN


def test_dme_product_search_matches_code_then_name(admin: MagicMock, mocker: MagicMock) -> None:
    from types import SimpleNamespace

    from charting_tools.api.search_api import SearchAPI

    walker = SimpleNamespace(id="7c9e6679-7425-40de-944b-e07fc1f90ae7", code="E0143", code_system="HCPCS", name="Walker")
    cane = SimpleNamespace(id="8d0e6679-7425-40de-944b-e07fc1f90ae8", code="E0100", code_system="HCPCS", name="Cane, walker style")
    active = mocker.patch("charting_tools.api.search_api.DmeProduct.objects.filter")
    by = {"code__istartswith": [walker], "name__icontains": [walker, cane]}
    active.return_value.filter.side_effect = lambda **kw: MagicMock(
        order_by=MagicMock(return_value=MagicMock(__getitem__=lambda self, k: by[next(iter(kw))])))
    mocker.patch("charting_tools.api.search_api.staff_can_manage_templates", return_value=True)
    api = object.__new__(SearchAPI)
    api.request = make_request()
    api.request.query_params = {"q": "E01"}
    api.secrets, api.environment = {}, {}
    [response] = api.dme_products()
    rows = json.loads(response.content)["results"]
    assert [r["code"] for r in rows] == ["E0143", "E0100"]  # code matches first, no repeats
    assert rows[0]["display"] == "Walker (E0143)"
    assert active.call_args.kwargs == {"active": True}


class TestSendToSearch:
    """Directory providers first, then Science contacts the way home-app filters them."""

    def _api(self, mocker: MagicMock, query: str = "smith", kind: str = "refer") -> Any:
        from charting_tools.api.search_api import SearchAPI

        mocker.patch("charting_tools.api.search_api.staff_can_manage_templates", return_value=True)
        api = object.__new__(SearchAPI)
        api.request = make_request()
        api.request.query_params = {"q": query, "for": kind}
        api.secrets, api.environment = {}, {}
        return api

    def _directory(self, mocker: MagicMock, providers: list) -> None:
        from types import SimpleNamespace

        rows = [dict(first_name=p[0], last_name=p[1], practice_name="", specialty=p[2], business_phone="",
                     business_fax="", business_address="", science_contact_id=p[3]) for p in providers]
        self.directory = mocker.patch("charting_tools.api.search_api.ServiceProvider.objects.filter")
        self.directory.return_value.order_by.return_value.values.return_value.__getitem__.return_value = rows

    def _zips(self, mocker: MagicMock, zips: list | None) -> None:
        mocker.patch("charting_tools.api.search_api.Staff.objects.filter").return_value.values_list.return_value.first.return_value = 5
        mocker.patch(
            "charting_tools.api.search_api.PracticeLocationSetting.objects.filter"
        ).return_value.values_list.return_value.first.return_value = zips

    def _science(self, mocker: MagicMock, rows: list) -> MagicMock:
        science = mocker.patch("charting_tools.api.search_api.science_http.get_json")
        science.return_value.json.return_value = {"results": rows}
        return science

    def test_directory_comes_first_then_science_without_repeats(self, mocker: MagicMock) -> None:
        self._directory(mocker, [("Ann", "Smith", "Nephrology", 42)])
        self._zips(mocker, ["78701", "78702"])
        science = self._science(mocker, [
            {"id": 42, "firstName": "Ann", "lastName": "Smith", "specialty": "Nephrology"},  # already in the directory
            {"id": 7, "firstName": "Bo", "lastName": "Smithers", "specialty": "Cardiology"},
        ])
        [response] = self._api(mocker).contact()
        rows = json.loads(response.content)["results"]
        assert [(r["last_name"], r["source"]) for r in rows] == [("Smith", "directory"), ("Smithers", "science")]
        url = science.call_args.args[0]
        assert "business_postal_code__in=78701%2C78702" in url and "job_title" not in url
        # One directory query covers every field, active customer-managed only.
        self.directory.assert_called_once()
        kwargs = self.directory.call_args.kwargs
        assert kwargs == {"is_active": True, "is_customer_managed": True}
        matching = str(self.directory.call_args.args[0])
        assert all(f"{field}__icontains" in matching for field in ("last_name", "first_name", "practice_name", "specialty"))

    def test_imaging_searches_radiology_contacts(self, mocker: MagicMock) -> None:
        self._directory(mocker, [])
        self._zips(mocker, None)
        science = self._science(mocker, [])
        self._api(mocker, kind="imaging").contact()
        url = science.call_args.args[0]
        assert "job_title__icontains=radiology" in url and "business_postal_code" not in url

    def test_science_down_still_returns_the_directory(self, mocker: MagicMock) -> None:
        self._directory(mocker, [("Ann", "Smith", "Nephrology", None)])
        self._zips(mocker, [])
        mocker.patch("charting_tools.api.search_api.science_http.get_json", side_effect=OSError("down"))
        [response] = self._api(mocker).contact()
        assert [r["last_name"] for r in json.loads(response.content)["results"]] == ["Smith"]
