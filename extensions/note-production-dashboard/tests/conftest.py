"""Shared fixtures for note-production-dashboard tests."""
from types import SimpleNamespace
from typing import Any


# ── provider / staff ──────────────────────────────────────────────────────────

def make_staff(
    staff_id: str = "prov-1",
    first_name: str = "Jane",
    last_name: str = "Smith",
    credentialed_name: str | None = None,
) -> SimpleNamespace:
    """Return a SimpleNamespace that mimics a Staff record."""
    cred = credentialed_name or f"{first_name} {last_name}"
    return SimpleNamespace(
        id=staff_id,
        first_name=first_name,
        last_name=last_name,
        credentialed_name=cred,
    )


# ── note command helper ───────────────────────────────────────────────────────

def make_command(schema_key: str, data: dict[str, Any], dbid: int = 1) -> SimpleNamespace:
    """Return a SimpleNamespace that mimics a Command record."""
    return SimpleNamespace(schema_key=schema_key, data=data, dbid=dbid)


# ── mock note ─────────────────────────────────────────────────────────────────

def make_note(
    note_id: str = "note-1",
    provider_id: str = "prov-1",
    patient_first: str = "John",
    patient_last: str = "Doe",
    datetime_of_service: Any = None,
    note_type_name: str = "Office Visit",
    cpt_codes: list[str] | None = None,
    rfv_commands: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    """Return a SimpleNamespace mimicking a Note with prefetched related data."""
    import datetime as dt

    if datetime_of_service is None:
        datetime_of_service = dt.datetime(2025, 4, 27, 9, 30, tzinfo=dt.timezone.utc)

    patient = SimpleNamespace(first_name=patient_first, last_name=patient_last)
    note_type_version = SimpleNamespace(name=note_type_name)

    # Simulate prefetched active_billing_items
    active_billing_items = [
        SimpleNamespace(cpt=code) for code in (cpt_codes or [])
    ]

    # Simulate prefetched rfv_commands_prefetched
    rfv_prefetched: list[SimpleNamespace] = rfv_commands or []

    # commands.all() returns the same list for _rfv_text fallback path
    rfv_list = rfv_prefetched
    commands_qs = SimpleNamespace(all=lambda: rfv_list)

    return SimpleNamespace(
        id=note_id,
        provider=make_staff(staff_id=provider_id),
        patient=patient,
        datetime_of_service=datetime_of_service,
        note_type_version=note_type_version,
        active_billing_items=active_billing_items,
        rfv_commands_prefetched=rfv_prefetched,
        commands=commands_qs,
    )


def make_state_event(note: SimpleNamespace) -> SimpleNamespace:
    """Wrap a note in a SimpleNamespace that mimics CurrentNoteStateEvent."""
    return SimpleNamespace(note=note)
