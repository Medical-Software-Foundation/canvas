"""The Refer search handler, the API routes and the menu app."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.effects import EffectType
from django.template import Context, Engine

from preferred_referrals import CACHE_BUST
from preferred_referrals.applications.directory_app import PreferredReferralsApp
from preferred_referrals.directory import MAX_IMPORT_ROWS
from preferred_referrals.handlers.refer_search import PreferredFirstReferSearch
from preferred_referrals.routes import directory_api
from preferred_referrals.routes.directory_api import DirectoryAPI, _report_days

ADMIN = "4150cd20de8a470aa570a852859ac87e"
PROVIDER_ID = "d2194110-5c9a-4842-8733-ef09ea5ead11"


def _body(response):
    return json.loads(response.content)


# --- Refer search -------------------------------------------------------------


def _search(context):
    handler = PreferredFirstReferSearch.__new__(PreferredFirstReferSearch)
    handler.event = MagicMock(context=context)
    return handler.compute()


def test_no_match_returns_a_null_payload_not_an_empty_list():
    with patch(
        "preferred_referrals.handlers.refer_search.matching_preferred", return_value=[]
    ):
        effects = _search({"search_term": "zzz", "results": [{"text": "A"}]})
    assert len(effects) == 1
    assert json.loads(effects[0].payload) is None


def test_matches_are_merged_ahead_of_directory_results():
    provider = MagicMock()
    with (
        patch(
            "preferred_referrals.handlers.refer_search.matching_preferred",
            return_value=[provider],
        ) as matching,
        patch(
            "preferred_referrals.handlers.refer_search.merge_results",
            return_value=[{"text": "ours"}, {"text": "theirs"}],
        ) as merge,
    ):
        effects = _search({"search_term": " cardio ", "results": None})
    matching.assert_called_once_with("cardio")
    merge.assert_called_once_with([provider], [])
    assert json.loads(effects[0].payload) == [{"text": "ours"}, {"text": "theirs"}]


def test_non_preferred_directory_rows_for_the_same_specialty_stay_under_ours():
    """The real merge keeps every directory row it was given, under the preferred one.

    Guards the live question "did the plugin hide a non-preferred cardiology
    practice?": whatever the directory search returns is passed through.
    """
    provider = MagicMock()
    provider.as_search_result.return_value = {
        "text": "Preferred Cardiology - Cardiology",
        "value": 7,
        "annotations": ["Preferred"],
    }
    directory_rows = [
        {"text": "Bay Cardiology - Cardiology", "extra": {"contact": {"id": 1}}},
        {"text": "Harbor Heart - Cardiology", "extra": {}},
    ]
    with patch(
        "preferred_referrals.handlers.refer_search.matching_preferred",
        return_value=[provider],
    ):
        effects = _search({"search_term": "Cardiology", "results": directory_rows})
    texts = [row["text"] for row in json.loads(effects[0].payload)]
    assert texts == [
        "Preferred Cardiology - Cardiology",
        "Bay Cardiology - Cardiology",
        "Harbor Heart - Cardiology",
    ]


def test_missing_search_term_is_treated_as_empty():
    with patch(
        "preferred_referrals.handlers.refer_search.matching_preferred", return_value=[]
    ) as matching:
        _search({})
    matching.assert_called_once_with("")


# --- menu app -----------------------------------------------------------------


def test_app_opens_the_page_with_the_pinned_cache_bust():
    app = PreferredReferralsApp.__new__(PreferredReferralsApp)
    effect = app.on_open()
    payload = json.loads(effect.payload)
    assert f"/plugin-io/api/preferred_referrals/app/?v={CACHE_BUST}" in json.dumps(
        payload
    )


# --- API helpers ----------------------------------------------------------------


def _api(staff=ADMIN, admins=ADMIN, body=None, path_params=None, query=None):
    handler = DirectoryAPI.__new__(DirectoryAPI)
    handler.secrets = {"ADMIN_STAFF_IDS": admins}
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": staff} if staff is not None else {}
    if isinstance(body, Exception):
        request.json.side_effect = body
    else:
        request.json.return_value = body
    request.path_params = path_params or {}
    request.query_params = query or {}
    handler.request = request
    return handler


@pytest.mark.parametrize(
    ("staff", "admins", "expected"),
    [
        (ADMIN, ADMIN, True),
        ("4150cd20-de8a-470a-a570-a852859ac87e", ADMIN.upper(), True),
        (ADMIN, f"someone, {ADMIN} ,", True),
        ("other", ADMIN, False),
        (ADMIN, "", False),
        (ADMIN, None, False),
        ("", ADMIN, False),
        (None, ADMIN, False),
    ],
)
def test_admin_check_fails_closed(staff, admins, expected):
    assert _api(staff=staff, admins=admins)._is_admin() is expected


def test_request_without_headers_is_not_admin():
    handler = _api()
    handler.request.headers = None
    assert handler._is_admin() is False


@pytest.mark.parametrize(
    ("raw", "days"),
    [(None, 90), ("abc", 90), ("30", 30), ("0", 1), ("-5", 1), ("9999", 365)],
)
def test_report_days_are_clamped(raw, days):
    assert _report_days(raw) == days


# --- page -----------------------------------------------------------------------


def test_page_renders_with_admin_flag():
    with patch.object(
        directory_api, "render_to_string", return_value="<html>"
    ) as render:
        responses = _api().page()
    assert responses[0].content == b"<html>"
    template, context = render.call_args.args
    assert template == "templates/directory.html"
    assert context == {
        "cache_bust": CACHE_BUST,
        "is_admin": True,
        "max_import_rows": MAX_IMPORT_ROWS,
    }


TEMPLATE_DIR = Path(__file__).parent.parent / "preferred_referrals"


def _render_real(template, context):
    """Render the shipped template with Django's engine, as the plugin runner would."""
    source = (TEMPLATE_DIR / template).read_text()
    return Engine().from_string(source).render(Context(context))


def _real_page(**kwargs):
    with patch.object(directory_api, "render_to_string", side_effect=_render_real):
        return _api(**kwargs).page()[0].content.decode()


def test_page_template_renders_for_a_non_admin():
    """Render the real template so a template syntax error fails here, not on an instance."""
    html = _real_page(admins="")
    assert "Preferred referrals" in html
    assert 'id="csv"' not in html
    assert "var IS_ADMIN = false;" in html


def test_page_template_renders_the_import_form_for_an_admin():
    html = _real_page()
    assert 'id="csv"' in html
    assert "var IS_ADMIN = true;" in html
    assert f"var CHUNK = {MAX_IMPORT_ROWS};" in html


# --- list -----------------------------------------------------------------------


def _provider(dbid):
    provider = MagicMock()
    provider.dbid = dbid
    provider.id = f"id-{dbid}"
    provider.first_name = f"P{dbid}"
    provider.last_name = ""
    for field in (
        "practice_name",
        "specialty",
        "business_address",
        "business_phone",
        "business_fax",
        "npi",
    ):
        setattr(provider, field, "")
    provider.is_active = True
    return provider


def test_list_attaches_referral_counts_in_one_aggregate():
    providers = [_provider(1), _provider(2)]
    with (
        patch.object(directory_api, "preferred_providers") as preferred,
        patch.object(directory_api, "Referral") as referral,
    ):
        preferred.return_value.order_by.return_value.__getitem__.return_value = (
            providers
        )
        referral.objects.committed.return_value.filter.return_value.values.return_value.annotate.return_value = [
            {"service_provider_id": 2, "n": 7}
        ]
        body = _body(_api(admins="").list_providers()[0])

    assert [p["referrals"] for p in body["providers"]] == [0, 7]
    assert body["truncated"] is False
    assert body["is_admin"] is False
    referral.objects.committed.return_value.filter.assert_called_once_with(
        service_provider__is_customer_managed=True
    )


# --- import ---------------------------------------------------------------------


def test_import_needs_an_admin():
    response = _api(admins="").import_providers()[0]
    assert response.status_code == 403


@pytest.mark.parametrize(
    "body",
    [ValueError("bad json"), [], {"rows": []}, {"rows": "x"}, {}],
)
def test_import_rejects_bad_bodies(body):
    response = _api(body=body).import_providers()[0]
    assert response.status_code == 400


def test_import_caps_rows_per_request():
    response = _api(body={"rows": [{}] * (MAX_IMPORT_ROWS + 1)}).import_providers()[0]
    assert response.status_code == 400
    assert str(MAX_IMPORT_ROWS) in _body(response)["error"]


def test_import_returns_effects_then_a_summary():
    rows = [
        {
            "first_name": "Lakeside Cardiology",
            "specialty": "Cardiology",
            "business_address": "1 Main St",
        },
        {"first_name": "No specialty"},
    ]
    results = _api(body={"rows": rows}).import_providers()
    assert EffectType.Name(results[0].type) == "CREATE_SERVICE_PROVIDER"
    summary = _body(results[-1])
    assert summary["saved"] == 1
    assert summary["errors"][0]["row"] == 2


# --- activation -----------------------------------------------------------------


def test_activation_needs_an_admin():
    assert _api(admins="").deactivate()[0].status_code == 403
    assert _api(admins="").reactivate()[0].status_code == 403


def test_activation_rejects_a_malformed_id():
    assert _api(path_params={"provider_id": "nope"}).deactivate()[0].status_code == 404


def test_activation_refuses_providers_that_are_not_ours():
    with patch.object(directory_api, "preferred_providers") as preferred:
        preferred.return_value.filter.return_value.only.return_value.first.return_value = None
        response = _api(path_params={"provider_id": PROVIDER_ID}).deactivate()[0]
    assert response.status_code == 404
    preferred.return_value.filter.assert_called_once_with(id=PROVIDER_ID)


@pytest.mark.parametrize(
    ("method", "effect_type", "active"),
    [
        ("deactivate", "DEACTIVATE_SERVICE_PROVIDER", False),
        ("reactivate", "UPDATE_SERVICE_PROVIDER", True),
    ],
)
def test_activation_emits_the_matching_effect(method, effect_type, active):
    with (
        patch.object(directory_api, "preferred_providers") as preferred,
        patch("canvas_sdk.effects.service_provider.ServiceProviderModel") as model,
    ):
        preferred.return_value.filter.return_value.only.return_value.first.return_value = MagicMock()
        model.objects.filter.return_value.exists.return_value = True
        effect, response = getattr(
            _api(path_params={"provider_id": PROVIDER_ID}), method
        )()
    assert EffectType.Name(effect.type) == effect_type
    data = json.loads(effect.payload)["data"]
    assert data["id"] == PROVIDER_ID
    if active:
        assert data["is_active"] is True
    assert _body(response) == {"id": PROVIDER_ID, "is_active": active}


# --- report ---------------------------------------------------------------------


def _report(total, to_preferred, awaiting, rows):
    with patch.object(directory_api, "Referral") as referral:
        window = referral.objects.committed.return_value.filter.return_value
        preferred = MagicMock()
        awaiting_qs = MagicMock()

        def filter_side_effect(**kwargs):
            return (
                preferred
                if "service_provider__is_customer_managed" in kwargs
                else awaiting_qs
            )

        window.filter.side_effect = filter_side_effect
        window.count.return_value = total
        preferred.count.return_value = to_preferred
        awaiting_qs.count.return_value = awaiting
        preferred.values.return_value.annotate.return_value.order_by.return_value.__getitem__.return_value = rows
        body = _body(_api(query={"days": "30"}).report()[0])
        return body, referral


def test_report_counts_preferred_share_and_awaiting():
    body, referral = _report(
        10,
        4,
        3,
        [
            {
                "service_provider_id": 1,
                "service_provider__first_name": "Lakeside Cardiology",
                "service_provider__last_name": "",
                "service_provider__specialty": None,
                "n": 4,
            }
        ],
    )
    assert body["days"] == 30
    assert body["total"] == 10
    assert body["to_preferred"] == 4
    assert body["to_other"] == 6
    assert body["preferred_share"] == 0.4
    assert body["awaiting_report"] == 3
    assert body["by_provider"] == [
        {"name": "Lakeside Cardiology", "specialty": "", "referrals": 4}
    ]
    since = referral.objects.committed.return_value.filter.call_args.kwargs[
        "date_referred__gte"
    ]
    assert since.tzinfo is not None


def test_report_with_no_referrals_has_no_share():
    body, _ = _report(0, 0, 0, [])
    assert body["preferred_share"] is None
    assert body["by_provider"] == []
