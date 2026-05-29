"""Tests for clinical_pathways.models.pathway."""

from __future__ import annotations

from clinical_pathways.models.pathway import Pathway


class TestPathwayModel:
    def test_pathway_is_a_custom_model_subclass(self) -> None:
        from canvas_sdk.v1.data.base import CustomModel  # noqa: PLC0415

        assert issubclass(Pathway, CustomModel)

    def test_pathway_instance_accepts_field_kwargs(self) -> None:
        pw = Pathway(
            title="Asthma",
            description="Pediatric asthma triage",
            status="published",
            is_active=True,
            recommendation="Refer to pulm",
            definition={"version": 3, "steps": []},
        )
        assert pw.title == "Asthma"
        assert pw.description == "Pediatric asthma triage"
        assert pw.status == "published"
        assert pw.is_active is True
        assert pw.recommendation == "Refer to pulm"
        assert pw.definition == {"version": 3, "steps": []}

    def test_pathway_save_is_callable(self) -> None:
        pw = Pathway(title="X")
        # The conftest stub returns None; nothing to assert other than callability.
        assert pw.save() is None
