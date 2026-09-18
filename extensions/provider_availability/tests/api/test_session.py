"""Tests for provider_availability.api.session."""

from __future__ import annotations

from unittest.mock import MagicMock

from provider_availability.api.session import signed_in_staff_id


def _request(headers) -> MagicMock:
    request = MagicMock()
    request.headers = headers
    return request


class TestSignedInStaffId:
    def test_reads_the_staff_id_from_the_session_headers(self):
        request = _request({
            "canvas-logged-in-user-id": "staff-7",
            "canvas-logged-in-user-type": "Staff",
        })

        assert signed_in_staff_id(request) == "staff-7"

    def test_a_patient_session_is_not_treated_as_staff(self):
        """A patient must never be read as a staff member."""
        request = _request({
            "canvas-logged-in-user-id": "patient-7",
            "canvas-logged-in-user-type": "Patient",
        })

        assert signed_in_staff_id(request) == ""

    def test_user_type_is_matched_case_insensitively(self):
        request = _request({
            "canvas-logged-in-user-id": "staff-7",
            "canvas-logged-in-user-type": "staff",
        })

        assert signed_in_staff_id(request) == "staff-7"

    def test_missing_headers_yield_no_identity(self):
        assert signed_in_staff_id(_request({})) == ""

    def test_missing_id_with_staff_type_yields_no_identity(self):
        request = _request({"canvas-logged-in-user-type": "Staff"})

        assert signed_in_staff_id(request) == ""

    def test_a_request_without_headers_at_all_yields_no_identity(self):
        request = MagicMock()
        del request.headers

        assert signed_in_staff_id(request) == ""

    def test_whitespace_is_stripped(self):
        request = _request({
            "canvas-logged-in-user-id": "  staff-7  ",
            "canvas-logged-in-user-type": " Staff ",
        })

        assert signed_in_staff_id(request) == "staff-7"
