"""Unit tests for PubSubBundleDispatchStage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from src.modules.flow_ingestion.domain.exceptions import PublisherUnavailableError
from src.modules.flow_ingestion.domain.models import PipelineContext, TelemetryRecord
from src.modules.flow_ingestion.domain.stages.bundle_stage import (
    PubSubBundleDispatchStage,
)


class FakePublisher:
    """Fake publisher port implementing synchronous publish."""

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.published_messages: list[tuple[str, Mapping[str, Any], str]] = []

    def publish(self, topic: str, message: Mapping[str, Any], ordering_key: str) -> str:
        """Records message or raises simulated error."""
        if self.should_fail:
            raise RuntimeError("Connection dropped to pubsub")
        msg_id = f"pubsub-msg-{len(self.published_messages) + 1}"
        self.published_messages.append((topic, message, ordering_key))
        return msg_id


def _make_record(seq: int, stream: str = "PLANT-01:REG-01:SN-01") -> TelemetryRecord:
    parts = stream.split(":")
    return TelemetryRecord(
        plant_id=parts[0],
        regulator_id=parts[1],
        sensor_id=parts[2],
        sequence_number=seq,
        timestamp_ns=1_000_000_000,
        flow_rate_sccm=100.0,
        pressure_bar=10.0,
        temperature_celsius=20.0,
        status_flags=0,
    )


def test_bundle_dispatch_success() -> None:
    """[US-1][AC-1.4] Verify records are bundled, dispatched with ordering key, and message_id returned."""
    publisher = FakePublisher()
    stage = PubSubBundleDispatchStage(publisher=publisher, topic="telemetry-normalized")
    assert stage.stage_name == "pubsub_bundle_dispatch"

    records = (_make_record(1), _make_record(2))
    ctx = PipelineContext(
        stream_id="PLANT-01:REG-01:SN-01",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=records,
    )

    result = stage.process(ctx)
    assert len(result.dispatched_messages) == 1
    assert result.dispatched_messages[0] == "pubsub-msg-1"
    assert len(publisher.published_messages) == 1
    topic, msg, ordering_key = publisher.published_messages[0]
    assert topic == "telemetry-normalized"
    assert ordering_key == "PLANT-01:REG-01:SN-01"
    assert msg["stream_id"] == "PLANT-01:REG-01:SN-01"
    assert len(msg["records"]) == 2


def test_bundle_dispatch_failure_raises_publisher_unavailable() -> None:
    """[US-1][AC-1.4] Verify publisher error wraps in PublisherUnavailableError (500)."""
    publisher = FakePublisher(should_fail=True)
    stage = PubSubBundleDispatchStage(publisher=publisher, topic="telemetry-normalized")

    records = (_make_record(1),)
    ctx = PipelineContext(
        stream_id="PLANT-01:REG-01:SN-01",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=records,
    )

    with pytest.raises(PublisherUnavailableError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "PUBLISHER_UNAVAILABLE"
    assert exc_info.value.status_code == 500


def test_bundle_dispatch_empty_records_noop() -> None:
    """[US-1][AC-1.4] Verify dispatch with empty records does not publish anything."""
    publisher = FakePublisher()
    stage = PubSubBundleDispatchStage(publisher=publisher, topic="telemetry-normalized")

    ctx = PipelineContext(
        stream_id="PLANT-01:REG-01:SN-01",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(),
    )

    result = stage.process(ctx)
    assert result.dispatched_messages == ()
    assert len(publisher.published_messages) == 0
