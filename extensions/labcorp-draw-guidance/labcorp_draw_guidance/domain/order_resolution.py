"""Resolve draw guidance for the tests currently staged on a LabOrderCommand."""

from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q

from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.lab import LabPartnerTest

from labcorp_draw_guidance.domain.command_parsing import (
    extract_lab_partner_name,
    extract_test_identifiers,
)
from labcorp_draw_guidance.domain.tube_guidance import (
    ConsolidatedTube,
    ResolvedTest,
    consolidate,
    resolve_tube_requirement,
)

LAB_ORDER_SCHEMA_KEY = "labOrder"


@dataclass(frozen=True)
class OrderGuidance:
    """The result of resolving draw guidance for a staged lab order command."""

    consolidated: tuple[ConsolidatedTube, ...]
    unresolved_test_names: tuple[str, ...]


def _split_identifiers(identifiers: list[str]) -> tuple[list[UUID], list[str]]:
    """Split identifiers into LabPartnerTest UUIDs and order codes.

    Mirrors the same or-code-or-id resolution `LabOrderCommand` uses to
    validate `tests_order_codes` (see
    `canvas_sdk.commands.commands.lab_order.LabOrderCommand._get_error_details`).
    """
    uuids: list[UUID] = []
    order_codes: list[str] = []

    for identifier in identifiers:
        try:
            uuids.append(UUID(identifier))
        except ValueError:
            order_codes.append(identifier)

    return uuids, order_codes


def _qualifying_identifiers(command: Command) -> tuple[list[UUID], list[str]] | None:
    """Return the test identifiers for a command that's a Labcorp lab order with tests staged.

    Returns None when the command isn't a lab order, has no patient, isn't a
    Labcorp order, or has no tests staged yet. Pure Python -- issues no
    queries -- so it's cheap to run per-command before any `LabPartnerTest`
    lookup happens.
    """
    if command.schema_key != LAB_ORDER_SCHEMA_KEY:
        return None

    # `patient_id` is the FK column already present on the fetched row -- no
    # query, and no need to hydrate the (large) related `Patient` row just to
    # check it exists.
    if command.patient_id is None:
        return None

    command_data = command.data or {}

    lab_partner_name = extract_lab_partner_name(command_data)
    if not lab_partner_name or "labcorp" not in lab_partner_name.lower():
        return None

    identifiers = extract_test_identifiers(command_data)
    if not identifiers:
        return None

    return _split_identifiers(identifiers)


def _build_guidance(matched_tests: list[LabPartnerTest]) -> OrderGuidance | None:
    """Build consolidated guidance from a command's already-matched `LabPartnerTest` rows."""
    resolved: list[ResolvedTest] = []
    unresolved_names: list[str] = []

    for test in matched_tests:
        requirement = resolve_tube_requirement(test.order_code, test.order_name)
        if requirement is None:
            unresolved_names.append(test.order_name or test.order_code)
            continue
        resolved.append(
            ResolvedTest(
                order_code=test.order_code,
                display_name=test.order_name or test.order_code,
                tube=requirement,
            )
        )

    if not resolved:
        return None

    return OrderGuidance(
        consolidated=tuple(consolidate(resolved)),
        unresolved_test_names=tuple(unresolved_names),
    )


def resolve_order_guidance(command: Command) -> OrderGuidance | None:
    """Resolve consolidated tube guidance for a single staged/committed lab order command."""
    identifiers = _qualifying_identifiers(command)
    if identifiers is None:
        return None

    uuids, order_codes = identifiers
    matched_tests = list(LabPartnerTest.objects.filter(Q(order_code__in=order_codes) | Q(id__in=uuids)))
    return _build_guidance(matched_tests)


def resolve_note_guidances(note_dbid: int) -> list[OrderGuidance]:
    """Resolve draw guidance for every lab order command on a note.

    A note may have more than one staged/committed `LabOrderCommand`. Rather
    than resolving each independently (which would run one `LabPartnerTest`
    query per command), every qualifying command's test identifiers are
    gathered up front and resolved against the compendium in a single shared
    query, then matches are grouped back per command.
    """
    commands = list(Command.objects.filter(note_id=note_dbid, schema_key=LAB_ORDER_SCHEMA_KEY))

    per_command: list[tuple[list[UUID], list[str]]] = []
    for command in commands:
        identifiers = _qualifying_identifiers(command)
        if identifiers is not None:
            per_command.append(identifiers)

    if not per_command:
        return []

    all_uuids = [uuid for uuids, _ in per_command for uuid in uuids]
    all_order_codes = [code for _, codes in per_command for code in codes]

    matched_tests = list(
        LabPartnerTest.objects.filter(Q(order_code__in=all_order_codes) | Q(id__in=all_uuids))
    )
    tests_by_code = {test.order_code: test for test in matched_tests}
    tests_by_id = {test.id: test for test in matched_tests}

    guidances: list[OrderGuidance] = []
    for uuids, order_codes in per_command:
        seen_ids: set[UUID] = set()
        command_tests: list[LabPartnerTest] = []
        for code in order_codes:
            test = tests_by_code.get(code)
            if test is not None and test.id not in seen_ids:
                seen_ids.add(test.id)
                command_tests.append(test)
        for uuid in uuids:
            test = tests_by_id.get(uuid)
            if test is not None and test.id not in seen_ids:
                seen_ids.add(test.id)
                command_tests.append(test)

        guidance = _build_guidance(command_tests)
        if guidance is not None:
            guidances.append(guidance)

    return guidances
