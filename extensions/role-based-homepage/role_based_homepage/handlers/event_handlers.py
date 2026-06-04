import json

from pydantic import ValidationError

from canvas_sdk.effects import Effect
from canvas_sdk.effects.default_homepage import DefaultHomepageEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Staff
from logger import log

#: Config key reserved for the catch-all default destination. It can never collide with a real
#: ``StaffRole.internal_code`` (codes are alphanumeric).
WILDCARD_KEY = "*"

#: Built-in homepage page names, keyed by their uppercased name for case-insensitive lookup.
PAGE_BY_NAME = {page.name.upper(): page for page in DefaultHomepageEffect.Pages}


class RoleBasedHomepage(BaseHandler):
    """Set each staff member's default homepage based on their StaffRole.

    Responds to ``GET_HOMEPAGE_CONFIGURATION`` (fired on login when the provider homepage
    loads). The acting user is read from ``self.event.actor``; their highest-privilege role
    whose ``internal_code`` appears in the ``ROLE_HOMEPAGE_MAP`` secret determines the
    destination. See ``.cpa-workflow-artifacts/plugin-spec.md`` for the full design.
    """

    RESPONDS_TO = EventType.Name(EventType.GET_HOMEPAGE_CONFIGURATION)

    def compute(self) -> list[Effect]:
        """Return a single ``DefaultHomepageEffect`` for the acting staff member, or ``[]``."""
        role_map = self._load_role_map()
        if not role_map:
            return []

        staff = self._resolve_staff()
        if staff is None:
            return []

        destination = self._select_destination(staff, role_map)
        if destination is None:
            return []

        effect = self._build_effect(destination)
        if effect is None:
            return []

        return [effect]

    def _load_role_map(self) -> dict[str, str]:
        """Parse and normalize the ``ROLE_HOMEPAGE_MAP`` secret.

        Keys (role internal codes and the ``*`` wildcard) are upper-cased and stripped so
        matching is case/whitespace insensitive. Returns ``{}`` on any missing/invalid config;
        the caller treats that as "no override" (Canvas falls back to ``/schedule``).
        """
        raw = (self.secrets.get("ROLE_HOMEPAGE_MAP") or "").strip()
        if not raw:
            log.warning("[RoleBasedHomepage] ROLE_HOMEPAGE_MAP is not configured; skipping.")
            return {}

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("[RoleBasedHomepage] ROLE_HOMEPAGE_MAP is not valid JSON; skipping.")
            return {}

        if not isinstance(parsed, dict):
            log.warning("[RoleBasedHomepage] ROLE_HOMEPAGE_MAP must be a JSON object; skipping.")
            return {}

        normalized: dict[str, str] = {}
        for key, value in parsed.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            norm_key = key.strip().upper()
            norm_value = value.strip()
            if norm_key and norm_value:
                normalized[norm_key] = norm_value
        return normalized

    def _resolve_staff(self) -> Staff | None:
        """Resolve the acting staff member from the event actor.

        The event fires with ``actor = <CanvasUser dbid>``. Roles are prefetched so destination
        selection runs in a single additional query (no N+1).
        """
        actor_id = self.event.actor.id
        if not actor_id:
            return None
        # ``user_id`` holds the related CanvasUser's dbid, which is exactly what the actor id is,
        # so filter on the FK column directly (no join).
        return Staff.objects.filter(user_id=actor_id).prefetch_related("roles").first()

    def _select_destination(self, staff: Staff, role_map: dict[str, str]) -> str | None:
        """Pick the destination for the highest-privilege explicitly-mapped role.

        Falls back to the ``*`` wildcard destination when the staff has no explicitly mapped
        role, or ``None`` when neither applies.
        """
        best_destination: str | None = None
        best_privilege: int | None = None

        for role in staff.roles.all():
            code = (role.internal_code or "").strip().upper()
            if not code or code not in role_map:
                continue
            privilege = role.domain_privilege_level
            if best_privilege is None or privilege > best_privilege:
                best_privilege = privilege
                best_destination = role_map[code]

        if best_destination is not None:
            return best_destination

        return role_map.get(WILDCARD_KEY)

    def _build_effect(self, destination: str) -> Effect | None:
        """Build a ``DefaultHomepageEffect`` from a destination string.

        A value matching a built-in page name (case-insensitive) becomes a ``page``; anything
        else is treated as a plugin ``application_identifier``. ``apply()`` validates that the
        application actually exists, so a stale/misconfigured identifier raises a
        ``ValidationError`` — in that case we log and return ``None`` so Canvas falls back to its
        default rather than crashing the homepage load.
        """
        page = PAGE_BY_NAME.get(destination.upper())
        if page is not None:
            return DefaultHomepageEffect(page=page).apply()

        try:
            return DefaultHomepageEffect(application_identifier=destination).apply()
        except ValidationError:
            log.warning(
                "[RoleBasedHomepage] Destination %r is not a known page or installed "
                "application; skipping.",
                destination,
            )
            return None
