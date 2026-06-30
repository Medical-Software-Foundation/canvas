"""Tests for practitioner_bulk_loader.api.bulk_upload_api."""

import json
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
import requests

from canvas_sdk.effects.simple_api import JSONResponse, Response

from practitioner_bulk_loader.api.bulk_upload_api import (
    _ISSUING_AUTHORITY_SHORT_NAME_URL,
    _ISSUING_AUTHORITY_STATE_URL,
    _ISSUING_AUTHORITY_URL,
    _NPI_SYSTEM,
    BulkUploadAPI,
    _apply_csv_address,
    _apply_csv_non_address,
    _apply_csv_to_existing,
    _build_staff_directory,
    _expand_address_for_fhir,
    _extract_fumage_error_text,
    _is_username_collision,
    _compute_field_conflicts,
    _extract_existing_field_values,
    _normalize_existing_address,
    _normalize_existing_practitioner_identifier,
    _normalize_existing_qualification_identifiers,
    _normalize_existing_qualification_license_name,
    _normalize_existing_telecom,
    _resolve_field_label,
    humanise_fhir_error,
)
from practitioner_bulk_loader.utils.csv_parser import DEFAULT_NPI, TEMPLATE_CSV
from practitioner_bulk_loader.utils.fhir_client import MissingSecretError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_staff_dir():
    """Empty directory shape returned by _build_staff_directory()."""
    return {"by_email": {}, "by_npi": {}, "by_name_dob": {}, "by_name": {}}


def _staff_dir_with_email(email, staff_id):
    """One-entry directory matched only by email — used for the simple
    "existing practitioner found by email" tests."""
    d = _empty_staff_dir()
    d["by_email"][email.lower()] = {
        "id": staff_id, "first_name": "", "last_name": "", "birth_date": "",
    }
    return d


def make_handler(body=None, query_params=None):
    """Create a BulkUploadAPI instance with mocked request and secrets."""
    handler = BulkUploadAPI.__new__(BulkUploadAPI)
    handler.secrets = {
        "fumage-client-id": "test-client-id",
        "fumage-client-secret": "test-client-secret",
    }
    handler.environment = {"CUSTOMER_IDENTIFIER": "test"}

    mock_request = MagicMock()
    mock_request.json.return_value = body or {}
    mock_request.query_params = query_params or {}

    handler.request = mock_request
    return handler


def _extract_json(result_list):
    """Extract the JSONResponse payload dict from a handler return list."""
    for item in result_list:
        if isinstance(item, JSONResponse):
            return json.loads(item.content)
    return None


def _extract_response(result_list):
    """Extract the first Response object from a handler return list."""
    for item in result_list:
        if isinstance(item, Response):
            return item
    return None


# ---------------------------------------------------------------------------
# GET /template.csv
# ---------------------------------------------------------------------------

class TestGetTemplate:
    def test_returns_response_object(self):
        handler = make_handler()
        result = handler.get_template()
        resp = _extract_response(result)
        assert resp is not None

    def test_content_type_is_csv(self):
        handler = make_handler()
        result = handler.get_template()
        resp = _extract_response(result)
        assert resp.headers.get("Content-Type") == "text/csv"

    def test_content_matches_template(self):
        handler = make_handler()
        result = handler.get_template()
        resp = _extract_response(result)
        assert resp.content == TEMPLATE_CSV.encode("utf-8")

    def test_content_disposition_attachment(self):
        handler = make_handler()
        result = handler.get_template()
        resp = _extract_response(result)
        assert "attachment" in resp.headers.get("Content-Disposition", "")


# ---------------------------------------------------------------------------
# POST /parse-and-validate
# ---------------------------------------------------------------------------

VALID_CSV = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,License Primary
Jane,Smith,MD,Main Clinic,jane.smith@example.com,5555550100,,,1980-03-15,,,,,,,,,,,
"""

INVALID_CSV = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,License Primary
,Smith,MD,Main Clinic,not-an-email,abc123,,,1980-03-15,,,,,,,,,,,
"""


_HELP_URL = "https://canvas-medical.help.usepylon.com/articles/6649603926-staff-roles"


class TestParseAndValidateHeaderGate:
    """Header validation runs as the first step of parse_and_validate so a
    single schema error doesn't cascade into thousands of confusing per-row
    errors. The dominant real-world case: a CSV where the per-license state
    column was named ``State`` (duplicating the practitioner address state
    column header), which silently dropped every license's state value and
    produced 4,011 "License State is required" errors against a single
    practitioner — a debugging nightmare. With the gate, that's one clear
    "duplicate header" error and an obvious fix."""

    def test_duplicate_state_header_short_circuits_with_clear_error(self):
        """Real customer CSV had ``State`` for both columns 13 and 17; the
        second silently shadowed License State data. The gate must catch
        this before per-row validation runs (which would emit 4,011 errors)
        and return one error pointing at both column positions."""
        # Header row with "State" twice (cols 13 and 17), one data row.
        csv_text = (
            "First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,"
            "Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,State,"
            "License Number,License Issue Date,License Expiration Date,Primary\n"
            "Jane,Doe,MD,,jane@x.com,5555550100,,,1980-01-01,,,,CA,90001,STATE,NY Board,NY,"
            "12345,2020-01-01,2026-01-01,TRUE\n"
        )
        handler = make_handler(body={"csv_text": csv_text})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn:
            mock_client_fn.return_value = MagicMock()
            result = handler.parse_and_validate()

        data = _extract_json(result)
        assert len(data["errors"]) == 1, (
            "Header gate must short-circuit — one clear error, not "
            "thousands of cascading per-row errors."
        )
        msg = data["errors"][0]["message"]
        assert "State" in msg
        assert "column 13" in msg
        assert "column 17" in msg
        # Per-row work was skipped, so no practitioners came through.
        assert data["practitioners"] == []

    def test_missing_required_header_short_circuits_with_clear_error(self):
        """If "First Name" is missing entirely, the gate catches it once
        instead of letting every row fail with "First Name is required"."""
        csv_text = (
            # No "First Name" column.
            "Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,"
            "Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,"
            "License Number,License Issue Date,License Expiration Date,Primary\n"
            "Doe,MD,,jane@x.com,5555550100,,,1980-01-01,,,,CA,90001,STATE,NY Board,NY,"
            "12345,2020-01-01,2026-01-01,TRUE\n"
        )
        handler = make_handler(body={"csv_text": csv_text})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn:
            mock_client_fn.return_value = MagicMock()
            result = handler.parse_and_validate()

        data = _extract_json(result)
        assert any(
            "First Name" in e["message"] and "missing" in e["message"].lower()
            for e in data["errors"]
        )
        assert data["practitioners"] == []

    def test_valid_headers_proceed_to_per_row_validation(self):
        """Sanity: a CSV with correct headers makes it past the gate and
        through normal validation."""
        # Reuse the existing valid CSV from this file.
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = _empty_staff_dir()
            result = handler.parse_and_validate()

        data = _extract_json(result)
        assert data["errors"] == []
        # Per-row parse ran and produced a practitioner record.
        assert len(data["practitioners"]) == 1


class TestParseAndValidate:
    """Parse-and-validate pipeline. Role codes are NOT pre-flight validated —
    Canvas checks them at POST time and we surface the error in the results UI.
    """

    def test_missing_csv_text_returns_400(self):
        handler = make_handler(body={})
        result = handler.parse_and_validate()
        resp = _extract_json(result)
        assert resp is not None
        assert "error" in resp

    def test_valid_csv_returns_practitioners(self):
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_find:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_find.return_value = _empty_staff_dir()

            result = handler.parse_and_validate()

        data = _extract_json(result)
        assert data is not None
        assert data["errors"] == []
        assert len(data["practitioners"]) == 1
        assert data["practitioners"][0]["status"] == "new"

    def test_invalid_csv_returns_errors_no_practitioners(self):
        handler = make_handler(body={"csv_text": INVALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            result = handler.parse_and_validate()

        data = _extract_json(result)
        assert len(data["errors"]) > 0
        assert data["practitioners"] == []

    def test_unknown_role_is_not_flagged_at_validation(self):
        """Unknown role codes pass parse-and-validate; Canvas rejects them at POST time."""
        csv_wizard = VALID_CSV.replace("Jane,Smith,MD,", "Jane,Smith,WIZARD,")
        handler = make_handler(body={"csv_text": csv_wizard})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_find:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_find.return_value = _empty_staff_dir()

            result = handler.parse_and_validate()

        data = _extract_json(result)
        assert not any(e.get("field") == "Role" for e in data["errors"])
        assert not any("not configured" in w.get("message", "") for w in data["warnings"])
        assert len(data["practitioners"]) == 1

    def test_existing_practitioner_flagged_as_existing(self):
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_find:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            # VALID_CSV's email is jane.smith@example.com — the by_email index
            # is keyed on the lowercased value.
            mock_find.return_value = _staff_dir_with_email(
                "jane.smith@example.com", "existing-uuid-123"
            )

            result = handler.parse_and_validate()

        data = _extract_json(result)
        p = data["practitioners"][0]
        assert p["status"] == "existing"
        assert p["existing_id"] == "Practitioner/existing-uuid-123"

    def test_unresolved_location_produces_error(self):
        handler = make_handler(body={"csv_text": """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,License Primary
Jane,Smith,MD,Unknown Clinic,jane.smith@example.com,5555550100,,,1980-03-15,,,,,,,,,,,
"""})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}  # Location not found

            result = handler.parse_and_validate()

        data = _extract_json(result)
        loc_errors = [e for e in data["errors"] if e.get("field") == "Primary Practice Location"]
        assert len(loc_errors) == 1
        assert "Unknown Clinic" in loc_errors[0]["message"]
        assert "Settings → Practice Locations" in loc_errors[0]["message"]
        assert loc_errors[0]["value"] == "Unknown Clinic"
        assert data["practitioners"] == []

    def test_resolved_location_sets_location_reference(self):
        handler = make_handler(body={"csv_text": """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,License Primary
Jane,Smith,MD,Main Clinic,jane.smith@example.com,5555550100,,,1980-03-15,,,,,,,,,,,
"""})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_find:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-abc"}
            mock_find.return_value = _empty_staff_dir()

            result = handler.parse_and_validate()

        data = _extract_json(result)
        p = data["practitioners"][0]
        assert p["location_reference"] == "Location/loc-abc"


# ---------------------------------------------------------------------------
# Duplicate detection: NPI fallback
# ---------------------------------------------------------------------------

# CSV with a real (non-placeholder) NPI on a row whose email won't be found
# in the mocked Canvas. Lets us drive the email-miss → NPI-fallback path.
NPI_FALLBACK_CSV = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
Jane,Smith,MD,Main Clinic,jane.new.email@example.com,5555550100,,1234567890,1980-03-15,,,,,,,,,,,,
"""


class TestParseAndValidateDuplicateDetection:
    """Multi-tier duplicate detection: email → real NPI → name+DOB → name-only warning."""

    def test_email_match_takes_priority(self):
        """Email match must win even if NPI / name+DOB would also hit."""
        handler = make_handler(body={"csv_text": NPI_FALLBACK_CSV})

        email_match = {"id": "by-email-id"}
        npi_match = {"id": "by-npi-id"}

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = {
                "by_email": {"jane.new.email@example.com": email_match},
                "by_npi": {"1234567890": npi_match},
                "by_name_dob": {},
                "by_name": {},
            }

            result = handler.parse_and_validate()

        p = _extract_json(result)["practitioners"][0]
        assert p["status"] == "existing"
        assert p["match_reason"] == "email"
        assert p["existing_id"] == "Practitioner/by-email-id"

    def test_npi_fallback_when_email_misses(self):
        handler = make_handler(body={"csv_text": NPI_FALLBACK_CSV})
        existing = {"id": "old-uuid-123"}

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = {
                "by_email": {},
                "by_npi": {"1234567890": existing},
                "by_name_dob": {},
                "by_name": {},
            }

            result = handler.parse_and_validate()

        p = _extract_json(result)["practitioners"][0]
        assert p["status"] == "existing"
        assert p["match_reason"] == "npi"
        assert p["existing_id"] == "Practitioner/old-uuid-123"

    def test_placeholder_npi_does_not_match_via_npi_tier(self):
        """The placeholder NPI is shared across all blank-NPI rows; using it
        for matching would false-positive every blank-NPI upload."""
        no_npi_csv = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
Jane,Smith,MD,Main Clinic,jane@example.com,5555550100,,,1980-03-15,,,,,,,,,,,,
"""
        handler = make_handler(body={"csv_text": no_npi_csv})

        # Pretend Canvas already has a placeholder-NPI Practitioner (which
        # the NPI fallback must NOT match against).
        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = {
                "by_email": {},
                "by_npi": {"1111155556": {"id": "placeholder-shared"}},
                "by_name_dob": {},
                "by_name": {},
            }
            result = handler.parse_and_validate()

        p = _extract_json(result)["practitioners"][0]
        assert p["match_reason"] != "npi"  # must NOT match via placeholder

    def test_name_dob_fallback_when_email_and_npi_miss(self):
        """John has blank NPI in CSV (becomes placeholder) and a typo'd email
        — name + DOB still catches him."""
        no_npi_csv = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
John,Smith,MD,Main Clinic,john.tipo@example.com,5555550100,,,1980-03-15,,,,,,,,,,,,
"""
        handler = make_handler(body={"csv_text": no_npi_csv})

        existing = {"id": "real-john-id", "birthDate": "1980-03-15"}

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = {
                "by_email": {},
                "by_npi": {},
                "by_name_dob": {("john", "smith", "1980-03-15"): existing},
                "by_name": {("john", "smith"): [existing]},
            }

            result = handler.parse_and_validate()

        p = _extract_json(result)["practitioners"][0]
        assert p["status"] == "existing"
        assert p["match_reason"] == "name_dob"
        assert p["existing_id"] == "Practitioner/real-john-id"

    def test_name_dob_match_uses_normalized_iso_date(self):
        """CSV DOB in MM-DD-YYYY format must be normalized to ISO before
        looking up the directory's ISO-keyed by_name_dob index."""
        csv = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
Jane,Doe,MD,Main Clinic,j.doe@example.com,5555550100,,,03-15-1980,,,,,,,,,,,,
"""
        handler = make_handler(body={"csv_text": csv})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = {
                "by_email": {},
                "by_npi": {},
                "by_name_dob": {("jane", "doe", "1980-03-15"): {"id": "jane-id"}},
                "by_name": {},
            }

            result = handler.parse_and_validate()

        p = _extract_json(result)["practitioners"][0]
        assert p["match_reason"] == "name_dob"

    def test_name_only_match_surfaces_possible_duplicate_count_on_row(self):
        """Name-only collision (different DOB) is too weak to auto-flag the
        row as Existing — instead, the per-row result carries
        possible_duplicate_count so the UI renders a "Possible Duplicate"
        badge in the row's Status column. It is NOT echoed into the top
        warnings list (avoids duplicate UX)."""
        csv = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
John,Smith,MD,Main Clinic,new.john@example.com,5555550100,,,07-04-1990,,,,,,,,,,,,
"""
        handler = make_handler(body={"csv_text": csv})

        # Existing John Smith on Canvas with a DIFFERENT DOB (1980 vs CSV's 1990).
        # Name+DOB tier misses; only the by_name index hits.
        other_john = {"id": "other-john", "birthDate": "1980-03-15"}

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = {
                "by_email": {},
                "by_npi": {},
                "by_name_dob": {("john", "smith", "1980-03-15"): other_john},
                "by_name": {("john", "smith"): [other_john]},
            }

            result = handler.parse_and_validate()

        data = _extract_json(result)
        p = data["practitioners"][0]
        # NOT auto-flagged as existing — name-only is too weak
        assert p["status"] == "new"
        assert p["match_reason"] is None
        # Count is on the row so the UI can render the badge
        assert p["possible_duplicate_count"] == 1
        # And NOT in the top warnings list (we removed the banner per UAT feedback)
        assert not any("Possible duplicate" in w.get("message", "") for w in data["warnings"])

    def test_existing_row_carries_new_license_count(self):
        """For existing rows, parse-and-validate fetches the existing
        Practitioner's qualifications and reports how many CSV licenses
        are NEW so the admin can pick Skip vs Add new licenses only."""
        csv_with_licenses = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
Jane,Smith,MD,Main Clinic,jane.smith@example.com,5555550100,,,1980-03-15,,,,,,STATE,NY Board,NY,NY-OLD,2020-01-01,2026-01-01,TRUE
,,,,jane.smith@example.com,,,,,,,,,,DEA,DEA Reg,,DEA-NEW,2021-01-01,2027-01-01,FALSE
"""
        handler = make_handler(body={"csv_text": csv_with_licenses})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = _staff_dir_with_email("jane.smith@example.com", "jane-id")
            # Canvas already has the STATE license; the DEA one is new.
            mock_read.return_value = {
                "id": "jane-id",
                "qualification": [
                    {
                        "code": {"text": "STATE"},
                        "identifier": [{
                            "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                            "value": "NY-OLD",
                        }],
                    }
                ],
            }
            result = handler.parse_and_validate()

        p = _extract_json(result)["practitioners"][0]
        assert p["status"] == "existing"
        # 2 in CSV, 1 already on Canvas → 1 new
        assert p["new_license_count"] == 1
        assert len(p["licenses"]) == 2

    def test_existing_phantom_row_has_null_new_license_count(self):
        """When the existing match has no FHIR Practitioner (phantom Staff),
        read_practitioner 404s; new_license_count stays None so the UI
        shows the CSV total without a (N new) suffix."""
        csv = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
Jane,Smith,MD,Main Clinic,jane.smith@example.com,5555550100,,,1980-03-15,,,,,,DEA,,,DEA-001,2021-01-01,2027-01-01,FALSE
"""
        handler = make_handler(body={"csv_text": csv})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner",
                   side_effect=requests.HTTPError("404 Not Found")) as mock_read:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = _staff_dir_with_email("jane.smith@example.com", "phantom-id")
            result = handler.parse_and_validate()

        p = _extract_json(result)["practitioners"][0]
        assert p["status"] == "existing"
        assert p["new_license_count"] is None  # fetch failed → unknown
        assert mock_read.call_count == 1

    def test_no_match_no_warning(self):
        handler = make_handler(body={"csv_text": NPI_FALLBACK_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = _empty_staff_dir()

            result = handler.parse_and_validate()

        data = _extract_json(result)
        p = data["practitioners"][0]
        assert p["status"] == "new"
        assert p["match_reason"] is None
        # No spurious "Possible duplicate" warning when there's truly no match.
        assert not any("Possible duplicate" in w.get("message", "") for w in data["warnings"])


# ---------------------------------------------------------------------------
# POST /create-practitioners
# ---------------------------------------------------------------------------

class TestCreatePractitioners:
    def _base_prac(self, **overrides):
        prac = {
            "source_row_number": 2,
            "email": "jane.smith@example.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "role": "MD",
            "phone": "5555550100",
            "npi": "",
            "dob": "1980-03-15",
            "fax": "",
            "address": {},
            "location_reference": None,
            "primary_practice_location": "",
            "licenses": [],
            "status": "new",
            "existing_id": None,
            "action": "create",
        }
        prac.update(overrides)
        return prac

    def test_empty_list_returns_400(self):
        handler = make_handler(body={"practitioners": []})
        result = handler.create_practitioners()
        data = _extract_json(result)
        assert "error" in data

    def test_missing_field_returns_400(self):
        handler = make_handler(body={})
        result = handler.create_practitioners()
        data = _extract_json(result)
        assert "error" in data

    def test_create_action_calls_create_practitioner(self):
        prac = self._base_prac(action="create")
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner") as mock_create, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner") as mock_build:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_build.return_value = {"resourceType": "Practitioner"}
            mock_create.return_value = "Practitioner/new-uuid"

            result = handler.create_practitioners()

        data = _extract_json(result)
        results = data["results"]
        assert len(results) == 1
        assert results[0]["status"] == "created"
        # staff_key is the bare key, no Practitioner/ prefix (Cecilia's UAT feedback)
        assert results[0]["staff_key"] == "new-uuid"
        mock_create.assert_called_once()

    def test_skip_action_returns_existing_id(self):
        prac = self._base_prac(action="skip", status="existing", existing_id="Practitioner/existing-xyz")
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        data = _extract_json(result)
        r = data["results"][0]
        assert r["status"] == "skipped"
        assert r["staff_key"] == "existing-xyz"

    def test_skip_action_on_new_row_returns_blank_staff_key(self):
        """The dropdown is now actionable on every row, so a 'new' row can
        be skipped at the admin's request — no Canvas API call, no staff
        key (since nothing was created or matched)."""
        prac = self._base_prac(action="skip", status="new", existing_id=None)
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner") as mock_create:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "skipped"
        assert r["staff_key"] == ""  # nothing to point at
        assert r["first_name"] == "Jane"  # name still surfaced for the results table
        # Critically: no POST /Practitioner happened.
        mock_create.assert_not_called()

    def test_merge_action_with_new_licenses(self):
        prac = self._base_prac(
            action="merge",
            status="existing",
            existing_id="Practitioner/existing-xyz",
            licenses=[{
                "type": "DEA", "number": "DEA001", "name": "", "license_state": "",
                "issue_date": "", "expiration_date": "", "primary_raw": "FALSE", "is_primary": False,
            }],
        )
        handler = make_handler(body={"practitioners": [prac]})

        existing_resource = {"id": "existing-xyz", "qualification": []}

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        data = _extract_json(result)
        r = data["results"][0]
        assert r["status"] == "merged"
        assert r["staff_key"] == "existing-xyz"
        # Merge uses PUT of the full resource — the existing qualification
        # array must be preserved with the new qualification appended.
        mock_put.assert_called_once()
        put_resource = mock_put.call_args[0][2]
        assert put_resource["id"] == "existing-xyz"
        assert len(put_resource["qualification"]) == 1  # existing was empty + 1 new

    def test_merge_renewal_updates_existing_qualification_period(self):
        """When the CSV row matches an existing qualification by type+number
        but carries different dates, _do_merge updates the existing
        qualification's period in place (instead of creating a duplicate)."""
        prac = self._base_prac(
            action="merge",
            status="existing",
            existing_id="Practitioner/existing-xyz",
            licenses=[{
                "type": "DEA", "number": "DEA001", "name": "", "license_state": "",
                "issue_date": "2020-01-01", "expiration_date": "2030-01-01",
                "primary_raw": "FALSE", "is_primary": False,
            }],
        )
        handler = make_handler(body={"practitioners": [prac]})

        # Canvas already has DEA / DEA001, but with an earlier expiration.
        existing_resource = {
            "id": "existing-xyz",
            "qualification": [{
                "code": {"text": "DEA"},
                "period": {"start": "2020-01-01", "end": "2026-01-01"},
                "identifier": [{
                    "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                    "value": "DEA001",
                }],
                "issuer": {"display": "DEA"},  # other fields preserved as-is
            }],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        assert "renewal" in r["message"].lower()

        # PUT body: still only ONE qualification, but the period.end is updated.
        put_resource = mock_put.call_args[0][2]
        quals = put_resource["qualification"]
        assert len(quals) == 1, "renewal must update in place, not duplicate"
        assert quals[0]["period"]["end"] == "2030-01-01"
        assert quals[0]["period"]["start"] == "2020-01-01"
        # Other qualification fields preserved
        assert quals[0]["issuer"]["display"] == "DEA"
        assert quals[0]["identifier"][0]["value"] == "DEA001"

    def test_merge_no_new_licenses_returns_skipped(self):
        prac = self._base_prac(
            action="merge",
            status="existing",
            existing_id="Practitioner/existing-xyz",
            licenses=[{
                "type": "STATE", "number": "MD001", "name": "", "license_state": "",
                "issue_date": "", "expiration_date": "", "primary_raw": "TRUE", "is_primary": True,
            }],
        )
        handler = make_handler(body={"practitioners": [prac]})

        # Existing resource already has this license
        existing_resource = {
            "id": "existing-xyz",
            "qualification": [
                {
                    "code": {"text": "STATE"},
                    "identifier": [
                        {
                            "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                            "value": "MD001",
                        }
                    ],
                }
            ],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        data = _extract_json(result)
        r = data["results"][0]
        assert r["status"] == "skipped"
        assert "no new licenses" in r["message"].lower()
        mock_put.assert_not_called()

    def test_merge_missing_existing_id_returns_error(self):
        prac = self._base_prac(action="merge", status="existing", existing_id=None)
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        data = _extract_json(result)
        r = data["results"][0]
        assert r["status"] == "error"

    def test_unknown_action_returns_error(self):
        prac = self._base_prac(action="delete")
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        data = _extract_json(result)
        r = data["results"][0]
        assert r["status"] == "error"
        assert "delete" in r["message"]

    def test_multiple_practitioners_processed(self):
        p1 = self._base_prac(action="create", email="a@x.com")
        p2 = self._base_prac(
            action="skip", status="existing",
            email="b@x.com", existing_id="Practitioner/bbb"
        )
        handler = make_handler(body={"practitioners": [p1, p2]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner") as mock_create, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner") as mock_build:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_build.return_value = {}
            mock_create.return_value = "Practitioner/new-aaa"

            result = handler.create_practitioners()

        data = _extract_json(result)
        assert len(data["results"]) == 2
        assert data["results"][0]["status"] == "created"
        assert data["results"][1]["status"] == "skipped"


# ---------------------------------------------------------------------------
# Create-practitioners error handling — Canvas rejections become per-row errors
# ---------------------------------------------------------------------------

class _FakeFhirResponse:
    """Mimic an httpx-style response object for HTTPStatusError payloads."""

    def __init__(self, status_code: int, json_body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


def _role_operation_outcome(role_code: str) -> dict:
    """Canvas's real 422 OperationOutcome payload for an unconfigured role code."""
    return {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": "error",
                "code": "business-rule",
                "details": {
                    "text": (
                        f"Cannot find 1 Staff role(s) for the given role_codes."
                        f"Missing roles: {{'{role_code}'}}"
                    )
                },
            }
        ],
    }


class TestCreatePractitionersErrorHandling:
    """Per-row errors from Canvas must not crash the batch, and must be surfaced
    to the UI with enough context (name, row, reason) for staff admins to act."""

    def _prac(self, **overrides):
        prac = {
            "source_row_number": 7,
            "email": "harry.potter@example.com",
            "first_name": "Harry",
            "last_name": "Potter",
            "role": "XY",
            "phone": "5555550100",
            "npi": "",
            "dob": "1980-03-15",
            "fax": "",
            "address": {},
            "location_reference": None,
            "primary_practice_location": "",
            "licenses": [],
            "status": "new",
            "existing_id": None,
            "action": "create",
        }
        prac.update(overrides)
        return prac

    def test_bad_role_returns_error_result_with_reason_and_name(self):
        prac = self._prac()
        handler = make_handler(body={"practitioners": [prac]})

        response = _FakeFhirResponse(status_code=422, json_body=_role_operation_outcome("XY"))
        http_err = requests.HTTPError("422 Unprocessable Entity", response=response)

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner", side_effect=http_err), \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        data = _extract_json(result)
        assert len(data["results"]) == 1
        r = data["results"][0]
        assert r["status"] == "error"
        assert r["row"] == 7
        assert r["first_name"] == "Harry"
        assert r["last_name"] == "Potter"
        assert r["staff_key"] is None
        assert "XY" in r["message"]
        assert "Staff role" in r["message"]
        # Role-related errors get the help URL appended so the UI can linkify it.
        assert _HELP_URL in r["message"]

    def test_non_role_error_is_surfaced_without_help_url(self):
        """Generic Canvas error (e.g. bad birthDate) — no help URL annotation."""
        prac = self._prac(role="MD")
        handler = make_handler(body={"practitioners": [prac]})

        body = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid",
                       "details": {"text": "birthDate is not a valid date"}}],
        }
        response = _FakeFhirResponse(status_code=400, json_body=body)
        http_err = requests.HTTPError("400", response=response)

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner", side_effect=http_err), \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "error"
        assert "birthDate" in r["message"]
        assert _HELP_URL not in r["message"]

    def test_one_bad_row_does_not_abort_batch(self):
        """A 422 on row 1 must not stop row 2 from being created."""
        bad = self._prac(source_row_number=2, email="bad@x.com", first_name="Bad", role="XY")
        good = self._prac(source_row_number=3, email="ok@x.com", first_name="OK", role="MD")
        handler = make_handler(body={"practitioners": [bad, good]})

        response = _FakeFhirResponse(status_code=422, json_body=_role_operation_outcome("XY"))
        http_err = requests.HTTPError("422", response=response)

        def fake_create(_client, resource):
            # Pick which call fails based on the email in the built resource.
            # (Simpler: use side_effect list.)
            raise AssertionError("should use side_effect list")

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner",
                   side_effect=[http_err, "Practitioner/ok-id"]), \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        results = _extract_json(result)["results"]
        assert len(results) == 2
        assert results[0]["status"] == "error"
        assert results[0]["first_name"] == "Bad"
        assert results[1]["status"] == "created"
        assert results[1]["first_name"] == "OK"
        assert results[1]["staff_key"] == "ok-id"

    def test_pydantic_path_error_is_humanised(self):
        """FHIR validator errors like
        'body -> qualification -> 0 -> issuer — field required' must be
        translated to readable text that names the license and the field."""
        prac = self._prac(role="MD")
        handler = make_handler(body={"practitioners": [prac]})

        body = {
            "resourceType": "OperationOutcome",
            "issue": [{
                "severity": "error",
                "code": "invalid",
                "details": {"text":
                    "body -> qualification -> 0 -> issuer — field required (type=value_error)"
                },
            }],
        }
        response = _FakeFhirResponse(status_code=400, json_body=body)
        http_err = requests.HTTPError("400", response=response)

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner", side_effect=http_err), \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        msg = _extract_json(result)["results"][0]["message"]
        assert "License 1" in msg
        assert "issuer" in msg.lower()
        assert "required" in msg.lower()
        # The raw pydantic path should NOT leak into the user-facing text.
        assert "body ->" not in msg
        assert "type=value_error" not in msg

    def test_exception_without_response_attr_still_produces_error(self):
        """Network errors (no .response) should surface str(exc) as the message."""
        prac = self._prac()
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner",
                   side_effect=requests.RequestException("network unreachable")), \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "error"
        assert "network unreachable" in r["message"]


class TestAddressRoundTrip:
    """Regression test for the preview→Import schema mismatch:
    parse_and_validate returns nested ``address: {line1, line2, city, state, zip}``
    for the UI, the UI sends that back on Import, and _do_create has to
    expand it back to the flat keys build_fhir_practitioner reads from."""

    def test_nested_address_from_ui_lands_in_fhir_payload(self):
        prac = {
            "source_row_number": 5,
            "email": "addr@example.com",
            "first_name": "Addr",
            "last_name": "Person",
            "role": "MD",
            "phone": "5555550100",
            "npi": "",
            "dob": "1990-01-01",
            "fax": "",
            "address": {
                "line1": "987 Cedar Blvd",
                "line2": "Suite 4",
                "city": "Austin",
                "state": "TX",
                "zip": "78701",
            },
            "location_reference": None,
            "primary_practice_location": "",
            "licenses": [],
            "status": "new",
            "existing_id": None,
            "action": "create",
        }
        handler = make_handler(body={"practitioners": [prac]})

        captured: dict[str, Any] = {}

        def _spy(_client, resource):
            captured["resource"] = resource
            return "Practitioner/new-uuid"

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner",
                   side_effect=_spy):

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            handler.create_practitioners()

        assert "address" in captured["resource"], (
            "FHIR resource is missing the address field — _expand_address_for_fhir "
            "must un-flatten the nested UI shape before build_fhir_practitioner runs."
        )
        addr = captured["resource"]["address"][0]
        assert addr["line"] == ["987 Cedar Blvd", "Suite 4"]
        assert addr["city"] == "Austin"
        assert addr["state"] == "TX"
        assert addr["postalCode"] == "78701"

    def test_existing_flat_keys_take_precedence_over_nested(self):
        """Defensive: if a caller somehow supplies both shapes, the explicit
        flat keys win — we never overwrite a real value with the nested
        version."""
        from typing import Any
        from practitioner_bulk_loader.api.bulk_upload_api import _expand_address_for_fhir
        prac: dict[str, Any] = {
            "address_line1": "FLAT WINS",
            "address": {"line1": "nested loses"},
        }
        _expand_address_for_fhir(prac)
        assert prac["address_line1"] == "FLAT WINS"


def _username_collision_error():
    """Reusable HTTP error simulating Canvas's username-collision 422."""
    body = {
        "resourceType": "OperationOutcome",
        "issue": [{
            "severity": "error",
            "code": "business-rule",
            "details": {"text":
                "Cannot create Staff with default generated username `mariagarcia` "
                "because Staff with same first name and last name already exists. "
                "Please provide unique username in payload."
            },
        }],
    }
    response = _FakeFhirResponse(status_code=422, json_body=body)
    return requests.HTTPError("422 Unprocessable Entity", response=response)


class TestCreatePractitionersUsernameRetry:
    """Smart fallback: first POST has no username (Canvas auto-generates
    ``firstlast``); on a username-collision 422 we retry once with an explicit
    ``first.last`` override before surfacing an error."""

    def _prac(self, **overrides):
        prac = {
            "source_row_number": 7,
            "email": "maria.garcia@example.com",
            "first_name": "Maria",
            "last_name": "Garcia",
            "role": "MA",
            "phone": "5555550100",
            "npi": "",
            "dob": "1995-11-03",
            "fax": "",
            "address": {},
            "location_reference": None,
            "primary_practice_location": "",
            "licenses": [],
            "status": "new",
            "existing_id": None,
            "action": "create",
        }
        prac.update(overrides)
        return prac

    def test_collision_triggers_retry_with_first_dot_last(self):
        prac = self._prac()
        handler = make_handler(body={"practitioners": [prac]})

        # First call collides; second call (the retry) succeeds.
        side_effects = [_username_collision_error(), "Practitioner/new-id-456"]

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner",
                   side_effect=side_effects) as mock_create, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner") as mock_build:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_build.return_value = {"resourceType": "Practitioner"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "created"
        assert r["staff_key"] == "new-id-456"
        # First call: no username override; second call: maria.garcia.
        assert mock_create.call_count == 2
        assert mock_build.call_count == 2
        first_call_kwargs = mock_build.call_args_list[0].kwargs
        retry_call_kwargs = mock_build.call_args_list[1].kwargs
        assert "username_override" not in first_call_kwargs
        assert retry_call_kwargs["username_override"] == "maria.garcia"

    def test_non_collision_error_is_not_retried(self):
        """A different 422 (e.g. unknown role) must not trigger the retry —
        we'd just be wasting a second POST and confusing the error path."""
        prac = self._prac(role="WIZARD")
        handler = make_handler(body={"practitioners": [prac]})

        body = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "business-rule",
                       "details": {"text": "Cannot find 1 Staff role(s) for the given role_codes.Missing roles: {'WIZARD'}"}}],
        }
        response = _FakeFhirResponse(status_code=422, json_body=body)
        err = requests.HTTPError("422", response=response)

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner",
                   side_effect=err) as mock_create, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "error"
        assert "Staff role" in r["message"]
        assert mock_create.call_count == 1  # no retry

    def test_retry_failure_surfaces_second_error(self):
        """If the retry also fails, the second error becomes the message
        (not the original collision text)."""
        prac = self._prac()
        handler = make_handler(body={"practitioners": [prac]})

        # Second collision on the retry — Canvas claims first.last is taken too.
        second_error = _username_collision_error()
        side_effects = [_username_collision_error(), second_error]

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner",
                   side_effect=side_effects) as mock_create, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "error"
        assert mock_create.call_count == 2

    def test_no_retry_when_name_sanitises_to_empty(self):
        """A name that's all non-ASCII (e.g. 李 王) → build_username() returns
        empty → no retry possible. The original collision error is surfaced."""
        prac = self._prac(first_name="李", last_name="王")
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.create_practitioner",
                   side_effect=_username_collision_error()) as mock_create, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.build_fhir_practitioner", return_value={}):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "error"
        assert mock_create.call_count == 1  # no retry attempted


# ---------------------------------------------------------------------------
# humanise_fhir_error — pydantic path → end-user sentence
# ---------------------------------------------------------------------------

class TestHumaniseFhirError:
    def test_field_required_on_qualification(self):
        raw = "body -> qualification -> 0 -> issuer — field required (type=value_error)"
        out = humanise_fhir_error(raw)
        assert out == "License 1: Issuer is required."

    def test_qualification_index_plus_one(self):
        """Qualification index is zero-based in FHIR; users think one-based."""
        raw = "body -> qualification -> 2 -> code — field required (type=value_error)"
        out = humanise_fhir_error(raw)
        assert out.startswith("License 3:")

    def test_regex_mismatch_is_translated_to_named_field(self):
        """Regex-mismatch errors must name the actual CSV column the staff
        admin should fix — not opaque labels like "value" or "text". The
        path-aware resolver maps ``extension -> 0 -> valueString`` to the
        License Name column (slot 0 is the issuing-authority-short-name
        extension that the plugin populates from License Name)."""
        raw = (
            "body -> qualification -> 0 -> extension -> 0 -> valueString — "
            'string does not match regex "[ \\r\\n\\t\\S]+" (type=value_error.str.regex)'
        )
        out = humanise_fhir_error(raw)
        assert "License 1" in out
        assert "License Name" in out  # path-aware label, not raw "valueString"
        assert "blank" in out.lower() or "required" in out.lower()
        assert "body ->" not in out
        assert "regex" not in out.lower()

    def test_regex_mismatch_on_code_text_names_license_type(self):
        """code.text comes only from License Type — so an empty regex
        mismatch there must translate to a clear "License Type is required"
        message, not the cryptic "text is empty"."""
        raw = (
            "body -> qualification -> 1 -> code -> text — "
            'string does not match regex "[ \\r\\n\\t\\S]+" (type=value_error.str.regex)'
        )
        out = humanise_fhir_error(raw)
        assert "License 2" in out
        assert "License Type" in out

    def test_identifier_system_path_named(self):
        """``identifier -> 0 -> system`` → "Issuing Authority URL" so
        the staff admin recognises which FHIR field is at fault when
        Canvas's PUT validator complains about a stale system value
        (typically a legacy record with a blank Issuing authority url)."""
        raw = (
            "body -> qualification -> 0 -> identifier -> 0 -> system — "
            "must be set to: http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url"
        )
        out = humanise_fhir_error(raw)
        assert "License 1" in out
        assert "Issuing Authority URL" in out

    def test_identifier_value_path_named(self):
        raw = (
            "body -> qualification -> 0 -> identifier -> 0 -> value — "
            'string does not match regex "[ \\r\\n\\t\\S]+" (type=value_error.str.regex)'
        )
        out = humanise_fhir_error(raw)
        assert "License 1" in out
        assert "License Number" in out

    def test_top_level_identifier_value_named_NPI_not_license_number(self):
        """The Practitioner-level ``identifier`` slot holds the NPI, not
        a license number. Without disambiguation we'd label a missing-NPI
        error as 'License Number is required' which sends the staff admin
        looking at the wrong column."""
        raw = (
            "body -> identifier -> 0 -> value — "
            'string does not match regex "[ \\r\\n\\t\\S]+" (type=value_error.str.regex)'
        )
        out = humanise_fhir_error(raw)
        # No "License N:" prefix because the path has no qualification index.
        assert "License" not in out
        assert "NPI" in out


class TestNormalizeExistingQualificationLicenseName:
    """Sanitiser fills blank ``issuer.display`` and short-name extension
    ``valueString`` slots with ``"{License Type} {License State}"`` so
    legacy records (saved through the Canvas admin UI without an
    "Issuing authority long/short name") clear Canvas's PUT validator.

    An existing Practitioner has an
    AL "State license" with both Issuing authority long and short name
    fields blank. Merge fails with "License 1: License Name is required."
    With the sanitiser, those slots get filled with "STATE AL" — drawn
    entirely from data already on the qualification (code.text + state
    extension valueString)."""

    def test_blank_display_filled_with_type_plus_state(self):
        """Legacy-blank-issuer case end-to-end on the helper level."""
        qual = {
            "code": {"text": "STATE"},
            "issuer": {
                "display": "",
                "extension": [
                    {
                        "url": _ISSUING_AUTHORITY_SHORT_NAME_URL,
                        "valueString": "",
                    },
                    {
                        "url": _ISSUING_AUTHORITY_STATE_URL,
                        "valueString": "AL",
                    },
                ],
            },
        }
        out = _normalize_existing_qualification_license_name(qual)
        assert out["issuer"]["display"] == "STATE AL"
        # short-name extension also filled with the same fallback
        short_name_ext = next(
            e for e in out["issuer"]["extension"]
            if e["url"] == _ISSUING_AUTHORITY_SHORT_NAME_URL
        )
        assert short_name_ext["valueString"] == "STATE AL"
        # State extension value is unchanged.
        state_ext = next(
            e for e in out["issuer"]["extension"]
            if e["url"] == _ISSUING_AUTHORITY_STATE_URL
        )
        assert state_ext["valueString"] == "AL"

    def test_blank_display_with_no_state_extension_falls_back_to_type_only(self):
        """For a DEA license (no state applicable) the fallback is just
        the License Type — joining empty state would leave a trailing
        space artefact."""
        qual = {
            "code": {"text": "DEA"},
            "issuer": {
                "display": "",
                "extension": [
                    {
                        "url": _ISSUING_AUTHORITY_SHORT_NAME_URL,
                        "valueString": "",
                    },
                ],
            },
        }
        out = _normalize_existing_qualification_license_name(qual)
        assert out["issuer"]["display"] == "DEA"
        assert out["issuer"]["extension"][0]["valueString"] == "DEA"

    def test_existing_display_left_alone(self):
        """If the existing record already has a real License Name on
        file (e.g. "Alabama Medical Board"), the sanitiser must NOT
        overwrite it — that's existing data, not a slot to fill."""
        qual = {
            "code": {"text": "STATE"},
            "issuer": {
                "display": "Alabama Medical Board",
                "extension": [
                    {
                        "url": _ISSUING_AUTHORITY_SHORT_NAME_URL,
                        "valueString": "AL Med Board",
                    },
                    {
                        "url": _ISSUING_AUTHORITY_STATE_URL,
                        "valueString": "AL",
                    },
                ],
            },
        }
        out = _normalize_existing_qualification_license_name(qual)
        assert out is qual  # no change, identity preserved

    def test_blank_code_text_with_no_state_returns_input(self):
        """No fallback can be computed when both License Type and
        License State are blank — leave the qualification alone so the
        downstream Canvas error still surfaces and prompts a manual fix."""
        qual = {
            "code": {"text": ""},
            "issuer": {
                "display": "",
                "extension": [
                    {"url": _ISSUING_AUTHORITY_SHORT_NAME_URL, "valueString": ""},
                ],
            },
        }
        out = _normalize_existing_qualification_license_name(qual)
        assert out is qual

    def test_only_short_name_blank_filled_from_display(self):
        """When display is populated and short-name slot is blank, fill
        short-name with the existing display value — preserves the
        admin's chosen label (e.g. 'Florida Medical Board') instead of
        replacing it with the systematic '{TYPE} {STATE}' form."""
        qual = {
            "code": {"text": "STATE"},
            "issuer": {
                "display": "Florida Medical Board",
                "extension": [
                    {"url": _ISSUING_AUTHORITY_SHORT_NAME_URL, "valueString": ""},
                    {"url": _ISSUING_AUTHORITY_STATE_URL, "valueString": "FL"},
                ],
            },
        }
        out = _normalize_existing_qualification_license_name(qual)
        assert out["issuer"]["display"] == "Florida Medical Board"  # unchanged
        short_name = next(
            e for e in out["issuer"]["extension"]
            if e["url"] == _ISSUING_AUTHORITY_SHORT_NAME_URL
        )
        assert short_name["valueString"] == "Florida Medical Board"

    def test_missing_short_name_extension_inserted_at_slot_0(self):
        """Legacy-record scenario: an existing
        qualification had no short-name extension at all — just state and
        license-primary. Canvas's PUT validator rejected the merge with
        'License 1: Url: must be set to: …short-name'. The fix inserts
        a short-name extension at slot 0 with the existing display value
        as its valueString, so the PUT body satisfies the position-
        sensitive validator."""
        qual = {
            "code": {"text": "STATE"},
            "issuer": {
                "display": "Texas Medical Board",
                "extension": [
                    {"url": _ISSUING_AUTHORITY_STATE_URL, "valueString": "TX"},
                    {"url": "http://schemas.canvasmedical.com/fhir/extensions/license-primary",
                     "valueBoolean": False},
                ],
            },
        }
        out = _normalize_existing_qualification_license_name(qual)
        exts = out["issuer"]["extension"]
        # Slot 0 must be short-name with non-empty value.
        assert exts[0]["url"] == _ISSUING_AUTHORITY_SHORT_NAME_URL
        assert exts[0]["valueString"] == "Texas Medical Board"
        # State and license-primary preserved in original relative order.
        assert exts[1]["url"] == _ISSUING_AUTHORITY_STATE_URL
        assert exts[1]["valueString"] == "TX"
        assert exts[2]["url"] == (
            "http://schemas.canvasmedical.com/fhir/extensions/license-primary"
        )

    def test_missing_short_name_falls_back_when_display_also_blank(self):
        """If both display and short-name are missing, fall back to the
        systematic '{TYPE} {STATE}' form. Drawn from data already on
        the qualification."""
        qual = {
            "code": {"text": "STATE"},
            "issuer": {
                "extension": [
                    {"url": _ISSUING_AUTHORITY_STATE_URL, "valueString": "TX"},
                ],
            },
        }
        out = _normalize_existing_qualification_license_name(qual)
        exts = out["issuer"]["extension"]
        assert exts[0]["url"] == _ISSUING_AUTHORITY_SHORT_NAME_URL
        assert exts[0]["valueString"] == "STATE TX"
        assert out["issuer"]["display"] == "STATE TX"


class TestMergeFillsBlankLicenseName:
    """End-to-end legacy-blank-issuer scenario: existing Practitioner has a legacy
    qualification with blank Issuing authority long/short name. Merge
    sanitiser fills those slots with "STATE AL" before PUT so Canvas's
    "License N: License Name is required" complaint clears."""

    def test_existing_blank_license_name_filled_in_put_body(self):
        prac = {
            "source_row_number": 2, "email": "jane.smith@example.com",
            "first_name": "Jane", "last_name": "Smith", "role": "NP",
            "phone": "3149492124", "npi": "1063878189", "dob": "1989-07-12",
            "fax": "3144455455", "address": {}, "location_reference": None,
            "primary_practice_location": "",
            "licenses": [{
                "type": "State license", "number": "203366", "name": "",
                "license_state": "AK",
                "issue_date": "2023-02-22", "expiration_date": "2026-11-30",
                "primary_raw": "", "is_primary": False,
            }],
            "status": "existing",
            "existing_id": "Practitioner/lori-id",
            "action": "merge",
        }
        handler = make_handler(body={"practitioners": [prac]})

        # An existing AL license — blank long/short name slots, state
        # populated, identifier value present. Mirrors the behavior observed on a real Canvas instance
        # screenshot from UAT.
        existing_resource = {
            "id": "lori-id",
            "qualification": [{
                "code": {"text": "STATE"},
                "period": {"start": "2000-04-16", "end": "2026-04-16"},
                "issuer": {
                    "display": "",
                    "extension": [
                        {
                            "url": _ISSUING_AUTHORITY_SHORT_NAME_URL,
                            "valueString": "",
                        },
                        {
                            "url": _ISSUING_AUTHORITY_STATE_URL,
                            "valueString": "AL",
                        },
                    ],
                },
                "identifier": [{
                    "system": _ISSUING_AUTHORITY_URL,
                    "value": "test",
                }],
            }],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"

        put_body = mock_put.call_args[0][2]
        # Existing AL license + new AK license appended
        assert len(put_body["qualification"]) == 2
        existing_qual = put_body["qualification"][0]
        new_qual = put_body["qualification"][1]

        # AL license now has the fallback filled in
        assert existing_qual["issuer"]["display"] == "STATE AL"
        short_name_ext = next(
            e for e in existing_qual["issuer"]["extension"]
            if e["url"] == _ISSUING_AUTHORITY_SHORT_NAME_URL
        )
        assert short_name_ext["valueString"] == "STATE AL"

        # AK license built from CSV uses the same fallback shape (CSV's
        # License Name was also blank).
        assert new_qual["issuer"]["display"] == "STATE AK"


class TestNormalizeExistingPractitionerIdentifier:
    """Sanitiser fills or drops blank top-level Practitioner identifiers
    (the NPI slot) on existing records before PUT. Real customer scenario:
    legacy records have NPI identifier present with blank value; Canvas's
    PUT validator rejects with "NPI is required" (which my path resolver
    used to mislabel as "License Number")."""

    def test_blank_npi_filled_from_csv(self):
        """CSV-supplied NPI fills the existing blank slot. This is the
        Existing record has NPI identifier with empty
        value, CSV row supplies a real NPI, plugin merges by writing it
        into the existing slot."""
        existing = {
            "identifier": [{"system": _NPI_SYSTEM, "value": ""}],
        }
        _normalize_existing_practitioner_identifier(existing, "1700199213")
        assert existing["identifier"][0]["value"] == "1700199213"
        assert existing["identifier"][0]["system"] == _NPI_SYSTEM

    def test_blank_npi_with_blank_csv_drops_entry(self):
        """When CSV also has no NPI, drop the empty identifier entry —
        we have no legitimate value to fill it with, and Canvas rejects
        empty values."""
        existing = {
            "identifier": [{"system": _NPI_SYSTEM, "value": ""}],
        }
        _normalize_existing_practitioner_identifier(existing, "")
        assert "identifier" not in existing

    def test_existing_npi_value_left_alone(self):
        """Don't overwrite a real existing NPI even if the CSV has a
        different one — merges shouldn't silently rewrite identifying
        data the staff admin didn't ask to change."""
        existing = {
            "identifier": [{"system": _NPI_SYSTEM, "value": "9999999999"}],
        }
        _normalize_existing_practitioner_identifier(existing, "1700199213")
        assert existing["identifier"][0]["value"] == "9999999999"

    def test_no_identifier_field_synthesizes_from_csv(self):
        """v0.1.39: if the existing record has no top-level identifier at
        all, add one from the CSV NPI (which is DEFAULT_NPI when blank).
        Canvas requires every Practitioner to have an NPI; the old
        no-op behavior left merged records without one."""
        existing: dict[str, Any] = {"name": [{"given": ["A"], "family": "B"}]}
        _normalize_existing_practitioner_identifier(existing, "1700199213")
        assert existing["identifier"] == [
            {"system": _NPI_SYSTEM, "value": "1700199213"}
        ]

    def test_no_identifier_field_with_blank_csv_skips(self):
        """Edge case: caller passed a literally empty csv_npi (shouldn't
        happen in practice since the parser substitutes DEFAULT_NPI on
        blank rows). Don't synthesise an empty identifier — Canvas would
        reject the PUT."""
        existing: dict[str, Any] = {"name": [{"given": ["A"], "family": "B"}]}
        _normalize_existing_practitioner_identifier(existing, "")
        assert "identifier" not in existing

    def test_non_npi_blank_identifier_dropped(self):
        """Top-level identifier with some other system (unlikely but
        possible) and blank value gets dropped — degenerate data and we
        have no caller-provided value to fill it with."""
        existing = {
            "identifier": [
                {"system": "urn:something-else", "value": ""},
                {"system": _NPI_SYSTEM, "value": "1700199213"},
            ],
        }
        _normalize_existing_practitioner_identifier(existing, "1700199213")
        assert len(existing["identifier"]) == 1
        assert existing["identifier"][0]["system"] == _NPI_SYSTEM


class TestExtractExistingFieldValues:
    def test_extracts_all_fields_from_full_record(self):
        existing = {
            "name": [{"given": ["Jane", "M"], "family": "Smith"}],
            "birthDate": "1980-03-15",
            "identifier": [{"system": _NPI_SYSTEM, "value": "1234567893"}],
            "telecom": [
                {"system": "email", "value": "jane@example.com", "rank": 1},
                {"system": "phone", "value": "5555550100", "rank": 1},
                {"system": "fax", "value": "5555550101", "rank": 1},
            ],
            "address": [{
                "line": ["100 Main St", "Suite 5"],
                "city": "Queens",
                "state": "NY",
                "postalCode": "11375",
            }],
        }
        values = _extract_existing_field_values(existing)
        assert values == {
            "first_name": "Jane",
            "last_name": "Smith",
            "dob": "1980-03-15",
            "email": "jane@example.com",
            "phone": "5555550100",
            "fax": "5555550101",
            "npi": "1234567893",
            "address_line1": "100 Main St",
            "address_line2": "Suite 5",
            "city": "Queens",
            "state": "NY",
            "zip": "11375",
        }

    def test_picks_rank_1_telecom_when_multiple_of_same_system(self):
        existing = {
            "telecom": [
                {"system": "phone", "value": "5555550999", "rank": 2},
                {"system": "phone", "value": "5555550100", "rank": 1},
            ],
        }
        values = _extract_existing_field_values(existing)
        assert values["phone"] == "5555550100"

    def test_handles_missing_optional_fields(self):
        values = _extract_existing_field_values({})
        # All fields default to empty strings — no crashes on a phantom-thin record.
        assert values["first_name"] == ""
        assert values["npi"] == ""
        assert values["address_line2"] == ""


class TestComputeFieldConflicts:
    def _csv_prac(self, **overrides):
        prac = {
            "first_name": "Jane",
            "last_name": "Smith",
            "dob": "03-15-1980",
            "email": "jane.smith@example.com",
            "phone": "5555550100",
            "fax": "",
            "npi": "1234567893",
            "address_line1": "100 Main St",
            "address_line2": "",
            "city": "Queens",
            "state": "NY",
            "zip": "11375",
        }
        prac.update(overrides)
        return prac

    def _existing(self, **overrides):
        base = {
            "first_name": "Jane",
            "last_name": "Smith",
            "dob": "1980-03-15",
            "email": "jane.smith@example.com",
            "phone": "5555550100",
            "fax": "",
            "npi": "1234567893",
            "address_line1": "100 Main St",
            "address_line2": "",
            "city": "Queens",
            "state": "NY",
            "zip": "11375",
        }
        base.update(overrides)
        return base

    def test_no_conflicts_returns_empty(self):
        assert _compute_field_conflicts(self._csv_prac(), self._existing()) == []

    def test_dob_normalised_to_iso_before_comparison(self):
        """CSV MM-DD-YYYY vs existing YYYY-MM-DD for the same date should
        not register as a conflict."""
        csv = self._csv_prac(dob="03-15-1980")
        existing = self._existing(dob="1980-03-15")
        assert _compute_field_conflicts(csv, existing) == []

    def test_name_compared_case_insensitively(self):
        csv = self._csv_prac(first_name="JANE")
        existing = self._existing(first_name="jane")
        assert _compute_field_conflicts(csv, existing) == []

    def test_state_conflict_reported(self):
        conflicts = _compute_field_conflicts(
            self._csv_prac(state="NY"),
            self._existing(state="CA"),
        )
        assert len(conflicts) == 1
        assert conflicts[0] == {"field": "State", "csv": "NY", "existing": "CA"}

    def test_npi_conflict_reported(self):
        conflicts = _compute_field_conflicts(
            self._csv_prac(npi="9876543219"),
            self._existing(npi="1234567893"),
        )
        assert any(c["field"] == "NPI" for c in conflicts)

    def test_default_npi_surfaces_asymmetric_npi_conflict(self):
        """When the CSV row was blank (parser substituted DEFAULT_NPI) and
        Canvas already has a real NPI, surface that as a conflict so the
        admin sees Canvas's value in the diff panel. The CSV side is the
        empty string — distinguishing it from a real value mismatch — and
        the write path guards against clobbering the existing real NPI
        with the placeholder, so existing is preserved regardless of
        action."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(npi=DEFAULT_NPI),
            self._existing(npi="1234567893"),
        )
        npi_conflicts = [c for c in conflicts if c["field"] == "NPI"]
        assert len(npi_conflicts) == 1
        assert npi_conflicts[0]["csv"] == ""
        assert npi_conflicts[0]["existing"] == "1234567893"

    def test_blank_npi_no_conflict_when_existing_also_blank(self):
        """Asymmetric NPI surfacing only fires when Canvas has a real
        NPI. If both sides are empty, nothing to disclose."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(npi=DEFAULT_NPI),
            self._existing(npi=""),
        )
        assert not any(c["field"] == "NPI" for c in conflicts)

    def test_blank_npi_no_conflict_when_existing_is_placeholder(self):
        """A practitioner originally loaded with a blank NPI has the
        placeholder stored on Canvas. When that same row is re-uploaded
        with a still-blank NPI, both sides are effectively "no NPI on
        file" — surfacing a conflict here would be noise and would
        misleadingly imply the existing record has a real NPI."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(npi=DEFAULT_NPI),
            self._existing(npi=DEFAULT_NPI),
        )
        assert not any(c["field"] == "NPI" for c in conflicts)

    def test_real_csv_npi_against_existing_placeholder_no_phantom_conflict(self):
        """Inverse asymmetric case: existing Canvas record has the
        placeholder (loaded with blank NPI at some earlier point), CSV
        now supplies a real NPI. The placeholder is not a real existing
        value, so no conflict should surface — the upgrade is the
        intended outcome and the diff panel should not force an ack flow.
        Backend write correctly upgrades the placeholder to the real NPI
        regardless; this is the UX-side guard."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(npi="1234567893"),
            self._existing(npi=DEFAULT_NPI),
        )
        assert not any(c["field"] == "NPI" for c in conflicts)

    def test_phone_formatting_does_not_produce_phantom_conflict(self):
        """Canvas admin UI saves formatted phone like '(555) 555-0100',
        but Rule 3 enforces digits-only on the CSV side. Stripping non-
        digits before comparison prevents every admin-UI-entered record
        from producing a phantom Phone conflict on merge re-upload."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(phone="5555550100"),
            self._existing(phone="(555) 555-0100"),
        )
        assert not any(c["field"] == "Phone" for c in conflicts)

    def test_fax_formatting_does_not_produce_phantom_conflict(self):
        conflicts = _compute_field_conflicts(
            self._csv_prac(fax="5559990000"),
            self._existing(fax="555-999-0000"),
        )
        assert not any(c["field"] == "Fax" for c in conflicts)

    def test_genuine_phone_difference_still_surfaces(self):
        """Sanity: a real phone-number difference (different digits, not
        just formatting) must still produce a conflict."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(phone="5555550100"),
            self._existing(phone="(555) 999-9999"),
        )
        phone_conflicts = [c for c in conflicts if c["field"] == "Phone"]
        assert len(phone_conflicts) == 1

    def test_only_csv_value_no_conflict(self):
        """CSV has a state, existing is blank → fill-missing path, not a
        conflict. The address normalizer will write it."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(state="NY"),
            self._existing(state=""),
        )
        assert not any(c["field"] == "State" for c in conflicts)

    def test_only_existing_value_no_conflict(self):
        """Existing has a state, CSV is blank → CSV has nothing to say."""
        conflicts = _compute_field_conflicts(
            self._csv_prac(state=""),
            self._existing(state="CA"),
        )
        assert not any(c["field"] == "State" for c in conflicts)

    def test_multiple_field_conflicts(self):
        conflicts = _compute_field_conflicts(
            self._csv_prac(phone="5555550100", state="NY"),
            self._existing(phone="5559990000", state="CA"),
        )
        fields = {c["field"] for c in conflicts}
        assert fields == {"Phone", "State"}


class TestNormalizeExistingAddress:
    """Fill missing address fields on an existing Practitioner from CSV
    data during merge. Mirror the NPI fill-not-overwrite policy."""

    def _csv_prac(self, **overrides):
        prac = {
            "address_line1": "100 Main St",
            "address_line2": "Suite 5",
            "city": "Queens",
            "state": "NY",
            "zip": "11375",
        }
        prac.update(overrides)
        return prac

    def test_missing_address_built_from_csv(self):
        """Maria's bug: existing record has no address array, merge wrote
        nothing. After fix: full CSV address is written."""
        existing: dict[str, Any] = {}
        _normalize_existing_address(existing, self._csv_prac())
        assert existing["address"] == [{
            "use": "work",
            "type": "both",
            "country": "US",
            "line": ["100 Main St", "Suite 5"],
            "city": "Queens",
            "state": "NY",
            "postalCode": "11375",
        }]

    def test_empty_address_array_built_from_csv(self):
        existing: dict[str, Any] = {"address": []}
        _normalize_existing_address(existing, self._csv_prac())
        assert len(existing["address"]) == 1
        assert existing["address"][0]["state"] == "NY"

    def test_partial_existing_address_blanks_filled(self):
        """Existing has line+city but no state/zip; CSV provides them →
        state and postalCode get filled, existing line/city untouched."""
        existing = {"address": [{
            "use": "work",
            "type": "both",
            "line": ["999 Other St"],
            "city": "Different City",
        }]}
        _normalize_existing_address(existing, self._csv_prac())
        addr = existing["address"][0]
        assert addr["line"] == ["999 Other St"]  # not overwritten
        assert addr["city"] == "Different City"  # not overwritten
        assert addr["state"] == "NY"             # filled
        assert addr["postalCode"] == "11375"     # filled
        assert addr["country"] == "US"           # filled

    def test_populated_field_not_overwritten(self):
        """If existing has a real state (even if different from CSV), keep
        it. Same policy as NPI: don't silently rewrite identifying data."""
        existing = {"address": [{"state": "CA", "city": "LA"}]}
        _normalize_existing_address(existing, self._csv_prac())
        assert existing["address"][0]["state"] == "CA"

    def test_no_csv_address_is_noop(self):
        existing = {"address": [{"state": "CA"}]}
        _normalize_existing_address(existing, {
            "address_line1": "", "address_line2": "",
            "city": "", "state": "", "zip": "",
        })
        assert existing["address"][0] == {"state": "CA"}

    def test_no_existing_no_csv_is_noop(self):
        existing: dict[str, Any] = {}
        _normalize_existing_address(existing, {
            "address_line1": "", "city": "", "state": "", "zip": "",
        })
        assert "address" not in existing


class TestMergeFillsBlankNpi:
    """End-to-end: merging into a Practitioner whose existing record has
    blank NPI must fill it from the CSV row before PUT."""

    def test_existing_blank_npi_filled_in_put_body(self):
        prac = {
            "source_row_number": 6, "email": "frank@x.com",
            "first_name": "Frank", "last_name": "NoNpi", "role": "DO",
            "phone": "5555550100", "npi": "1700199213", "dob": "1980-01-01",
            "fax": "", "address": {}, "location_reference": None,
            "primary_practice_location": "",
            "licenses": [{
                "type": "STATE", "number": "NEW001", "name": "FL",
                "license_state": "FL",
                "issue_date": "2024-01-01", "expiration_date": "2028-01-01",
                "primary_raw": "FALSE", "is_primary": False,
            }],
            "status": "existing", "existing_id": "Practitioner/frank-id",
            "action": "merge",
        }
        handler = make_handler(body={"practitioners": [prac]})

        existing_resource = {
            "id": "frank-id",
            "identifier": [{"system": _NPI_SYSTEM, "value": ""}],
            "qualification": [],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        put_body = mock_put.call_args[0][2]
        npi_entry = next(
            i for i in put_body["identifier"] if i["system"] == _NPI_SYSTEM
        )
        assert npi_entry["value"] == "1700199213"

    def test_non_pydantic_error_passes_through(self):
        """Canvas's own business-rule messages should not be mangled."""
        raw = "Cannot find 1 Staff role(s) for the given role_codes.Missing roles: {'XY'}"
        out = humanise_fhir_error(raw)
        assert out == raw  # Unchanged — no "body ->" prefix to trigger translation.

    def test_type_suffix_stripped_even_when_path_absent(self):
        """(type=...) tails should be removed in all cases."""
        raw = "some unrelated message (type=value_error)"
        out = humanise_fhir_error(raw)
        assert "type=" not in out
        assert "some unrelated message" in out

    def test_empty_input_returns_empty(self):
        assert humanise_fhir_error("") == ""

    def test_practitioner_level_path(self):
        """Errors on non-qualification paths should still be translated (no License N: prefix)."""
        raw = "body -> telecom -> 0 -> value — field required (type=value_error)"
        out = humanise_fhir_error(raw)
        assert "License" not in out  # No license prefix for practitioner-level fields
        assert "required" in out.lower()

    def test_canvas_502_transient_message_replaced(self):
        """Canvas's "Unable to parse response from downstream server" gets a
        helpful actionable message pointing at the duplicate-Staff likely cause."""
        raw = "Unable to parse response from downstream server"
        out = humanise_fhir_error(raw)
        # The literal proxy text should not leak through to the admin.
        assert "Unable to parse" not in out
        assert "downstream" not in out
        # The replacement must point at duplicates and at next-step actions.
        assert "duplicate" in out.lower()
        assert "Staff" in out
        assert "Canvas" in out

    def test_canvas_405_method_not_allowed_replaced(self):
        """Cryptic '{"detail":"Method Not Allowed"}' gets turned into an
        actionable hint instead of leaking through verbatim."""
        raw = '{"detail":"Method Not Allowed"}'
        out = humanise_fhir_error(raw)
        assert '"detail"' not in out
        assert out.lower() != "method not allowed"
        # Should suggest a path forward.
        assert "Canvas" in out
        assert "Skip" in out or "support" in out.lower()

    def test_none_not_allowed_message(self):
        """pydantic 'none is not an allowed value' translates to '... is required.'"""
        raw = "body -> birthDate — none is not an allowed value (type=type_error.none.not_allowed)"
        out = humanise_fhir_error(raw)
        assert "date of birth" in out.lower()
        assert "required" in out.lower()

    def test_invalid_date_message(self):
        """'invalid date' / 'not a valid date' becomes '... is not a valid date.'"""
        raw = "body -> birthDate — not a valid date (type=value_error.date)"
        out = humanise_fhir_error(raw)
        assert "date of birth" in out.lower()
        assert "not a valid date" in out.lower()

    def test_fallback_message_uses_field_label_and_message(self):
        """When no known phrase matches, fall through to '{field}: {message}'."""
        raw = "body -> telecom — something else entirely"
        out = humanise_fhir_error(raw)
        # 'telecom' has a friendly label ('contact info') and the message
        # is preserved verbatim after the colon.
        assert "contact info" in out.lower()
        assert "something else entirely" in out


# ---------------------------------------------------------------------------
# Internal helpers — narrow tests for branches not reached above
# ---------------------------------------------------------------------------

class TestExpandAddressForFhir:
    """``_expand_address_for_fhir`` is a no-op when the nested address is
    missing or not a dict — exercised here so the early return is covered."""

    def test_missing_address_key_is_noop(self):
        prac: dict = {"first_name": "Jane"}
        _expand_address_for_fhir(prac)
        assert prac == {"first_name": "Jane"}

    def test_non_dict_address_is_noop(self):
        prac: dict = {"address": "123 Main St"}
        _expand_address_for_fhir(prac)
        # Nothing was expanded; the original (string) value stays intact.
        assert prac == {"address": "123 Main St"}


class TestIsUsernameCollision:
    """The match returns False when there's no extractable text."""

    def test_returns_false_when_no_response_and_empty_str(self):
        # No .response, str(exc) == "" → _extract_fumage_error_text returns
        # ("", "") → _is_username_collision short-circuits to False.
        exc = Exception("")
        assert _is_username_collision(exc) is False


class TestExtractFumageErrorText:
    """Direct tests for the three fall-through branches in error extraction."""

    def test_no_response_attr_uses_str_exc(self):
        status, text = _extract_fumage_error_text(RuntimeError("network unreachable"))
        assert status is None
        assert "network unreachable" in text

    def test_invalid_json_falls_back_to_response_text(self):
        """When response.json() raises and OperationOutcome can't be read,
        we use response.text (truncated to 500 chars)."""

        class BadJsonResponse:
            status_code = 500
            text = "internal server error: connection reset"

            def json(self):
                raise ValueError("not json")

        exc = Exception("boom")
        exc.response = BadJsonResponse()  # type: ignore[attr-defined]

        status, text = _extract_fumage_error_text(exc)
        assert status == 500
        assert "internal server error" in text

    def test_empty_response_text_falls_back_to_str_exc(self):
        """When response is present but has no JSON and no text, the final
        fallback is str(exc)."""

        class EmptyResponse:
            status_code = 503
            text = ""

            def json(self):
                raise ValueError("not json")

        exc = Exception("upstream timeout")
        exc.response = EmptyResponse()  # type: ignore[attr-defined]

        status, text = _extract_fumage_error_text(exc)
        assert status == 503
        assert "upstream timeout" in text


# ---------------------------------------------------------------------------
# MissingSecretError handling — both endpoints surface it as a 500 JSON error
# ---------------------------------------------------------------------------

class TestMissingSecretsHandling:
    def test_parse_and_validate_returns_500_when_secrets_missing(self):
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch(
            "practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client",
            side_effect=MissingSecretError("fumage-client-id is missing"),
        ):
            result = handler.parse_and_validate()

        # The first item should be a JSONResponse with the error message and
        # the right HTTP status — admins see a clear "configure secrets" hint
        # instead of a 500 traceback.
        for item in result:
            if isinstance(item, JSONResponse):
                assert item.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
                payload = json.loads(item.content)
                assert "fumage-client-id" in payload["error"]
                return
        pytest.fail("expected a JSONResponse in the result")

    def test_create_practitioners_returns_500_when_secrets_missing(self):
        prac = {
            "source_row_number": 2, "email": "a@x.com", "first_name": "A",
            "last_name": "B", "role": "MD", "phone": "5", "npi": "",
            "dob": "1980-01-01", "fax": "", "address": {},
            "location_reference": None, "primary_practice_location": "",
            "licenses": [], "status": "new", "existing_id": None,
            "action": "create",
        }
        handler = make_handler(body={"practitioners": [prac]})

        with patch(
            "practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client",
            side_effect=MissingSecretError("fumage-client-secret is missing"),
        ):
            result = handler.create_practitioners()

        for item in result:
            if isinstance(item, JSONResponse):
                assert item.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
                payload = json.loads(item.content)
                assert "fumage-client-secret" in payload["error"]
                return
        pytest.fail("expected a JSONResponse in the result")


# ---------------------------------------------------------------------------
# Graceful degradation — staff-directory query failures and merge errors
# ---------------------------------------------------------------------------

class TestParseAndValidateDirectoryFailureDegrades:
    """If the Staff ORM query itself blows up, the upload should keep going
    (with empty duplicate-detection indexes) rather than failing the whole
    batch — admins can re-run after the underlying issue is fixed."""

    def test_directory_exception_yields_new_status(self):
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory",
                   side_effect=RuntimeError("Staff ORM exploded")):

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}

            result = handler.parse_and_validate()

        data = _extract_json(result)
        # The pipeline still produced a row; with no directory entries it's "new".
        assert len(data["practitioners"]) == 1
        assert data["practitioners"][0]["status"] == "new"
        assert data["practitioners"][0]["match_reason"] is None

    def test_directory_exception_appends_top_level_warning(self):
        """Silent degradation would let admins unknowingly duplicate every
        Staff record. The response must carry a row=0 (upload-wide) warning
        so the UI banners it above the preview."""
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory",
                   side_effect=RuntimeError("Staff ORM exploded")):

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}

            result = handler.parse_and_validate()

        data = _extract_json(result)
        upload_warnings = [w for w in data["warnings"] if w["row"] == 0]
        assert len(upload_warnings) == 1
        msg = upload_warnings[0]["message"].lower()
        assert "duplicate detection unavailable" in msg
        assert "review existing staff" in msg


class TestSandboxImportSafety:
    """The plugin-runner sandbox disallows importing django. If the API module
    does, the whole BulkUploadAPI handler fails to load and every /bulk-upload
    route 404s — the application handler still loads, so the modal opens but its
    fetches fail. Guard against reintroduction."""

    def test_api_module_does_not_import_django(self):
        """A django import would unregister the handler and 404 its routes."""
        import re
        from pathlib import Path

        import practitioner_bulk_loader.api.bulk_upload_api as mod

        source = Path(mod.__file__).read_text()
        django_imports = re.findall(
            r"^[ \t]*(?:from|import)[ \t]+django\b.*$", source, re.MULTILINE
        )
        assert not django_imports, (
            f"bulk_upload_api imports django ({django_imports}); the plugin "
            "sandbox blocks django imports, so the SimpleAPI handler will not "
            "register and its routes 404"
        )


class TestMergeReadOrWriteFailure:
    def test_read_practitioner_failure_returns_error_result(self):
        """A failure inside the GET-modify-PUT sequence (e.g. 404 on read)
        must be surfaced as a per-row error, not crash the batch."""
        prac = {
            "source_row_number": 4, "email": "merge.fail@example.com",
            "first_name": "Merge", "last_name": "Fail", "role": "MD",
            "phone": "5555550100", "npi": "", "dob": "1980-01-01",
            "fax": "", "address": {}, "location_reference": None,
            "primary_practice_location": "",
            "licenses": [{
                "type": "DEA", "number": "DEA001", "name": "", "license_state": "",
                "issue_date": "", "expiration_date": "",
                "primary_raw": "FALSE", "is_primary": False,
            }],
            "status": "existing", "existing_id": "Practitioner/missing",
            "action": "merge",
        }
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner",
                   side_effect=requests.HTTPError("404 Not Found")):

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "error"
        assert "404 Not Found" in r["message"]
        # The row's identifying fields still come back so admins can locate it.
        assert r["row"] == 4
        assert r["first_name"] == "Merge"


class TestNormalizeExistingQualificationIdentifiers:
    """The merge path sanitises identifier system URLs on existing
    qualifications before PUTting back. URL only — other blank required
    fields are intentionally left alone so they surface as clear per-row
    errors instead of being silently masked."""

    def test_blank_system_is_replaced(self):
        qual = {
            "code": {"text": "STATE"},
            "identifier": [{"system": "", "value": "71140"}],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert out["identifier"][0]["system"] == _ISSUING_AUTHORITY_URL
        assert out["identifier"][0]["value"] == "71140"

    def test_missing_system_key_is_added(self):
        qual = {
            "code": {"text": "STATE"},
            "identifier": [{"value": "71140"}],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert out["identifier"][0]["system"] == _ISSUING_AUTHORITY_URL

    def test_wrong_system_url_is_corrected(self):
        qual = {
            "identifier": [{"system": "urn:oid:something-else", "value": "71140"}],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert out["identifier"][0]["system"] == _ISSUING_AUTHORITY_URL

    def test_correct_system_url_returns_input_unchanged(self):
        """No-op when identifier already has the canonical URL — avoid
        gratuitous dict-spread copies that bloat memory on large records."""
        qual = {
            "identifier": [{"system": _ISSUING_AUTHORITY_URL, "value": "71140"}],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert out is qual

    def test_qualification_without_identifier_returns_input_unchanged(self):
        """Don't synthesise an identifier where none existed — that's
        creating data, not normalising it (and we'd have no value to put
        in the identifier anyway)."""
        qual = {"code": {"text": "STATE"}, "issuer": {"display": "NY Board"}}
        out = _normalize_existing_qualification_identifiers(qual)
        assert out is qual

    def test_blank_value_identifier_is_dropped(self):
        """Identifier with blank value is degenerate data — there's nothing
        to identify. Drop it (preserving the qualification itself) so Canvas
        doesn't reject the merge with "License Number is required."""
        qual = {
            "code": {"text": "STATE"},
            "identifier": [{"system": "", "value": ""}],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert "identifier" not in out
        # Other qualification fields preserved
        assert out["code"]["text"] == "STATE"

    def test_partial_blank_value_drop_preserves_real_identifier(self):
        """Drop only blank-value entries; keep the ones with real numbers,
        and still rewrite their system URL."""
        qual = {
            "identifier": [
                {"system": "", "value": ""},        # drop
                {"system": "", "value": "71140"},   # keep, fix URL
            ],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert len(out["identifier"]) == 1
        assert out["identifier"][0]["value"] == "71140"
        assert out["identifier"][0]["system"] == _ISSUING_AUTHORITY_URL

    def test_whitespace_only_value_treated_as_blank(self):
        """A value of "   " is no more useful than ""; drop it too so
        we don't ship semantically-blank data Canvas will reject."""
        qual = {"identifier": [{"system": "x", "value": "   "}]}
        out = _normalize_existing_qualification_identifiers(qual)
        assert "identifier" not in out


class TestNormalizeExistingTelecom:
    """Sanitiser ensures every system in the existing telecom list has
    exactly one entry at ``rank=1``. Canvas's PUT validator rejects merges
    where there are multiple ``email + rank=1`` entries (or none); legacy
    customer data sometimes has both shapes. The sanitiser only rewrites
    rank metadata — no contact values are dropped, so we never lose an
    email/phone/fax address that was on file."""

    def test_empty_input_returns_empty(self):
        assert _normalize_existing_telecom([]) == []

    def test_single_entry_promoted_to_rank_1_when_unset(self):
        telecom = [{"system": "email", "value": "a@x.com"}]
        out = _normalize_existing_telecom(telecom)
        assert out[0]["rank"] == 1
        assert out[0]["value"] == "a@x.com"

    def test_single_entry_at_rank_1_returns_input_unchanged(self):
        telecom = [{"system": "email", "value": "a@x.com", "rank": 1}]
        out = _normalize_existing_telecom(telecom)
        assert out is telecom  # no copy — nothing to fix

    def test_duplicate_rank_1_emails_demoted(self):
        """Two emails both at rank=1 — keep the first as rank=1, demote
        the second to rank=2 so Canvas's "exactly one rank=1 email"
        constraint is satisfied."""
        telecom = [
            {"system": "email", "value": "primary@x.com", "rank": 1},
            {"system": "email", "value": "secondary@x.com", "rank": 1},
        ]
        out = _normalize_existing_telecom(telecom)
        assert out[0]["rank"] == 1
        assert out[1]["rank"] == 2
        # Both values preserved — no email lost.
        assert out[0]["value"] == "primary@x.com"
        assert out[1]["value"] == "secondary@x.com"

    def test_no_rank_1_email_among_existing_promotes_first(self):
        """Existing record has email entries but none at rank=1 (e.g. all
        rank=2 or rank missing). Promote the first occurrence."""
        telecom = [
            {"system": "email", "value": "a@x.com", "rank": 2},
            {"system": "email", "value": "b@x.com", "rank": 2},
        ]
        out = _normalize_existing_telecom(telecom)
        assert out[0]["rank"] == 1
        assert out[1]["rank"] == 2

    def test_email_and_phone_handled_independently(self):
        """Each system gets its own rank=1 — email rank=1, phone rank=1
        can coexist (the validator constraint is per-system)."""
        telecom = [
            {"system": "email", "value": "a@x.com"},
            {"system": "phone", "value": "5555550100"},
            {"system": "email", "value": "b@x.com", "rank": 1},
        ]
        out = _normalize_existing_telecom(telecom)
        # email: index 0 picked first, then b@x.com at index 2 was at rank=1
        # But the prefer-existing-rank-1 logic picks index 2 for email.
        # Phone: only one entry, gets rank=1.
        email_entries = [e for e in out if e["system"] == "email"]
        phone_entries = [e for e in out if e["system"] == "phone"]
        assert sum(1 for e in email_entries if e["rank"] == 1) == 1
        assert sum(1 for e in phone_entries if e["rank"] == 1) == 1

    def test_prefer_existing_rank_1_over_first_occurrence(self):
        telecom = [
            {"system": "email", "value": "a@x.com", "rank": 2},
            {"system": "email", "value": "b@x.com", "rank": 1},
        ]
        out = _normalize_existing_telecom(telecom)
        # b@x.com had rank=1 and should keep it; a@x.com stays at rank=2
        assert out[0]["rank"] == 2
        assert out[1]["rank"] == 1

    def test_phone_with_formatting_stripped_to_digits(self):
        """Real customer scenario: existing record has phone saved as
        ``(555) 555-0100`` — Canvas's UI accepts on save but the FHIR
        PUT validator rejects with "must only contain digits". Strip
        non-digits in place; preserve the actual number."""
        telecom = [
            {"system": "phone", "value": "(555) 555-0100", "rank": 1},
        ]
        out = _normalize_existing_telecom(telecom)
        assert out[0]["value"] == "5555550100"
        # Other fields preserved exactly.
        assert out[0]["system"] == "phone"
        assert out[0]["rank"] == 1

    def test_phone_with_dashes_stripped(self):
        telecom = [{"system": "phone", "value": "555-555-0100"}]
        out = _normalize_existing_telecom(telecom)
        assert out[0]["value"] == "5555550100"

    def test_fax_with_formatting_also_stripped(self):
        """Same digit-only constraint applies to fax."""
        telecom = [{"system": "fax", "value": "(555) 999-0000"}]
        out = _normalize_existing_telecom(telecom)
        assert out[0]["value"] == "5559990000"

    def test_email_value_left_alone(self):
        """Email values are not digit-only — letters and ``@`` are
        legitimate. Stripper must not touch them."""
        telecom = [{"system": "email", "value": "a@x.com", "rank": 1}]
        out = _normalize_existing_telecom(telecom)
        assert out[0]["value"] == "a@x.com"

    def test_phone_with_no_digits_dropped(self):
        """If after stripping the value is empty (e.g. it was ``"N/A"``),
        drop the entry — we don't ship empty contact info."""
        telecom = [
            {"system": "phone", "value": "N/A"},
            {"system": "email", "value": "a@x.com"},
        ]
        out = _normalize_existing_telecom(telecom)
        # Only the email entry survives.
        assert len(out) == 1
        assert out[0]["system"] == "email"

    def test_digits_only_phone_returns_input_unchanged(self):
        """Already-digit-only phone with rank=1: nothing to fix."""
        telecom = [{"system": "phone", "value": "5555550100", "rank": 1}]
        out = _normalize_existing_telecom(telecom)
        assert out is telecom


class TestHumaniseFhirErrorTelecomLabel:
    def test_telecom_value_path_named(self):
        """Real failure observed in production: a phone value with non-digit
        characters produced "Value: must only contain digits" with no
        useful context. Path-aware resolution gives the staff admin a
        recognisable field name."""
        raw = (
            "body -> telecom -> 0 -> value — must only contain digits"
        )
        out = humanise_fhir_error(raw)
        assert "Phone" in out or "fax" in out.lower() or "email" in out.lower()
        assert "must only contain digits" in out


class TestMergeSanitisesTelecom:
    """End-to-end: merging into a Practitioner whose existing telecom has
    multiple rank=1 emails (Canvas's "exactly one ContactPoint where
    system=email and rank=1" complaint) must rewrite ranks before PUT."""

    def test_existing_duplicate_rank_1_emails_normalised_in_put_body(self):
        prac = {
            "source_row_number": 5, "email": "x@x.com",
            "first_name": "X", "last_name": "Y", "role": "MD",
            "phone": "5555550100", "npi": "", "dob": "1980-01-01",
            "fax": "", "address": {}, "location_reference": None,
            "primary_practice_location": "",
            "licenses": [{
                "type": "STATE", "number": "NEW001", "name": "FL",
                "license_state": "FL",
                "issue_date": "2024-01-01", "expiration_date": "2028-01-01",
                "primary_raw": "FALSE", "is_primary": False,
            }],
            "status": "existing", "existing_id": "Practitioner/dup-id",
            "action": "merge",
        }
        handler = make_handler(body={"practitioners": [prac]})

        # Canvas legacy shape: two emails both at rank=1.
        existing_resource = {
            "id": "dup-id",
            "telecom": [
                {"system": "email", "value": "primary@x.com", "rank": 1},
                {"system": "phone", "value": "5555550100", "rank": 1},
                {"system": "email", "value": "secondary@x.com", "rank": 1},
            ],
            "qualification": [],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        put_body = mock_put.call_args[0][2]
        emails = [t for t in put_body["telecom"] if t["system"] == "email"]
        rank1_emails = [t for t in emails if t.get("rank") == 1]
        assert len(rank1_emails) == 1, (
            "Canvas's PUT validator requires exactly one email at rank=1; "
            "sanitiser must demote duplicates."
        )
        # Both email values still present (no data loss)
        assert {t["value"] for t in emails} == {"primary@x.com", "secondary@x.com"}

    def test_blank_license_type_is_left_alone(self):
        """Sanitiser must NOT auto-fill any required field other than
        the URL. A blank ``code.text`` (legacy data with no License Type
        on file) should pass through untouched so Canvas's checker
        rejects the row with a clear "License Type is required" error."""
        qual = {
            "code": {"text": ""},  # blank — staff admin must fix in Canvas UI
            "identifier": [{"system": "", "value": "71140"}],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert out["code"]["text"] == ""  # untouched
        assert out["identifier"][0]["system"] == _ISSUING_AUTHORITY_URL

    def test_other_qualification_fields_are_preserved(self):
        qual = {
            "code": {"text": "STATE"},
            "period": {"start": "2020-01-01", "end": "2026-01-01"},
            "issuer": {
                "display": "NY Board",
                "extension": [{
                    "url": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-short-name",
                    "valueString": "NY Medical Board",
                }],
            },
            "identifier": [{"system": "", "value": "71140"}],
        }
        out = _normalize_existing_qualification_identifiers(qual)
        assert out["period"] == qual["period"]
        assert out["issuer"] == qual["issuer"]
        assert out["code"] == qual["code"]


class TestMergeSanitisesIdentifierUrl:
    """End-to-end: a merge into a Practitioner whose existing qualifications
    have blank identifier system URLs must rewrite them on the PUT body."""

    def test_existing_blank_system_is_normalised_in_put_body(self):
        """Christopher Findley's screenshot shape: existing license has
        ``identifier[0].system = ""``. Plugin merge appends a new license
        and PUTs back; the existing identifier's system must be rewritten
        before PUT or Canvas rejects with "License N: System: must be
        set to: …"."""
        prac = {
            "source_row_number": 4, "email": "findley@x.com",
            "first_name": "Chris", "last_name": "Findley", "role": "MD",
            "phone": "5555550100", "npi": "", "dob": "1980-01-01",
            "fax": "", "address": {}, "location_reference": None,
            "primary_practice_location": "",
            "licenses": [{
                "type": "STATE", "number": "NEW001", "name": "FL Board",
                "license_state": "FL",
                "issue_date": "2024-01-01", "expiration_date": "2028-01-01",
                "primary_raw": "FALSE", "is_primary": False,
            }],
            "status": "existing", "existing_id": "Practitioner/findley-id",
            "action": "merge",
        }
        handler = make_handler(body={"practitioners": [prac]})

        # Canvas's stored shape mirrors the screenshot: a real value with
        # a blank system. Plus a second qualification with a wrong/legacy
        # system URL to confirm the sanitiser fires on both.
        existing_resource = {
            "id": "findley-id",
            "qualification": [
                {
                    "code": {"text": "STATE"},
                    "identifier": [{"system": "", "value": "71140"}],
                },
                {
                    "code": {"text": "STATE"},
                    "identifier": [{"system": "urn:legacy", "value": "45616"}],
                },
            ],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        put_resource = mock_put.call_args[0][2]
        for qual in put_resource["qualification"]:
            for ident in qual.get("identifier") or []:
                assert ident["system"] == _ISSUING_AUTHORITY_URL


class TestMergeMixedRenewalAndKeep:
    """When a practitioner has multiple existing qualifications and only one
    matches the incoming renewal, the unrelated qualifications are preserved
    untouched — covers the "incoming is None → append qual as-is" branch."""

    def test_unrelated_qualification_preserved_unchanged(self):
        prac = {
            "source_row_number": 9, "email": "mixed@example.com",
            "first_name": "Mixed", "last_name": "Renewal", "role": "MD",
            "phone": "5555550100", "npi": "", "dob": "1980-01-01",
            "fax": "", "address": {}, "location_reference": None,
            "primary_practice_location": "",
            "licenses": [{
                "type": "DEA", "number": "DEA001", "name": "", "license_state": "",
                "issue_date": "2020-01-01", "expiration_date": "2030-01-01",
                "primary_raw": "FALSE", "is_primary": False,
            }],
            "status": "existing", "existing_id": "Practitioner/mixed-id",
            "action": "merge",
        }
        handler = make_handler(body={"practitioners": [prac]})

        # Two existing quals: STATE (untouched) and DEA (renewed).
        existing_resource = {
            "id": "mixed-id",
            "qualification": [
                {
                    "code": {"text": "STATE"},
                    "period": {"start": "2019-01-01", "end": "2025-01-01"},
                    "identifier": [{
                        "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                        "value": "STATE001",
                    }],
                    "issuer": {"display": "State Board"},
                },
                {
                    "code": {"text": "DEA"},
                    "period": {"start": "2020-01-01", "end": "2026-01-01"},
                    "identifier": [{
                        "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                        "value": "DEA001",
                    }],
                    "issuer": {"display": "DEA"},
                },
            ],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc_map, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client_fn.return_value = MagicMock()
            mock_loc_map.return_value = {"main clinic": "Location/loc-1"}
            mock_read.return_value = existing_resource

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        put_resource = mock_put.call_args[0][2]
        quals = put_resource["qualification"]
        # 2 originals — STATE preserved, DEA renewed in place.
        assert len(quals) == 2
        state_qual = next(q for q in quals if q["code"]["text"] == "STATE")
        dea_qual = next(q for q in quals if q["code"]["text"] == "DEA")
        assert state_qual["period"]["end"] == "2025-01-01"  # untouched
        assert dea_qual["period"]["end"] == "2030-01-01"  # renewed


# ---------------------------------------------------------------------------
# _build_staff_directory — direct tests of the Staff-ORM-backed indexer
# ---------------------------------------------------------------------------

def _make_staff(
    staff_id="s1",
    first_name="Ada",
    last_name="Lovelace",
    birth_date=None,
    npi_number="",
    emails=(),
):
    """Build a MagicMock that quacks like a Staff row for _build_staff_directory.

    The indexer reads .first_name/.last_name/.birth_date/.npi_number directly
    and iterates .telecom.all() for StaffContactPoint-shaped objects with
    ``system`` and ``value`` attributes."""
    staff = MagicMock()
    staff.id = staff_id
    staff.first_name = first_name
    staff.last_name = last_name
    staff.birth_date = birth_date
    staff.npi_number = npi_number

    telecom_entries = []
    for email in emails:
        cp = MagicMock()
        cp.system = "email"
        cp.value = email
        telecom_entries.append(cp)
    staff.telecom.all.return_value = telecom_entries
    return staff


def _patch_staff_queryset(staff_rows):
    """Patch Staff.objects so the chained filter().only().prefetch_related()
    ends with .iterator() yielding the rows. The indexer chains four calls
    on the queryset; we return the same MagicMock from each so .iterator()
    on the final link iterates the provided list."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.only.return_value = qs
    qs.prefetch_related.return_value = qs
    qs.iterator.return_value = iter(staff_rows)
    return patch(
        "practitioner_bulk_loader.api.bulk_upload_api.Staff.objects",
        qs,
    )


class TestBuildStaffDirectory:
    """The Staff-ORM-backed duplicate-detection indexer. Builds four lookup
    tables keyed by email / NPI / (first, last, dob) / (first, last). All
    keys are lowercased / stripped, the placeholder NPI is excluded, and
    blank-DOB or blank-name staff are dropped from the relevant tables."""

    def test_empty_queryset_returns_empty_tables(self):
        with _patch_staff_queryset([]):
            out = _build_staff_directory()
        assert out == {"by_email": {}, "by_npi": {}, "by_name_dob": {}, "by_name": {}}

    def test_single_staff_indexed_by_all_four_keys(self):
        import datetime as _dt
        staff = _make_staff(
            staff_id="s-1",
            first_name="Ada",
            last_name="Lovelace",
            birth_date=_dt.date(1815, 12, 10),
            npi_number="1234567890",
            emails=("Ada@Example.com",),
        )
        with _patch_staff_queryset([staff]):
            out = _build_staff_directory()
        assert out["by_email"]["ada@example.com"]["id"] == "s-1"
        assert out["by_npi"]["1234567890"]["id"] == "s-1"
        assert out["by_name_dob"][("ada", "lovelace", "1815-12-10")]["id"] == "s-1"
        assert out["by_name"][("ada", "lovelace")] == [out["by_email"]["ada@example.com"]]

    def test_placeholder_npi_excluded(self):
        """Placeholder NPI is shared by every blank-NPI staff and would
        produce false-positive collisions if indexed."""
        staff = _make_staff(npi_number=DEFAULT_NPI)
        with _patch_staff_queryset([staff]):
            out = _build_staff_directory()
        assert DEFAULT_NPI not in out["by_npi"]
        assert out["by_npi"] == {}

    def test_blank_name_skips_name_indexes(self):
        """Blank first or last name → row is omitted from by_name and
        by_name_dob (the keys would collapse together and produce noise)."""
        import datetime as _dt
        staff = _make_staff(
            first_name="",
            last_name="Lovelace",
            birth_date=_dt.date(1815, 12, 10),
            emails=("only-email@example.com",),
        )
        with _patch_staff_queryset([staff]):
            out = _build_staff_directory()
        assert out["by_name"] == {}
        assert out["by_name_dob"] == {}
        # Email still indexed independently.
        assert "only-email@example.com" in out["by_email"]

    def test_blank_dob_skips_name_dob_but_keeps_by_name(self):
        staff = _make_staff(
            first_name="Ada", last_name="Lovelace", birth_date=None,
        )
        with _patch_staff_queryset([staff]):
            out = _build_staff_directory()
        assert out["by_name_dob"] == {}
        assert ("ada", "lovelace") in out["by_name"]

    def test_first_occurrence_wins_per_key(self):
        """Two staff sharing the same NPI/email/(name,dob) — only the first
        is indexed. The indexer chooses arbitrarily but consistently, so the
        downstream UI shows one match instead of a flapping list."""
        import datetime as _dt
        s1 = _make_staff(
            staff_id="s-1", npi_number="9999999999",
            emails=("dup@example.com",),
            birth_date=_dt.date(1980, 1, 1),
        )
        s2 = _make_staff(
            staff_id="s-2", npi_number="9999999999",
            emails=("dup@example.com",),
            birth_date=_dt.date(1980, 1, 1),
        )
        with _patch_staff_queryset([s1, s2]):
            out = _build_staff_directory()
        assert out["by_email"]["dup@example.com"]["id"] == "s-1"
        assert out["by_npi"]["9999999999"]["id"] == "s-1"
        assert out["by_name_dob"][("ada", "lovelace", "1980-01-01")]["id"] == "s-1"
        # by_name appends — both staff land here so the UI can show the count.
        assert len(out["by_name"][("ada", "lovelace")]) == 2

    def test_non_email_telecom_ignored(self):
        """Phone/fax entries on the Staff record must not pollute by_email."""
        staff = _make_staff()
        phone_cp = MagicMock()
        phone_cp.system = "phone"
        phone_cp.value = "5555550100"
        staff.telecom.all.return_value = [phone_cp]
        with _patch_staff_queryset([staff]):
            out = _build_staff_directory()
        assert out["by_email"] == {}

    def test_blank_email_value_skipped(self):
        """An empty email value is meaningless; the lookup key would be ""
        and collide with every other blank-email staff."""
        staff = _make_staff(emails=("", "  "))
        with _patch_staff_queryset([staff]):
            out = _build_staff_directory()
        assert out["by_email"] == {}


# ---------------------------------------------------------------------------
# _apply_csv_to_existing / _apply_csv_non_address / _apply_csv_address
# ---------------------------------------------------------------------------

class TestApplyCsvNonAddress:
    """Overwrite name / DOB / telecom / NPI on an existing FHIR resource."""

    def test_overwrites_family_and_given_when_csv_has_both(self):
        existing = {"name": [{"family": "OldLast", "given": ["OldFirst"]}]}
        _apply_csv_non_address(existing, {"first_name": "NewFirst", "last_name": "NewLast"})
        assert existing["name"][0]["family"] == "NewLast"
        assert existing["name"][0]["given"] == ["NewFirst"]

    def test_only_first_name_replaces_given_index_0(self):
        existing = {"name": [{"family": "Lovelace", "given": ["Ada", "Augusta"]}]}
        _apply_csv_non_address(existing, {"first_name": "Augusta", "last_name": ""})
        # Family untouched (CSV blank); given[0] replaced, given[1] preserved.
        assert existing["name"][0]["family"] == "Lovelace"
        assert existing["name"][0]["given"] == ["Augusta", "Augusta"]

    def test_empty_given_array_gets_first_name_inserted(self):
        existing = {"name": [{"family": "Lovelace"}]}
        _apply_csv_non_address(existing, {"first_name": "Ada", "last_name": ""})
        assert existing["name"][0]["given"] == ["Ada"]

    def test_no_name_array_created_from_csv(self):
        """Existing record had no ``name`` field; CSV provides first+last."""
        existing: dict[str, Any] = {}
        _apply_csv_non_address(existing, {"first_name": "Ada", "last_name": "Lovelace"})
        assert existing["name"][0]["family"] == "Lovelace"
        assert existing["name"][0]["given"] == ["Ada"]

    def test_blank_csv_name_leaves_existing_untouched(self):
        existing = {"name": [{"family": "Lovelace", "given": ["Ada"]}]}
        _apply_csv_non_address(existing, {"first_name": "", "last_name": ""})
        assert existing["name"][0] == {"family": "Lovelace", "given": ["Ada"]}

    def test_dob_overwritten_when_csv_has_value(self):
        existing = {"birthDate": "1900-01-01"}
        _apply_csv_non_address(existing, {"dob": "1815-12-10"})
        assert existing["birthDate"] == "1815-12-10"

    def test_blank_dob_leaves_existing_birth_date_alone(self):
        existing = {"birthDate": "1900-01-01"}
        _apply_csv_non_address(existing, {"dob": ""})
        assert existing["birthDate"] == "1900-01-01"

    def test_phone_upserted_into_rank_1_slot(self):
        existing = {"telecom": [
            {"system": "phone", "value": "5550000000", "rank": 1, "use": "work"},
        ]}
        _apply_csv_non_address(existing, {"phone": "5559990000"})
        phone_entries = [t for t in existing["telecom"] if t["system"] == "phone"]
        rank1 = [t for t in phone_entries if t.get("rank") == 1]
        assert len(rank1) == 1
        assert rank1[0]["value"] == "5559990000"

    def test_phone_appended_when_no_phone_entry_exists(self):
        existing = {"telecom": [{"system": "email", "value": "a@x.com", "rank": 1}]}
        _apply_csv_non_address(existing, {"phone": "5559990000"})
        phone = next(t for t in existing["telecom"] if t["system"] == "phone")
        assert phone == {"system": "phone", "value": "5559990000", "rank": 1, "use": "work"}

    def test_fax_handled_independently_of_phone(self):
        existing: dict[str, Any] = {}
        _apply_csv_non_address(existing, {"phone": "5550000001", "fax": "5550000002"})
        systems = {t["system"]: t["value"] for t in existing["telecom"]}
        assert systems == {"phone": "5550000001", "fax": "5550000002"}

    def test_no_phone_or_fax_means_no_telecom_field_created(self):
        """If existing had no telecom and CSV has no phone/fax, don't write
        an empty telecom array (some validators reject empty arrays)."""
        existing: dict[str, Any] = {}
        _apply_csv_non_address(existing, {"phone": "", "fax": ""})
        assert "telecom" not in existing

    def test_npi_updates_existing_identifier_in_place(self):
        existing = {"identifier": [{"system": _NPI_SYSTEM, "value": "1111111111"}]}
        _apply_csv_non_address(existing, {"npi": "2222222222"})
        assert existing["identifier"][0]["value"] == "2222222222"
        assert existing["identifier"][0]["system"] == _NPI_SYSTEM

    def test_npi_appended_when_identifier_slot_missing(self):
        existing: dict[str, Any] = {}
        _apply_csv_non_address(existing, {"npi": "1234567890"})
        assert existing["identifier"] == [{"system": _NPI_SYSTEM, "value": "1234567890"}]

    def test_blank_npi_does_not_create_identifier(self):
        existing: dict[str, Any] = {}
        _apply_csv_non_address(existing, {"npi": ""})
        assert "identifier" not in existing


class TestApplyCsvAddress:
    """Write the CSV address onto an existing Practitioner."""

    def _csv(self, **overrides):
        prac = {
            "address_line1": "100 Main St",
            "address_line2": "Suite 5",
            "city": "Queens",
            "state": "NY",
            "zip": "11375",
        }
        prac.update(overrides)
        return prac

    def test_overwrite_replaces_first_address_in_place(self):
        existing = {"address": [{"line": ["Old St"], "city": "Old City", "state": "CA"}]}
        _apply_csv_address(existing, self._csv(), address_mode="overwrite")
        assert existing["address"][0]["line"] == ["100 Main St", "Suite 5"]
        assert existing["address"][0]["city"] == "Queens"
        assert existing["address"][0]["state"] == "NY"
        assert existing["address"][0]["postalCode"] == "11375"
        assert existing["address"][0]["country"] == "US"
        assert len(existing["address"]) == 1  # replaced, not appended

    def test_additional_appends_second_entry(self):
        existing = {"address": [{"line": ["Primary St"], "city": "Primary City"}]}
        _apply_csv_address(existing, self._csv(), address_mode="additional")
        assert len(existing["address"]) == 2
        # Existing primary preserved.
        assert existing["address"][0] == {"line": ["Primary St"], "city": "Primary City"}
        # Appended new address has the CSV values.
        assert existing["address"][1]["city"] == "Queens"

    def test_no_existing_address_creates_one_regardless_of_mode(self):
        existing: dict[str, Any] = {}
        _apply_csv_address(existing, self._csv(), address_mode="additional")
        assert len(existing["address"]) == 1
        assert existing["address"][0]["city"] == "Queens"

    def test_blank_csv_address_is_noop(self):
        existing = {"address": [{"city": "Original"}]}
        _apply_csv_address(
            existing,
            {"address_line1": "", "address_line2": "", "city": "", "state": "", "zip": ""},
            address_mode="overwrite",
        )
        assert existing["address"][0] == {"city": "Original"}

    def test_partial_csv_only_writes_provided_fields(self):
        """Only the city + state come from CSV; line/zip stay absent on the
        new address. Country still defaults to US."""
        existing: dict[str, Any] = {}
        _apply_csv_address(
            existing,
            {"address_line1": "", "address_line2": "", "city": "Queens", "state": "NY", "zip": ""},
            address_mode="overwrite",
        )
        addr = existing["address"][0]
        assert addr == {"use": "work", "type": "both", "country": "US",
                        "city": "Queens", "state": "NY"}

    def test_overwrite_preserves_existing_id_and_extensions(self):
        """Real-world destructive case: existing address has an ``id``
        and a custom extension; CSV carries only Line 1 + City + State.
        Overwrite must merge into the existing dict so the ``id`` and
        extension survive — otherwise Canvas's PUT creates a new address
        record (per FHIR docs: ``id`` omitted on PUT means new record)
        and the custom extension is gone."""
        existing = {"address": [{
            "id": "addr-uuid-1",
            "use": "work", "type": "both", "country": "US",
            "line": ["Old St"], "city": "Old City",
            "state": "CA", "postalCode": "90000",
            "extension": [{"url": "http://example.com/custom", "valueString": "preserved"}],
        }]}
        _apply_csv_address(
            existing,
            {"address_line1": "100 Main St", "address_line2": "",
             "city": "Queens", "state": "NY", "zip": ""},
            address_mode="overwrite",
        )
        addr = existing["address"][0]
        # CSV slots applied.
        assert addr["line"] == ["100 Main St"]
        assert addr["city"] == "Queens"
        assert addr["state"] == "NY"
        # Non-CSV slots preserved.
        assert addr["id"] == "addr-uuid-1"
        assert addr["extension"] == [
            {"url": "http://example.com/custom", "valueString": "preserved"}
        ]
        # postalCode: CSV blank, existing populated → preserved.
        assert addr["postalCode"] == "90000"

    def test_overwrite_preserves_existing_line2_when_csv_line2_blank(self):
        """Most common destructive case: existing has 'Suite 200' in Line 2;
        CSV updates Line 1 but leaves Line 2 blank (admin didn't think to
        re-type the apartment number). Pre-fix: Suite 200 silently destroyed.
        Post-fix: the line array is treated as a unit — CSV provided
        Line 1 (and blank Line 2), and the line update is a deliberate
        replace, not a per-slot merge. So in this overwrite-mode call the
        line array becomes ['200 Oak Ave']. The point of this test is to
        lock in that the OTHER slots (city/state/zip the CSV did populate,
        and the id/extension/etc. the CSV doesn't touch) all survive."""
        existing = {"address": [{
            "id": "addr-uuid-1",
            "use": "work", "type": "both", "country": "US",
            "line": ["100 Main St", "Suite 200"],
            "city": "Brooklyn", "state": "NY", "postalCode": "11201",
        }]}
        _apply_csv_address(
            existing,
            {"address_line1": "200 Oak Ave", "address_line2": "",
             "city": "Manhattan", "state": "NY", "zip": "10001"},
            address_mode="overwrite",
        )
        addr = existing["address"][0]
        assert addr["line"] == ["200 Oak Ave"]  # CSV said line is just this
        assert addr["city"] == "Manhattan"
        assert addr["state"] == "NY"
        assert addr["postalCode"] == "10001"
        # id survives so PUT updates the existing record, doesn't orphan it.
        assert addr["id"] == "addr-uuid-1"

    def test_overwrite_zip_only_does_not_destroy_other_fields(self):
        """Edge case from the user-facing 'I just want to fix the zip'
        flow. Existing record has full address; CSV row carries only the
        zip update. Pre-fix: line/city/state silently destroyed. Post-fix:
        only the zip slot changes, everything else preserved."""
        existing = {"address": [{
            "id": "addr-uuid-1",
            "use": "work", "type": "both", "country": "US",
            "line": ["100 Main St", "Suite 200"],
            "city": "Brooklyn", "state": "NY", "postalCode": "11200",  # wrong zip
        }]}
        _apply_csv_address(
            existing,
            {"address_line1": "", "address_line2": "",
             "city": "", "state": "", "zip": "11201"},
            address_mode="overwrite",
        )
        addr = existing["address"][0]
        assert addr["postalCode"] == "11201"  # the fix
        # Everything else preserved.
        assert addr["line"] == ["100 Main St", "Suite 200"]
        assert addr["city"] == "Brooklyn"
        assert addr["state"] == "NY"
        assert addr["id"] == "addr-uuid-1"


class TestApplyCsvToExisting:
    """Dispatch wrapper: ``scope=all`` overwrites name+telecom+NPI+address;
    ``scope=address_only`` skips the non-address fields entirely."""

    def test_scope_all_overwrites_name_and_address(self):
        existing = {
            "name": [{"family": "Old", "given": ["Old"]}],
            "address": [{"city": "Old City"}],
        }
        prac = {
            "first_name": "New", "last_name": "New",
            "address_line1": "100 Main", "city": "Queens",
            "state": "", "zip": "", "address_line2": "",
        }
        _apply_csv_to_existing(existing, prac, address_mode="overwrite", scope="all")
        assert existing["name"][0]["family"] == "New"
        assert existing["address"][0]["city"] == "Queens"

    def test_scope_address_only_leaves_name_untouched(self):
        existing = {
            "name": [{"family": "Keep", "given": ["Keep"]}],
            "address": [{"city": "Old City"}],
        }
        prac = {
            "first_name": "Ignored", "last_name": "Ignored",
            "address_line1": "", "address_line2": "",
            "city": "Queens", "state": "", "zip": "",
        }
        _apply_csv_to_existing(existing, prac, address_mode="overwrite", scope="address_only")
        assert existing["name"][0]["family"] == "Keep"
        assert existing["address"][0]["city"] == "Queens"


# ---------------------------------------------------------------------------
# _resolve_field_label — branches not exercised by humanise_fhir_error tests
# ---------------------------------------------------------------------------

class TestResolveFieldLabel:
    """Path-aware FHIR error label resolution. Covers the empty-path,
    issuer/display, and extension-slot branches that don't flow through
    the higher-level ``humanise_fhir_error`` tests."""

    def test_empty_tokens_returns_empty_string(self):
        assert _resolve_field_label([]) == ""

    def test_issuer_display_maps_to_license_name(self):
        assert _resolve_field_label(["qualification", "0", "issuer", "display"]) == "License Name"

    def test_extension_slot_0_is_license_name(self):
        tokens = ["qualification", "0", "issuer", "extension", "0", "valueString"]
        assert _resolve_field_label(tokens) == "License Name"

    def test_extension_slot_1_is_license_state(self):
        tokens = ["qualification", "0", "issuer", "extension", "1", "valueString"]
        assert _resolve_field_label(tokens) == "License State"

    def test_extension_slot_other_falls_back_to_generic_label(self):
        """Slots beyond the known short-name (0) and state (1) — there's no
        domain meaning for these in the current schema, so a generic label
        is the honest answer."""
        tokens = ["qualification", "0", "issuer", "extension", "5", "valueString"]
        assert _resolve_field_label(tokens) == "Extension value"


# ---------------------------------------------------------------------------
# End-to-end: apply-strategy merge actions (merge_apply, merge_replace_address,
# merge_apply_additional) — covers the action dispatch + message-building
# branches in _do_merge.
# ---------------------------------------------------------------------------

def _apply_strategy_prac(action, **overrides):
    """Build a CSV row with ``status=existing`` and the apply-strategy action."""
    prac = {
        "source_row_number": 1,
        "email": "apply@example.com",
        "first_name": "ApplyFirst",
        "last_name": "ApplyLast",
        "role": "MD",
        "phone": "5559990000",
        "npi": "1700199213",
        "dob": "1980-01-01",
        "fax": "",
        "address": {},
        "address_line1": "200 New St",
        "address_line2": "",
        "city": "Brooklyn",
        "state": "NY",
        "zip": "11201",
        "location_reference": None,
        "primary_practice_location": "",
        "licenses": [],
        "status": "existing",
        "existing_id": "Practitioner/apply-id",
        "action": action,
    }
    prac.update(overrides)
    return prac


def _existing_resource_for_apply():
    """Existing Practitioner resource with old name/address; used as the
    GET response in apply-strategy merge tests."""
    return {
        "id": "apply-id",
        "name": [{"family": "OldLast", "given": ["OldFirst"]}],
        "birthDate": "1900-01-01",
        "telecom": [{"system": "phone", "value": "5550000000", "rank": 1, "use": "work"}],
        "identifier": [{"system": _NPI_SYSTEM, "value": "1111111111"}],
        "address": [{
            "use": "work", "type": "both", "country": "US",
            "line": ["1 Old Ln"], "city": "Oldtown",
            "state": "CA", "postalCode": "90000",
        }],
        "qualification": [],
    }


class TestMergeApplyAllScope:
    """Action ``merge_apply`` — 'Replace record': overwrite name, DOB,
    telecom, NPI and address with CSV values."""

    def test_dispatch_and_message_for_full_replace(self):
        prac = _apply_strategy_prac("merge_apply")
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client.return_value = MagicMock()
            mock_loc.return_value = {}
            mock_read.return_value = _existing_resource_for_apply()

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        # Message must reflect the apply-strategy branch (1662): generic
        # "applied CSV values" copy, not the address-only branch.
        assert "applied csv values" in r["message"].lower()
        put_body = mock_put.call_args[0][2]
        # CSV name overwrote existing.
        assert put_body["name"][0]["family"] == "ApplyLast"
        assert put_body["name"][0]["given"][0] == "ApplyFirst"
        # CSV DOB overwrote existing.
        assert put_body["birthDate"] == "1980-01-01"
        # CSV address overwrote existing line/city.
        assert put_body["address"][0]["city"] == "Brooklyn"
        assert put_body["address"][0]["line"] == ["200 New St"]
        # Only one address slot (overwrite, not additional).
        assert len(put_body["address"]) == 1


class TestMergeReplaceAddressOnly:
    """Action ``merge_replace_address`` — 'Replace address only': overwrite
    ONLY the address; keep name, DOB, telecom and NPI from the existing
    record."""

    def test_address_overwritten_other_fields_preserved(self):
        prac = _apply_strategy_prac("merge_replace_address")
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client.return_value = MagicMock()
            mock_loc.return_value = {}
            mock_read.return_value = _existing_resource_for_apply()

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        # Message reflects the address-only / overwrite branch (1660).
        assert "replaced address" in r["message"].lower()
        put_body = mock_put.call_args[0][2]
        # Name and DOB stayed at the existing values.
        assert put_body["name"][0]["family"] == "OldLast"
        assert put_body["birthDate"] == "1900-01-01"
        # Address was overwritten with CSV values.
        assert put_body["address"][0]["city"] == "Brooklyn"
        assert len(put_body["address"]) == 1


class TestMergeApplyAdditionalAddress:
    """Action ``merge_apply_additional`` — 'Add address as additional':
    append the CSV address as a second address entry; keep the existing
    primary plus all other fields untouched."""

    def test_csv_address_appended_existing_primary_kept(self):
        prac = _apply_strategy_prac("merge_apply_additional")
        handler = make_handler(body={"practitioners": [prac]})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client.return_value = MagicMock()
            mock_loc.return_value = {}
            mock_read.return_value = _existing_resource_for_apply()

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        # Message reflects the address-only / additional branch (1658).
        assert "additional" in r["message"].lower()
        put_body = mock_put.call_args[0][2]
        # Name preserved (scope=address_only).
        assert put_body["name"][0]["family"] == "OldLast"
        # Two address entries — existing primary first, CSV appended.
        assert len(put_body["address"]) == 2
        assert put_body["address"][0]["city"] == "Oldtown"
        assert put_body["address"][1]["city"] == "Brooklyn"

    def test_no_existing_address_message_discloses_primary_promotion(self):
        """Edge case: admin picked 'Add address as additional' but the
        existing record carries no address. The CSV address can only land
        as the primary, which diverges from the admin's intent. The result
        message must disclose this so they understand what they got."""
        prac = _apply_strategy_prac("merge_apply_additional")
        handler = make_handler(body={"practitioners": [prac]})

        # Existing resource with no address array — phantom/legacy shape.
        existing = _existing_resource_for_apply()
        existing.pop("address", None)

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client.return_value = MagicMock()
            mock_loc.return_value = {}
            mock_read.return_value = existing

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        msg = r["message"].lower()
        assert "no address" in msg or "added this as primary" in msg
        put_body = mock_put.call_args[0][2]
        # Only one address slot — the CSV value, now primary.
        assert len(put_body["address"]) == 1
        assert put_body["address"][0]["city"] == "Brooklyn"


# ---------------------------------------------------------------------------
# _do_merge expands nested address into flat keys — UI parity
# ---------------------------------------------------------------------------

class TestMergeExpandsNestedAddress:
    """The UI echoes back the nested ``address: {line1, line2, city, state,
    zip}`` shape parse-and-validate emits; the address-touching helpers
    read flat keys. _do_merge must call _expand_address_for_fhir(prac)
    first or every merge silently drops the address payload — the bug
    that made "Replace address only" report success without changing
    anything on Canvas."""

    def test_merge_replace_address_only_writes_csv_address_with_nested_payload(self):
        # Build a practitioner with the nested-only shape the UI actually
        # sends (no flat address_* keys). The fix must expand it.
        prac = {
            "source_row_number": 1,
            "email": "nested@example.com",
            "first_name": "Nested",
            "last_name": "Address",
            "role": "MD",
            "phone": "5550000001",
            "npi": "1700199213",
            "dob": "1980-01-01",
            "fax": "",
            "address": {
                "line1": "200 NEW Ave",
                "line2": "Suite 9",
                "city": "Brooklyn",
                "state": "NY",
                "zip": "11201",
            },
            "location_reference": None,
            "primary_practice_location": "",
            "licenses": [],
            "status": "existing",
            "existing_id": "Practitioner/nested-id",
            "action": "merge_replace_address",
        }
        handler = make_handler(body={"practitioners": [prac]})

        existing = {
            "id": "nested-id",
            "name": [{"family": "OldLast", "given": ["OldFirst"]}],
            "birthDate": "1900-01-01",
            "telecom": [{"system": "phone", "value": "5550000000", "rank": 1, "use": "work"}],
            "identifier": [{"system": _NPI_SYSTEM, "value": "1111111111"}],
            "address": [{
                "use": "work", "type": "both", "country": "US",
                "line": ["1 Old Ln"], "city": "Oldtown",
                "state": "CA", "postalCode": "90000",
            }],
            "qualification": [],
        }

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.replace_practitioner") as mock_put:

            mock_client.return_value = MagicMock()
            mock_loc.return_value = {}
            mock_read.return_value = existing

            result = handler.create_practitioners()

        r = _extract_json(result)["results"][0]
        assert r["status"] == "merged"
        put_body = mock_put.call_args[0][2]
        # Address came from the nested payload — proves _expand_address_for_fhir fired.
        assert put_body["address"][0]["city"] == "Brooklyn"
        assert put_body["address"][0]["state"] == "NY"
        assert put_body["address"][0]["postalCode"] == "11201"
        assert put_body["address"][0]["line"] == ["200 NEW Ave", "Suite 9"]
        # scope=address_only so name and DOB stayed at the existing values.
        assert put_body["name"][0]["family"] == "OldLast"
        assert put_body["birthDate"] == "1900-01-01"


# ---------------------------------------------------------------------------
# _apply_csv_non_address: never write placeholder NPI over existing real value
# ---------------------------------------------------------------------------

class TestApplyCsvNonAddressNpiGuard:
    """The CSV parser substitutes DEFAULT_NPI for blank cells (so the
    Practitioner FHIR resource always has an NPI identifier present).
    The merge-apply write path must NOT clobber an existing real NPI on
    Canvas with that placeholder — that would silently destroy a valid
    NPI without any UI signal."""

    def test_placeholder_npi_does_not_overwrite_real_existing(self):
        existing = {"identifier": [{"system": _NPI_SYSTEM, "value": "1234567893"}]}
        # CSV NPI is the placeholder (parser substituted it for a blank cell).
        _apply_csv_non_address(existing, {"npi": "1111155556"})
        # Existing real NPI preserved.
        npi_entry = next(
            i for i in existing["identifier"] if i["system"] == _NPI_SYSTEM
        )
        assert npi_entry["value"] == "1234567893"

    def test_real_csv_npi_still_overwrites(self):
        """Sanity: a real CSV NPI (not the placeholder) still updates."""
        existing = {"identifier": [{"system": _NPI_SYSTEM, "value": "1234567893"}]}
        _apply_csv_non_address(existing, {"npi": "9876543219"})
        npi_entry = next(
            i for i in existing["identifier"] if i["system"] == _NPI_SYSTEM
        )
        assert npi_entry["value"] == "9876543219"

    def test_placeholder_npi_does_not_create_identifier_when_existing_has_none(self):
        """If the existing record has no NPI identifier at all, the
        placeholder shouldn't get appended either — same intent: never
        write the placeholder as if it were a real NPI."""
        existing: dict[str, Any] = {}
        _apply_csv_non_address(existing, {"npi": "1111155556"})
        assert "identifier" not in existing


# ---------------------------------------------------------------------------
# Existing-resource read failure surfaces a per-row flag
# ---------------------------------------------------------------------------

class TestExistingReadFailureSurfacesPerRowFlag:
    """When read_practitioner fails during parse-and-validate (5xx, auth,
    parse error, or the documented phantom-404), the row is still marked
    'existing' (because the staff directory caught the match) but the
    merge preview is incomplete. The response must include
    ``existing_read_failed: true`` on that row so the UI renders
    'Couldn't preview merge details' rather than silently showing an
    incomplete preview."""

    def test_read_failure_sets_existing_read_failed_true(self):
        """Staff directory finds the match by email; read_practitioner
        blows up afterward. Row stays 'existing' but carries the flag."""
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner",
                   side_effect=requests.HTTPError("Canvas returned 503")):

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = _staff_dir_with_email(
                "jane.smith@example.com", "staff-1"
            )

            result = handler.parse_and_validate()

        data = _extract_json(result)
        row = data["practitioners"][0]
        assert row["status"] == "existing"
        assert row["existing_read_failed"] is True

    def test_successful_read_leaves_flag_false(self):
        """Control: when read_practitioner succeeds, the flag stays False
        so the per-row 'preview unavailable' UI doesn't render."""
        handler = make_handler(body={"csv_text": VALID_CSV})

        with patch("practitioner_bulk_loader.api.bulk_upload_api.make_fhir_client") as mock_client_fn, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.get_location_map") as mock_loc, \
             patch("practitioner_bulk_loader.api.bulk_upload_api._build_staff_directory") as mock_dir, \
             patch("practitioner_bulk_loader.api.bulk_upload_api.read_practitioner") as mock_read:

            mock_client_fn.return_value = MagicMock()
            mock_loc.return_value = {"main clinic": "Location/loc-1"}
            mock_dir.return_value = _staff_dir_with_email(
                "jane.smith@example.com", "staff-1"
            )
            mock_read.return_value = {"id": "staff-1", "qualification": []}

            result = handler.parse_and_validate()

        data = _extract_json(result)
        row = data["practitioners"][0]
        assert row["status"] == "existing"
        assert row["existing_read_failed"] is False


# ---------------------------------------------------------------------------
# Residual coverage gaps — _normalize_existing_telecom + _normalize_existing_address
# ---------------------------------------------------------------------------

class TestNormalizeExistingTelecomAllDropped:
    """When every entry has a non-digit-only value (e.g. multiple ``"N/A"``
    phones), all are dropped and the pass-1 rank loop must be skipped —
    returning the empty list instead of indexing into nothing."""

    def test_all_non_digit_entries_dropped_returns_empty(self):
        telecom = [
            {"system": "phone", "value": "N/A"},
            {"system": "fax", "value": "TBD"},
        ]
        out = _normalize_existing_telecom(telecom)
        assert out == []


class TestNormalizeExistingAddressFillsBlankCity:
    """When the existing record has a partial address with city blank but
    state/zip populated, CSV city must fill the city slot — distinct from
    ``test_partial_existing_address_blanks_filled`` (which has city
    already populated and tests the state/zip fills)."""

    def test_blank_city_filled_from_csv(self):
        existing = {"address": [{
            "use": "work",
            "type": "both",
            "country": "US",
            "line": ["999 Other St"],
            "city": "",
            "state": "CA",
            "postalCode": "90000",
        }]}
        prac = {
            "address_line1": "100 Main St",
            "address_line2": "",
            "city": "Queens",
            "state": "NY",
            "zip": "11375",
        }
        _normalize_existing_address(existing, prac)
        addr = existing["address"][0]
        assert addr["city"] == "Queens"  # filled
        assert addr["state"] == "CA"     # untouched (already populated)
        assert addr["postalCode"] == "90000"  # untouched
