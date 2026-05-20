"""Unit tests for compound_medication_loader.api.loader.

Covers:
- module helpers _potency_unit_choices / _controlled_substance_choices
- _validate_row (all error branches)
- _process_row (skip / dedup / NDC normalization / batch-tracking / shape)
- CompoundMedicationLoaderAPI.authenticate (4 paths)
- CompoundMedicationLoaderAPI.ping / .enums / .existing
- CompoundMedicationLoaderAPI.bulk_create (input shape, happy path, mixed batch)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from compound_medication_loader.api import loader as loader_mod
from compound_medication_loader.api.loader import (
    CompoundMedicationLoaderAPI,
    MAX_FORMULATION_LEN,
    NOT_SCHEDULED,
    _controlled_substance_choices,
    _potency_unit_choices,
    _process_row,
    _validate_row,
)


# ---------- module-level choice helpers ----------


class TestChoiceHelpers:
    def test_potency_unit_choices_passthrough(self, potency_choices):
        with patch.object(loader_mod, "CompoundMedicationModel") as mock_model:
            mock_model.PotencyUnits.choices = potency_choices
            result = _potency_unit_choices()

            assert mock_model.mock_calls == []
            assert result == potency_choices

    def test_controlled_substance_choices_passthrough(self, controlled_choices):
        with patch.object(loader_mod, "CompoundMedicationModel") as mock_model:
            mock_model.ControlledSubstanceOptions.choices = controlled_choices
            result = _controlled_substance_choices()

            assert mock_model.mock_calls == []
            assert result == controlled_choices


# ---------- _validate_row ----------


class TestValidateRow:
    def _valid_sets(self):
        return {"C48155", "C28253"}, {"N", "3"}

    def test_empty_formulation_errors(self):
        valid_pot, valid_con = self._valid_sets()
        errors = _validate_row("", "C48155", "N", None, valid_pot, valid_con)
        assert errors == ["formulation is required"]

    def test_too_long_formulation_errors(self):
        valid_pot, valid_con = self._valid_sets()
        long_name = "x" * (MAX_FORMULATION_LEN + 1)
        errors = _validate_row(long_name, "C48155", "N", None, valid_pot, valid_con)
        assert errors == [f"formulation must be <= {MAX_FORMULATION_LEN} characters"]

    def test_missing_potency_errors(self):
        valid_pot, valid_con = self._valid_sets()
        errors = _validate_row("Cream", None, "N", None, valid_pot, valid_con)
        assert errors == ["potency_unit_code is required (see GET /enums)"]

    def test_invalid_potency_errors(self):
        valid_pot, valid_con = self._valid_sets()
        errors = _validate_row("Cream", "BOGUS", "N", None, valid_pot, valid_con)
        assert errors == ["invalid potency_unit_code 'BOGUS' (see GET /enums)"]

    def test_invalid_controlled_errors(self):
        valid_pot, valid_con = self._valid_sets()
        errors = _validate_row("Cream", "C48155", "Z", None, valid_pot, valid_con)
        assert errors == ["invalid controlled_substance 'Z' (see GET /enums)"]

    def test_controlled_without_ndc_errors(self):
        valid_pot, valid_con = self._valid_sets()
        errors = _validate_row("Cream", "C48155", "3", None, valid_pot, valid_con)
        assert errors == [
            f"controlled_substance_ndc is required when controlled_substance != {NOT_SCHEDULED!r}"
        ]

    def test_controlled_with_ndc_ok(self):
        valid_pot, valid_con = self._valid_sets()
        errors = _validate_row("Cream", "C48155", "3", "12345-6789", valid_pot, valid_con)
        assert errors == []

    def test_valid_row_no_errors(self):
        valid_pot, valid_con = self._valid_sets()
        errors = _validate_row("Cream", "C48155", "N", None, valid_pot, valid_con)
        assert errors == []


# ---------- _process_row ----------


class TestProcessRow:
    @pytest.fixture
    def valid_sets(self):
        return {"C48155", "C28253"}, {"N", "3"}

    def test_non_dict_row_returns_error(self, valid_sets):
        valid_pot, valid_con = valid_sets
        result = _process_row("not a dict", 0, {}, True, valid_pot, valid_con)
        assert result == {
            "index": 0,
            "formulation": None,
            "already_exists": False,
            "existing_active": None,
            "status": "error",
            "errors": ["row must be a JSON object"],
        }

    def test_validation_error_carries_already_exists_flag(self, valid_sets):
        valid_pot, valid_con = valid_sets
        existing = {"Some Cream": True}
        row = {"formulation": "Some Cream", "potency_unit_code": "BOGUS"}
        result = _process_row(row, 1, existing, True, valid_pot, valid_con)

        assert result["index"] == 1
        assert result["status"] == "error"
        assert result["already_exists"] is True
        assert result["existing_active"] is True
        assert result["errors"] == [
            "invalid potency_unit_code 'BOGUS' (see GET /enums)",
            "controlled_substance 'N' is not allowed",  # never hit, see next assert
        ][:1]  # only the first error fires

    def test_skip_existing_active_marks_skipped(self, valid_sets):
        valid_pot, valid_con = valid_sets
        existing = {"Magic Cream": True}
        row = {
            "formulation": "Magic Cream",
            "potency_unit_code": "C48155",
            "controlled_substance": "N",
        }
        result = _process_row(row, 0, existing, True, valid_pot, valid_con)

        assert result["status"] == "skipped"
        assert result["already_exists"] is True
        assert result["existing_active"] is True
        assert result["reason"] == "formulation already exists (active)"
        assert "_effect" not in result

    def test_skip_existing_inactive_marks_skipped_with_inactive_label(self, valid_sets):
        valid_pot, valid_con = valid_sets
        existing = {"Old Cream": False}
        row = {
            "formulation": "Old Cream",
            "potency_unit_code": "C48155",
            "controlled_substance": "N",
        }
        result = _process_row(row, 0, existing, True, valid_pot, valid_con)

        assert result["status"] == "skipped"
        assert result["existing_active"] is False
        assert result["reason"] == "formulation already exists (inactive)"

    def test_skip_disabled_attempts_create_even_for_dupe(self, valid_sets):
        valid_pot, valid_con = valid_sets
        existing = {"Magic Cream": True}
        row = {
            "formulation": "Magic Cream",
            "potency_unit_code": "C48155",
            "controlled_substance": "N",
        }
        with patch.object(loader_mod, "Effect") as mock_effect:
            sentinel = MagicMock(name="effect-instance")
            mock_effect.return_value = sentinel

            result = _process_row(row, 0, existing, False, valid_pot, valid_con)

            calls = [
                call(
                    type="CREATE_COMPOUND_MEDICATION",
                    payload=json.dumps({
                        "formulation": "Magic Cream",
                        "potency_unit_code": "C48155",
                        "controlled_substance": "N",
                        "active": True,
                    }),
                )
            ]
            assert mock_effect.mock_calls == calls

        assert result["status"] == "created"
        assert result["already_exists"] is True
        assert result["existing_active"] is True
        assert result["_effect"] is sentinel

    def test_new_row_strips_ndc_dashes_and_emits_effect(self, valid_sets):
        valid_pot, valid_con = valid_sets
        existing: dict[str, bool] = {}
        row = {
            "formulation": "Test C-II",
            "potency_unit_code": "C48155",
            "controlled_substance": "3",
            "controlled_substance_ndc": "12345-6789-01",
            "active": True,
        }
        with patch.object(loader_mod, "Effect") as mock_effect:
            sentinel = MagicMock(name="effect-instance")
            mock_effect.return_value = sentinel

            result = _process_row(row, 4, existing, True, valid_pot, valid_con)

            calls = [
                call(
                    type="CREATE_COMPOUND_MEDICATION",
                    payload=json.dumps({
                        "formulation": "Test C-II",
                        "potency_unit_code": "C48155",
                        "controlled_substance": "3",
                        "active": True,
                        "controlled_substance_ndc": "12345678901",
                    }),
                )
            ]
            assert mock_effect.mock_calls == calls

        assert result["status"] == "created"
        assert result["index"] == 4
        assert result["already_exists"] is False
        assert result["existing_active"] is None
        assert result["_effect"] is sentinel
        # batch dedup: existing dict mutated
        assert existing == {"Test C-II": True}

    def test_new_row_records_active_flag_in_batch_index(self, valid_sets):
        valid_pot, valid_con = valid_sets
        existing: dict[str, bool] = {}
        row = {
            "formulation": "Inactive Loaded",
            "potency_unit_code": "C48155",
            "controlled_substance": "N",
            "active": False,
        }
        with patch.object(loader_mod, "Effect"):
            _process_row(row, 0, existing, True, valid_pot, valid_con)
        assert existing == {"Inactive Loaded": False}

    def test_effect_construction_error_returns_error_row(self, valid_sets):
        valid_pot, valid_con = valid_sets
        existing: dict[str, bool] = {}
        row = {
            "formulation": "Boom",
            "potency_unit_code": "C48155",
            "controlled_substance": "N",
        }
        with patch.object(loader_mod, "Effect") as mock_effect:
            mock_effect.side_effect = RuntimeError("kapow")

            result = _process_row(row, 7, existing, True, valid_pot, valid_con)

            calls = [
                call(
                    type="CREATE_COMPOUND_MEDICATION",
                    payload=json.dumps({
                        "formulation": "Boom",
                        "potency_unit_code": "C48155",
                        "controlled_substance": "N",
                        "active": True,
                    }),
                )
            ]
            assert mock_effect.mock_calls == calls

        assert result["status"] == "error"
        assert result["index"] == 7
        assert result["errors"] == ["kapow"]


# ---------- API handler — bypass __init__ to test methods in isolation ----------


def _make_handler():
    return CompoundMedicationLoaderAPI.__new__(CompoundMedicationLoaderAPI)


class TestAuthenticate:
    def test_staff_session_passes(self):
        handler = _make_handler()
        handler.request = MagicMock()
        handler.request.headers.get.return_value = "Staff"
        handler.secrets = {}

        credentials = MagicMock()

        assert handler.authenticate(credentials) is True

        # 1. handler.request
        assert handler.request.mock_calls == [
            call.headers.get("canvas-logged-in-user-type"),
        ]
        # 2. credentials never read on the staff-session path
        assert credentials.mock_calls == []

    def test_missing_bearer_secret_rejects(self):
        handler = _make_handler()
        handler.request = MagicMock()
        handler.request.headers.get.return_value = "SomethingElse"
        handler.secrets = {"BULK_LOAD_API_KEY": ""}

        credentials = MagicMock()

        assert handler.authenticate(credentials) is False

        assert handler.request.mock_calls == [
            call.headers.get("canvas-logged-in-user-type"),
        ]
        assert credentials.mock_calls == []

    def test_valid_bearer_passes(self):
        handler = _make_handler()
        handler.request = MagicMock()
        # First call (user-type) returns non-Staff so we fall through to Bearer;
        # second call (Authorization) returns the matching header.
        handler.request.headers.get.side_effect = [None, "Bearer s3cret"]
        handler.secrets = {"BULK_LOAD_API_KEY": "s3cret"}

        credentials = MagicMock()

        assert handler.authenticate(credentials) is True

        assert handler.request.mock_calls == [
            call.headers.get("canvas-logged-in-user-type"),
            call.headers.get("Authorization", ""),
        ]
        assert credentials.mock_calls == []

    def test_wrong_bearer_rejects(self):
        handler = _make_handler()
        handler.request = MagicMock()
        handler.request.headers.get.side_effect = [None, "Bearer nope"]
        handler.secrets = {"BULK_LOAD_API_KEY": "s3cret"}

        credentials = MagicMock()

        assert handler.authenticate(credentials) is False

        assert handler.request.mock_calls == [
            call.headers.get("canvas-logged-in-user-type"),
            call.headers.get("Authorization", ""),
        ]
        assert credentials.mock_calls == []


class TestSimpleEndpoints:
    def test_ping_returns_ok(self):
        handler = _make_handler()
        with patch.object(loader_mod, "JSONResponse") as mock_resp:
            sentinel = MagicMock(name="resp")
            mock_resp.return_value = sentinel

            result = handler.ping()

            assert mock_resp.mock_calls == [
                call({"ok": True}, status_code=200),
            ]
            assert result == [sentinel]

    def test_enums_passes_choices_through(self, potency_choices, controlled_choices):
        handler = _make_handler()
        with patch.object(loader_mod, "CompoundMedicationModel") as mock_model, \
             patch.object(loader_mod, "JSONResponse") as mock_resp:
            mock_model.PotencyUnits.choices = potency_choices
            mock_model.ControlledSubstanceOptions.choices = controlled_choices
            sentinel = MagicMock(name="resp")
            mock_resp.return_value = sentinel

            result = handler.enums()

            assert mock_model.mock_calls == []  # only attribute reads on choices
            expected_body = {
                "potency_unit_code": [
                    {"code": "C48155", "label": "Gram"},
                    {"code": "C28253", "label": "Milligram"},
                    {"code": "C28254", "label": "Milliliter"},
                ],
                "controlled_substance": [
                    {"code": "N", "label": "Not scheduled"},
                    {"code": "2", "label": "Schedule II"},
                    {"code": "3", "label": "Schedule III"},
                    {"code": "4", "label": "Schedule IV"},
                    {"code": "5", "label": "Schedule V"},
                ],
                "max_formulation_length": MAX_FORMULATION_LEN,
            }
            assert mock_resp.mock_calls == [call(expected_body, status_code=200)]
            assert result == [sentinel]

    def test_existing_returns_formulation_map(self):
        handler = _make_handler()
        rows = [("A Cream", True), ("B Cream", False)]
        with patch.object(loader_mod, "CompoundMedicationModel") as mock_model, \
             patch.object(loader_mod, "JSONResponse") as mock_resp:
            mock_model.objects.values_list.return_value = rows
            sentinel = MagicMock(name="resp")
            mock_resp.return_value = sentinel

            result = handler.existing()

            assert mock_model.mock_calls == [
                call.objects.values_list("formulation", "active"),
            ]
            assert mock_resp.mock_calls == [
                call({"compounds": {"A Cream": True, "B Cream": False}}, status_code=200),
            ]
            assert result == [sentinel]


class TestBulkCreate:
    def _set_request_body(self, handler, body_obj):
        handler.request = MagicMock()
        handler.request.body = json.dumps(body_obj).encode("utf-8")

    def _patch_model(self, ctx, potency_choices, controlled_choices, existing_rows):
        mock_model = ctx.enter_context(patch.object(loader_mod, "CompoundMedicationModel"))
        mock_model.PotencyUnits.choices = potency_choices
        mock_model.ControlledSubstanceOptions.choices = controlled_choices
        mock_model.objects.values_list.return_value = existing_rows
        return mock_model

    def test_invalid_json_body_returns_400(self):
        handler = _make_handler()
        handler.request = MagicMock()
        handler.request.body = b"{not json"
        with patch.object(loader_mod, "JSONResponse") as mock_resp:
            sentinel = MagicMock()
            mock_resp.return_value = sentinel

            result = handler.bulk_create()

            assert mock_resp.mock_calls == [
                call({"error": "Invalid JSON body."}, status_code=400),
            ]
            assert result == [sentinel]

    def test_non_object_body_returns_400(self):
        handler = _make_handler()
        self._set_request_body(handler, ["not", "an", "object"])
        with patch.object(loader_mod, "JSONResponse") as mock_resp:
            sentinel = MagicMock()
            mock_resp.return_value = sentinel

            result = handler.bulk_create()

            assert mock_resp.mock_calls == [
                call({"error": "Body must be a JSON object."}, status_code=400),
            ]
            assert result == [sentinel]

    def test_missing_compounds_returns_400(self):
        handler = _make_handler()
        self._set_request_body(handler, {"skip_existing": True})
        with patch.object(loader_mod, "JSONResponse") as mock_resp:
            sentinel = MagicMock()
            mock_resp.return_value = sentinel

            result = handler.bulk_create()

            assert mock_resp.mock_calls == [
                call(
                    {"error": "Expected non-empty list under 'compounds' key."},
                    status_code=400,
                ),
            ]
            assert result == [sentinel]

    def test_empty_body_falls_through_to_missing_compounds(self):
        """Empty/whitespace body decodes to {} and hits the compounds guard."""
        handler = _make_handler()
        handler.request = MagicMock()
        handler.request.body = b""
        with patch.object(loader_mod, "JSONResponse") as mock_resp:
            sentinel = MagicMock()
            mock_resp.return_value = sentinel

            result = handler.bulk_create()

            assert mock_resp.mock_calls == [
                call(
                    {"error": "Expected non-empty list under 'compounds' key."},
                    status_code=400,
                ),
            ]
            assert result == [sentinel]

    def test_happy_path_single_row(self, potency_choices, controlled_choices):
        handler = _make_handler()
        self._set_request_body(handler, {
            "skip_existing": True,
            "compounds": [
                {
                    "formulation": "New Cream",
                    "potency_unit_code": "C48155",
                    "controlled_substance": "N",
                }
            ],
        })

        from contextlib import ExitStack

        with ExitStack() as ctx:
            mock_model = self._patch_model(ctx, potency_choices, controlled_choices, [])
            mock_effect = ctx.enter_context(patch.object(loader_mod, "Effect"))
            mock_resp = ctx.enter_context(patch.object(loader_mod, "JSONResponse"))
            mock_log = ctx.enter_context(patch.object(loader_mod, "log"))

            effect_sentinel = MagicMock(name="effect")
            mock_effect.return_value = effect_sentinel
            resp_sentinel = MagicMock(name="resp")
            mock_resp.return_value = resp_sentinel

            result = handler.bulk_create()

            # 1. CompoundMedicationModel: only the pre-load for dedup index
            assert mock_model.mock_calls == [
                call.objects.values_list("formulation", "active"),
            ]
            # 2. Effect: one create with the flat payload
            assert mock_effect.mock_calls == [
                call(
                    type="CREATE_COMPOUND_MEDICATION",
                    payload=json.dumps({
                        "formulation": "New Cream",
                        "potency_unit_code": "C48155",
                        "controlled_substance": "N",
                        "active": True,
                    }),
                )
            ]
            # 3. JSONResponse: one summary response
            assert mock_resp.mock_calls == [
                call(
                    {
                        "summary": {"total": 1, "created": 1, "skipped": 0, "errors": 0},
                        "results": [
                            {
                                "index": 0,
                                "formulation": "New Cream",
                                "already_exists": False,
                                "existing_active": None,
                                "status": "created",
                            }
                        ],
                    },
                    status_code=200,
                ),
            ]
            # 4. logger
            assert mock_log.mock_calls == [
                call.info(
                    "[compound_medication_loader] bulk load summary: "
                    "{'total': 1, 'created': 1, 'skipped': 0, 'errors': 0}"
                ),
            ]

        assert result == [resp_sentinel, effect_sentinel]

    def test_mixed_batch_new_dupe_invalid(self, potency_choices, controlled_choices):
        handler = _make_handler()
        self._set_request_body(handler, {
            "skip_existing": True,
            "compounds": [
                {
                    "formulation": "Existing Cream",
                    "potency_unit_code": "C48155",
                    "controlled_substance": "N",
                },
                {
                    "formulation": "Brand New Cream",
                    "potency_unit_code": "C48155",
                    "controlled_substance": "N",
                },
                {
                    "formulation": "",
                    "potency_unit_code": "C48155",
                    "controlled_substance": "N",
                },
            ],
        })

        from contextlib import ExitStack

        with ExitStack() as ctx:
            mock_model = self._patch_model(
                ctx, potency_choices, controlled_choices,
                [("Existing Cream", True)],
            )
            mock_effect = ctx.enter_context(patch.object(loader_mod, "Effect"))
            mock_resp = ctx.enter_context(patch.object(loader_mod, "JSONResponse"))
            ctx.enter_context(patch.object(loader_mod, "log"))

            effect_sentinel = MagicMock(name="effect")
            mock_effect.return_value = effect_sentinel
            resp_sentinel = MagicMock(name="resp")
            mock_resp.return_value = resp_sentinel

            result = handler.bulk_create()

            # Model pre-loaded once
            assert mock_model.mock_calls == [
                call.objects.values_list("formulation", "active"),
            ]
            # Only the "Brand New Cream" row reaches Effect()
            assert mock_effect.mock_calls == [
                call(
                    type="CREATE_COMPOUND_MEDICATION",
                    payload=json.dumps({
                        "formulation": "Brand New Cream",
                        "potency_unit_code": "C48155",
                        "controlled_substance": "N",
                        "active": True,
                    }),
                )
            ]
            # JSONResponse: summary = 3 total / 1 created / 1 skipped / 1 errors
            assert mock_resp.mock_calls == [
                call(
                    {
                        "summary": {"total": 3, "created": 1, "skipped": 1, "errors": 1},
                        "results": [
                            {
                                "index": 0,
                                "formulation": "Existing Cream",
                                "already_exists": True,
                                "existing_active": True,
                                "status": "skipped",
                                "reason": "formulation already exists (active)",
                            },
                            {
                                "index": 1,
                                "formulation": "Brand New Cream",
                                "already_exists": False,
                                "existing_active": None,
                                "status": "created",
                            },
                            {
                                "index": 2,
                                "formulation": None,
                                "already_exists": False,
                                "existing_active": None,
                                "status": "error",
                                "errors": ["formulation is required"],
                            },
                        ],
                    },
                    status_code=200,
                ),
            ]

        assert result == [resp_sentinel, effect_sentinel]
