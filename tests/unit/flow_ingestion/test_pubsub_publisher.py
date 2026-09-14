"""Unit tests for PubSubPublisher adapter."""

from __future__ import annotations

import pytest

from src.modules.flow_ingestion.adapters.pubsub_publisher import PubSubPublisher


def test_pubsub_publisher_in_memory_mode() -> None:
    """[US-1][AC-1.4] Verify publisher publishes message with ordering key and increments counter."""
    publisher = PubSubPublisher(project_id="custom-project")
    assert publisher.project_id == "custom-project"
    assert publisher.is_connected() is True

    msg_id = publisher.publish(
        topic="telemetry-topic",
        message={"stream_id": "P1:R1:S1", "val": 42},
        ordering_key="P1:R1:S1",
    )
    assert msg_id.startswith("mock-pubsub-msg-")
    assert publisher.published_count == 1
    assert len(publisher.published_history) == 1

    entry = publisher.published_history[0]
    assert entry["topic"] == "telemetry-topic"
    assert entry["ordering_key"] == "P1:R1:S1"
    assert entry["message"]["val"] == 42


def test_pubsub_publisher_simulate_disconnect() -> None:
    """[US-1][AC-1.4] Verify publisher raises RuntimeError when disconnected."""
    publisher = PubSubPublisher()
    publisher.set_connected(False)
    assert publisher.is_connected() is False

    with pytest.raises(RuntimeError) as exc_info:
        publisher.publish(
            topic="test-topic",
            message={},
            ordering_key="key",
        )
    assert "Pub/Sub client is not connected" in str(exc_info.value)


def test_pubsub_publisher_clear() -> None:
    """[US-1][AC-1.4] Verify publisher history can be cleared."""
    publisher = PubSubPublisher()
    publisher.publish("t", {}, "k")
    assert publisher.published_count == 1
    publisher.clear()
    assert publisher.published_count == 0
    assert len(publisher.published_history) == 0
