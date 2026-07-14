"""Protocol handlers for staff lifecycle events and plugin install."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.staff import Staff
from logger import log

from provider_availability.engine.admin_calendar import deterministic_calendar_id
from provider_availability.engine.event_sync import (
    build_block_event_effects,
    build_delete_block_effects,
    build_delete_effects,
    build_lead_time_block_effects,
    build_recurring_block_sync_effects,
    sync_provider_availability,
)
from provider_availability.engine.storage import (
    delete_rules_for_provider,
    get_all_blocks,
    get_all_recurring_blocks,
    get_all_rules,
    get_rules_for_provider,
    is_first_install,
    mark_installed,
)


class OnStaffActivated(BaseProtocol):
    """Create a Clinic calendar when a provider is activated."""

    RESPONDS_TO = EventType.Name(EventType.STAFF_ACTIVATED)

    def compute(self) -> list[Effect]:
        staff_id = self.event.target.id
        staff_key = str(staff_id)

        try:
            staff = Staff.objects.get(id=staff_id)
        except Staff.DoesNotExist:
            log.warning("OnStaffActivated: staff not found for id %s", staff_id)
            return []

        # Only create calendars for providers
        role = staff.top_role_abbreviation
        if not role or role.upper() not in ("MD", "DO", "NP", "PA"):
            log.info(
                "OnStaffActivated: %s %s (role=%s) not a schedulable provider, skipping",
                staff.first_name,
                staff.last_name,
                role,
            )
            return []

        provider_name = staff.full_name
        calendar_id = deterministic_calendar_id(staff_key, CalendarType.Clinic, None)
        existing = (
            CalendarModel.objects.filter(id=calendar_id).first()
            or CalendarModel.objects.for_calendar_name(
                provider_name=provider_name,
                calendar_type=CalendarType.Clinic,
                location=None,
            ).first()
        )
        if existing:
            log.info(
                "OnStaffActivated: Clinic calendar already exists for %s %s",
                staff.first_name,
                staff.last_name,
            )
            return []

        cal_effect = CalendarEffect(
            id=calendar_id,
            provider=staff_key,
            type=CalendarType.Clinic,
            description=staff_key,
        ).create()

        log.info(
            "OnStaffActivated: created Clinic calendar for %s %s",
            staff.first_name,
            staff.last_name,
        )
        return [cal_effect]


class OnStaffDeactivated(BaseProtocol):
    """Clean up availability rules and calendar events when a staff member is deactivated."""

    RESPONDS_TO = EventType.Name(EventType.STAFF_DEACTIVATED)

    def compute(self) -> list[Effect]:
        staff_id = self.event.target.id
        provider_id = str(staff_id)

        try:
            staff = Staff.objects.get(id=staff_id)
            staff_name = f"{staff.first_name} {staff.last_name}".strip()
        except Staff.DoesNotExist:
            staff_name = provider_id

        rules = get_rules_for_provider(provider_id)
        if not rules:
            log.info(
                "OnStaffDeactivated: no rules for provider %s (%s), skipping",
                provider_id,
                staff_name,
            )
            return []

        effects = build_delete_effects(provider_id)

        count = delete_rules_for_provider(provider_id)
        log.info(
            "OnStaffDeactivated: deleted %d rules and %d event effects for %s (%s)",
            count,
            len(effects),
            provider_id,
            staff_name,
        )
        return effects


class OnPluginInstalled(BaseProtocol):
    """Create Clinic calendars for all active providers and sync rules on install/update.

    Fires on PLUGIN_CREATED which occurs on both initial install and every
    redeployment.  Creates Clinic calendars for all active providers (required
    for the Canvas schedule view to work), then syncs any cached rules to
    Calendar Events.
    """

    RESPONDS_TO = EventType.Name(EventType.PLUGIN_CREATED)

    def compute(self) -> list[Effect]:
        effects: list[Effect] = []

        # Step 1: Create Clinic calendars for all active providers
        cal_created = 0
        cal_skipped = 0
        active_staff = Staff.objects.filter(active=True, roles__role_type="PROVIDER").distinct()
        log.info("OnPluginInstalled: checking %d active providers for Clinic calendars", active_staff.count())

        for staff in active_staff:
            try:
                staff_key = str(staff.id)
                provider_name = staff.full_name
                calendar_id = deterministic_calendar_id(staff_key, CalendarType.Clinic, None)
                existing = (
                    CalendarModel.objects.filter(id=calendar_id).first()
                    or CalendarModel.objects.for_calendar_name(
                        provider_name=provider_name,
                        calendar_type=CalendarType.Clinic,
                        location=None,
                    ).first()
                )

                if existing:
                    cal_skipped += 1
                    continue

                cal_effect = CalendarEffect(
                    id=calendar_id,
                    provider=staff_key,
                    type=CalendarType.Clinic,
                    description=staff_key,
                ).create()
                effects.append(cal_effect)
                cal_created += 1
                log.info(
                    "OnPluginInstalled: created Clinic calendar for %s %s",
                    staff.first_name,
                    staff.last_name,
                )
            except Exception:
                log.exception(
                    "OnPluginInstalled: failed to create calendar for staff %s",
                    staff.id,
                )

        log.info(
            "OnPluginInstalled: calendars created=%d, skipped=%d",
            cal_created,
            cal_skipped,
        )

        # Step 2: Read cached data
        rules = get_all_rules()
        blocks = get_all_blocks()
        recurring_blocks = get_all_recurring_blocks()
        first_install = is_first_install()

        if not (rules or blocks or recurring_blocks):
            log.warning(
                "OnPluginInstalled: cache empty, preserving existing events"
            )
            if first_install:
                mark_installed()
            return effects

        rules_synced = 0
        lead_time_count = 0
        blocks_synced = 0
        recurring_synced = 0

        if first_install:
            mark_installed()
        log.info(
            "OnPluginInstalled: %s — reconciling plugin events (non-destructive)",
            "first install" if first_install else "redeploy",
        )

        # Step 3: Per-entity reconciliation. We deliberately do NOT sweep every
        # event off the Clinic/Admin calendars — that would delete events this
        # plugin didn't create (manual entries, other plugins, external sync).
        # Each builder below deletes only its OWN prior events (scoped by the
        # plugin's titles / the entity's time range) before recreating, so a
        # redeploy repairs drift without collateral deletion or duplicates.
        provider_ids_synced: set[str] = set()
        for rule in rules:
            try:
                # sync_provider_availability deletes this provider's "Available"
                # events (preserving past) then rebuilds — safe to call directly.
                if rule.provider_id not in provider_ids_synced:
                    effects.extend(sync_provider_availability(rule.provider_id))
                    provider_ids_synced.add(rule.provider_id)
                rules_synced += 1
                if rule.is_active and rule.booking_interval.min_lead_hours > 0:
                    effects.extend(build_lead_time_block_effects(rule))
                    lead_time_count += 1
            except Exception:
                log.exception(
                    "OnPluginInstalled: failed to sync rule %s for provider %s",
                    rule.id,
                    rule.provider_id,
                )

        for block in blocks:
            try:
                # build_block_event_effects only creates; delete this block's
                # own prior events first so a redeploy doesn't duplicate them.
                effects.extend(build_delete_block_effects(block.provider_id, block))
                effects.extend(build_block_event_effects(block))
                blocks_synced += 1
            except Exception:
                log.exception(
                    "OnPluginInstalled: failed to sync block %s for provider %s",
                    block.id,
                    block.provider_id,
                )

        for rb in recurring_blocks:
            try:
                effects.extend(build_recurring_block_sync_effects(rb))
                recurring_synced += 1
            except Exception:
                log.exception(
                    "OnPluginInstalled: failed to sync recurring block %s for provider %s",
                    rb.id,
                    rb.provider_id,
                )

        log.info(
            "OnPluginInstalled: first_install=%s, synced %d rules, %d lead-time, %d blocks, %d recurring blocks, %d total effects",
            first_install,
            rules_synced,
            lead_time_count,
            blocks_synced,
            recurring_synced,
            len(effects),
        )
        return effects
