"""Shared fixtures for last_reviewed tests."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_event():
    """Factory: build a minimal event whose `target.id` and `context` are usable.

    `context["section"]` defaults to the SECTION_KEY constant so accept_event()
    returns True without callers needing to know the value.
    """
    from last_reviewed.handlers.section_config import SECTION_KEY

    def _create(patient_id: str = "patient-1", section: str | None = None) -> Mock:
        event = Mock()
        event.target = SimpleNamespace(id=patient_id)
        event.context = {"section": SECTION_KEY if section is None else section}
        return event

    return _create


def make_staff_user(
    first_name: str = "Jane",
    last_name: str = "Smith",
    is_staff: bool = True,
    raises_on_staff_access: bool = False,
) -> SimpleNamespace:
    """Build a CanvasUser-shaped object exposing `.is_staff` and `.staff`."""
    if raises_on_staff_access:
        class _U:
            is_staff = True

            @property
            def staff(self) -> Any:
                raise RuntimeError("simulated staff access failure")

        return _U()  # type: ignore[return-value]

    staff = SimpleNamespace(first_name=first_name, last_name=last_name)
    return SimpleNamespace(is_staff=is_staff, staff=staff)


def make_review_command(
    section: str,
    created: datetime,
    committer: Any | None = None,
    data_extra: dict | None = None,
) -> SimpleNamespace:
    """Build a Command-shaped object as returned by the SDK queryset."""
    data = {"section": section}
    if data_extra:
        data.update(data_extra)
    return SimpleNamespace(
        schema_key="chartSectionReview",
        state="committed",
        data=data,
        created=created,
        committer=committer,
    )


@pytest.fixture
def mock_command_queryset():
    """Factory: stub the `Command.objects.filter().select_related().order_by()` chain.

    The returned queryset's `.iterator()` yields the supplied list of commands,
    matching the iteration pattern used inside the handler.
    """

    def _install(mock_command_module_attr, commands: list[Any]):
        ordered = Mock()
        ordered.iterator.return_value = iter(commands)

        select_related_result = Mock()
        select_related_result.order_by.return_value = ordered

        filter_result = Mock()
        filter_result.select_related.return_value = select_related_result

        mock_command_module_attr.objects.filter.return_value = filter_result
        return SimpleNamespace(
            filter_result=filter_result,
            select_related_result=select_related_result,
            ordered=ordered,
        )

    return _install


@pytest.fixture
def utc_now() -> datetime:
    """A stable 'now' useful for building command timestamps in tests."""
    return datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
