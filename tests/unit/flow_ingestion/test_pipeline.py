"""Unit tests for TelemetryPipelineRunner."""

from __future__ import annotations

import pytest

from src.modules.flow_ingestion.domain.exceptions import (
    FlowIngestionError,
    InternalIngestionError,
)
from src.modules.flow_ingestion.domain.models import PipelineContext, TelemetryRecord
from src.modules.flow_ingestion.domain.pipeline import TelemetryPipelineRunner
from src.modules.flow_ingestion.domain.stages.base import PipelineStage


class StageOne(PipelineStage):
    """Test stage appending metadata."""

    @property
    def stage_name(self) -> str:
        """Returns stage name."""
        return "stage_one"

    def process(self, context: PipelineContext) -> PipelineContext:
        """Processes stage one."""
        return context.with_metadata("stage_one", "done")


class StageTwo(PipelineStage):
    """Test stage creating a record and dispatch id."""

    @property
    def stage_name(self) -> str:
        """Returns stage name."""
        return "stage_two"

    def process(self, context: PipelineContext) -> PipelineContext:
        """Processes stage two."""
        rec = TelemetryRecord(
            plant_id="P1",
            regulator_id="R1",
            sensor_id="S1",
            sequence_number=1,
            timestamp_ns=1000,
            flow_rate_sccm=10.0,
            pressure_bar=1.0,
            temperature_celsius=20.0,
            status_flags=0,
        )
        return context.with_records((rec,)).with_dispatched_messages(("msg-101",))


class FailingStage(PipelineStage):
    """Stage raising unexpected error."""

    @property
    def stage_name(self) -> str:
        """Returns stage name."""
        return "failing_stage"

    def process(self, context: PipelineContext) -> PipelineContext:
        """Fails unconditionally."""
        raise RuntimeError("Unexpected failure")


def test_pipeline_runner_sequential_execution() -> None:
    """[US-1][AC-1.1][AC-1.4] Verify pipeline executes stages sequentially and returns IngestionResult."""
    runner = TelemetryPipelineRunner(stages=(StageOne(), StageTwo()))
    assert len(runner.stages) == 2

    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={"foo": "bar"},
        hmac_signature="sig",
        key_id="k1",
    )

    result = runner.run(ctx)
    assert result.status == "accepted"
    assert result.stream_id == "P1:R1:S1"
    assert result.message_ids == ("msg-101",)
    assert result.records_count == 1
    assert result.processed_at_ns > 0


def test_pipeline_runner_replayed_status() -> None:
    """[US-5][AC-137] Verify replayed context produces status='replayed'."""
    runner = TelemetryPipelineRunner(stages=(StageTwo(),))
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        is_replayed=True,
    )

    result = runner.run(ctx)
    assert result.status == "replayed"


def test_pipeline_runner_reraises_flow_ingestion_error() -> None:
    """[US-1][AC-1.1] Verify domain exceptions bubble up intact."""

    class DomainErrorStage(PipelineStage):
        @property
        def stage_name(self) -> str:
            return "domain_error_stage"

        def process(self, context: PipelineContext) -> PipelineContext:
            raise FlowIngestionError("Domain error", code="TEST_ERR", status_code=400)

    runner = TelemetryPipelineRunner(stages=(DomainErrorStage(),))
    ctx = PipelineContext(stream_id="P1", raw_payload={}, hmac_signature="", key_id="")

    with pytest.raises(FlowIngestionError) as exc_info:
        runner.run(ctx)
    assert exc_info.value.code == "TEST_ERR"
    assert exc_info.value.status_code == 400


def test_pipeline_runner_wraps_unexpected_exceptions() -> None:
    """[US-1][AC-1.1] Verify unexpected exceptions wrap in InternalIngestionError (500)."""
    runner = TelemetryPipelineRunner(stages=(FailingStage(),))
    ctx = PipelineContext(stream_id="P1", raw_payload={}, hmac_signature="", key_id="")

    with pytest.raises(InternalIngestionError) as exc_info:
        runner.run(ctx)
    assert exc_info.value.code == "INTERNAL_INGESTION_ERROR"
    assert exc_info.value.status_code == 500
