"""Pub/Sub bundle packaging and message dispatch stage."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from ..exceptions import PublisherUnavailableError
from ..models import PipelineContext
from .base import PipelineStage


class _PublisherPort(Protocol):
    """Abstract port interface for publishing telemetry bundles."""

    def publish(self, topic: str, message: dict[str, Any], ordering_key: str) -> str:
        """Publishes payload to messaging broker with ordering key.

        Args:
            topic: Destination topic identifier.
            message: Dictionary payload.
            ordering_key: Deterministic ordering key.

        Returns:
            Published message identifier.
        """
        ...


class PubSubBundleDispatchStage(PipelineStage):
    """Packages normalized telemetry frames and dispatches them to Pub/Sub."""

    def __init__(
        self, publisher: _PublisherPort, topic: str = "gas-regulator-telemetry"
    ) -> None:
        """Initializes stage with publisher port and target topic.

        Args:
            publisher: Component implementing PublisherPort.
            topic: Target topic name.
        """
        self._publisher = publisher
        self._topic = topic

    @property
    def stage_name(self) -> str:
        """Returns the stage identifier."""
        return "pubsub_bundle_dispatch"

    def process(self, context: PipelineContext) -> PipelineContext:
        """Packages records into a telemetry bundle and dispatches via publisher.

        Args:
            context: Incoming PipelineContext.

        Returns:
            Updated PipelineContext with message identifier recorded.

        Raises:
            PublisherUnavailableError: If publisher fails or connection dropped.
        """
        records = context.records
        if not records:
            return context

        bundle_payload: dict[str, Any] = {
            "stream_id": context.stream_id,
            "key_id": context.key_id,
            "is_replayed": context.is_replayed,
            "records": [asdict(r) for r in records],
            "metrics": dict(context.evaluated_metrics),
        }

        ordering_key = context.stream_id

        try:
            msg_id = self._publisher.publish(
                topic=self._topic,
                message=bundle_payload,
                ordering_key=ordering_key,
            )
        except Exception as err:
            raise PublisherUnavailableError(
                f"Failed to dispatch telemetry bundle to topic '{self._topic}': {err}",
                code="PUBLISHER_UNAVAILABLE",
                status_code=500,
            ) from err

        return context.with_dispatched_messages((msg_id,))
