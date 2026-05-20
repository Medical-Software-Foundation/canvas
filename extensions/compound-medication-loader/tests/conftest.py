"""Shared fixtures for compound_medication_loader tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def potency_choices():
    """Tuple list mirroring CompoundMedicationModel.PotencyUnits.choices."""
    return [("C48155", "Gram"), ("C28253", "Milligram"), ("C28254", "Milliliter")]


@pytest.fixture
def controlled_choices():
    """Tuple list mirroring CompoundMedicationModel.ControlledSubstanceOptions.choices."""
    return [
        ("N", "Not scheduled"),
        ("2", "Schedule II"),
        ("3", "Schedule III"),
        ("4", "Schedule IV"),
        ("5", "Schedule V"),
    ]


@pytest.fixture
def mock_model_with_choices(potency_choices, controlled_choices):
    """Patch-target stand-in for CompoundMedicationModel exposing .choices."""
    m = MagicMock()
    m.PotencyUnits.choices = potency_choices
    m.ControlledSubstanceOptions.choices = controlled_choices
    return m
