"""Unit tests for pipeline stage base interface."""

from __future__ import annotations

import pytest

from src.modules.flow_ingestion.domain.models import PipelineContext
from src.modules.flow_ingestion.domain.stages.base import PipelineStage


class DummyStage(PipelineStage):
    """Concrete dummy stage for interface verification."""

    @property
    def stage_name(self) -> str:
        """Returns the stage name."""
        return "dummy_stage"

    def process(self, context: PipelineContext) -> PipelineContext:
        """Processes the context by recording metadata."""
        return context.with_metadata("dummy", "processed")


def test_pipeline_stage_abc() -> None:
    """[US-1][AC-1.1] Verify PipelineStage ABC contracts and enforcement."""
    with pytest.raises(TypeError):
        PipelineStage()  # type: ignore[abstract]

    stage = DummyStage()
    assert stage.stage_name == "dummy_stage"

    ctx = PipelineContext(
        stream_id="PLANT-01:REG-01:SN-01",
        raw_payload={},
        hmac_signature="",
        key_id="",
    )
    result = stage.process(ctx)
    assert result.metadata["dummy"] == "processed"
