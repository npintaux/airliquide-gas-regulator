"""Google Cloud Pub/Sub publisher adapter with in-memory fallback support."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any


class PubSubPublisher:
    """Publishes telemetry bundles to Google Cloud Pub/Sub topics with ordering keys."""

    def __init__(self, project_id: str = "airliquide-iot-regulator") -> None:
        """Initializes publisher adapter.

        Args:
            project_id: Target GCP project identifier.
        """
        self._project_id = project_id
        self._connected = True
        self._history: list[dict[str, Any]] = []

    @property
    def project_id(self) -> str:
        """Returns the GCP project identifier."""
        return self._project_id

    @property
    def published_count(self) -> int:
        """Returns the total number of successfully published messages."""
        return len(self._history)

    @property
    def published_history(self) -> list[dict[str, Any]]:
        """Returns copy of published messages history."""
        return list(self._history)

    def is_connected(self) -> bool:
        """Checks readiness and connectivity of publisher client."""
        return self._connected

    def set_connected(self, status: bool) -> None:
        """Toggles connectivity state for testing and degradation simulation.

        Args:
            status: Boolean flag indicating if publisher is online.
        """
        self._connected = status

    def publish(self, topic: str, message: Mapping[str, Any], ordering_key: str) -> str:
        """Publishes a structured payload with an ordering key.

        Args:
            topic: Destination Pub/Sub topic name.
            message: Telemetry dictionary payload.
            ordering_key: Deterministic ordering key (plant_id:regulator_id:sensor_id).

        Returns:
            Assigned message identifier.

        Raises:
            RuntimeError: If publisher client is disconnected or fails.
        """
        if not self._connected:
            raise RuntimeError("Pub/Sub client is not connected to downstream broker")

        msg_id = f"mock-pubsub-msg-{uuid.uuid4().hex[:12]}"
        self._history.append(
            {
                "message_id": msg_id,
                "topic": topic,
                "message": dict(message),
                "ordering_key": ordering_key,
            }
        )
        return msg_id

    def clear(self) -> None:
        """Clears published message history."""
        self._history.clear()
