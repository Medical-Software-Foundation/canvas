"""Service layer for clinical-favorites CRUD, visibility filtering, and hide defaults."""

import datetime
import uuid
from decimal import Decimal
from typing import Any

from django.db.models import Q
from logger import log

from clinical_favorites.models import ClinicalFavorite, CustomStaff, HiddenDefault


REQUIRED_MEDICATION_FIELDS = [
    "display_name",
    "fdb_code",
    "sig",
    "days_supply",
    "quantity_to_dispense",
    "unit",
    "representative_ndc",
    "ncpdp_quantity_qualifier_code",
]
REQUIRED_CONDITION_FIELDS = ["code", "display_name"]


class FavoritesService:
    """Service for managing clinical favorites."""

    def get_all_favorites(
        self,
        staff_id: str | None = None,
        visibility_filter: str | None = None,
        favorite_type: str | None = None,
        include_hidden: bool = False,
    ) -> list[dict[str, Any]]:
        queryset = ClinicalFavorite.objects.select_related("created_by").all().order_by("dbid")

        if favorite_type:
            queryset = queryset.filter(favorite_type=favorite_type)

        if visibility_filter == "mine" and staff_id:
            queryset = queryset.filter(created_by__id=staff_id)
        elif visibility_filter == "shared":
            queryset = queryset.filter(is_shared=True)
        elif staff_id:
            queryset = queryset.filter(
                Q(is_shared=True) | Q(created_by__id=staff_id) | Q(created_by__isnull=True)
            )

        return [self._to_dict(f, staff_id=staff_id) for f in queryset]

    def is_custom_favorite(self, favorite_id: str) -> bool:
        return favorite_id.startswith("custom_")

    def validate_favorite_payload(
        self,
        favorite_type: str,
        payload: Any,
    ) -> str | None:
        """Return None if the payload is acceptable, else a reason string.

        Mirrors every check save_favorite would run before persistence,
        minus the staff lookup and the database write. Used by the bulk
        import dry-run path to surface per row reasons before commit.
        """
        if not isinstance(payload, dict):
            return "Row is not an object"

        if favorite_type == "medication":
            missing = [f for f in REQUIRED_MEDICATION_FIELDS if not payload.get(f)]
        elif favorite_type == "condition":
            missing = [f for f in REQUIRED_CONDITION_FIELDS if not payload.get(f)]
        else:
            return "favorite_type must be medication or condition"

        if missing:
            return f"Missing required fields, {', '.join(missing)}"

        if favorite_type == "medication":
            try:
                int(payload["days_supply"])
            except (TypeError, ValueError):
                return "days_supply must be an integer"
            try:
                Decimal(str(payload["quantity_to_dispense"]))
            except Exception:
                return "quantity_to_dispense must be a decimal"
            if "refills" in payload and payload["refills"] is not None:
                try:
                    int(payload["refills"])
                except (TypeError, ValueError):
                    return "refills must be an integer"

        return None

    def save_favorite(
        self,
        favorite_type: str,
        payload: dict[str, Any],
        staff_id: str | None,
    ) -> dict[str, Any]:
        reason = self.validate_favorite_payload(favorite_type, payload)
        if reason:
            raise ValueError(reason)

        staff_obj = None
        if staff_id:
            try:
                staff_obj = CustomStaff.objects.get(id=staff_id)
            except CustomStaff.DoesNotExist as exc:
                raise ValueError(f"Staff record not found for UUID {staff_id}") from exc

        custom_id = f"custom_{uuid.uuid4().hex[:12]}"

        kwargs: dict[str, Any] = {
            "custom_id": custom_id,
            "favorite_type": favorite_type,
            "code": str(payload.get("code") or payload.get("fdb_code") or ""),
            "display_name": payload["display_name"],
            "label": payload.get("label") or "",
            "label_color": payload.get("label_color") or "",
            "group_name": payload.get("group_name") or "",
            "is_shared": payload.get("is_shared", True),
            "created_by": staff_obj,
            "fdb_code": "",
        }

        if favorite_type == "medication":
            kwargs.update({
                "medication_name": payload.get("medication_name", payload["display_name"]),
                "fdb_code": str(payload["fdb_code"]),
                "sig": payload["sig"],
                "days_supply": int(payload["days_supply"]),
                "quantity_to_dispense": Decimal(str(payload["quantity_to_dispense"])),
                "unit": payload["unit"],
                "refills": int(payload.get("refills") or 0),
                "representative_ndc": str(payload["representative_ndc"]),
                "ncpdp_quantity_qualifier_code": payload["ncpdp_quantity_qualifier_code"],
                "generic_substitution_allowed": payload.get("generic_substitution_allowed", True),
                "search_terms": payload.get("search_terms", []),
                "default_pharmacy_ncpdp_id": payload.get("default_pharmacy_ncpdp_id") or "",
                "default_pharmacy_name": payload.get("default_pharmacy_name") or "",
                "note_to_pharmacist": payload.get("note_to_pharmacist") or "",
            })

        favorite = ClinicalFavorite.objects.create(**kwargs)
        log.info(f"Saved clinical favorite {custom_id} ({favorite_type})")
        return self._to_dict(favorite, staff_id=staff_id)

    def update_favorite(self, custom_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            ClinicalFavorite.objects.get(custom_id=custom_id)
        except ClinicalFavorite.DoesNotExist:
            return None

        update_fields: dict[str, Any] = {}
        for key in (
            "display_name",
            "label",
            "label_color",
            "group_name",
            "medication_name",
            "sig",
            "unit",
            "representative_ndc",
            "ncpdp_quantity_qualifier_code",
            "default_pharmacy_ncpdp_id",
            "default_pharmacy_name",
            "note_to_pharmacist",
        ):
            if key in payload:
                update_fields[key] = payload[key] or ""

        if "fdb_code" in payload:
            update_fields["fdb_code"] = str(payload["fdb_code"] or "")
        if "days_supply" in payload:
            update_fields["days_supply"] = (
                int(payload["days_supply"]) if payload["days_supply"] is not None else None
            )
        if "quantity_to_dispense" in payload:
            update_fields["quantity_to_dispense"] = Decimal(str(payload["quantity_to_dispense"]))
        if "refills" in payload:
            update_fields["refills"] = (
                int(payload["refills"]) if payload["refills"] is not None else 0
            )
        if "generic_substitution_allowed" in payload:
            update_fields["generic_substitution_allowed"] = payload["generic_substitution_allowed"]
        if "search_terms" in payload:
            update_fields["search_terms"] = payload["search_terms"]
        if "is_shared" in payload:
            update_fields["is_shared"] = payload["is_shared"]

        if update_fields:
            update_fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
            ClinicalFavorite.objects.filter(custom_id=custom_id).update(**update_fields)

        favorite = ClinicalFavorite.objects.select_related("created_by").get(custom_id=custom_id)
        return self._to_dict(favorite)

    def delete_favorite(self, custom_id: str) -> bool:
        deleted, _ = ClinicalFavorite.objects.filter(custom_id=custom_id).delete()
        return deleted > 0

    def get_favorite_by_id(self, custom_id: str) -> dict[str, Any] | None:
        try:
            favorite = ClinicalFavorite.objects.select_related("created_by").get(custom_id=custom_id)
        except ClinicalFavorite.DoesNotExist:
            return None
        return self._to_dict(favorite)

    def get_favorites_by_ids(
        self, custom_ids: list[str], staff_id: str | None = None
    ) -> dict[str, dict[str, Any]]:
        queryset = ClinicalFavorite.objects.select_related("created_by").filter(
            custom_id__in=custom_ids
        )
        if staff_id:
            queryset = queryset.filter(
                Q(is_shared=True) | Q(created_by__id=staff_id) | Q(created_by__isnull=True)
            )
        else:
            queryset = queryset.filter(is_shared=True)
        return {f.custom_id: self._to_dict(f, staff_id=staff_id) for f in queryset}

    def hide_default(
        self, default_id: str, favorite_type: str, staff_id: str
    ) -> str | bool:
        try:
            staff = CustomStaff.objects.get(id=staff_id)
        except CustomStaff.DoesNotExist:
            return "Staff record not found"
        HiddenDefault.objects.get_or_create(
            default_id=default_id,
            favorite_type=favorite_type,
            hidden_by=staff,
        )
        return True

    def unhide_default(self, default_id: str, staff_id: str) -> bool:
        try:
            hidden = HiddenDefault.objects.get(
                default_id=default_id, hidden_by__id=staff_id
            )
        except HiddenDefault.DoesNotExist:
            return False
        hidden.delete()
        return True

    def _to_dict(
        self, favorite: ClinicalFavorite, staff_id: str | None = None
    ) -> dict[str, Any]:
        creator = favorite.created_by
        creator_uuid = str(creator.id) if creator else None
        creator_name = None
        if creator:
            first = getattr(creator, "first_name", "") or ""
            last = getattr(creator, "last_name", "") or ""
            creator_name = f"{first} {last}".strip() or None

        return {
            "id": favorite.custom_id,
            "favorite_type": favorite.favorite_type,
            "code": favorite.code,
            "display_name": favorite.display_name,
            "label": favorite.label or None,
            "label_color": favorite.label_color or None,
            "group_name": favorite.group_name or None,
            "is_shared": favorite.is_shared,
            "is_mine": bool(staff_id and creator_uuid == staff_id),
            "is_custom": True,
            "created_by_id": creator_uuid,
            "created_by_name": creator_name,
            "created_at": favorite.created_at.isoformat() if favorite.created_at else None,
            "medication_name": favorite.medication_name or None,
            "fdb_code": favorite.fdb_code or None,
            "sig": favorite.sig or None,
            "days_supply": favorite.days_supply,
            "quantity_to_dispense": float(favorite.quantity_to_dispense) if favorite.quantity_to_dispense is not None else None,
            "unit": favorite.unit or None,
            "refills": favorite.refills,
            "representative_ndc": favorite.representative_ndc or None,
            "ncpdp_quantity_qualifier_code": favorite.ncpdp_quantity_qualifier_code or None,
            "generic_substitution_allowed": favorite.generic_substitution_allowed,
            "search_terms": favorite.search_terms,
            "default_pharmacy_ncpdp_id": favorite.default_pharmacy_ncpdp_id or None,
            "default_pharmacy_name": favorite.default_pharmacy_name or None,
            "note_to_pharmacist": favorite.note_to_pharmacist or None,
        }
