"""Abstract base stage for the pipeline-reducer pattern."""

from __future__ import annotations

import abc

from ..models import PipelineContext


class PipelineStage(abc.ABC):
    """Abstract stage in the flow ingestion transformation pipeline."""

    @property
    @abc.abstractmethod
    def stage_name(self) -> str:
        """Returns the unique name of this pipeline stage."""
        ...

    @abc.abstractmethod
    def process(self, context: PipelineContext) -> PipelineContext:
        """Processes the context and returns the transformed context.

        Args:
            context: Immutable PipelineContext to process.

        Returns:
            Transformed PipelineContext.

        Raises:
            FlowIngestionError: If processing or validation fails.
        """
        ...
