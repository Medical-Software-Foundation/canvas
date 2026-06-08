"""Service for managing lab order favorites in Custom Data storage."""

from typing import Any, cast
from uuid import uuid4

from django.db.models import Q
from logger import log

from lab_order_favorites.models import CustomStaff, LabFavorite


class FavoritesService:
    """Create, read, update, delete and search lab order favorites.

    Favorites are stored in the plugin's Custom Data namespace via the
    LabFavorite model. Authorization (who may edit/delete) is enforced by the
    API layer, not here. Visibility: a staff member sees shared favorites plus
    their own personal favorites.
    """

    def visible_queryset(self, staff_id: str | None):  # type: ignore[no-untyped-def]
        """Return favorites the given staff member is allowed to see."""
        queryset = LabFavorite.objects.select_related("created_by").all().order_by("name")
        if staff_id:
            return queryset.filter(Q(is_shared=True) | Q(created_by__id=staff_id))
        return queryset.filter(is_shared=True)

    def list_favorites(
        self,
        staff_id: str | None,
        visibility_filter: str = "all",
        search: str = "",
    ) -> list[dict[str, Any]]:
        """List visible favorites, optionally filtered by ownership and search.

        visibility_filter: "all", "mine", or "shared".
        search: matched (case-insensitive, OR) against favorite name, tag,
        author name, test name/code, and lab partner name.
        """
        queryset = self.visible_queryset(staff_id)
        if visibility_filter == "mine" and staff_id:
            queryset = queryset.filter(created_by__id=staff_id)
        elif visibility_filter == "shared":
            queryset = queryset.filter(is_shared=True)

        favorites = [self._to_dict(fav, staff_id=staff_id) for fav in queryset]

        needle = search.strip().lower()
        if needle:
            favorites = [fav for fav in favorites if _matches(fav, needle)]
        return favorites

    def get_favorite(self, custom_id: str, staff_id: str | None) -> dict[str, Any] | None:
        """Get a single visible favorite as a dict, or None."""
        fav = self.get_favorite_model(custom_id)
        if fav is None:
            return None
        if not self._is_visible(fav, staff_id):
            return None
        return self._to_dict(fav, staff_id=staff_id)

    def get_favorite_model(self, custom_id: str) -> LabFavorite | None:
        """Get the LabFavorite model instance by custom_id, or None."""
        try:
            favorite = LabFavorite.objects.select_related("created_by").get(custom_id=custom_id)
        except LabFavorite.DoesNotExist:
            return None
        return cast(LabFavorite, favorite)

    def create_favorite(self, data: dict[str, Any], staff_id: str) -> dict[str, Any]:
        """Create a favorite owned by staff_id. Raises ValueError on bad input."""
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        lab_partner_id = str(data.get("lab_partner_id", "")).strip()
        if not lab_partner_id:
            raise ValueError("lab_partner_id is required")
        tests = data.get("tests") or []
        if not tests:
            raise ValueError("at least one test is required")

        try:
            staff_obj = CustomStaff.objects.get(id=staff_id)
        except CustomStaff.DoesNotExist:
            raise ValueError(f"Staff record not found for UUID: {staff_id}")

        favorite = LabFavorite.objects.create(
            custom_id=f"labfav_{uuid4().hex[:12]}",
            name=name,
            lab_partner_id=lab_partner_id,
            lab_partner_name=str(data.get("lab_partner_name", "")).strip(),
            tests=_normalize_tests(tests),
            tags=_normalize_tags(data.get("tags") or []),
            fasting_required=bool(data.get("fasting_required", False)),
            comment=str(data.get("comment", "")).strip(),
            diagnosis_codes=_normalize_codes(data.get("diagnosis_codes") or []),
            ordering_provider_key=str(data.get("ordering_provider_key", "")).strip(),
            ordering_provider_name=str(data.get("ordering_provider_name", "")).strip(),
            is_shared=bool(data.get("is_shared", True)),
            created_by=staff_obj,
        )
        log.info(f"Created lab favorite {favorite.custom_id} ({name})")
        return self._to_dict(favorite, staff_id=staff_id)

    def update_favorite(
        self, custom_id: str, data: dict[str, Any], staff_id: str
    ) -> dict[str, Any] | None:
        """Update a favorite by id. Authorization is enforced by the caller.

        Returns the updated favorite, or None if it does not exist.
        """
        favorite = self.get_favorite_model(custom_id)
        if favorite is None:
            return None

        if "name" in data:
            name = str(data["name"]).strip()
            if not name:
                raise ValueError("name cannot be empty")
            favorite.name = name
        if "lab_partner_id" in data:
            favorite.lab_partner_id = str(data["lab_partner_id"]).strip()
        if "lab_partner_name" in data:
            favorite.lab_partner_name = str(data["lab_partner_name"]).strip()
        if "tests" in data:
            tests = data["tests"] or []
            if not tests:
                raise ValueError("at least one test is required")
            favorite.tests = _normalize_tests(tests)
        if "tags" in data:
            favorite.tags = _normalize_tags(data["tags"] or [])
        if "fasting_required" in data:
            favorite.fasting_required = bool(data["fasting_required"])
        if "comment" in data:
            favorite.comment = str(data["comment"]).strip()
        if "diagnosis_codes" in data:
            favorite.diagnosis_codes = _normalize_codes(data["diagnosis_codes"] or [])
        if "ordering_provider_key" in data:
            favorite.ordering_provider_key = str(data["ordering_provider_key"]).strip()
        if "ordering_provider_name" in data:
            favorite.ordering_provider_name = str(data["ordering_provider_name"]).strip()
        if "is_shared" in data:
            favorite.is_shared = bool(data["is_shared"])

        favorite.save()
        log.info(f"Updated lab favorite {custom_id}")
        return self._to_dict(favorite, staff_id=staff_id)

    def delete_favorite(self, custom_id: str) -> bool:
        """Delete a favorite by id. Authorization is enforced by the caller.

        Returns True if a favorite was deleted, False if it did not exist.
        """
        favorite = self.get_favorite_model(custom_id)
        if favorite is None:
            return False
        favorite.delete()
        log.info(f"Deleted lab favorite {custom_id}")
        return True

    def _is_visible(self, favorite: LabFavorite, staff_id: str | None) -> bool:
        if favorite.is_shared:
            return True
        return bool(staff_id and str(favorite.created_by.id) == staff_id)

    def _to_dict(self, favorite: LabFavorite, staff_id: str | None = None) -> dict[str, Any]:
        """Convert a LabFavorite to an API/UI dict.

        Expects select_related('created_by') so author access is not an extra query.
        """
        creator = favorite.created_by
        creator_uuid = str(creator.id)
        first = (creator.first_name or "").strip()
        last = (creator.last_name or "").strip()
        creator_name = f"{first} {last}".strip() or None

        return {
            "id": favorite.custom_id,
            "name": favorite.name,
            "lab_partner_id": favorite.lab_partner_id,
            "lab_partner_name": favorite.lab_partner_name,
            "tests": favorite.tests,
            "tags": favorite.tags,
            "fasting_required": favorite.fasting_required,
            "comment": favorite.comment,
            "diagnosis_codes": favorite.diagnosis_codes,
            "ordering_provider_key": favorite.ordering_provider_key,
            "ordering_provider_name": favorite.ordering_provider_name,
            "is_shared": favorite.is_shared,
            "is_mine": bool(staff_id and creator_uuid == staff_id),
            "created_by_id": creator_uuid,
            "created_by_name": creator_name,
            "created_at": favorite.created_at.isoformat() if favorite.created_at else None,
        }


def _matches(favorite: dict[str, Any], needle: str) -> bool:
    """Return True if the favorite matches the search needle on any axis."""
    haystack_parts = [
        favorite.get("name", "") or "",
        favorite.get("lab_partner_name", "") or "",
        favorite.get("created_by_name", "") or "",
    ]
    haystack_parts.extend(favorite.get("tags", []) or [])
    for test in favorite.get("tests", []) or []:
        haystack_parts.append(test.get("order_name", "") or "")
        haystack_parts.append(test.get("order_code", "") or "")
    return needle in " ".join(haystack_parts).lower()


def _normalize_tests(tests: list[Any]) -> list[dict[str, str]]:
    """Coerce test entries to {order_code, order_name, cpt_code} string dicts."""
    normalized: list[dict[str, str]] = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        normalized.append(
            {
                "order_code": str(test.get("order_code", "")).strip(),
                "order_name": str(test.get("order_name", "")).strip(),
                "cpt_code": str(test.get("cpt_code", "")).strip(),
            }
        )
    return normalized


def _normalize_tags(tags: list[Any]) -> list[str]:
    """Lowercase, strip, and de-duplicate tags preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        cleaned = str(tag).strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _normalize_codes(codes: list[Any]) -> list[str]:
    """Strip and drop empty diagnosis codes preserving order."""
    return [str(code).strip() for code in codes if str(code).strip()]
