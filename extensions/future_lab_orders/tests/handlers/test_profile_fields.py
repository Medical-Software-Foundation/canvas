"""Behavior tests for the future lab order profile fields."""

import json
from typing import Any

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.test_utils.factories import LabPartnerFactory

from future_lab_orders.fields import DUE_DATE_KEY, LAB_KEY, TESTS_KEY
from future_lab_orders.handlers.profile_fields import FutureLabOrderProfileFields


def fields() -> list[dict[str, Any]]:
    effects = FutureLabOrderProfileFields(event=None).compute()  # type: ignore[arg-type]
    assert len(effects) == 1
    assert effects[0].type == EffectType.PATIENT_METADATA__CREATE_ADDITIONAL_FIELDS
    return json.loads(effects[0].payload)["data"]["form"]


@pytest.mark.django_db
def test_lab_is_a_dropdown_of_active_lab_partners() -> None:
    LabPartnerFactory.create(name="Quest", active=True)
    LabPartnerFactory.create(name="Labcorp", active=True)
    LabPartnerFactory.create(name="Retired Lab", active=False)

    form = fields()

    assert [f["key"] for f in form] == [LAB_KEY, TESTS_KEY, DUE_DATE_KEY]
    lab = form[0]
    assert lab["type"] == "select"
    assert lab["options"] == ["Labcorp", "Quest"]
    assert form[1]["type"] == "text"
    assert form[2]["type"] == "date"
    assert all(f["required"] is False and f["editable"] is True for f in form)


@pytest.mark.django_db
def test_lab_is_free_text_when_no_lab_partner_is_active() -> None:
    LabPartnerFactory.create(name="Retired Lab", active=False)

    lab = fields()[0]

    assert lab["type"] == "text"
    assert not lab.get("options")
