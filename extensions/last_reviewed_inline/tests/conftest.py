"""Shared fixtures for last_reviewed_inline tests."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_event():
    """Factory: build a minimal event whose `target.id` is a patient id."""

    def _create(patient_id: str = "patient-1") -> Mock:
        event = Mock()
        event.target = SimpleNamespace(id=patient_id)
        event.context = []
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
) -> SimpleNamespace:
    """Build a Command-shaped object as returned by the SDK queryset."""
    return SimpleNamespace(
        schema_key="chartSectionReview",
        state="committed",
        data={"section": section},
        created=created,
        committer=committer,
    )


@pytest.fixture
def mock_command_chain():
    """Factory: stub the `Command.objects.filter().exclude().select_related().order_by().first()` chain.

    Returns a SimpleNamespace exposing each link in the chain so tests can
    assert on the arguments passed to any step.
    """

    def _install(mock_command_module_attr, command: Any | None):
        ordered = Mock()
        ordered.first.return_value = command

        select_related_result = Mock()
        select_related_result.order_by.return_value = ordered

        exclude_result = Mock()
        exclude_result.select_related.return_value = select_related_result

        filter_result = Mock()
        filter_result.exclude.return_value = exclude_result

        mock_command_module_attr.objects.filter.return_value = filter_result
        return SimpleNamespace(
            filter_result=filter_result,
            exclude_result=exclude_result,
            select_related_result=select_related_result,
            ordered=ordered,
        )

    return _install


@pytest.fixture
def utc_now() -> datetime:
    """A stable 'now' useful for building command timestamps in tests."""
    return datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
