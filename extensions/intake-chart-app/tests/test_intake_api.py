"""Tests for the IntakeAPI route handlers and module-level helpers.

The route methods read from ``self.request`` (query params, headers,
body) and ``self.secrets`` — both wired by the SDK at request time. We
build IntakeAPI instances via ``object.__new__`` so the runtime base-class
plumbing is bypassed; the test injects a ``SimpleNamespace``-shaped
request and a dict for secrets.
"""
from __future__ import annotations

import json
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from intake_chart_app.api import intake_api
from intake_chart_app.api.intake_api import (
    IntakeAPI,
    _cached_static,
    _json,
    _looks_like_uuid,
    _note_exists,
    _post_section_review,
    _summarize_effects,
)


def _json_body(resp):
    """Decode a JSONResponse body for assertion. Routes return
    ``[resp]``; the test usually unpacks before passing here."""
    return json.loads(resp.content)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_json_wraps_body_with_default_status():
    resp = _json({"ok": True})
    # JSONResponse exposes status_code; just verify we got 200 back.
    assert getattr(resp, "status_code", 200) in (200, HTTPStatus.OK)


def test_json_passes_through_explicit_status():
    resp = _json({"ok": False}, status=HTTPStatus.BAD_REQUEST)
    assert getattr(resp, "status_code", 0) == HTTPStatus.BAD_REQUEST


def test_looks_like_uuid_accepts_valid_uuid():
    assert _looks_like_uuid("550e8400-e29b-41d4-a716-446655440000") is True


def test_looks_like_uuid_rejects_invalid_and_empty():
    assert _looks_like_uuid("") is False
    assert _looks_like_uuid(None) is False  # type: ignore[arg-type]
    assert _looks_like_uuid(12345) is False  # type: ignore[arg-type]
    assert _looks_like_uuid("not-a-uuid") is False


# ---------------------------------------------------------------------------
# _note_exists — wraps _looks_like_uuid + a Note.objects.filter().exists().
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_note():
    """Patch ``intake_api.Note`` for tests that touch _note_exists / commit."""
    with patch("intake_chart_app.api.intake_api.Note") as mock:
        mock.DoesNotExist = type("DoesNotExist", (Exception,), {})
        yield mock


def test_note_exists_false_for_malformed_uuid(mock_note):
    assert _note_exists("not-a-uuid") is False
    mock_note.objects.filter.assert_not_called()


def test_note_exists_true_when_note_present(mock_note):
    mock_note.objects.filter.return_value.exists.return_value = True
    assert _note_exists("550e8400-e29b-41d4-a716-446655440000") is True


def test_note_exists_false_when_note_absent(mock_note):
    mock_note.objects.filter.return_value.exists.return_value = False
    assert _note_exists("550e8400-e29b-41d4-a716-446655440000") is False


# ---------------------------------------------------------------------------
# _summarize_effects — buckets emitted effects by lifecycle.
# ---------------------------------------------------------------------------


def _effect_of(type_name: str) -> MagicMock:
    """Build an effect-shaped mock whose ``type`` resolves to ``type_name``
    via ``EffectType.Name()``."""
    eff = MagicMock()
    eff.type = type_name  # the mocked EffectType.Name reads this back
    return eff


def test_summarize_effects_buckets_lifecycle():
    with patch("intake_chart_app.api.intake_api.EffectType") as MockET:
        MockET.Name.side_effect = lambda t: t  # identity mapping
        result = _summarize_effects([
            _effect_of("ORIGINATE_VITALS_COMMAND"),
            _effect_of("EDIT_DIAGNOSE_COMMAND"),
            _effect_of("EDIT_DIAGNOSE_COMMAND"),
            _effect_of("DELETE_ALLERGY_COMMAND"),
            _effect_of("UNKNOWN_PREFIX"),  # silently dropped
        ])
    assert result == {"originate": 1, "edit": 2, "delete": 1}


def test_summarize_effects_handles_lookup_error():
    """A bad effect type triggers EffectType.Name to raise; we drop it."""
    with patch("intake_chart_app.api.intake_api.EffectType") as MockET:
        MockET.Name.side_effect = ValueError("unknown")
        result = _summarize_effects([_effect_of(99)])
    assert result == {"originate": 0, "edit": 0, "delete": 0}


def test_summarize_effects_empty():
    assert _summarize_effects([]) == {"originate": 0, "edit": 0, "delete": 0}


# ---------------------------------------------------------------------------
# _cached_static — in-process cache for static assets.
# ---------------------------------------------------------------------------


def test_cached_static_renders_once_and_returns_cached_bytes():
    intake_api._static_cache.clear()
    with patch(
        "intake_chart_app.api.intake_api.render_to_string",
        return_value="body content",
    ) as mock_render:
        first = _cached_static("templates/x.css")
        second = _cached_static("templates/x.css")

    assert first == b"body content"
    assert second == b"body content"
    mock_render.assert_called_once_with("templates/x.css")
    intake_api._static_cache.clear()


# ---------------------------------------------------------------------------
# _post_section_review — cookie-bearing side-channel POST.
# ---------------------------------------------------------------------------


def _make_note_mock() -> MagicMock:
    note = MagicMock()
    note.patient.dbid = 42
    note.dbid = 99
    return note


def test_post_section_review_skips_unknown_section_id():
    assert (
        _post_section_review(
            "note-uuid",
            "unknown_section",
            instance_origin="https://tenant.canvasmedical.com",
            forwarded_cookie="sessionid=abc",
            note=_make_note_mock(),
        )
        is False
    )


def test_post_section_review_skips_without_origin_or_cookie():
    note = _make_note_mock()
    assert (
        _post_section_review(
            "note-uuid", "problems",
            instance_origin="", forwarded_cookie="abc", note=note,
        )
        is False
    )
    assert (
        _post_section_review(
            "note-uuid", "problems",
            instance_origin="https://x.canvasmedical.com",
            forwarded_cookie="", note=note,
        )
        is False
    )


def test_post_section_review_fetches_note_when_not_passed(mock_note):
    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )
    with patch("intake_chart_app.api.intake_api.Http") as MockHttp:
        MockHttp.return_value.post.return_value = SimpleNamespace(status_code=200)
        ok = _post_section_review(
            "note-uuid",
            "problems",
            instance_origin="https://tenant.canvasmedical.com",
            forwarded_cookie="sessionid=abc",
        )
    assert ok is True
    mock_note.objects.select_related.assert_called_once_with("patient")


def test_post_section_review_returns_false_when_note_missing(mock_note):
    mock_note.objects.select_related.return_value.get.side_effect = (
        mock_note.DoesNotExist()
    )
    assert (
        _post_section_review(
            "note-uuid",
            "problems",
            instance_origin="https://tenant.canvasmedical.com",
            forwarded_cookie="sessionid=abc",
        )
        is False
    )


def test_post_section_review_returns_false_on_non_2xx(mock_note):
    with patch("intake_chart_app.api.intake_api.Http") as MockHttp:
        MockHttp.return_value.post.return_value = SimpleNamespace(
            status_code=500, text="server error",
        )
        ok = _post_section_review(
            "note-uuid",
            "problems",
            instance_origin="https://tenant.canvasmedical.com",
            forwarded_cookie="sessionid=abc",
            note=_make_note_mock(),
        )
    assert ok is False


def test_post_section_review_returns_false_when_http_raises(mock_note):
    """Network/HTTP errors are caught (`requests.exceptions.RequestException`
    family); other exception classes propagate to Sentry."""
    from requests.exceptions import ConnectionError as RequestsConnectionError
    with patch("intake_chart_app.api.intake_api.Http") as MockHttp:
        MockHttp.return_value.post.side_effect = RequestsConnectionError("network down")
        ok = _post_section_review(
            "note-uuid",
            "problems",
            instance_origin="https://tenant.canvasmedical.com",
            forwarded_cookie="sessionid=abc",
            note=_make_note_mock(),
        )
    assert ok is False


def test_post_section_review_does_not_swallow_non_http_errors(mock_note):
    """REVIEW.md §55: non-HTTP errors (e.g. AttributeError from SDK
    drift) must propagate, not silently log."""
    with patch("intake_chart_app.api.intake_api.Http") as MockHttp:
        MockHttp.return_value.post.side_effect = AttributeError(
            "Http().post signature changed"
        )
        import pytest
        with pytest.raises(AttributeError):
            _post_section_review(
                "note-uuid",
                "problems",
                instance_origin="https://tenant.canvasmedical.com",
                forwarded_cookie="sessionid=abc",
                note=_make_note_mock(),
            )


def test_post_section_review_posts_expected_payload(mock_note):
    captured: dict = {}

    def fake_post(url, json, headers):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return SimpleNamespace(status_code=201)

    with patch("intake_chart_app.api.intake_api.Http") as MockHttp:
        MockHttp.return_value.post.side_effect = fake_post
        assert (
            _post_section_review(
                "note-uuid",
                "allergies",
                instance_origin="https://tenant.canvasmedical.com",
                forwarded_cookie="sessionid=abc",
                note=_make_note_mock(),
            )
            is True
        )
    assert captured["url"] == "https://tenant.canvasmedical.com/ChartSectionReview/"
    assert captured["json"] == {"patient": 42, "note": 99, "section": "allergies"}
    assert captured["headers"]["Cookie"] == "sessionid=abc"
    assert captured["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# IntakeAPI — route methods. Build an instance via object.__new__ and inject
# the attributes the routes touch.
# ---------------------------------------------------------------------------


def _make_request(
    *,
    query_params: dict | None = None,
    headers: dict | None = None,
    json_body=None,
    json_raises: bool = False,
) -> SimpleNamespace:
    """Lightweight stand-in for ``self.request``. Route methods only call
    ``query_params.get``, ``headers.get``, and ``json()``."""
    qp = query_params or {}
    hdr = headers or {}

    def _json_call():
        if json_raises:
            raise ValueError("malformed body")
        return json_body

    return SimpleNamespace(
        query_params=SimpleNamespace(get=lambda key, default="": qp.get(key, default)),
        headers=SimpleNamespace(get=lambda key, default="": hdr.get(key, default)),
        json=_json_call,
    )


def _make_api(
    *,
    request: SimpleNamespace | None = None,
    secrets: dict | None = None,
) -> IntakeAPI:
    api_handler = object.__new__(IntakeAPI)
    api_handler.request = request or _make_request()  # type: ignore[attr-defined]
    api_handler.secrets = secrets or {}  # type: ignore[attr-defined]
    return api_handler


# ----- get_form_state ------------------------------------------------------


def test_get_form_state_requires_note_id(fake_hubs):
    api = _make_api(request=_make_request(query_params={}))
    [resp] = api.get_form_state()
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_get_form_state_returns_drafts_from_snapshot(fake_hubs, note_uuid):
    from intake_chart_app.data import form_state

    form_state.set_section(note_uuid, "vitals", {"systolic": 120})
    form_state.set_section(note_uuid, "social_history", {"answers": {}})

    api = _make_api(request=_make_request(query_params={"note_id": note_uuid}))
    [resp] = api.get_form_state()
    assert resp.status_code in (200, HTTPStatus.OK)
    body = _json_body(resp)
    assert body["success"] is True
    assert body["note_uuid"] == note_uuid
    assert body["sections"] == {
        "vitals": {"systolic": 120},
        "social_history": {"answers": {}},
    }


def test_get_form_state_400_body_carries_error_code(fake_hubs):
    api = _make_api(request=_make_request(query_params={}))
    [resp] = api.get_form_state()
    body = _json_body(resp)
    assert body == {"success": False, "error": "note_id_required"}


# ----- save_section --------------------------------------------------------


def test_save_section_400_when_missing_query_params(fake_hubs):
    api = _make_api(request=_make_request())
    [resp] = api.save_section()
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_save_section_400_when_body_invalid_json(fake_hubs, note_uuid):
    api = _make_api(
        request=_make_request(
            query_params={"section": "vitals", "note_id": note_uuid},
            json_raises=True,
        ),
    )
    [resp] = api.save_section()
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_save_section_400_when_body_not_object(fake_hubs, note_uuid):
    api = _make_api(
        request=_make_request(
            query_params={"section": "vitals", "note_id": note_uuid},
            json_body=["not", "a", "dict"],
        ),
    )
    [resp] = api.save_section()
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_save_section_413_when_payload_too_large(fake_hubs, note_uuid):
    huge = {"k": "x" * (intake_api._MAX_SECTION_PAYLOAD_BYTES + 1)}
    api = _make_api(
        request=_make_request(
            query_params={"section": "vitals", "note_id": note_uuid},
            json_body=huge,
        ),
    )
    [resp] = api.save_section()
    assert resp.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


def test_save_section_404_when_note_not_found(fake_hubs, note_uuid, mock_note):
    mock_note.objects.filter.return_value.exists.return_value = False
    api = _make_api(
        request=_make_request(
            query_params={"section": "vitals", "note_id": note_uuid},
            json_body={"systolic": 120},
        ),
    )
    [resp] = api.save_section()
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_save_section_writes_to_form_state(fake_hubs, note_uuid, mock_note):
    from intake_chart_app.data import form_state

    mock_note.objects.filter.return_value.exists.return_value = True
    api = _make_api(
        request=_make_request(
            query_params={"section": "vitals", "note_id": note_uuid},
            json_body={"systolic": 120, "diastolic": 80},
        ),
    )
    [resp] = api.save_section()
    assert resp.status_code in (200, HTTPStatus.OK)
    assert _json_body(resp) == {"success": True, "section": "vitals"}
    assert form_state.get_section(note_uuid, "vitals") == {
        "systolic": 120, "diastolic": 80,
    }


# ----- commit --------------------------------------------------------------


def test_commit_400_when_missing_note_id(fake_hubs):
    api = _make_api(request=_make_request())
    [resp] = api.commit()
    assert resp.status_code == HTTPStatus.BAD_REQUEST


def test_commit_404_when_invalid_uuid(fake_hubs):
    api = _make_api(
        request=_make_request(query_params={"note_id": "not-a-uuid"}),
    )
    [resp] = api.commit()
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_commit_404_when_note_does_not_exist(fake_hubs, note_uuid, mock_note):
    mock_note.objects.select_related.return_value.get.side_effect = (
        mock_note.DoesNotExist()
    )
    api = _make_api(
        request=_make_request(query_params={"note_id": note_uuid}),
    )
    [resp] = api.commit()
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_commit_returns_ack_with_no_drafts(fake_hubs, note_uuid, mock_note):
    """No section drafts → no effects → success ack with zeroed counts."""
    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )
    api = _make_api(
        request=_make_request(query_params={"note_id": note_uuid}),
    )
    result = api.commit()
    # First element is the ack; nothing else when no effects.
    assert len(result) == 1
    ack = result[0]
    assert ack.status_code in (200, HTTPStatus.OK)
    assert _json_body(ack) == {
        "success": True,
        "effects": {"originate": 0, "edit": 0, "delete": 0},
    }


def test_commit_400_when_section_fails(fake_hubs, note_uuid, mock_note):
    """If any section raises a validation error, commit aborts with 400 and
    surfaces the failing section in the body so the front-end can highlight."""
    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )

    def _fail(*args, **kwargs):
        return [], {"section": "vitals", "error": "bad input"}

    with patch(
        "intake_chart_app.api.intake_api._commit_single_section",
        side_effect=_fail,
    ), patch(
        "intake_chart_app.api.intake_api._commit_questionnaire_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_multi_section",
        return_value=([], None),
    ):
        api = _make_api(
            request=_make_request(query_params={"note_id": note_uuid}),
        )
        [resp] = api.commit()
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    body = _json_body(resp)
    assert body["success"] is False
    assert {"section": "vitals", "error": "bad input"} in body["failures"]


def test_commit_failure_does_not_persist_earlier_section_uuids(
    fake_hubs, note_uuid, mock_note
):
    """All-or-nothing commit regression test. If a later section's
    helper returns an error, the staged UUIDs from earlier successful
    sections must NOT be persisted to AttributeHub — otherwise a retry
    sees ``existing_uuid`` truthy, takes ``edit()`` against a command
    that was never originated, and silently no-ops on a target that
    doesn't exist."""
    from intake_chart_app.data import form_state

    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )

    def _vitals_succeeds(note_uuid, section, snapshot):
        # Stage a UUID like the real _commit_single_section does after
        # a successful cmd.originate().
        snapshot.set_originated_command("vitals", "vitals-uuid-staged")
        return [MagicMock(name="vitals-originate-effect")], None

    def _problems_fails(note_uuid, section, snapshot, **kwargs):
        return [], {"section": "problems", "error": "bad icd10_code"}

    with patch(
        "intake_chart_app.api.intake_api._commit_single_section",
        side_effect=_vitals_succeeds,
    ), patch(
        "intake_chart_app.api.intake_api._commit_questionnaire_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_multi_section",
        side_effect=_problems_fails,
    ):
        api = _make_api(
            request=_make_request(query_params={"note_id": note_uuid}),
        )
        [resp] = api.commit()

    # Failure response shape unchanged.
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert _json_body(resp)["success"] is False

    # The staged Vitals UUID must NOT have landed on AttributeHub.
    # A fresh snapshot for the same note reads nothing for that section,
    # so the retry will take the originate() path again — not edit()
    # against a phantom UUID.
    fresh = form_state.FormStateSnapshot(note_uuid)
    assert fresh.get_originated_command("vitals") is None
    assert form_state.get_originated_command(note_uuid, "vitals") is None


def test_commit_success_flushes_staged_uuids(
    fake_hubs, note_uuid, mock_note
):
    """The complement of the regression above: when every section
    succeeds, ``commit()`` calls ``snapshot.flush()`` and staged UUIDs
    do land durably so the next ``commit()`` recognises them and emits
    edit() instead of a duplicate originate()."""
    from intake_chart_app.data import form_state

    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )

    def _vitals_succeeds(note_uuid, section, snapshot):
        snapshot.set_originated_command("vitals", "vitals-uuid-final")
        return [MagicMock(name="vitals-originate-effect")], None

    with patch(
        "intake_chart_app.api.intake_api._commit_single_section",
        side_effect=_vitals_succeeds,
    ), patch(
        "intake_chart_app.api.intake_api._commit_questionnaire_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_multi_section",
        return_value=([], None),
    ):
        api = _make_api(
            request=_make_request(query_params={"note_id": note_uuid}),
        )
        result = api.commit()

    # Success ack + effects.
    assert result[0].status_code in (200, HTTPStatus.OK)
    assert _json_body(result[0])["success"] is True
    # Staged UUID is now durable.
    assert (
        form_state.get_originated_command(note_uuid, "vitals")
        == "vitals-uuid-final"
    )


def test_commit_failure_does_not_dispatch_section_review_posts(
    fake_hubs, note_uuid, mock_note
):
    """All-or-nothing covers the ChartSectionReview side-channel POST too.
    If an all-confirmed multi-section stages a review POST and a later
    section's validator returns an error, the POST must NOT fire —
    otherwise the home-app persists a `Reviewed:` card the user thinks
    was rolled back, and the retry produces a duplicate (the endpoint
    isn't idempotent). Dispatch is keyed on section_id rather than
    invocation order so the test stays robust to commit's registry
    walk order."""
    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )

    fail_target = "allergies"
    stager = "problems"
    seen = {"fail": False, "stager": False}

    def _dispatch(note_uuid, section, snapshot):
        section_id = getattr(section, "section_id", "")
        if section_id == stager:
            snapshot.stage_review(section_id)
            seen["stager"] = True
            return [], None
        if section_id == fail_target:
            seen["fail"] = True
            return [], {"section": fail_target, "error": "validator says no"}
        return [], None

    with patch(
        "intake_chart_app.api.intake_api._commit_single_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_questionnaire_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_multi_section",
        side_effect=_dispatch,
    ), patch(
        "intake_chart_app.api.intake_api._post_section_review",
    ) as mock_post:
        api = _make_api(
            request=_make_request(query_params={"note_id": note_uuid}),
        )
        [resp] = api.commit()

    assert seen["stager"] and seen["fail"], (
        "test setup error: one of the target sections was never hit by the "
        "commit walk — both 'problems' and 'allergies' must be in the registry"
    )
    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert _json_body(resp)["success"] is False
    # Critical: no review POST went out, even though `problems` staged one.
    mock_post.assert_not_called()


def test_commit_success_dispatches_staged_section_review_posts(
    fake_hubs, note_uuid, mock_note
):
    """Complement: when every section succeeds, the staged review POSTs
    DO fire — one per section_id that called ``snapshot.stage_review``."""
    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )

    stage_targets = {"problems", "allergies"}

    def _dispatch(note_uuid, section, snapshot):
        section_id = getattr(section, "section_id", "")
        if section_id in stage_targets:
            snapshot.stage_review(section_id)
        return [], None

    with patch(
        "intake_chart_app.api.intake_api._commit_single_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_questionnaire_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_multi_section",
        side_effect=_dispatch,
    ), patch(
        "intake_chart_app.api.intake_api._post_section_review",
    ) as mock_post:
        api = _make_api(
            request=_make_request(query_params={"note_id": note_uuid}),
        )
        result = api.commit()

    assert result[0].status_code in (200, HTTPStatus.OK)
    assert _json_body(result[0])["success"] is True
    # Both staged section_ids got their POST.
    posted_section_ids = {c.args[1] for c in mock_post.call_args_list}
    assert posted_section_ids == stage_targets


def test_commit_dispatch_continues_when_one_review_post_raises(
    fake_hubs, note_uuid, mock_note
):
    """Partial dispatch failure: one section's review POST raises a
    ``RequestException``, the other succeeds.

    The dispatch loop must still attempt the second POST (one section's
    network blip can't take down the rest) and the commit handler must
    still return ``{success: true}`` — staged review POSTs are documented
    as recoverable (the MA can re-mark from the chart sidebar), unlike
    the AttributeHub flush which is not.

    Mocks the real ``Http()`` rather than ``_post_section_review`` so the
    helper's own ``RequestException`` catch is exercised — the test
    fails if the catch is ever narrowed or removed."""
    from requests.exceptions import ConnectionError as RequestsConnectionError

    mock_note.objects.select_related.return_value.get.return_value = (
        _make_note_mock()
    )

    stage_targets = {"problems", "allergies"}

    def _stage_two(note_uuid, section, snapshot):
        section_id = getattr(section, "section_id", "")
        if section_id in stage_targets:
            snapshot.stage_review(section_id)
        return [], None

    # First POST raises, second succeeds. Order of (raise, success)
    # doesn't matter for the assertion — we only care that both calls
    # were attempted.
    post_results = iter([
        RequestsConnectionError("home-app unreachable"),
        SimpleNamespace(status_code=201),
    ])

    def _fake_post(url, json, headers):
        outcome = next(post_results)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with patch(
        "intake_chart_app.api.intake_api._commit_single_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_questionnaire_section",
        return_value=([], None),
    ), patch(
        "intake_chart_app.api.intake_api._commit_multi_section",
        side_effect=_stage_two,
    ), patch(
        "intake_chart_app.api.intake_api.Http",
    ) as MockHttp:
        MockHttp.return_value.post.side_effect = _fake_post
        api = _make_api(
            request=_make_request(
                query_params={"note_id": note_uuid},
                headers={"Cookie": "sessionid=abc"},
            ),
            secrets={
                "canvas-instance-origin": "https://tenant.canvasmedical.com",
            },
        )
        result = api.commit()

    # Both POSTs attempted — the loop didn't bail after the first raise.
    assert MockHttp.return_value.post.call_count == 2
    # Commit still succeeds — failed reviews are recoverable.
    assert result[0].status_code in (200, HTTPStatus.OK)
    assert _json_body(result[0])["success"] is True


# ----- search routes -------------------------------------------------------


def test_search_medication_empty_term_returns_empty(fake_hubs):
    api = _make_api(request=_make_request(query_params={"q": ""}))
    [resp] = api.search_medication()
    # NLM Clinical Tables shape: [count, ids, null, rows].
    assert _json_body(resp) == [0, [], None, []]


def test_search_medication_proxies_to_ontologies(fake_hubs):
    fake_response = SimpleNamespace(
        json=lambda: {
            "results": [
                {
                    "med_medication_id": "12345",
                    "med_medication_description": "Lisinopril 10 mg",
                },
                {"med_medication_id": "67890", "med_medication_description": "Other"},
                {"med_medication_id": "", "med_medication_description": "empty-id"},
                "not-a-dict",  # dropped
            ]
        }
    )
    with patch(
        "intake_chart_app.api.intake_api.ontologies_http.get_json",
        return_value=fake_response,
    ):
        api = _make_api(
            request=_make_request(query_params={"q": "lisin"}),
        )
        [resp] = api.search_medication()
    # Empty-id row and the non-dict are filtered out; the rest pass through.
    assert _json_body(resp) == [
        2, ["12345", "67890"], None,
        [["Lisinopril 10 mg"], ["Other"]],
    ]


def test_search_medication_returns_empty_on_http_exception(fake_hubs):
    """Network errors degrade gracefully to an empty result set."""
    from requests.exceptions import Timeout
    with patch(
        "intake_chart_app.api.intake_api.ontologies_http.get_json",
        side_effect=Timeout("ontologies timed out"),
    ):
        api = _make_api(
            request=_make_request(query_params={"q": "lisin"}),
        )
        [resp] = api.search_medication()
    assert _json_body(resp) == [0, [], None, []]


def test_search_medication_does_not_swallow_non_http_errors(fake_hubs):
    """SDK drift / refactor errors must propagate, not silently return
    an empty list."""
    with patch(
        "intake_chart_app.api.intake_api.ontologies_http.get_json",
        side_effect=AttributeError("get_json signature changed"),
    ):
        api = _make_api(
            request=_make_request(query_params={"q": "lisin"}),
        )
        import pytest
        with pytest.raises(AttributeError):
            api.search_medication()


def test_search_allergy_empty_term_returns_empty(fake_hubs):
    api = _make_api(request=_make_request(query_params={"q": ""}))
    [resp] = api.search_allergy()
    assert _json_body(resp) == [0, [], None, []]


def test_search_allergy_filters_unsupported_concept_types(fake_hubs):
    fake_response = SimpleNamespace(
        json=lambda: {
            "results": [
                {
                    "dam_allergen_concept_id": 111,
                    "dam_allergen_concept_id_type": 1,
                    "dam_allergen_concept_id_description": "Peanut",
                },
                {
                    "dam_allergen_concept_id": 222,
                    "dam_allergen_concept_id_type": 6,
                    "dam_allergen_concept_id_description": "Latex",
                },
                {
                    "dam_allergen_concept_id": 333,
                    "dam_allergen_concept_id_type": 99,  # not in {1,2,6}
                    "dam_allergen_concept_id_description": "Excluded",
                },
                {"dam_allergen_concept_id": None, "dam_allergen_concept_id_type": 1},
                "not-a-dict",
            ]
        }
    )
    with patch(
        "intake_chart_app.api.intake_api.ontologies_http.get_json",
        return_value=fake_response,
    ):
        api = _make_api(
            request=_make_request(query_params={"q": "peanut"}),
        )
        [resp] = api.search_allergy()
    # concept_id|concept_type compound code; only the two allowed-type rows
    # survive; None concept_id and the non-dict are dropped.
    assert _json_body(resp) == [
        2, ["111|1", "222|6"], None,
        [["Peanut"], ["Latex"]],
    ]


def test_search_allergy_returns_empty_on_http_exception(fake_hubs):
    """Network errors degrade gracefully to an empty result set."""
    from requests.exceptions import ConnectionError as RequestsConnectionError
    with patch(
        "intake_chart_app.api.intake_api.ontologies_http.get_json",
        side_effect=RequestsConnectionError("ontologies unreachable"),
    ):
        api = _make_api(
            request=_make_request(query_params={"q": "peanut"}),
        )
        [resp] = api.search_allergy()
    assert _json_body(resp) == [0, [], None, []]


def test_search_allergy_does_not_swallow_non_http_errors(fake_hubs):
    """SDK drift / refactor errors must propagate, not silently return
    an empty list."""
    with patch(
        "intake_chart_app.api.intake_api.ontologies_http.get_json",
        side_effect=AttributeError("get_json signature changed"),
    ):
        api = _make_api(
            request=_make_request(query_params={"q": "peanut"}),
        )
        import pytest
        with pytest.raises(AttributeError):
            api.search_allergy()


# ----- static asset routes -------------------------------------------------


def test_get_intake_css_returns_rendered_bytes_with_css_content_type(fake_hubs):
    intake_api._static_cache.clear()
    css = ".intake { color: red; }"
    with patch(
        "intake_chart_app.api.intake_api.render_to_string",
        return_value=css,
    ):
        api = _make_api()
        [resp] = api.get_intake_css()
    assert resp.status_code in (200, HTTPStatus.OK)
    assert "text/css" in (
        getattr(resp, "content_type", "")
        or getattr(resp, "headers", {}).get("Content-Type", "")
    )
    assert resp.content == css.encode()
    intake_api._static_cache.clear()


def test_get_intake_js_returns_rendered_bytes_with_js_content_type(fake_hubs):
    intake_api._static_cache.clear()
    js = "console.log('intake');"
    with patch(
        "intake_chart_app.api.intake_api.render_to_string",
        return_value=js,
    ):
        api = _make_api()
        [resp] = api.get_intake_js()
    assert resp.status_code in (200, HTTPStatus.OK)
    assert "javascript" in (
        getattr(resp, "content_type", "")
        or getattr(resp, "headers", {}).get("Content-Type", "")
    )
    assert resp.content == js.encode()
    intake_api._static_cache.clear()
