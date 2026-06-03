"""Tests for clinical_pathways.models.pathway_run."""

from __future__ import annotations

from clinical_pathways.models.pathway import Pathway
from clinical_pathways.models.pathway_run import PathwayRun


class TestPathwayRunModel:
    def test_pathway_run_is_a_custom_model_subclass(self) -> None:
        from canvas_sdk.v1.data.base import CustomModel  # noqa: PLC0415

        assert issubclass(PathwayRun, CustomModel)

    def test_pathway_run_accepts_field_kwargs(self) -> None:
        run = PathwayRun(
            note_uuid="abc-123",
            pathway_id=42,
            current_step_id="s_start",
            inserted_questionnaires=["qn-1"],
            committed_questionnaires=["qn-1"],
            last_processed_event_token="tok-1",
            status="active",
            captured_responses={"q1": {"text": "yes"}},
        )
        assert run.note_uuid == "abc-123"
        assert run.pathway_id == 42
        assert run.current_step_id == "s_start"
        assert run.inserted_questionnaires == ["qn-1"]
        assert run.committed_questionnaires == ["qn-1"]
        assert run.last_processed_event_token == "tok-1"
        assert run.status == "active"
        assert run.captured_responses == {"q1": {"text": "yes"}}

    def test_pathway_module_reexports_models(self) -> None:
        from clinical_pathways.models import Pathway as ExportedPathway  # noqa: PLC0415
        from clinical_pathways.models import PathwayRun as ExportedRun  # noqa: PLC0415

        assert ExportedPathway is Pathway
        assert ExportedRun is PathwayRun
