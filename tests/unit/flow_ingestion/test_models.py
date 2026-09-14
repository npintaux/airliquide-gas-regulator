"""Unit tests for flow ingestion domain models and exceptions."""

from __future__ import annotations

import pytest

from src.modules.flow_ingestion.domain.exceptions import (
    FlowIngestionError,
    InternalIngestionError,
    JitterThresholdExceededError,
    MalformedPayloadError,
    PublisherUnavailableError,
    RateLimitExceededError,
    SequenceDiscontinuityError,
    SignatureVerificationError,
)
from src.modules.flow_ingestion.domain.models import (
    IngestionResult,
    PipelineContext,
    TelemetryRecord,
)


def test_telemetry_record_creation() -> None:
    """[US-1][AC-1.1] Verify TelemetryRecord holds immutable fields."""
    record = TelemetryRecord(
        plant_id="PLANT-BEL-01",
        regulator_id="REG-OX-401",
        sensor_id="FLOW-SN-8820",
        sequence_number=10452,
        timestamp_ns=1726312800000000000,
        flow_rate_sccm=2500.5,
        pressure_bar=16.2,
        temperature_celsius=21.4,
        status_flags=0,
    )
    assert record.plant_id == "PLANT-BEL-01"
    assert record.regulator_id == "REG-OX-401"
    assert record.sensor_id == "FLOW-SN-8820"
    assert record.sequence_number == 10452
    assert record.timestamp_ns == 1726312800000000000
    assert record.flow_rate_sccm == 2500.5
    assert record.pressure_bar == 16.2
    assert record.temperature_celsius == 21.4
    assert record.status_flags == 0


def test_pipeline_context_immutability_and_evolution() -> None:
    """[US-1][AC-1.1] Verify PipelineContext functional updates create new instances."""
    record = TelemetryRecord(
        plant_id="PLANT-01",
        regulator_id="REG-01",
        sensor_id="SN-01",
        sequence_number=1,
        timestamp_ns=1000,
        flow_rate_sccm=10.0,
        pressure_bar=1.0,
        temperature_celsius=20.0,
        status_flags=0,
    )
    context = PipelineContext(
        stream_id="PLANT-01:REG-01:SN-01",
        raw_payload={"sample": "data"},
        hmac_signature="sig-123",
        key_id="k-1",
        is_replayed=False,
    )
    assert context.stream_id == "PLANT-01:REG-01:SN-01"
    assert context.is_authenticated is False
    assert context.records == ()

    ctx2 = context.with_authentication(True)
    assert ctx2 is not context
    assert ctx2.is_authenticated is True
    assert context.is_authenticated is False

    ctx3 = ctx2.with_records((record,))
    assert ctx3.records == (record,)
    assert ctx2.records == ()

    ctx4 = ctx3.with_metric("jitter_ms", 1.5)
    assert ctx4.evaluated_metrics["jitter_ms"] == 1.5

    ctx5 = ctx4.with_dispatched_messages(("msg-1", "msg-2"))
    assert ctx5.dispatched_messages == ("msg-1", "msg-2")

    ctx6 = ctx5.with_metadata("source", "mqtt")
    assert ctx6.metadata["source"] == "mqtt"


def test_ingestion_result() -> None:
    """[US-1][AC-1.4] Verify IngestionResult holds execution results."""
    result = IngestionResult(
        status="accepted",
        stream_id="PLANT-01:REG-01:SN-01",
        message_ids=("msg-1",),
        records_count=1,
        processed_at_ns=123456789,
    )
    assert result.status == "accepted"
    assert result.records_count == 1
    assert result.message_ids == ("msg-1",)


def test_domain_exceptions_hierarchy_and_attributes() -> None:
    """[US-1][AC-1.1][AC-1.3] Verify custom exception classes and their properties."""
    with pytest.raises(MalformedPayloadError) as exc_info:
        raise MalformedPayloadError(
            "Missing key", code="MALFORMED_PAYLOAD", status_code=400
        )
    assert exc_info.value.code == "MALFORMED_PAYLOAD"
    assert exc_info.value.status_code == 400
    assert isinstance(exc_info.value, FlowIngestionError)

    sig_err = SignatureVerificationError(
        "bad sig", code="INVALID_SIGNATURE", status_code=401
    )
    assert sig_err.code == "INVALID_SIGNATURE"
    assert sig_err.status_code == 401

    seq_err = SequenceDiscontinuityError(
        "out of order", code="SEQUENCE_DISCONTINUITY", status_code=422
    )
    assert seq_err.code == "SEQUENCE_DISCONTINUITY"
    assert seq_err.status_code == 422

    jit_err = JitterThresholdExceededError(
        "too jittery", code="JITTER_THRESHOLD_EXCEEDED", status_code=422
    )
    assert jit_err.code == "JITTER_THRESHOLD_EXCEEDED"
    assert jit_err.status_code == 422

    rat_err = RateLimitExceededError(
        "rate limit", code="RATE_LIMIT_EXCEEDED", status_code=422
    )
    assert rat_err.code == "RATE_LIMIT_EXCEEDED"
    assert rat_err.status_code == 422

    pub_err = PublisherUnavailableError(
        "pubsub down", code="PUBLISHER_UNAVAILABLE", status_code=500
    )
    assert pub_err.code == "PUBLISHER_UNAVAILABLE"
    assert pub_err.status_code == 500

    int_err = InternalIngestionError(
        "internal boom", code="INTERNAL_INGESTION_ERROR", status_code=500
    )
    assert int_err.code == "INTERNAL_INGESTION_ERROR"
    assert int_err.status_code == 500
