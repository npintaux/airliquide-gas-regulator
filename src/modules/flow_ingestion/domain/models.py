"""Domain models for flow ingestion subsystem."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TelemetryRecord:
    """Immutable normalized telemetry reading.

    Attributes:
        plant_id: Plant identifier.
        regulator_id: Gas regulator unit identifier.
        sensor_id: Sensor stream identifier.
        sequence_number: Monotonically increasing sequence number per stream.
        timestamp_ns: Edge capture timestamp in Unix epoch nanoseconds.
        flow_rate_sccm: Standard cubic centimeters per minute (sccm).
        pressure_bar: Line pressure measurement in bar.
        temperature_celsius: Gas temperature measurement in degrees Celsius.
        status_flags: Bitmask of sensor hardware diagnostic status flags.
    """

    plant_id: str
    regulator_id: str
    sensor_id: str
    sequence_number: int
    timestamp_ns: int
    flow_rate_sccm: float
    pressure_bar: float
    temperature_celsius: float
    status_flags: int


@dataclass(frozen=True)
class PipelineContext:
    """Accumulating context threaded through pipeline transformation stages.

    Attributes:
        stream_id: Stream identifier (ordering key plant_id:regulator_id:sensor_id).
        raw_payload: Original unprocessed payload dictionary.
        hmac_signature: Hex-encoded HMAC-SHA256 signature.
        key_id: Key version identifier.
        is_replayed: Flag indicating if frame is replayed from offline buffer.
        is_authenticated: Flag set once HMAC signature is verified.
        records: Tuple of normalized TelemetryRecord instances.
        evaluated_metrics: Mapping of evaluated metric names to float values.
        dispatched_messages: Tuple of published message identifiers.
        metadata: Execution metadata and diagnostics.
    """

    stream_id: str
    raw_payload: Mapping[str, Any]
    hmac_signature: str
    key_id: str
    is_replayed: bool = False
    is_authenticated: bool = False
    records: tuple[TelemetryRecord, ...] = ()
    evaluated_metrics: Mapping[str, float] = field(default_factory=dict)
    dispatched_messages: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def with_authentication(self, authenticated: bool) -> PipelineContext:
        """Returns new context with updated authentication status."""
        return PipelineContext(
            stream_id=self.stream_id,
            raw_payload=self.raw_payload,
            hmac_signature=self.hmac_signature,
            key_id=self.key_id,
            is_replayed=self.is_replayed,
            is_authenticated=authenticated,
            records=self.records,
            evaluated_metrics=self.evaluated_metrics,
            dispatched_messages=self.dispatched_messages,
            metadata=self.metadata,
        )

    def with_records(self, records: tuple[TelemetryRecord, ...]) -> PipelineContext:
        """Returns new context with updated normalized records."""
        return PipelineContext(
            stream_id=self.stream_id,
            raw_payload=self.raw_payload,
            hmac_signature=self.hmac_signature,
            key_id=self.key_id,
            is_replayed=self.is_replayed,
            is_authenticated=self.is_authenticated,
            records=records,
            evaluated_metrics=self.evaluated_metrics,
            dispatched_messages=self.dispatched_messages,
            metadata=self.metadata,
        )

    def with_metric(self, name: str, value: float) -> PipelineContext:
        """Returns new context with an evaluated metric appended or updated."""
        updated = dict(self.evaluated_metrics)
        updated[name] = value
        return PipelineContext(
            stream_id=self.stream_id,
            raw_payload=self.raw_payload,
            hmac_signature=self.hmac_signature,
            key_id=self.key_id,
            is_replayed=self.is_replayed,
            is_authenticated=self.is_authenticated,
            records=self.records,
            evaluated_metrics=updated,
            dispatched_messages=self.dispatched_messages,
            metadata=self.metadata,
        )

    def with_dispatched_messages(self, message_ids: tuple[str, ...]) -> PipelineContext:
        """Returns new context with dispatched message identifiers."""
        return PipelineContext(
            stream_id=self.stream_id,
            raw_payload=self.raw_payload,
            hmac_signature=self.hmac_signature,
            key_id=self.key_id,
            is_replayed=self.is_replayed,
            is_authenticated=self.is_authenticated,
            records=self.records,
            evaluated_metrics=self.evaluated_metrics,
            dispatched_messages=message_ids,
            metadata=self.metadata,
        )

    def with_metadata(self, key: str, value: str) -> PipelineContext:
        """Returns new context with updated diagnostic metadata."""
        updated = dict(self.metadata)
        updated[key] = value
        return PipelineContext(
            stream_id=self.stream_id,
            raw_payload=self.raw_payload,
            hmac_signature=self.hmac_signature,
            key_id=self.key_id,
            is_replayed=self.is_replayed,
            is_authenticated=self.is_authenticated,
            records=self.records,
            evaluated_metrics=self.evaluated_metrics,
            dispatched_messages=self.dispatched_messages,
            metadata=updated,
        )


@dataclass(frozen=True)
class IngestionResult:
    """Terminal outcome of telemetry pipeline execution.

    Attributes:
        status: Ingestion status ("accepted", "duplicate", "replayed").
        stream_id: Stream identifier (plant_id:regulator_id:sensor_id).
        message_ids: Pub/Sub publication message identifiers or audit IDs.
        records_count: Total normalized records processed.
        processed_at_ns: Cloud processing completion timestamp in nanoseconds.
    """

    status: str
    stream_id: str
    message_ids: tuple[str, ...]
    records_count: int
    processed_at_ns: int
