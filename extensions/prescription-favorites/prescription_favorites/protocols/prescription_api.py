"""SimpleAPI routes for prescription favorites."""

import json
from urllib.parse import urlencode

from canvas_sdk.commands import PrescribeCommand
from canvas_sdk.commands.constants import ClinicalQuantity
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from canvas_sdk.utils.http import ontologies_http, pharmacy_http
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from logger import log

from prescription_favorites.services import FavoritesService


class FavoritesAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to manage prescription favorites."""

    PATH = "/routes/favorites"

    def _get_service(self) -> FavoritesService:
        """Create a FavoritesService."""
        return FavoritesService()

    def _get_staff_id(self) -> str:
        """Get the logged-in staff user ID from request headers."""
        staff_id: str = self.request.headers.get("canvas-logged-in-user-id", "")
        log.info(f"Staff ID from header: '{staff_id}'")
        return staff_id

    def get(self) -> list[Response]:
        """Get all prescription favorites (hardcoded + custom).

        Query parameters:
            filter: "all" (default), "mine", or "shared"
        """
        log.info("Fetching all prescription favorites")

        staff_id = self._get_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status=400)]

        visibility_filter = self.request.query_params.get("filter", "all").strip()

        include_hidden = self.request.query_params.get("include_hidden", "").strip() == "true"

        service = self._get_service()
        favorites = service.get_all_favorites(
            staff_id=staff_id,
            visibility_filter=visibility_filter,
            include_hidden=include_hidden,
        )

        log.info(f"Returning {len(favorites)} favorites (filter={visibility_filter})")

        return [
            JSONResponse(
                {
                    "favorites": favorites,
                    "count": len(favorites),
                    "success": True,
                }
            )
        ]

    def post(self) -> list[Response]:
        """Create a new custom prescription favorite.

        Request body:
            display_name: Human-readable name
            fdb_code: FDB medication code
            sig: Prescription instructions
            days_supply: Number of days
            quantity_to_dispense: Amount to dispense
            unit: Unit type (e.g., "Tablet")
            refills: Number of refills (0-99)
            representative_ndc: NDC code
            ncpdp_quantity_qualifier_code: NCPDP qualifier code
            medication_name: (optional) Clinical medication name
            generic_substitution_allowed: (optional) Boolean, defaults to True
            search_terms: (optional) List of search keywords
            default_pharmacy_ncpdp_id: (optional) Default pharmacy NCPDP ID

        Returns:
            The created favorite with generated ID and is_custom=True.
        """
        log.info("Creating new custom favorite")

        try:
            # Try request.json() first (works in test environment)
            # Fall back to raw body parsing (needed in production Canvas environment)
            try:
                request_data = self.request.json()
            except Exception:
                raw_body = self.request.body
                if hasattr(raw_body, 'decode'):
                    request_data = json.loads(raw_body.decode('utf-8'))
                else:
                    request_data = json.loads(raw_body)
        except Exception as e:
            log.error(f"Failed to parse JSON: {e}")
            return [
                JSONResponse({"error": "Invalid JSON in request body", "success": False}, status=400)
            ]

        # Required fields (refills can be 0, so check for None separately)
        required_fields = [
            "display_name",
            "fdb_code",
            "sig",
            "days_supply",
            "quantity_to_dispense",
            "unit",
            "representative_ndc",
            "ncpdp_quantity_qualifier_code",
        ]

        missing_fields = [f for f in required_fields if not request_data.get(f)]
        # Check refills separately since 0 is a valid value
        if request_data.get("refills") is None:
            missing_fields.append("refills")
        if missing_fields:
            log.warning(f"Missing required fields: {missing_fields}")
            return [
                JSONResponse(
                    {
                        "error": f"Missing required fields: {', '.join(missing_fields)}",
                        "success": False,
                    },
                    status=400,
                )
            ]

        staff_id = self._get_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status=400)]

        # Build the medication config
        medication_config = {
            "display_name": request_data["display_name"],
            "label": request_data.get("label"),
            "label_color": request_data.get("label_color"),
            "medication_name": request_data.get("medication_name", request_data["display_name"]),
            "fdb_code": str(request_data["fdb_code"]),
            "sig": request_data["sig"],
            "days_supply": int(request_data["days_supply"]),
            "quantity_to_dispense": float(request_data["quantity_to_dispense"]),
            "unit": request_data["unit"],
            "refills": int(request_data["refills"]),
            "representative_ndc": str(request_data["representative_ndc"]),
            "ncpdp_quantity_qualifier_code": request_data["ncpdp_quantity_qualifier_code"],
            "generic_substitution_allowed": request_data.get("generic_substitution_allowed", True),
            "search_terms": request_data.get("search_terms", []),
            "default_pharmacy_ncpdp_id": request_data.get("default_pharmacy_ncpdp_id"),
            "default_pharmacy_name": request_data.get("default_pharmacy_name"),
            "is_shared": request_data.get("is_shared", True),
            "created_by_id": staff_id,
        }

        # Save custom favorite
        service = self._get_service()
        try:
            created_favorite = service.save_custom_favorite(medication_config)
        except ValueError as e:
            log.error(f"Failed to save favorite: {e}")
            return [JSONResponse({"error": str(e), "success": False}, status=400)]

        log.info(f"Created custom favorite: {created_favorite['id']}")

        return [
            JSONResponse(
                {
                    "favorite": created_favorite,
                    "success": True,
                }
            )
        ]

    def put(self) -> list[Response]:
        """Update an existing custom prescription favorite.

        Request body:
            id: The favorite ID to update (required, must be custom)
            display_name: Human-readable name
            fdb_code: FDB medication code
            sig: Prescription instructions
            days_supply: Number of days
            quantity_to_dispense: Amount to dispense
            unit: Unit type (e.g., "Tablet")
            refills: Number of refills (0-99)
            representative_ndc: NDC code
            ncpdp_quantity_qualifier_code: NCPDP qualifier code
            ... (other optional fields)

        Returns:
            The updated favorite.
        """
        staff_id = self._get_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status=400)]

        log.info("Updating custom favorite")

        try:
            # Try request.json() first (works in test environment)
            # Fall back to raw body parsing (needed in production Canvas environment)
            try:
                request_data = self.request.json()
            except Exception:
                raw_body = self.request.body
                if hasattr(raw_body, 'decode'):
                    request_data = json.loads(raw_body.decode('utf-8'))
                else:
                    request_data = json.loads(raw_body)
        except Exception as e:
            log.error(f"Failed to parse JSON in PUT: {e}")
            return [
                JSONResponse({"error": "Invalid JSON in request body", "success": False}, status=400)
            ]

        favorite_id = request_data.get("id")
        if not favorite_id:
            return [
                JSONResponse({"error": "Favorite ID is required", "success": False}, status=400)
            ]

        service = self._get_service()

        # Check if it's a custom favorite
        if not service.is_custom_favorite(favorite_id):
            return [
                JSONResponse({"error": "Cannot modify hardcoded default favorites", "success": False}, status=400)
            ]

        # Check if favorite exists
        existing = service.get_favorite_by_id(favorite_id)
        if not existing:
            return [
                JSONResponse({"error": "Favorite not found", "success": False}, status=404)
            ]

        # Ownership check - deny if creator unknown or not the caller
        if not existing.get("created_by_id") or existing["created_by_id"] != staff_id:
            return [
                JSONResponse({"error": "Not authorized to edit this favorite", "success": False}, status=403)
            ]

        # Build updated config, using existing values as defaults
        medication_config = {
            "display_name": request_data.get("display_name", existing.get("display_name")),
            "label": request_data.get("label", existing.get("label")),
            "label_color": request_data.get("label_color", existing.get("label_color")),
            "medication_name": request_data.get("medication_name", existing.get("medication_name")),
            "fdb_code": str(request_data.get("fdb_code", existing.get("fdb_code"))),
            "sig": request_data.get("sig", existing.get("sig")),
            "days_supply": int(request_data.get("days_supply", existing.get("days_supply"))),
            "quantity_to_dispense": float(request_data.get("quantity_to_dispense", existing.get("quantity_to_dispense"))),
            "unit": request_data.get("unit", existing.get("unit")),
            "refills": int(request_data.get("refills", existing.get("refills"))),
            "representative_ndc": str(request_data.get("representative_ndc", existing.get("representative_ndc"))),
            "ncpdp_quantity_qualifier_code": request_data.get("ncpdp_quantity_qualifier_code", existing.get("ncpdp_quantity_qualifier_code")),
            "generic_substitution_allowed": request_data.get("generic_substitution_allowed", existing.get("generic_substitution_allowed", True)),
            "search_terms": request_data.get("search_terms", existing.get("search_terms", [])),
            "default_pharmacy_ncpdp_id": request_data.get("default_pharmacy_ncpdp_id", existing.get("default_pharmacy_ncpdp_id")),
            "default_pharmacy_name": request_data.get("default_pharmacy_name", existing.get("default_pharmacy_name")),
        }

        if "is_shared" in request_data:
            medication_config["is_shared"] = request_data["is_shared"]

        # Validate required fields aren't empty after merge
        required_fields = [
            "display_name", "fdb_code", "sig", "days_supply",
            "quantity_to_dispense", "unit", "representative_ndc",
            "ncpdp_quantity_qualifier_code",
        ]
        missing_fields = [f for f in required_fields if not medication_config.get(f)]
        if missing_fields:
            log.warning(f"Update would clear required fields: {missing_fields}")
            return [
                JSONResponse(
                    {
                        "error": f"Cannot clear required fields: {', '.join(missing_fields)}",
                        "success": False,
                    },
                    status=400,
                )
            ]

        updated_favorite = service.update_custom_favorite(favorite_id, medication_config)

        if not updated_favorite:
            return [
                JSONResponse({"error": "Failed to update favorite", "success": False}, status=500)
            ]

        log.info(f"Updated custom favorite: {favorite_id}")

        return [
            JSONResponse(
                {
                    "favorite": updated_favorite,
                    "success": True,
                }
            )
        ]

    def delete(self) -> list[Response]:
        """Delete a custom prescription favorite.

        Query parameters:
            id: The favorite ID to delete (required, must be custom)

        Returns:
            Success message if deleted.
        """
        staff_id = self._get_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status=400)]

        favorite_id = self.request.query_params.get("id", "").strip()

        if not favorite_id:
            return [
                JSONResponse({"error": "Favorite ID is required", "success": False}, status=400)
            ]

        log.info(f"Deleting custom favorite: {favorite_id}")

        service = self._get_service()

        # Check if it's a custom favorite
        if not service.is_custom_favorite(favorite_id):
            return [
                JSONResponse({"error": "Cannot delete hardcoded default favorites", "success": False}, status=400)
            ]

        # Ownership check - only the creator can delete
        existing = service.get_favorite_by_id(favorite_id)
        if not existing:
            return [JSONResponse({"error": "Favorite not found", "success": False}, status=404)]
        if not existing.get("created_by_id") or existing["created_by_id"] != staff_id:
            return [
                JSONResponse({"error": "Not authorized to delete this favorite", "success": False}, status=403)
            ]

        # Attempt to delete
        deleted = service.delete_custom_favorite(favorite_id)

        if not deleted:
            return [
                JSONResponse({"error": "Favorite not found", "success": False}, status=404)
            ]

        log.info(f"Deleted custom favorite: {favorite_id}")

        return [
            JSONResponse(
                {
                    "message": f"Favorite {favorite_id} deleted successfully",
                    "success": True,
                }
            )
        ]


class HideDefaultAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to hide/unhide default favorites."""

    PATH = "/routes/favorites/hide-default"

    def _get_service(self) -> FavoritesService:
        """Create a FavoritesService."""
        return FavoritesService()

    def _get_staff_id(self) -> str:
        """Get the logged-in staff user ID from request headers."""
        result: str = self.request.headers.get("canvas-logged-in-user-id", "")
        return result

    def post(self) -> list[Response]:
        """Hide a default favorite for the current user.

        Request body:
            default_id: The default favorite ID to hide (e.g., "wegovy_0.25mg")
        """
        try:
            try:
                request_data = self.request.json()
            except Exception:
                raw_body = self.request.body
                if hasattr(raw_body, 'decode'):
                    request_data = json.loads(raw_body.decode('utf-8'))
                else:
                    request_data = json.loads(raw_body)
        except Exception:
            return [JSONResponse({"error": "Invalid JSON", "success": False}, status=400)]

        default_id = request_data.get("default_id", "").strip()
        if not default_id:
            return [JSONResponse({"error": "default_id is required", "success": False}, status=400)]

        staff_id = self._get_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status=400)]

        service = self._get_service()
        result = service.hide_default(default_id, staff_id)

        if result is not True:
            return [JSONResponse({"error": result or "Failed to hide default", "success": False}, status=400)]

        return [JSONResponse({"success": True, "message": f"Default {default_id} hidden"})]

    def delete(self) -> list[Response]:
        """Unhide a default favorite for the current user.

        Query parameters:
            default_id: The default favorite ID to unhide
        """
        default_id = self.request.query_params.get("default_id", "").strip()
        if not default_id:
            return [JSONResponse({"error": "default_id is required", "success": False}, status=400)]

        staff_id = self._get_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status=400)]

        service = self._get_service()
        result = service.unhide_default(default_id, staff_id)
        if not result:
            return [JSONResponse({"error": "Default was not hidden", "success": False}, status=404)]

        return [JSONResponse({"success": True, "message": f"Default {default_id} unhidden"})]


class MedicationSearchAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to search for medications in the FDB database."""

    PATH = "/routes/medications/search"

    def get(self) -> list[Response]:
        """Search for medications by name.

        Query parameters:
            query: Search term for medication name (required)

        Returns:
            List of matching medications with FDB codes and clinical quantities.
        """
        query = self.request.query_params.get("query", "").strip()

        if not query:
            return [
                JSONResponse({"error": "Query parameter is required", "success": False}, status=400)
            ]

        if len(query) < 2:
            return [
                JSONResponse({"error": "Query must be at least 2 characters", "success": False}, status=400)
            ]

        log.info(f"Searching medications for: {query}")

        try:
            # Search FDB database using ontologies_http
            response = ontologies_http.get_json(
                f"/fdb/grouped-medication/?{urlencode({'search': query})}"
            )
            data = response.json()
            results = data.get("results", [])

            # Format results for the frontend
            medications = []
            for med in results[:20]:  # Limit to top 20 results
                clinical_quantities = med.get("clinical_quantities", [])
                medications.append({
                    "fdb_code": str(med.get("med_medication_id", "")),
                    "display_name": med.get("med_medication_description", ""),
                    "description_and_quantity": med.get("description_and_quantity", ""),
                    "clinical_quantities": [
                        {
                            "representative_ndc": cq.get("representative_ndc", ""),
                            "ncpdp_quantity_qualifier_code": cq.get(
                                "erx_ncpdp_script_quantity_qualifier_code", ""
                            ),
                            "quantity_description": cq.get(
                                "clinical_quantity_description", ""
                            ),
                            "erx_quantity": cq.get("erx_quantity", "1.0"),
                        }
                        for cq in clinical_quantities
                    ],
                    "rxnorm_rxcui": med.get("rxnorm_rxcui", ""),
                })

            log.info(f"Found {len(medications)} medications matching '{query}'")

            return [
                JSONResponse(
                    {
                        "medications": medications,
                        "count": len(medications),
                        "success": True,
                    }
                )
            ]

        except Exception as e:
            log.error(f"Error searching medications: {e}")
            return [
                JSONResponse({"error": "Failed to search medications", "success": False}, status=500)
            ]


class PharmacySearchAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to search for pharmacies."""

    PATH = "/routes/pharmacies/search"

    def get(self) -> list[Response]:
        """Search for pharmacies by name.

        Query parameters:
            query: Search term for pharmacy name (required)

        Returns:
            List of matching pharmacies with NCPDP IDs and addresses.
        """
        query = self.request.query_params.get("query", "").strip()

        if not query:
            return [
                JSONResponse({"error": "Query parameter is required", "success": False}, status=400)
            ]

        if len(query) < 2:
            return [
                JSONResponse({"error": "Query must be at least 2 characters", "success": False}, status=400)
            ]

        log.info(f"Searching pharmacies for: {query}")

        try:
            # Search pharmacies using pharmacy_http
            results = pharmacy_http.search_pharmacies(query)

            # Format results for the frontend
            pharmacies = []
            for pharm in results[:20]:  # Limit to top 20 results
                # Format address
                address_parts = [
                    pharm.get("address_line_1", ""),
                    pharm.get("address_line_2", ""),
                ]
                address_line = ", ".join(p for p in address_parts if p)
                city_state_zip = f"{pharm.get('city', '')}, {pharm.get('state', '')} {pharm.get('zip_code', '')}"
                full_address = f"{address_line}, {city_state_zip}" if address_line else city_state_zip

                pharmacies.append({
                    "ncpdp_id": pharm.get("ncpdp_id", ""),
                    "organization_name": pharm.get("organization_name", ""),
                    "address": full_address.strip(", "),
                    "phone_primary": pharm.get("phone_primary", ""),
                    "fax": pharm.get("fax", ""),
                    "specialty_type": pharm.get("specialty_type", ""),
                })

            log.info(f"Found {len(pharmacies)} pharmacies matching '{query}'")

            return [
                JSONResponse(
                    {
                        "pharmacies": pharmacies,
                        "count": len(pharmacies),
                        "success": True,
                    }
                )
            ]

        except Exception as e:
            log.error(f"Error searching pharmacies: {e}")
            return [
                JSONResponse({"error": "Failed to search pharmacies", "success": False}, status=500)
            ]


class PharmacyLookupAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Diagnostic API to lookup pharmacy NCPDP IDs."""

    PATH = "/routes/pharmacy-lookup"

    def get(self) -> list[Response]:
        """Look up pharmacies by name."""
        query = self.request.query_params.get("query", "").strip()

        if not query:
            return [JSONResponse({"error": "Query parameter required", "success": False}, status=400)]

        try:
            results = pharmacy_http.search_pharmacies(query)

            pharmacies = []
            for pharm in results[:10]:
                address_parts = [
                    pharm.get("address_line_1", ""),
                    pharm.get("city", ""),
                    pharm.get("state", ""),
                ]
                address = ", ".join(p for p in address_parts if p)

                pharmacies.append({
                    "ncpdp_id": pharm.get("ncpdp_id", ""),
                    "organization_name": pharm.get("organization_name", ""),
                    "address": address,
                    "phone": pharm.get("phone_primary", ""),
                })

            return [JSONResponse({"pharmacies": pharmacies, "success": True})]

        except Exception as e:
            return [JSONResponse({"error": str(e), "success": False}, status=500)]


class MedicationLookupAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Diagnostic API to lookup correct clinical quantities for hardcoded medications."""

    PATH = "/routes/medication-lookup"

    def get(self) -> list[Response]:
        """Look up clinical quantities for all hardcoded medications."""
        from prescription_favorites.medications import FAVORITE_MEDICATIONS

        results = []

        for med_id, med_config in FAVORITE_MEDICATIONS.items():
            fdb_code = med_config.get("fdb_code", "")
            display_name = med_config.get("display_name", "")

            # Search by medication name to get clinical quantities
            search_term = med_config.get("medication_name", display_name).split()[0]  # First word

            try:
                response = ontologies_http.get_json(
                    f"/fdb/grouped-medication/?{urlencode({'search': search_term})}"
                )
                data = response.json()
                api_results = data.get("results", [])

                # Find the medication with matching FDB code
                matched_med = None
                for api_med in api_results:
                    if str(api_med.get("med_medication_id", "")) == fdb_code:
                        matched_med = api_med
                        break

                if matched_med:
                    clinical_quantities = [
                        {
                            "representative_ndc": cq.get("representative_ndc", ""),
                            "ncpdp_quantity_qualifier_code": cq.get(
                                "erx_ncpdp_script_quantity_qualifier_code", ""
                            ),
                            "quantity_description": cq.get(
                                "clinical_quantity_description", ""
                            ),
                        }
                        for cq in matched_med.get("clinical_quantities", [])
                    ]

                    results.append({
                        "id": med_id,
                        "display_name": display_name,
                        "fdb_code": fdb_code,
                        "current_ndc": med_config.get("representative_ndc", ""),
                        "current_ncpdp_code": med_config.get("ncpdp_quantity_qualifier_code", ""),
                        "current_unit": med_config.get("unit", ""),
                        "api_clinical_quantities": clinical_quantities,
                        "status": "found",
                    })
                else:
                    results.append({
                        "id": med_id,
                        "display_name": display_name,
                        "fdb_code": fdb_code,
                        "status": "not_found",
                        "search_term": search_term,
                    })

            except Exception as e:
                results.append({
                    "id": med_id,
                    "display_name": display_name,
                    "fdb_code": fdb_code,
                    "status": "error",
                    "error": str(e),
                })

        return [JSONResponse({"medications": results, "success": True})]


class PrescribeFavoritesAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """API endpoint to handle prescription addition to most recent note."""

    PATH = "/routes/prescribe-favorites"

    def _get_service(self) -> FavoritesService:
        """Create a FavoritesService."""
        return FavoritesService()

    def post(self) -> list[Response | Effect]:
        """Add selected medications to most recently modified open note."""
        try:
            # Try request.json() first (works in test environment)
            # Fall back to raw body parsing (needed in production Canvas environment)
            try:
                request_data = self.request.json()
            except Exception:
                raw_body = self.request.body
                if hasattr(raw_body, 'decode'):
                    request_data = json.loads(raw_body.decode('utf-8'))
                else:
                    request_data = json.loads(raw_body)
        except Exception as e:
            log.error(f"Failed to parse JSON in prescribe: {e}")
            return [JSONResponse({"error": "Invalid JSON in request body", "success": False}, status=400)]

        # Extract patient ID and selected medications
        patient_id = request_data.get("patient_id")
        selected_meds = request_data.get("selected_medications", [])

        # Get the logged-in staff ID from request headers
        prescriber_id = self.request.headers.get("canvas-logged-in-user-id", "")
        if not prescriber_id:
            return [JSONResponse({"error": "Staff ID not found", "success": False}, status=400)]

        log.info(f"Adding {len(selected_meds)} medications to patient {patient_id}")

        if not patient_id:
            return [
                JSONResponse({"error": "Patient ID is required", "success": False}, status=400)
            ]

        if not selected_meds:
            return [
                JSONResponse({"error": "No medications selected", "success": False}, status=400)
            ]

        # Get most recently modified open note
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "Patient not found", "success": False}, status=404)]
        notes = self._get_all_open_notes(patient)

        if not notes.exists():
            log.warning(f"No open notes found for patient {patient_id}")
            return [
                JSONResponse(
                    {
                        "error": "No open notes found. Please create a new note to add prescriptions.",
                        "success": False,
                    },
                    status=400,
                )
            ]

        most_recent_note = notes.first()
        assert most_recent_note is not None  # We checked notes.exists() above
        log.info(f"Using note ID: {most_recent_note.id}")

        effects: list[Effect] = []
        skipped: list[str] = []

        # Batch-fetch all selected medications in one query (visibility-filtered)
        service = self._get_service()
        meds_by_id = service.get_favorites_by_ids(selected_meds, staff_id=prescriber_id)

        for med_id in selected_meds:
            med = meds_by_id.get(med_id)
            if med:
                # Validate required fields before prescribing
                if not med.get("fdb_code") or not med.get("sig"):
                    log.error(f"Skipping {med['display_name']}: missing fdb_code={med.get('fdb_code')!r} or sig={med.get('sig')!r}")
                    skipped.append(med["display_name"])
                    continue

                log.info(f"Creating prescription for {med['display_name']} (fdb_code={med['fdb_code']}, sig={med['sig']}, days={med['days_supply']}, qty={med['quantity_to_dispense']})")

                # Get pharmacy NCPDP ID if configured for this medication
                pharmacy_ncpdp_id = med.get("default_pharmacy_ncpdp_id")
                if pharmacy_ncpdp_id:
                    log.info(f"Using default pharmacy NCPDP ID: {pharmacy_ncpdp_id}")

                prescribe_effect = PrescribeCommand(
                    note_uuid=str(most_recent_note.id),
                    fdb_code=med["fdb_code"],
                    sig=med["sig"],
                    days_supply=med["days_supply"],
                    refills=med["refills"],
                    quantity_to_dispense=med["quantity_to_dispense"],
                    type_to_dispense=ClinicalQuantity(
                        representative_ndc=med["representative_ndc"],
                        ncpdp_quantity_qualifier_code=med[
                            "ncpdp_quantity_qualifier_code"
                        ],
                    ),
                    prescriber_id=prescriber_id,  # Current logged-in staff
                    pharmacy=pharmacy_ncpdp_id,  # Default pharmacy for this medication
                ).originate()

                effects.append(prescribe_effect)
            else:
                log.warning(f"Medication {med_id} not found in configuration")
                skipped.append(med_id)

        log.info(f"Created {len(effects)} prescription effects, {len(skipped)} skipped")

        if not effects:
            skipped_list = ", ".join(skipped) if skipped else "unknown"
            return [
                JSONResponse(
                    {
                        "error": f"Could not prescribe any of the selected medications. Failed: {skipped_list}",
                        "skipped": skipped,
                        "success": False,
                    },
                    status=400,
                )
            ]

        response_data: dict[str, object] = {
            "message": f"{len(effects)} prescriptions added to note",
            "note_id": str(most_recent_note.id),
            "count": len(effects),
            "success": True,
        }
        if skipped:
            response_data["skipped"] = skipped
            response_data["message"] = (
                f"{len(effects)} prescriptions added to note"
                f" ({len(skipped)} could not be prescribed: {', '.join(skipped)})"
            )

        return [
            JSONResponse(response_data),
            *effects,
        ]

    def _get_all_open_notes(self, patient: Patient):  # type: ignore[no-untyped-def]
        """Get all open notes for the patient, ordered by most recent."""
        open_note_states = [
            NoteStates.NEW,
            NoteStates.PUSHED,
            NoteStates.CONVERTED,
            NoteStates.UNLOCKED,
            NoteStates.RESTORED,
            NoteStates.UNDELETED,
        ]

        open_note_ids = CurrentNoteStateEvent.objects.filter(
            state__in=open_note_states
        ).values_list("note_id", flat=True)

        return Note.objects.filter(dbid__in=open_note_ids, patient=patient).order_by(
            "-modified"
        )
