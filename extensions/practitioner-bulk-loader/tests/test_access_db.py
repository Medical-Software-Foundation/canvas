"""Access check against real StaffRole rows (database-backed)."""

import pytest
from canvas_sdk.test_utils.factories import StaffFactory, StaffRoleFactory

from practitioner_bulk_loader.access import staff_can_load


@pytest.mark.django_db
def test_a_listed_role_allows_its_holder_from_the_database():
    admin = StaffFactory()
    StaffRoleFactory(staff=admin, internal_code="ADMIN", public_abbreviation="Adm", name="Practice Admin")
    assistant = StaffFactory()
    StaffRoleFactory(staff=assistant, internal_code="MA", public_abbreviation="MA", name="Medical Assistant")

    secrets = {"BULK_LOADER_ALLOWED_ROLES": "practice admin"}
    assert staff_can_load(str(admin.id), secrets) is True
    assert staff_can_load(str(assistant.id), secrets) is False
