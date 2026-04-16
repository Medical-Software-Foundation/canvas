"""Tests for API endpoints (FavoritesAPI, MedicationSearchAPI, PharmacySearchAPI, etc.)."""

from unittest.mock import MagicMock, patch

import pytest

from prescription_favorites.protocols.prescription_api import (
    FavoritesAPI,
    HideDefaultAPI,
    MedicationSearchAPI,
    MedicationLookupAPI,
    PharmacySearchAPI,
    PharmacyLookupAPI,
)
from prescription_favorites.medications import FAVORITE_MEDICATIONS


class TestFavoritesAPI:
    """Tests for FavoritesAPI."""

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_returns_all_favorites(
        self, mock_json_response: MagicMock, mock_favorites_service: MagicMock
    ) -> None:
        """Test GET returns all favorites."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = MagicMock()
        api.request.headers = {"canvas-logged-in-user-id": "test-staff-123"}
        api.request.query_params = {}

        mock_service_instance = MagicMock()
        mock_service_instance.get_all_favorites.return_value = list(FAVORITE_MEDICATIONS.values())
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.get()

        mock_service_instance.get_all_favorites.assert_called_once()
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert "favorites" in json_call
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_creates_favorite(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST creates a new favorite."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "display_name": "New Med",
            "fdb_code": "123456",
            "sig": "Take daily",
            "days_supply": 30,
            "quantity_to_dispense": 30,
            "unit": "Tablet",
            "refills": 0,
            "representative_ndc": "12345678901",
            "ncpdp_quantity_qualifier_code": "EA",
        }

        mock_service_instance = MagicMock()
        created_favorite = {
            "id": "custom_new123",
            "display_name": "New Med",
            "is_custom": True,
        }
        mock_service_instance.save_custom_favorite.return_value = created_favorite
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.post()

        mock_service_instance.save_custom_favorite.assert_called_once()
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert json_call["favorite"]["id"] == "custom_new123"
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_with_invalid_json(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test POST with invalid JSON returns error."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.side_effect = ValueError("Invalid JSON")

        mock_json_response.return_value = "error_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Invalid JSON" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_with_missing_fields(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test POST with missing required fields returns error."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "display_name": "Incomplete Med",
            # Missing other required fields
        }

        mock_json_response.return_value = "error_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Missing required fields" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_put_updates_custom_favorite(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test PUT updates a custom favorite."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "id": "custom_existing",
            "display_name": "Updated Med",
            "sig": "Updated sig",
        }

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = True
        mock_service_instance.get_favorite_by_id.return_value = {
            "id": "custom_existing",
            "display_name": "Old Med",
            "created_by_id": "test-staff-123",
            "fdb_code": "123456",
            "sig": "Take daily",
            "days_supply": 30,
            "quantity_to_dispense": 30.0,
            "unit": "Tablet",
            "refills": 0,
            "representative_ndc": "12345678901",
            "ncpdp_quantity_qualifier_code": "EA",
            "medication_name": "Old Med",
            "generic_substitution_allowed": True,
            "search_terms": [],
            "label": None,
            "label_color": None,
            "default_pharmacy_ncpdp_id": None,
            "default_pharmacy_name": None,
        }
        updated_favorite = {
            "id": "custom_existing",
            "display_name": "Updated Med",
            "is_custom": True,
        }
        mock_service_instance.update_custom_favorite.return_value = updated_favorite
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.put()

        mock_service_instance.update_custom_favorite.assert_called_once()
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert json_call["favorite"]["display_name"] == "Updated Med"
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_put_rejects_hardcoded_favorite(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test PUT rejects updating hardcoded favorites."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "id": "wegovy_0.25mg",
            "display_name": "Modified Tylenol",
        }

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = False
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "error_response"

        result = api.put()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Cannot modify hardcoded" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_removes_custom_favorite(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test DELETE removes a custom favorite."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"id": "custom_to_delete"}

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = True
        mock_service_instance.get_favorite_by_id.return_value = {
            "id": "custom_to_delete", "created_by_id": "test-staff-123",
        }
        mock_service_instance.delete_custom_favorite.return_value = True
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.delete()

        mock_service_instance.delete_custom_favorite.assert_called_once_with("custom_to_delete")
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_rejects_hardcoded_favorite(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test DELETE rejects deleting hardcoded favorites."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"id": "wegovy_0.25mg"}

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = False
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "error_response"

        result = api.delete()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Cannot delete hardcoded" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_without_id(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test DELETE without ID returns error."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {}

        mock_json_response.return_value = "error_response"

        result = api.delete()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Favorite ID is required" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_returns_success(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test DELETE returns success message when favorite is deleted."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"id": "custom_to_delete"}

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = True
        mock_service_instance.get_favorite_by_id.return_value = {
            "id": "custom_to_delete", "created_by_id": "test-staff-123",
        }
        mock_service_instance.delete_custom_favorite.return_value = True
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.delete()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert "deleted successfully" in json_call["message"]
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_not_found(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test DELETE returns error when favorite not found."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"id": "custom_nonexistent"}

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = True
        mock_service_instance.get_favorite_by_id.return_value = None
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "error_response"

        result = api.delete()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "not found" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_with_raw_body_parsing(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST with raw body fallback parsing (Canvas production environment)."""
        import json

        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        # Simulate request.json() failing, but raw body available
        api.request.json.side_effect = ValueError("No JSON")
        api.request.body = json.dumps({
            "display_name": "New Med",
            "fdb_code": "123456",
            "sig": "Take daily",
            "days_supply": 30,
            "quantity_to_dispense": 30,
            "unit": "Tablet",
            "refills": 0,
            "representative_ndc": "12345678901",
            "ncpdp_quantity_qualifier_code": "EA",
        }).encode('utf-8')

        mock_service_instance = MagicMock()
        created_favorite = {
            "id": "custom_new123",
            "display_name": "New Med",
            "is_custom": True,
        }
        mock_service_instance.save_custom_favorite.return_value = created_favorite
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_put_without_id(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test PUT without favorite ID returns error."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "display_name": "Updated Med",
            # Missing ID
        }

        mock_json_response.return_value = "error_response"

        result = api.put()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Favorite ID is required" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_put_favorite_not_found(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test PUT with non-existent favorite ID returns error."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "id": "custom_nonexistent",
            "display_name": "Updated Med",
        }

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = True
        mock_service_instance.get_favorite_by_id.return_value = None
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "error_response"

        result = api.put()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "not found" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_put_update_fails(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test PUT returns error when update fails."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {
            "id": "custom_existing",
            "display_name": "Updated Med",
        }

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = True
        mock_service_instance.get_favorite_by_id.return_value = {
            "id": "custom_existing",
            "display_name": "Old Med",
            "created_by_id": "test-staff-123",
            "fdb_code": "123",
            "sig": "Once daily",
            "days_supply": 30,
            "quantity_to_dispense": 30,
            "unit": "Tablet",
            "refills": 0,
            "representative_ndc": "12345",
            "ncpdp_quantity_qualifier_code": "EA",
        }
        mock_service_instance.update_custom_favorite.return_value = None
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "error_response"

        result = api.put()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Failed to update" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_put_with_raw_body_parsing(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test PUT with raw body fallback parsing (Canvas production environment)."""
        import json

        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        # Simulate request.json() failing, but raw body available
        api.request.json.side_effect = ValueError("No JSON")
        api.request.body = json.dumps({
            "id": "custom_existing",
            "display_name": "Updated Med",
        }).encode('utf-8')

        mock_service_instance = MagicMock()
        mock_service_instance.is_custom_favorite.return_value = True
        mock_service_instance.get_favorite_by_id.return_value = {
            "id": "custom_existing",
            "display_name": "Old Med",
            "created_by_id": "test-staff-123",
            "fdb_code": "123",
            "sig": "Once daily",
            "days_supply": 30,
            "quantity_to_dispense": 30,
            "unit": "Tablet",
            "refills": 0,
            "representative_ndc": "12345",
            "ncpdp_quantity_qualifier_code": "EA",
        }
        mock_service_instance.update_custom_favorite.return_value = {
            "id": "custom_existing",
            "display_name": "Updated Med",
            "is_custom": True,
        }
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.put()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_put_invalid_json(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test PUT with completely invalid JSON returns error."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.side_effect = ValueError("No JSON")
        api.request.body = b"not valid json"

        mock_json_response.return_value = "error_response"

        result = api.put()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Invalid JSON" in json_call["error"]
        assert result == ["error_response"]

    def test_authenticate_returns_true(self) -> None:
        """Test authenticate returns True for Staff users."""
        mock_event = MagicMock()
        api = FavoritesAPI(mock_event)
        credentials = MagicMock()
        credentials.logged_in_user = {"type": "Staff"}

        result = api.authenticate(credentials)

        assert result is True


class TestMedicationSearchAPI:
    """Tests for MedicationSearchAPI."""

    @patch("prescription_favorites.protocols.prescription_api.ontologies_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_searches_medications(
        self,
        mock_json_response: MagicMock,
        mock_ontologies_http: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test GET searches for medications."""
        mock_event = MagicMock()
        api = MedicationSearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"query": "tylenol"}

        # The code calls response.json() on the result from get_json()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "med_medication_id": "297946",
                    "med_medication_description": "Tylenol 500mg",
                    "clinical_quantities": [
                        {
                            "representative_ndc": "12345678901",
                            "erx_ncpdp_script_quantity_qualifier_code": "EA",
                            "clinical_quantity_description": "Tablet",
                        }
                    ],
                }
            ]
        }
        mock_ontologies_http.get_json.return_value = mock_response

        mock_json_response.return_value = "json_response"

        result = api.get()

        mock_ontologies_http.get_json.assert_called_once()
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert len(json_call["medications"]) == 1
        assert json_call["medications"][0]["fdb_code"] == "297946"
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_without_query(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test GET without query returns error."""
        mock_event = MagicMock()
        api = MedicationSearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {}

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Query parameter is required" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_with_short_query(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test GET with query less than 2 chars returns error."""
        mock_event = MagicMock()
        api = MedicationSearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"query": "a"}

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "at least 2 characters" in json_call["error"]
        assert result == ["error_response"]

    def test_authenticate_returns_true(self) -> None:
        """Test authenticate returns True for Staff users."""
        mock_event = MagicMock()
        api = MedicationSearchAPI(mock_event)
        credentials = MagicMock()
        credentials.logged_in_user = {"type": "Staff"}

        result = api.authenticate(credentials)

        assert result is True

    @patch("prescription_favorites.protocols.prescription_api.ontologies_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_handles_api_error(
        self,
        mock_json_response: MagicMock,
        mock_ontologies_http: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test GET handles FDB API errors gracefully."""
        mock_event = MagicMock()
        api = MedicationSearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"query": "tylenol"}

        mock_ontologies_http.get_json.side_effect = Exception("FDB API unavailable")

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Failed to search medications" in json_call["error"]
        assert result == ["error_response"]


class TestPharmacySearchAPI:
    """Tests for PharmacySearchAPI."""

    @patch("prescription_favorites.protocols.prescription_api.pharmacy_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_searches_pharmacies(
        self,
        mock_json_response: MagicMock,
        mock_pharmacy_http: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test GET searches for pharmacies."""
        mock_event = MagicMock()
        api = PharmacySearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"query": "CVS"}

        mock_pharmacy_http.search_pharmacies.return_value = [
            {
                "ncpdp_id": "1234567",
                "organization_name": "CVS Pharmacy",
                "address_line_1": "123 Main St",
                "city": "Boston",
                "state": "MA",
                "zip": "02101",
                "phone_primary": "555-1234",
            }
        ]

        mock_json_response.return_value = "json_response"

        result = api.get()

        mock_pharmacy_http.search_pharmacies.assert_called_once_with("CVS")
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert len(json_call["pharmacies"]) == 1
        assert json_call["pharmacies"][0]["ncpdp_id"] == "1234567"
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_without_query(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test GET without query returns error."""
        mock_event = MagicMock()
        api = PharmacySearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {}

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Query parameter is required" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_with_short_query(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test GET with query less than 2 chars returns error."""
        mock_event = MagicMock()
        api = PharmacySearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"query": "C"}

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "at least 2 characters" in json_call["error"]
        assert result == ["error_response"]

    def test_authenticate_returns_true(self) -> None:
        """Test authenticate returns True for Staff users."""
        mock_event = MagicMock()
        api = PharmacySearchAPI(mock_event)
        credentials = MagicMock()
        credentials.logged_in_user = {"type": "Staff"}

        result = api.authenticate(credentials)

        assert result is True

    @patch("prescription_favorites.protocols.prescription_api.pharmacy_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_handles_api_error(
        self,
        mock_json_response: MagicMock,
        mock_pharmacy_http: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test GET handles pharmacy API errors gracefully."""
        mock_event = MagicMock()
        api = PharmacySearchAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"query": "CVS"}

        mock_pharmacy_http.search_pharmacies.side_effect = Exception("API error")

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Failed to search pharmacies" in json_call["error"]
        assert result == ["error_response"]


class TestPharmacyLookupAPI:
    """Tests for PharmacyLookupAPI."""

    @patch("prescription_favorites.protocols.prescription_api.pharmacy_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_searches_pharmacies(
        self,
        mock_json_response: MagicMock,
        mock_pharmacy_http: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test GET searches for pharmacies by query."""
        mock_event = MagicMock()
        api = PharmacyLookupAPI(mock_event)
        api.request = mock_request
        api.request.query_params = MagicMock()
        api.request.query_params.get.return_value = "Walgreens"

        mock_pharmacy_http.search_pharmacies.return_value = [
            {
                "ncpdp_id": "9876543",
                "organization_name": "Walgreens Pharmacy",
                "address_line_1": "456 Oak Ave",
                "city": "Chicago",
                "state": "IL",
                "phone_primary": "555-5678",
            }
        ]

        mock_json_response.return_value = "json_response"

        result = api.get()

        mock_pharmacy_http.search_pharmacies.assert_called_once_with("Walgreens")
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert len(json_call["pharmacies"]) == 1
        assert json_call["pharmacies"][0]["ncpdp_id"] == "9876543"
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_without_query(
        self, mock_json_response: MagicMock, mock_request: MagicMock
    ) -> None:
        """Test GET without query returns error."""
        mock_event = MagicMock()
        api = PharmacyLookupAPI(mock_event)
        api.request = mock_request
        api.request.query_params = MagicMock()
        api.request.query_params.get.return_value = ""

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Query parameter required" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.pharmacy_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_handles_api_error(
        self,
        mock_json_response: MagicMock,
        mock_pharmacy_http: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test GET handles pharmacy API errors gracefully."""
        mock_event = MagicMock()
        api = PharmacyLookupAPI(mock_event)
        api.request = mock_request
        api.request.query_params = MagicMock()
        api.request.query_params.get.return_value = "Walgreens"

        mock_pharmacy_http.search_pharmacies.side_effect = Exception("Connection timeout")

        mock_json_response.return_value = "error_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Connection timeout" in json_call["error"]
        assert result == ["error_response"]


class TestMedicationLookupAPI:
    """Tests for MedicationLookupAPI."""

    @patch("prescription_favorites.protocols.prescription_api.ontologies_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_returns_medication_details(
        self,
        mock_json_response: MagicMock,
        mock_ontologies_http: MagicMock,
    ) -> None:
        """Test GET returns medication details for all hardcoded medications."""
        mock_event = MagicMock()
        api = MedicationLookupAPI(mock_event)

        # Mock the API response for each medication lookup
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "med_medication_id": "297946",
                    "med_medication_description": "Wegovy 0.25mg",
                    "clinical_quantities": [
                        {
                            "representative_ndc": "00169427413",
                            "erx_ncpdp_script_quantity_qualifier_code": "C62",
                            "clinical_quantity_description": "Pen-injector",
                        }
                    ],
                }
            ]
        }
        mock_ontologies_http.get_json.return_value = mock_response

        mock_json_response.return_value = "json_response"

        result = api.get()

        # Verify ontologies_http was called for medication lookups
        assert mock_ontologies_http.get_json.call_count > 0
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert "medications" in json_call
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.ontologies_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_handles_not_found(
        self,
        mock_json_response: MagicMock,
        mock_ontologies_http: MagicMock,
    ) -> None:
        """Test GET handles medication not found in FDB."""
        mock_event = MagicMock()
        api = MedicationLookupAPI(mock_event)

        # Mock empty results (medication not found)
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_ontologies_http.get_json.return_value = mock_response

        mock_json_response.return_value = "json_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        # Check that results have "not_found" status
        for med in json_call["medications"]:
            assert med["status"] == "not_found"
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.ontologies_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_handles_api_error(
        self,
        mock_json_response: MagicMock,
        mock_ontologies_http: MagicMock,
    ) -> None:
        """Test GET handles FDB API errors gracefully."""
        mock_event = MagicMock()
        api = MedicationLookupAPI(mock_event)

        mock_ontologies_http.get_json.side_effect = Exception("FDB API unavailable")

        mock_json_response.return_value = "json_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        # Check that results have "error" status
        for med in json_call["medications"]:
            assert med["status"] == "error"
            assert "FDB API unavailable" in med["error"]
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.ontologies_http")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_get_returns_matched_medication_with_clinical_quantities(
        self,
        mock_json_response: MagicMock,
        mock_ontologies_http: MagicMock,
    ) -> None:
        """Test GET returns clinical quantities when FDB code matches."""
        mock_event = MagicMock()
        api = MedicationLookupAPI(mock_event)

        # Use the actual FDB code of the first hardcoded medication
        first_id = next(iter(FAVORITE_MEDICATIONS.keys()))
        first_fdb_code = FAVORITE_MEDICATIONS[first_id]["fdb_code"]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "med_medication_id": first_fdb_code,
                    "med_medication_description": "Matched Med",
                    "clinical_quantities": [
                        {
                            "representative_ndc": "00169452514",
                            "erx_ncpdp_script_quantity_qualifier_code": "C28254",
                            "clinical_quantity_description": "Pen-injector",
                        }
                    ],
                }
            ]
        }
        mock_ontologies_http.get_json.return_value = mock_response

        mock_json_response.return_value = "json_response"

        result = api.get()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        matched = [m for m in json_call["medications"] if m.get("status") == "found"]
        assert len(matched) >= 1
        assert matched[0]["api_clinical_quantities"][0]["representative_ndc"] == "00169452514"
        assert result == ["json_response"]


class TestHideDefaultAPI:
    """Tests for HideDefaultAPI."""

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_hides_default_favorite(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST hides a default favorite for the current staff member."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {"default_id": "wegovy_0.25mg"}
        api.request.headers = {"canvas-logged-in-user-id": "staff-hide-123"}

        mock_service_instance = MagicMock()
        mock_service_instance.hide_default.return_value = True
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.post()

        mock_service_instance.hide_default.assert_called_once_with("wegovy_0.25mg", "staff-hide-123")
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_returns_error_when_default_id_missing(
        self,
        mock_json_response: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST returns error when default_id is not in the request body."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {}
        api.request.headers = {"canvas-logged-in-user-id": "staff-hide-123"}

        mock_json_response.return_value = "error_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "default_id" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_returns_error_when_staff_id_missing(
        self,
        mock_json_response: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST returns error when staff ID header is absent."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {"default_id": "wegovy_0.25mg"}
        api.request.headers = {}

        mock_json_response.return_value = "error_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Staff ID" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_returns_error_when_not_a_default(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST returns error when the ID is not a default favorite."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.json.return_value = {"default_id": "not_a_real_default"}
        api.request.headers = {"canvas-logged-in-user-id": "staff-hide-123"}

        mock_service_instance = MagicMock()
        mock_service_instance.hide_default.return_value = "Not a default favorite"
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "error_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Not a default favorite" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_returns_error_on_invalid_json(
        self,
        mock_json_response: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test POST returns error when request body is not valid JSON."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.json.side_effect = ValueError("Bad JSON")
        api.request.body = b"not valid json"
        api.request.headers = {"canvas-logged-in-user-id": "staff-hide-123"}

        mock_json_response.return_value = "error_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Invalid JSON" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_unhides_default_favorite(
        self,
        mock_json_response: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test DELETE unhides a default favorite for the current staff member."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"default_id": "wegovy_0.25mg"}
        api.request.headers = {"canvas-logged-in-user-id": "staff-hide-123"}

        mock_service_instance = MagicMock()
        mock_service_instance.unhide_default.return_value = True
        mock_favorites_service.return_value = mock_service_instance

        mock_json_response.return_value = "json_response"

        result = api.delete()

        mock_service_instance.unhide_default.assert_called_once_with("wegovy_0.25mg", "staff-hide-123")
        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is True
        assert result == ["json_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_returns_error_when_default_id_missing(
        self,
        mock_json_response: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test DELETE returns error when default_id query param is absent."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {}
        api.request.headers = {"canvas-logged-in-user-id": "staff-hide-123"}

        mock_json_response.return_value = "error_response"

        result = api.delete()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "default_id" in json_call["error"]
        assert result == ["error_response"]

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_delete_returns_error_when_staff_id_missing(
        self,
        mock_json_response: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test DELETE returns error when staff ID header is absent."""
        mock_event = MagicMock()
        api = HideDefaultAPI(mock_event)
        api.request = mock_request
        api.request.query_params = {"default_id": "wegovy_0.25mg"}
        api.request.headers = {}

        mock_json_response.return_value = "error_response"

        result = api.delete()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Staff ID" in json_call["error"]
        assert result == ["error_response"]


class TestPrescribeFavoritesAPIRawBody:
    """Tests for PrescribeFavoritesAPI raw body JSON fallback."""

    @patch("prescription_favorites.protocols.prescription_api.FavoritesService")
    @patch("prescription_favorites.protocols.prescription_api.Patient")
    @patch("prescription_favorites.protocols.prescription_api.CurrentNoteStateEvent")
    @patch("prescription_favorites.protocols.prescription_api.Note")
    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_falls_back_to_raw_body_parsing(
        self,
        mock_json_response: MagicMock,
        mock_note_model: MagicMock,
        mock_note_state_model: MagicMock,
        mock_patient_model: MagicMock,
        mock_favorites_service: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test PrescribeFavoritesAPI.post falls back to raw body when request.json() fails."""
        import json as json_module
        from prescription_favorites.protocols.prescription_api import PrescribeFavoritesAPI

        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        api.request = mock_request

        # Simulate request.json() failing but raw body is valid JSON
        api.request.json.side_effect = ValueError("No JSON")
        api.request.body = json_module.dumps({
            "patient_id": "patient-raw-123",
            "selected_medications": ["wegovy_0.25mg"],
        }).encode("utf-8")
        api.request.headers = {"canvas-logged-in-user-id": "staff-prescribe-1"}

        mock_patient_model.objects.get.return_value = MagicMock()
        # Return an empty open-notes queryset so we get a predictable early-exit response
        mock_note_state_model.objects.filter.return_value.values_list.return_value = []
        notes_qs = MagicMock()
        notes_qs.exists.return_value = False
        mock_note_model.objects.filter.return_value.order_by.return_value = notes_qs

        mock_json_response.return_value = "no_notes_response"

        result = api.post()

        # The raw body parse succeeded; the error (if any) must NOT be "Invalid JSON"
        json_call = mock_json_response.call_args[0][0]
        assert "Invalid JSON" not in json_call.get("error", "")

    @patch("prescription_favorites.protocols.prescription_api.JSONResponse")
    def test_post_returns_error_on_completely_invalid_json(
        self,
        mock_json_response: MagicMock,
        mock_request: MagicMock,
    ) -> None:
        """Test PrescribeFavoritesAPI.post returns error when body is not valid JSON."""
        from prescription_favorites.protocols.prescription_api import PrescribeFavoritesAPI

        mock_event = MagicMock()
        api = PrescribeFavoritesAPI(mock_event)
        api.request = mock_request
        api.request.json.side_effect = ValueError("No JSON")
        api.request.body = b"not valid json at all"
        api.request.headers = {"canvas-logged-in-user-id": "staff-prescribe-1"}

        mock_json_response.return_value = "error_response"

        result = api.post()

        json_call = mock_json_response.call_args[0][0]
        assert json_call["success"] is False
        assert "Invalid JSON" in json_call["error"]
        assert result == ["error_response"]
