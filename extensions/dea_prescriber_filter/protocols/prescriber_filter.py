import json
from typing import Any

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.commands.validation import CommandValidationErrorEffect
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.staff import Staff

from logger import log

from dea_prescriber_filter.engine.storage import get_all_delegations

AUTH_USER_CACHE_PREFIX = "dea:user:"
AUTH_USER_CACHE_TTL = 300  # seconds — stores user staff key for validation to read


DEFAULT_NPI = "1111155556"


def _get_staff_uuid(staff_key: str) -> str | None:
    """Resolve a staff key (dbid or UUID) to its UUID string."""
    try:
        if staff_key.isdigit():
            staff = Staff.objects.get(pk=int(staff_key))
        else:
            staff = Staff.objects.get(id=staff_key)
        return str(staff.id)
    except Staff.DoesNotExist:
        return None


def _get_staff_npi(staff_key: str) -> str | None:
    """Resolve a staff key to its NPI, returning None for default NPI."""
    try:
        if staff_key.isdigit():
            staff = Staff.objects.get(pk=int(staff_key))
        else:
            staff = Staff.objects.get(id=staff_key)
        npi = staff.npi_number
        if not npi:
            return None
        npi_str = str(npi)
        return None if npi_str == DEFAULT_NPI else npi_str
    except Staff.DoesNotExist:
        return None


def _get_all_uuids_for_npi(npi: str) -> list[str]:
    """Get all active staff UUIDs that share the same NPI."""
    return [str(s.id) for s in Staff.objects.filter(npi_number=npi, active=True)]


def _is_own_prescriber(user_staff_key: str, prescriber_staff_key: str) -> bool:
    """True if the user IS the prescriber — by Staff identity OR shared NPI.

    Staff-identity match (same DB row, regardless of NPI) handles the case where
    a staff member has no NPI on file yet but is refilling their own prescription.
    NPI-match handles the case where the same person has multiple Staff profiles
    (e.g. per state/role) that share an NPI.
    """
    user_uuid = _get_staff_uuid(user_staff_key)
    prescriber_uuid = _get_staff_uuid(prescriber_staff_key)
    if user_uuid and prescriber_uuid and user_uuid == prescriber_uuid:
        return True

    user_npi = _get_staff_npi(user_staff_key)
    prescriber_npi = _get_staff_npi(prescriber_staff_key)
    return bool(user_npi and prescriber_npi and user_npi == prescriber_npi)


def _is_authorized(user_staff_key: str, prescriber_staff_key: str) -> bool:
    """Check if user is authorized to sign for the prescriber via Prescriber Assist.

    Authorization is NPI-based: if any profile of the prescriber (same NPI)
    is authorized for any profile of the user (same NPI), it's a match.
    """
    user_uuid = _get_staff_uuid(user_staff_key)
    prescriber_uuid = _get_staff_uuid(prescriber_staff_key)
    if not user_uuid or not prescriber_uuid:
        return False

    delegations = get_all_delegations()

    prescriber_npi = _get_staff_npi(prescriber_staff_key)
    prescriber_uuids = _get_all_uuids_for_npi(prescriber_npi) if prescriber_npi else [prescriber_uuid]

    user_npi = _get_staff_npi(user_staff_key)
    user_uuids = _get_all_uuids_for_npi(user_npi) if user_npi else [user_uuid]

    for p_uuid in prescriber_uuids:
        authorized_staff = delegations.get(p_uuid, [])
        for u_uuid in user_uuids:
            if u_uuid in authorized_staff:
                return True

    return False


def _get_staff_license_state(staff_key: str) -> str | None:
    """Get the state from a staff member's license (DEA first, then any other)."""
    try:
        if staff_key.isdigit():
            staff = Staff.objects.get(pk=int(staff_key))
        else:
            staff = Staff.objects.get(id=staff_key)

        dea_license = staff.licenses.filter(license_type="DEA").first()
        if dea_license and dea_license.state:
            return str(dea_license.state)

        license_with_state = staff.licenses.exclude(state__isnull=True).exclude(state="").first()
        if license_with_state:
            return str(license_with_state.state)

        return None
    except Staff.DoesNotExist:
        return None


def _bulk_fetch_staff(staff_keys: list[str]) -> dict[str, Any]:
    """Fetch many Staff records by mixed pk/UUID keys in batched queries.

    Returns a dict mapping each input key to its Staff record (omitted if not found).
    Licenses are prefetched so callers can read them without further queries.
    """
    if not staff_keys:
        return {}

    pks: list[int] = []
    uuids: list[str] = []
    for key in staff_keys:
        if key.isdigit():
            pks.append(int(key))
        else:
            uuids.append(key)

    by_pk: dict[int, Any] = {}
    by_uuid: dict[str, Any] = {}
    if pks:
        for s in Staff.objects.filter(pk__in=pks).prefetch_related("licenses"):
            by_pk[s.pk] = s
    if uuids:
        for s in Staff.objects.filter(id__in=uuids).prefetch_related("licenses"):
            by_uuid[str(s.id)] = s

    result: dict[str, Any] = {}
    for key in staff_keys:
        s = by_pk.get(int(key)) if key.isdigit() else by_uuid.get(key)
        if s is not None:
            result[key] = s
    return result


def _npi_of_staff(staff: Any) -> str | None:
    """Read NPI from a Staff record, returning None for the default placeholder NPI."""
    if not staff or not getattr(staff, "npi_number", None):
        return None
    npi_str = str(staff.npi_number)
    return None if npi_str == DEFAULT_NPI else npi_str


def _license_state_of_staff(staff: Any) -> str | None:
    """Get the license state from a Staff record using prefetched licenses (DEA first)."""
    if not staff:
        return None
    licenses = list(staff.licenses.all())
    dea = next((l for l in licenses if l.license_type == "DEA" and l.state), None)
    if dea:
        return str(dea.state)
    other = next((l for l in licenses if l.state), None)
    return str(other.state) if other else None


class PrescriberSearchPrioritization(BaseProtocol):
    """
    Prioritizes prescriber search results so permitted profiles appear first
    with state annotations. Providers the user can prescribe for (own or
    authorized) show the license state. Others show no annotation.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE__PRESCRIBER__POST_SEARCH),
        EventType.Name(EventType.REFILL__PRESCRIBER__POST_SEARCH),
        EventType.Name(EventType.ADJUST_PRESCRIPTION__PRESCRIBER__POST_SEARCH),
    ]

    def compute(self) -> list[Effect]:
        results = self.event.context.get("results")

        if results is None:
            return [Effect(type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS, payload=json.dumps(None))]

        user_staff_key = self._get_user_staff_key()
        if not user_staff_key:
            return [Effect(type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS, payload=json.dumps(None))]

        # Pre-compute everything that doesn't change per result. The autocomplete
        # fires on every keystroke, so this loop runs in O(1) queries regardless
        # of result count instead of ~5-8 queries per result.
        result_staff_keys: list[str] = []
        for result in results:
            sk = self._extract_staff_key_from_result(result)
            if sk:
                result_staff_keys.append(sk)

        staff_by_key = _bulk_fetch_staff([user_staff_key, *result_staff_keys])
        user_staff = staff_by_key.get(user_staff_key)
        user_uuid = str(user_staff.id) if user_staff else None
        user_npi = _npi_of_staff(user_staff)

        # Batch-fetch every Staff record sharing any prescriber's NPI (and the
        # user's NPI) in a single query, so the per-result loop can look up
        # NPI -> [uuids] without hitting the DB.
        prescriber_npis: set[str] = set()
        for key in result_staff_keys:
            npi = _npi_of_staff(staff_by_key.get(key))
            if npi:
                prescriber_npis.add(npi)
        npis_to_query = prescriber_npis | ({user_npi} if user_npi else set())
        npi_to_uuids: dict[str, list[str]] = {}
        if npis_to_query:
            for s in (
                Staff.objects.filter(npi_number__in=npis_to_query, active=True)
                .only("id", "npi_number")
            ):
                npi_to_uuids.setdefault(str(s.npi_number), []).append(str(s.id))

        user_uuids = npi_to_uuids.get(user_npi, []) if user_npi else []
        if not user_uuids and user_uuid:
            user_uuids = [user_uuid]

        # Delegations cache: one read for the whole loop.
        delegations = get_all_delegations()

        permitted = []
        other_providers = []

        for result in results:
            staff_key = self._extract_staff_key_from_result(result)
            if not staff_key:
                other_providers.append(result)
                continue

            prescriber_staff = staff_by_key.get(staff_key)
            license_state = _license_state_of_staff(prescriber_staff)

            if result.get("annotations") is None:
                result["annotations"] = []

            if license_state:
                result["annotations"].append(license_state)

            prescriber_uuid = str(prescriber_staff.id) if prescriber_staff else None
            prescriber_npi = _npi_of_staff(prescriber_staff)

            # is_own: same Staff identity, or shared NPI between user and prescriber
            is_own_identity = bool(user_uuid and prescriber_uuid and user_uuid == prescriber_uuid)
            is_own_npi = bool(user_npi and prescriber_npi and prescriber_npi == user_npi)
            is_own = is_own_identity or is_own_npi

            # is_authorized: any prescriber UUID has any user UUID in its delegation list
            is_authorized = False
            if user_uuid and prescriber_uuid and user_uuids:
                prescriber_uuids = (
                    npi_to_uuids.get(prescriber_npi, [prescriber_uuid])
                    if prescriber_npi
                    else [prescriber_uuid]
                )
                for p_uuid in prescriber_uuids:
                    authorized_staff = delegations.get(p_uuid, [])
                    if any(u in authorized_staff for u in user_uuids):
                        is_authorized = True
                        break

            if is_own or is_authorized:
                permitted.append(result)
            else:
                other_providers.append(result)

        def get_result_state(result: dict) -> str | None:
            annotations = result.get("annotations", [])
            for ann in annotations:
                if isinstance(ann, str) and len(ann) == 2 and ann.isupper():
                    return ann
            return None

        def get_sort_key(result: dict) -> tuple:
            text = result.get("text", "")
            parts = text.split()
            last_name = parts[-1].lower() if parts else ""
            state = get_result_state(result) or ""
            return (last_name, state.lower())

        permitted.sort(key=get_sort_key)
        other_providers.sort(key=get_sort_key)

        post_processed_results = permitted + other_providers

        return [
            Effect(
                type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS,
                payload=json.dumps(post_processed_results),
            )
        ]

    def _get_user_staff_key(self) -> str | None:
        user_context = self.event.context.get("user", {})
        staff_key = user_context.get("staff")
        return str(staff_key) if staff_key else None

    def _extract_staff_key_from_result(self, result: dict[str, Any]) -> str | None:
        value = result.get("value")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("key") or value.get("id")
        return None


class PrescribeActionFilter(BaseProtocol):
    """
    Hides sign/commit actions when the current user isn't authorized for
    the selected prescriber. Also caches the user's staff key so the
    validation handler can display the error message during POST_VALIDATION.

    The button-hiding is the reliable safety gate — it always uses the
    current user's context (not a cached value) to decide authorization.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__AVAILABLE_ACTIONS),
    ]

    RESTRICTED_ACTIONS = {"sign_action", "sign_send_action", "sign_via_coverage_check", "print_action"}

    def compute(self) -> list[Effect]:
        actions = self.event.context.get("actions", [])
        user_staff_key = self.event.context.get("user", {}).get("staff")
        command_uuid = str(self.event.target.id)
        cache_key = f"{AUTH_USER_CACHE_PREFIX}{command_uuid}"

        if not user_staff_key:
            # No user context — hide sign actions to be safe
            get_cache().delete(cache_key)
            return self._restrict(actions)

        # Always refresh the cache with the CURRENT user — this overwrites any
        # stale entry left by a previous user on the same command.
        get_cache().set(cache_key, str(user_staff_key), timeout_seconds=AUTH_USER_CACHE_TTL)

        prescriber_key = self._get_prescriber_key()
        if not prescriber_key:
            return self._pass(actions)

        if _is_own_prescriber(str(user_staff_key), prescriber_key) or _is_authorized(
            str(user_staff_key), prescriber_key
        ):
            return self._pass(actions)

        return self._restrict(actions)

    def _pass(self, actions: list) -> list[Effect]:
        return [Effect(type=EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS, payload=json.dumps(actions))]

    def _restrict(self, actions: list) -> list[Effect]:
        filtered = [a for a in actions if a.get("name") not in self.RESTRICTED_ACTIONS]
        return [Effect(type=EffectType.COMMAND_AVAILABLE_ACTIONS_RESULTS, payload=json.dumps(filtered))]

    def _get_prescriber_key(self) -> str | None:
        try:
            command = Command.objects.get(id=self.event.target.id)
        except Command.DoesNotExist:
            return None
        data = command.data or {}
        prescriber = data.get("prescriber")
        if prescriber is None:
            return None
        if isinstance(prescriber, int):
            return str(prescriber)
        if isinstance(prescriber, str):
            return prescriber
        if isinstance(prescriber, dict):
            key = prescriber.get("key") or prescriber.get("id") or prescriber.get("value") or prescriber.get("pk")
            return str(key) if key else None
        return None


class RefillActionFilter(PrescribeActionFilter):
    """Auth check for refill commands — hides sign buttons when unauthorized."""
    RESPONDS_TO = [EventType.Name(EventType.REFILL_COMMAND__AVAILABLE_ACTIONS)]


class AdjustPrescriptionActionFilter(PrescribeActionFilter):
    """Auth check for adjust prescription commands — hides sign buttons when unauthorized."""
    RESPONDS_TO = [EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__AVAILABLE_ACTIONS)]


class PrescribeValidation(BaseProtocol):
    """
    Validates user authorization (via cached user key). Optionally also blocks
    when the selected prescriber's license state does not match the pharmacy's
    state — controlled by the STATE_VALIDATION_ENFORCE plugin secret
    (default: enforce, for backward compatibility with 0.3.0).

    Dropdown state annotations are independent of this setting and always show.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE_COMMAND__POST_VALIDATION),
    ]

    def compute(self) -> list[Effect]:
        effect = CommandValidationErrorEffect()

        prescriber_key = self._get_prescriber_key()
        if not prescriber_key:
            return [effect.apply()]

        # Prefer event.context.user.staff (direct, always current); fall back to
        # the cache populated by the action filter for SDK versions where
        # POST_VALIDATION events don't include user info.
        user_staff_key = self.event.context.get("user", {}).get("staff")
        if not user_staff_key:
            command_uuid = str(self.event.target.id)
            cache_key = f"{AUTH_USER_CACHE_PREFIX}{command_uuid}"
            user_staff_key = get_cache().get(cache_key)

        if user_staff_key:
            is_own = _is_own_prescriber(str(user_staff_key), prescriber_key)
            if not is_own and not _is_authorized(str(user_staff_key), prescriber_key):
                log.info(
                    f"[DEBUG] auth-block: event={self.event.type if hasattr(self.event, 'type') else '?'} "
                    f"user_staff_key={user_staff_key!r} prescriber_key={prescriber_key!r} "
                    f"is_own={is_own}"
                )
                effect.add_error("Not authorized to prescribe for this provider.")
        else:
            log.warning(
                "PrescribeValidation could not identify current user — "
                "skipping auth error message. Action filter still blocks signing."
            )

        if self._state_validation_enforced():
            state_error = self._check_pharmacy_state(prescriber_key)
            if state_error:
                effect.add_error(state_error)

        return [effect.apply()]

    def _state_validation_enforced(self) -> bool:
        """Whether to block on pharmacy/prescriber state mismatch.

        Reads the STATE_VALIDATION_ENFORCE plugin secret. Accepts
        true/1/yes (enforce) and false/0/no (don't enforce), case- and
        whitespace-insensitive. Anything else — including unset — defaults
        to True to preserve 0.3.0 behavior on upgrade.
        """
        raw = (self.secrets.get("STATE_VALIDATION_ENFORCE", "") or "").strip().lower()
        if raw in ("true", "1", "yes"):
            return True
        if raw in ("false", "0", "no"):
            return False
        return True

    def _get_prescriber_key(self) -> str | None:
        """Get prescriber key from the Command object (same approach as action filter)."""
        try:
            command = Command.objects.get(id=self.event.target.id)
        except Command.DoesNotExist:
            return None
        data = command.data or {}
        prescriber = data.get("prescriber")
        if prescriber is None:
            return None
        if isinstance(prescriber, int):
            return str(prescriber)
        if isinstance(prescriber, str):
            return prescriber
        if isinstance(prescriber, dict):
            key = prescriber.get("key") or prescriber.get("id") or prescriber.get("value") or prescriber.get("pk")
            return str(key) if key else None
        return None

    def _check_pharmacy_state(self, prescriber_key: str) -> str | None:
        """Check if prescriber has a license matching the pharmacy's state.
        Returns an error message string, or None if OK."""
        pharmacy_state = self._get_pharmacy_state()
        if not pharmacy_state:
            return None  # No pharmacy selected yet — nothing to validate

        prescriber_states = self._get_prescriber_license_states(prescriber_key)
        if not prescriber_states:
            return f"Prescriber has no licenses on file. A license for {pharmacy_state} is required."

        if pharmacy_state.upper() not in [s.upper() for s in prescriber_states]:
            return f"Prescriber state ({', '.join(sorted(prescriber_states))}) does not match pharmacy state ({pharmacy_state})."

        return None

    def _get_pharmacy_state(self) -> str | None:
        """Get the state of the selected pharmacy from command data."""
        try:
            command = Command.objects.get(id=self.event.target.id)
        except Command.DoesNotExist:
            return None
        data = command.data or {}
        pharmacy = data.get("pharmacy")
        if not pharmacy:
            return None

        ncpdp_id = None
        if isinstance(pharmacy, str):
            ncpdp_id = pharmacy
        elif isinstance(pharmacy, dict):
            ncpdp_id = pharmacy.get("ncpdp_id") or pharmacy.get("key") or pharmacy.get("value")

        if not ncpdp_id:
            return None

        from canvas_sdk.utils.http import pharmacy_http
        result = pharmacy_http.get_pharmacy_by_ncpdp_id(str(ncpdp_id))
        if result and isinstance(result, dict):
            return result.get("state")

        return None

    def _get_prescriber_license_states(self, staff_key: str) -> list[str]:
        """Get license states for the specific selected prescriber profile only."""
        try:
            if staff_key.isdigit():
                staff = Staff.objects.get(pk=int(staff_key))
            else:
                staff = Staff.objects.get(id=staff_key)

            all_profiles = [staff]

            states = []
            for profile in all_profiles:
                for lic in profile.licenses.exclude(state__isnull=True).exclude(state=""):
                    states.append(str(lic.state))
            return list(set(states))
        except Staff.DoesNotExist:
            return []


class RefillValidation(PrescribeValidation):
    """Authorization + optional state validation for refill commands."""
    RESPONDS_TO = [EventType.Name(EventType.REFILL_COMMAND__POST_VALIDATION)]


class AdjustPrescriptionValidation(PrescribeValidation):
    """Authorization + optional state validation for adjust prescription commands."""
    RESPONDS_TO = [EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION)]


class SupervisingProviderSorter(BaseProtocol):
    """
    Adds state annotations and sorts supervising provider search results
    alphabetically by last name, then by state.
    """

    RESPONDS_TO = [
        EventType.Name(EventType.PRESCRIBE__SUPERVISING_PROVIDER__POST_SEARCH),
        EventType.Name(EventType.REFILL__SUPERVISING_PROVIDER__POST_SEARCH),
        EventType.Name(EventType.ADJUST_PRESCRIPTION__SUPERVISING_PROVIDER__POST_SEARCH),
    ]

    def compute(self) -> list[Effect]:
        results = self.event.context.get("results")

        if results is None:
            return [Effect(type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS, payload=json.dumps(None))]

        # Batch-fetch all needed staff records so the per-result loop runs in
        # O(1) queries — supervising-provider autocomplete fires on every keystroke.
        result_staff_keys: list[str] = []
        for result in results:
            sk = self._extract_staff_key_from_result(result)
            if sk:
                result_staff_keys.append(sk)
        staff_by_key = _bulk_fetch_staff(result_staff_keys)

        for result in results:
            staff_key = self._extract_staff_key_from_result(result)
            if not staff_key:
                continue

            license_state = _license_state_of_staff(staff_by_key.get(staff_key))

            if result.get("annotations") is None:
                result["annotations"] = []

            if license_state:
                result["annotations"].append(license_state)

        def get_result_state(result: dict) -> str | None:
            annotations = result.get("annotations", [])
            for ann in annotations:
                if isinstance(ann, str) and len(ann) == 2 and ann.isupper():
                    return ann
            return None

        def get_sort_key(result: dict) -> tuple:
            text = result.get("text", "")
            parts = text.split()
            last_name = parts[-1].lower() if parts else ""
            state = get_result_state(result) or ""
            return (last_name, state.lower())

        sorted_results = sorted(results, key=get_sort_key)

        return [
            Effect(
                type=EffectType.AUTOCOMPLETE_SEARCH_RESULTS,
                payload=json.dumps(sorted_results),
            )
        ]

    def _extract_staff_key_from_result(self, result: dict[str, Any]) -> str | None:
        value = result.get("value")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("key") or value.get("id")
        return None
