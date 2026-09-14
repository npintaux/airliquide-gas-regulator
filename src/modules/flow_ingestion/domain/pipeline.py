"""Pipeline runner executing registered stages sequentially."""

from __future__ import annotations

import time
from collections.abc import Sequence

from .exceptions import (
    FlowIngestionError,
    InternalIngestionError,
)
from .models import (
    IngestionResult,
    PipelineContext,
)
from .stages.base import PipelineStage


class TelemetryPipelineRunner:
    """Orchestrates sequential execution of pipeline transformation stages."""

    def __init__(self, stages: Sequence[PipelineStage]) -> None:
        """Initializes the runner with an ordered sequence of stages.

        Args:
            stages: Sequence of PipelineStage instances to execute in order.
        """
        self._stages = tuple(stages)

    @property
    def stages(self) -> tuple[PipelineStage, ...]:
        """Returns the tuple of registered stages."""
        return self._stages

    def run(self, initial_context: PipelineContext) -> IngestionResult:
        """Executes all stages sequentially on the context and returns IngestionResult.

        Args:
            initial_context: The initial input PipelineContext.

        Returns:
            Terminal IngestionResult representing outcome.

        Raises:
            FlowIngestionError: If any stage raises a domain error.
            InternalIngestionError: If an unexpected error occurs during execution.
        """
        current = initial_context

        try:
            for stage in self._stages:
                current = stage.process(current)
        except FlowIngestionError:
            raise
        except Exception as err:
            raise InternalIngestionError(
                f"Unexpected error executing pipeline stage: {err}",
                code="INTERNAL_INGESTION_ERROR",
                status_code=500,
            ) from err

        processed_at_ns = time.time_ns()
        if current.metadata.get("is_duplicate") == "true":
            status = "duplicate"
        elif current.is_replayed:
            status = "replayed"
        else:
            status = "accepted"

        return IngestionResult(
            status=status,
            stream_id=current.stream_id,
            message_ids=current.dispatched_messages,
            records_count=len(current.records),
            processed_at_ns=processed_at_ns,
        )
