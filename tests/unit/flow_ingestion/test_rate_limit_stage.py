"""Unit tests for RateJitterEvaluationStage."""

from __future__ import annotations

import pytest

from src.modules.flow_ingestion.domain.exceptions import (
    JitterThresholdExceededError,
    RateLimitExceededError,
    SequenceDiscontinuityError,
)
from src.modules.flow_ingestion.domain.models import PipelineContext, TelemetryRecord
from src.modules.flow_ingestion.domain.stages.rate_limit_stage import (
    RateJitterEvaluationStage,
)


def _make_record(seq: int, ts_ns: int, stream: str = "P1:R1:S1") -> TelemetryRecord:
    parts = stream.split(":")
    return TelemetryRecord(
        plant_id=parts[0],
        regulator_id=parts[1],
        sensor_id=parts[2],
        sequence_number=seq,
        timestamp_ns=ts_ns,
        flow_rate_sccm=100.0,
        pressure_bar=10.0,
        temperature_celsius=20.0,
        status_flags=0,
    )


def test_rate_jitter_success_single_record() -> None:
    """[US-1][AC-1.1][AC-1.3] Verify valid single frame passes rate and jitter checks."""
    stage = RateJitterEvaluationStage(max_burst_per_sec=100)
    assert stage.stage_name == "rate_jitter_evaluation"

    record = _make_record(seq=100, ts_ns=1_000_000_000)
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(record,),
    )

    result = stage.process(ctx)
    assert result.evaluated_metrics["sequence_delta"] == 0.0
    assert result.evaluated_metrics["jitter_ns"] == 0.0


def test_rate_jitter_success_batch_monotonic() -> None:
    """[US-1][AC-1.1][AC-1.3] Verify monotonic batch frames with 100ms delta pass."""
    stage = RateJitterEvaluationStage()
    records = tuple(
        _make_record(seq=i, ts_ns=1_000_000_000 + i * 100_000_000) for i in range(10)
    )
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=records,
    )

    result = stage.process(ctx)
    assert result.evaluated_metrics["max_jitter_ns"] <= 10_000_000


def test_rate_jitter_sequence_discontinuity_in_batch() -> None:
    """[US-1][AC-1.3] Verify non-monotonic sequence numbers in batch raise SequenceDiscontinuityError (422)."""
    stage = RateJitterEvaluationStage()
    records = (
        _make_record(seq=1, ts_ns=1_000_000_000),
        _make_record(seq=3, ts_ns=1_100_000_000),  # Jump from 1 to 3
    )
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=records,
    )

    with pytest.raises(SequenceDiscontinuityError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "SEQUENCE_DISCONTINUITY"
    assert exc_info.value.status_code == 422


def test_rate_jitter_sequence_discontinuity_across_calls() -> None:
    """[US-1][AC-1.3] Verify out-of-order sequence across consecutive packets raises SequenceDiscontinuityError (422)."""
    stage = RateJitterEvaluationStage()
    rec1 = _make_record(seq=10, ts_ns=1_000_000_000)
    ctx1 = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(rec1,),
    )
    stage.process(ctx1)

    rec2 = _make_record(seq=9, ts_ns=1_100_000_000)  # Decreasing sequence
    ctx2 = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(rec2,),
    )

    with pytest.raises(SequenceDiscontinuityError) as exc_info:
        stage.process(ctx2)
    assert exc_info.value.code == "SEQUENCE_DISCONTINUITY"
    assert exc_info.value.status_code == 422


def test_rate_jitter_offline_replay_ignores_sequence_discontinuity() -> None:
    """[US-5][AC-137] Verify is_replayed=True bypasses strict sequence monotonicity checks."""
    stage = RateJitterEvaluationStage()
    # Populate history
    rec1 = _make_record(seq=100, ts_ns=1_000_000_000)
    ctx1 = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(rec1,),
    )
    stage.process(ctx1)

    # Replay packet from the past with lower sequence
    rec_replayed = _make_record(seq=50, ts_ns=500_000_000)
    ctx_replayed = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        is_replayed=True,
        records=(rec_replayed,),
    )

    result = stage.process(ctx_replayed)
    assert result.is_replayed is True


def test_rate_jitter_excessive_jitter_fails() -> None:
    """[US-1][AC-1.3] Verify timestamp variance exceeding jitter tolerance raises JitterThresholdExceededError (422)."""
    stage = RateJitterEvaluationStage(
        nominal_interval_ns=100_000_000, jitter_tolerance_ns=20_000_000
    )
    # Consecutive packets with 200ms gap instead of 100ms
    rec1 = _make_record(seq=1, ts_ns=1_000_000_000)
    rec2 = _make_record(
        seq=2, ts_ns=1_200_000_000
    )  # delta = 200ms, jitter = 100ms > 20ms
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(rec1, rec2),
    )

    with pytest.raises(JitterThresholdExceededError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "JITTER_THRESHOLD_EXCEEDED"
    assert exc_info.value.status_code == 422


def test_rate_jitter_rate_limit_exceeded() -> None:
    """[US-1][AC-1.3] Verify ingestion exceeding max burst limit raises RateLimitExceededError (422)."""
    stage = RateJitterEvaluationStage(max_burst_per_sec=5)
    records = tuple(
        _make_record(seq=i, ts_ns=1_000_000_000 + i * 100_000_000) for i in range(10)
    )
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=records,
    )

    with pytest.raises(RateLimitExceededError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "RATE_LIMIT_EXCEEDED"
    assert exc_info.value.status_code == 422


def test_rate_jitter_empty_records_noop() -> None:
    """[US-1] Verify empty records in context returns unmodified context."""
    stage = RateJitterEvaluationStage()
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(),
    )
    result = stage.process(ctx)
    assert len(result.records) == 0


def test_rate_jitter_clear_history() -> None:
    """[US-1] Verify clear_history resets internal stream history."""
    stage = RateJitterEvaluationStage()
    rec = _make_record(seq=10, ts_ns=1000)
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(rec,),
    )
    stage.process(ctx)
    stage.clear_history()
    assert len(stage._stream_history) == 0


def test_rate_jitter_timestamp_reset_resets_stream_history() -> None:
    """[US-1] Verify timestamp backwards jump resets stream history without failing sequence discontinuity."""
    stage = RateJitterEvaluationStage()
    rec1 = _make_record(seq=10452, ts_ns=2000)
    ctx1 = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(rec1,),
    )
    stage.process(ctx1)

    # Packet arrives with lower timestamp (e.g. sensor reboot / session reset)
    rec2 = _make_record(seq=1001, ts_ns=1000)
    ctx2 = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        records=(rec2,),
    )
    res2 = stage.process(ctx2)
    assert res2.evaluated_metrics["sequence_delta"] == 0.0
    assert stage._stream_history["P1:R1:S1"] == (1001, 1000)
