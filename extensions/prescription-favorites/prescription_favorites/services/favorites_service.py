"""Service for managing prescription favorites with Custom Data storage."""

import uuid
from decimal import Decimal
from typing import Any

from django.db.models import Q
from logger import log

from prescription_favorites.medications import FAVORITE_MEDICATIONS
from prescription_favorites.models import CustomFavorite, HiddenDefault
from prescription_favorites.models.custom_favorite import CustomStaff


class FavoritesService:
    """Service for managing prescription favorites.

    Combines hardcoded default medications with user-added custom favorites.
    Custom favorites are stored in the plugin's Custom Data namespace via
    the CustomFavorite model.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize FavoritesService.

        Accepts **kwargs for backwards compatibility during migration
        (callers may still pass secrets/instance). These are ignored -
        storage is handled by CustomFavorite model in the plugin namespace.
        """
        pass

    def get_all_favorites(
        self,
        staff_id: str | None = None,
        visibility_filter: str | None = None,
        include_hidden: bool = False,
    ) -> list[dict[str, Any]]:
        """Get all favorites (hardcoded defaults + custom).

        Args:
            staff_id: Current staff user ID (UUID), used for filtering "mine" vs "shared".
            visibility_filter: One of "all", "mine", "shared", or None (returns all).
            include_hidden: If True, include hidden defaults with is_hidden flag (for manage mode).
        """
        favorites: list[dict[str, Any]] = []

        # Get hidden default IDs (and who hid them) for this staff member
        hidden_map: dict[str, str | None] = {}
        if staff_id:
            for h in HiddenDefault.objects.select_related("hidden_by").filter(
                hidden_by__id=staff_id
            ):
                hider = h.hidden_by
                if hider:
                    first = getattr(hider, "first_name", "") or ""
                    last = getattr(hider, "last_name", "") or ""
                    hidden_map[h.default_id] = f"{first} {last}".strip() or None
                else:
                    hidden_map[h.default_id] = None

        # Hardcoded defaults - skip if filtering to "mine" only
        if visibility_filter != "mine":
            for med_id, med in FAVORITE_MEDICATIONS.items():
                is_hidden = med_id in hidden_map
                if not include_hidden and is_hidden:
                    continue
                favorite = dict(med)
                favorite["is_custom"] = False
                favorite["is_shared"] = True
                favorite["is_mine"] = False
                favorite["is_hidden"] = is_hidden
                if is_hidden:
                    favorite["hidden_by_name"] = hidden_map[med_id]
                favorites.append(favorite)

        # Get custom favorites with visibility filtering
        queryset = CustomFavorite.objects.select_related("created_by").all().order_by("dbid")

        if visibility_filter == "mine" and staff_id:
            queryset = queryset.filter(created_by__id=staff_id)
        elif visibility_filter == "shared":
            queryset = queryset.filter(is_shared=True)
        elif staff_id:
            # "all": show shared + my private ones + legacy (no creator set)
            queryset = queryset.filter(
                Q(is_shared=True) | Q(created_by__id=staff_id) | Q(created_by__isnull=True)
            )

        for custom in queryset:
            favorites.append(self._to_dict(custom, staff_id=staff_id))

        return favorites

    def get_custom_favorites(self) -> list[dict[str, Any]]:
        """Get only user-added custom favorites."""
        customs = list(
            CustomFavorite.objects.select_related("created_by").all().order_by("dbid")
        )
        return [self._to_dict(fav) for fav in customs]

    REQUIRED_FIELDS = [
        "display_name", "fdb_code", "sig", "days_supply",
        "quantity_to_dispense", "unit", "representative_ndc",
        "ncpdp_quantity_qualifier_code",
    ]

    def save_custom_favorite(self, medication_config: dict[str, Any]) -> dict[str, Any]:
        """Save a new custom favorite."""
        missing = [f for f in self.REQUIRED_FIELDS if not medication_config.get(f)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        custom_id = f"custom_{uuid.uuid4().hex[:12]}"

        # Resolve staff UUID to a CustomStaff object for the FK
        created_by_uuid = medication_config.get("created_by_id")
        staff_obj = None
        if created_by_uuid:
            try:
                staff_obj = CustomStaff.objects.get(id=created_by_uuid)
            except CustomStaff.DoesNotExist:
                raise ValueError(f"Staff record not found for UUID: {created_by_uuid}")

        favorite = CustomFavorite.objects.create(
            custom_id=custom_id,
            display_name=medication_config["display_name"],
            label=medication_config.get("label") or "",
            label_color=medication_config.get("label_color") or "",
            medication_name=medication_config.get("medication_name", medication_config["display_name"]),
            fdb_code=str(medication_config["fdb_code"]),
            sig=medication_config["sig"],
            days_supply=int(medication_config["days_supply"]),
            quantity_to_dispense=Decimal(str(medication_config["quantity_to_dispense"])),
            unit=medication_config["unit"],
            refills=int(medication_config.get("refills", 0)),
            representative_ndc=str(medication_config["representative_ndc"]),
            ncpdp_quantity_qualifier_code=medication_config["ncpdp_quantity_qualifier_code"],
            generic_substitution_allowed=medication_config.get("generic_substitution_allowed", True),
            search_terms=medication_config.get("search_terms", []),
            default_pharmacy_ncpdp_id=medication_config.get("default_pharmacy_ncpdp_id") or "",
            default_pharmacy_name=medication_config.get("default_pharmacy_name") or "",
            is_shared=medication_config.get("is_shared", True),
            created_by=staff_obj,
        )

        staff_uuid = str(favorite.created_by.id) if favorite.created_by else None
        log.info(f"Saved custom favorite: {custom_id} - {favorite.display_name} (shared={favorite.is_shared}, created_by={staff_uuid})")
        return self._to_dict(favorite)

    def update_custom_favorite(
        self, favorite_id: str, medication_config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update an existing custom favorite."""
        if not self.is_custom_favorite(favorite_id):
            log.warning(f"Cannot update non-custom favorite: {favorite_id}")
            return None

        try:
            favorite = CustomFavorite.objects.select_related("created_by").get(
                custom_id=favorite_id
            )
        except CustomFavorite.DoesNotExist:
            log.warning(f"Custom favorite not found: {favorite_id}")
            return None

        # Use "key in dict" checks so callers can explicitly clear fields
        # by passing None or empty string.
        if "display_name" in medication_config:
            favorite.display_name = medication_config["display_name"]
        if "label" in medication_config:
            favorite.label = medication_config["label"] or ""
        if "label_color" in medication_config:
            favorite.label_color = medication_config["label_color"] or ""
        if "medication_name" in medication_config:
            favorite.medication_name = medication_config["medication_name"]
        if "fdb_code" in medication_config:
            favorite.fdb_code = str(medication_config["fdb_code"])
        if "sig" in medication_config:
            favorite.sig = medication_config["sig"]
        if "days_supply" in medication_config:
            favorite.days_supply = int(medication_config["days_supply"])
        if "quantity_to_dispense" in medication_config:
            favorite.quantity_to_dispense = Decimal(str(medication_config["quantity_to_dispense"]))
        if "unit" in medication_config:
            favorite.unit = medication_config["unit"]
        if "refills" in medication_config:
            favorite.refills = int(medication_config["refills"])
        if "representative_ndc" in medication_config:
            favorite.representative_ndc = str(medication_config["representative_ndc"])
        if "ncpdp_quantity_qualifier_code" in medication_config:
            favorite.ncpdp_quantity_qualifier_code = medication_config["ncpdp_quantity_qualifier_code"]
        if "generic_substitution_allowed" in medication_config:
            favorite.generic_substitution_allowed = medication_config["generic_substitution_allowed"]
        if "search_terms" in medication_config:
            favorite.search_terms = medication_config["search_terms"]
        if "default_pharmacy_ncpdp_id" in medication_config:
            favorite.default_pharmacy_ncpdp_id = medication_config["default_pharmacy_ncpdp_id"] or ""
        if "default_pharmacy_name" in medication_config:
            favorite.default_pharmacy_name = medication_config["default_pharmacy_name"] or ""
        if "is_shared" in medication_config:
            favorite.is_shared = medication_config["is_shared"]
        favorite.save()

        log.info(f"Updated custom favorite: {favorite_id}")
        return self._to_dict(favorite)

    def delete_custom_favorite(self, favorite_id: str) -> bool:
        """Delete a custom favorite."""
        if not self.is_custom_favorite(favorite_id):
            log.warning(f"Cannot delete non-custom favorite: {favorite_id}")
            return False

        try:
            favorite = CustomFavorite.objects.get(custom_id=favorite_id)
        except CustomFavorite.DoesNotExist:
            log.warning(f"Custom favorite not found: {favorite_id}")
            return False

        favorite.delete()
        log.info(f"Deleted custom favorite: {favorite_id}")
        return True

    def is_custom_favorite(self, favorite_id: str) -> bool:
        """Check if a favorite ID is a custom (user-added) favorite."""
        return favorite_id.startswith("custom_")

    def get_favorite_by_id(self, favorite_id: str) -> dict[str, Any] | None:
        """Get a specific favorite by ID."""
        if favorite_id in FAVORITE_MEDICATIONS:
            favorite = dict(FAVORITE_MEDICATIONS[favorite_id])
            favorite["is_custom"] = False
            return favorite

        try:
            custom = CustomFavorite.objects.select_related("created_by").get(
                custom_id=favorite_id
            )
            return self._to_dict(custom)
        except CustomFavorite.DoesNotExist:
            return None

    def get_favorites_by_ids(
        self, favorite_ids: list[str], staff_id: str | None = None
    ) -> dict[str, dict[str, Any]]:
        """Batch-get favorites by IDs. Returns {id: favorite_dict}.

        Looks up hardcoded defaults from memory and custom favorites
        in a single DB query. When staff_id is provided, only returns
        custom favorites the caller can see (shared, own, or legacy).
        """
        result: dict[str, dict[str, Any]] = {}

        custom_ids = []
        for fid in favorite_ids:
            if fid in FAVORITE_MEDICATIONS:
                fav = dict(FAVORITE_MEDICATIONS[fid])
                fav["is_custom"] = False
                result[fid] = fav
            elif self.is_custom_favorite(fid):
                custom_ids.append(fid)

        if custom_ids:
            queryset = CustomFavorite.objects.select_related("created_by").filter(
                custom_id__in=custom_ids
            )
            if staff_id:
                queryset = queryset.filter(
                    Q(is_shared=True) | Q(created_by__id=staff_id) | Q(created_by__isnull=True)
                )
            else:
                queryset = queryset.filter(is_shared=True)
            for custom in queryset:
                result[custom.custom_id] = self._to_dict(custom, staff_id=staff_id)

        return result

    def hide_default(self, default_id: str, staff_id: str) -> str | bool:
        """Hide a default favorite for a staff member.

        Returns True on success, or a string error message on failure.
        """
        if default_id not in FAVORITE_MEDICATIONS:
            log.warning(f"Not a default favorite: {default_id}")
            return "Not a default favorite"
        try:
            staff = CustomStaff.objects.get(id=staff_id)
        except CustomStaff.DoesNotExist:
            log.warning(f"Staff not found for UUID: {staff_id}")
            return "Staff record not found"
        _, created = HiddenDefault.objects.get_or_create(
            default_id=default_id, hidden_by=staff
        )
        log.info(f"{'Hid' if created else 'Already hidden'} default {default_id} for staff {staff_id}")
        return True

    def unhide_default(self, default_id: str, staff_id: str) -> bool:
        """Unhide a default favorite for a staff member."""
        try:
            hidden = HiddenDefault.objects.get(
                default_id=default_id, hidden_by__id=staff_id
            )
            hidden.delete()
            log.info(f"Unhid default {default_id} for staff {staff_id}")
            return True
        except HiddenDefault.DoesNotExist:
            return False

    def _to_dict(
        self,
        favorite: CustomFavorite,
        staff_id: str | None = None,
    ) -> dict[str, Any]:
        """Convert a CustomFavorite model instance to an API-compatible dict.

        Expects the queryset to have used select_related('created_by')
        so accessing favorite.created_by doesn't trigger extra queries.
        """
        creator = favorite.created_by
        creator_uuid = str(creator.id) if creator else None
        creator_name = None
        if creator:
            first = getattr(creator, "first_name", "") or ""
            last = getattr(creator, "last_name", "") or ""
            name = f"{first} {last}".strip()
            creator_name = name or None

        return {
            "id": favorite.custom_id,
            "display_name": favorite.display_name,
            "label": favorite.label if favorite.label else None,
            "label_color": favorite.label_color if favorite.label_color else None,
            "medication_name": favorite.medication_name,
            "fdb_code": favorite.fdb_code,
            "sig": favorite.sig,
            "days_supply": favorite.days_supply,
            "quantity_to_dispense": float(favorite.quantity_to_dispense),
            "unit": favorite.unit,
            "refills": favorite.refills,
            "representative_ndc": favorite.representative_ndc,
            "ncpdp_quantity_qualifier_code": favorite.ncpdp_quantity_qualifier_code,
            "generic_substitution_allowed": favorite.generic_substitution_allowed,
            "search_terms": favorite.search_terms,
            "default_pharmacy_ncpdp_id": favorite.default_pharmacy_ncpdp_id if favorite.default_pharmacy_ncpdp_id else None,
            "default_pharmacy_name": favorite.default_pharmacy_name if favorite.default_pharmacy_name else None,
            "is_custom": True,
            "is_shared": favorite.is_shared,
            "is_mine": bool(staff_id and creator_uuid == staff_id),
            "created_by_id": creator_uuid,
            "created_by_name": creator_name,
            "created_at": favorite.created_at.isoformat() if favorite.created_at else None,
        }
