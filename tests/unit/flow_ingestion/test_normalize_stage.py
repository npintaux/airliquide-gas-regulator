"""Unit tests for FrameNormalizationStage."""

from __future__ import annotations

import pytest

from src.modules.flow_ingestion.domain.exceptions import MalformedPayloadError
from src.modules.flow_ingestion.domain.models import PipelineContext
from src.modules.flow_ingestion.domain.stages.normalize_stage import (
    FrameNormalizationStage,
)


def test_normalize_single_frame_success() -> None:
    """[US-1][AC-1.1] Verify single valid frame dictionary converts to TelemetryRecord."""
    stage = FrameNormalizationStage()
    assert stage.stage_name == "frame_normalization"

    raw_frame = {
        "plant_id": "PLANT-BEL-01",
        "regulator_id": "REG-OX-401",
        "sensor_id": "FLOW-SN-8820",
        "sequence_number": 10452,
        "timestamp_ns": 1726312800000000000,
        "flow_rate_sccm": 2500.5,
        "pressure_bar": 16.2,
        "temperature_celsius": 21.4,
        "status_flags": 0,
    }
    payload = {"frame": raw_frame}
    ctx = PipelineContext(
        stream_id="PLANT-BEL-01:REG-OX-401:FLOW-SN-8820",
        raw_payload=payload,
        hmac_signature="sig",
        key_id="k1",
        is_authenticated=True,
    )

    result = stage.process(ctx)
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.plant_id == "PLANT-BEL-01"
    assert rec.flow_rate_sccm == 2500.5
    assert rec.sequence_number == 10452


def test_normalize_batch_frames_success() -> None:
    """[US-1][AC-1.1] Verify batch frames payload converts to tuple of TelemetryRecords."""
    stage = FrameNormalizationStage()
    frames = [
        {
            "plant_id": "PLANT-01",
            "regulator_id": "REG-01",
            "sensor_id": "SN-01",
            "sequence_number": i,
            "timestamp_ns": 1000 + i * 100_000_000,
            "flow_rate_sccm": 100.0 + i,
            "pressure_bar": 10.0,
            "temperature_celsius": 20.0,
            "status_flags": 0,
        }
        for i in range(5)
    ]
    payload = {
        "plant_id": "PLANT-01",
        "regulator_id": "REG-01",
        "sensor_id": "SN-01",
        "batch_id": "BATCH-001",
        "frames": frames,
    }
    ctx = PipelineContext(
        stream_id="PLANT-01:REG-01:SN-01",
        raw_payload=payload,
        hmac_signature="sig",
        key_id="k1",
        is_authenticated=True,
    )

    result = stage.process(ctx)
    assert len(result.records) == 5
    assert result.records[0].sequence_number == 0
    assert result.records[4].sequence_number == 4


def test_normalize_empty_batch_frames_fails() -> None:
    """[US-1][AC-1.1] Verify empty frames array raises MalformedPayloadError (400)."""
    stage = FrameNormalizationStage()
    payload = {
        "plant_id": "PLANT-01",
        "regulator_id": "REG-01",
        "sensor_id": "SN-01",
        "batch_id": "BATCH-001",
        "frames": [],
    }
    ctx = PipelineContext(
        stream_id="PLANT-01:REG-01:SN-01",
        raw_payload=payload,
        hmac_signature="sig",
        key_id="k1",
        is_authenticated=True,
    )
    with pytest.raises(MalformedPayloadError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "MALFORMED_PAYLOAD"
    assert exc_info.value.status_code == 400


def test_normalize_missing_required_field_fails() -> None:
    """[US-1][AC-1.1] Verify frame missing a required field raises MalformedPayloadError (400)."""
    stage = FrameNormalizationStage()
    raw_frame = {
        "plant_id": "PLANT-BEL-01",
        # missing regulator_id
        "sensor_id": "FLOW-SN-8820",
        "sequence_number": 10452,
        "timestamp_ns": 1726312800000000000,
        "flow_rate_sccm": 2500.5,
        "pressure_bar": 16.2,
        "temperature_celsius": 21.4,
        "status_flags": 0,
    }
    payload = {"frame": raw_frame}
    ctx = PipelineContext(
        stream_id="PLANT-BEL-01:REG-OX-401:FLOW-SN-8820",
        raw_payload=payload,
        hmac_signature="sig",
        key_id="k1",
        is_authenticated=True,
    )

    with pytest.raises(MalformedPayloadError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "MALFORMED_PAYLOAD"
    assert exc_info.value.status_code == 400


def test_normalize_invalid_data_type_fails() -> None:
    """[US-1][AC-1.1] Verify field with invalid type raises MalformedPayloadError (400)."""
    stage = FrameNormalizationStage()
    raw_frame = {
        "plant_id": "PLANT-BEL-01",
        "regulator_id": "REG-OX-401",
        "sensor_id": "FLOW-SN-8820",
        "sequence_number": "not-an-int",
        "timestamp_ns": 1726312800000000000,
        "flow_rate_sccm": 2500.5,
        "pressure_bar": 16.2,
        "temperature_celsius": 21.4,
        "status_flags": 0,
    }
    payload = {"frame": raw_frame}
    ctx = PipelineContext(
        stream_id="PLANT-BEL-01:REG-OX-401:FLOW-SN-8820",
        raw_payload=payload,
        hmac_signature="sig",
        key_id="k1",
        is_authenticated=True,
    )

    with pytest.raises(MalformedPayloadError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "MALFORMED_PAYLOAD"
    assert exc_info.value.status_code == 400


def test_normalize_empty_payload_fails() -> None:
    """[US-1][AC-1.1] Verify completely empty payload raises MalformedPayloadError (400)."""
    stage = FrameNormalizationStage()
    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={},
        hmac_signature="sig",
        key_id="k1",
        is_authenticated=True,
    )

    with pytest.raises(MalformedPayloadError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "MALFORMED_PAYLOAD"
    assert exc_info.value.status_code == 400


def test_normalize_payload_structure_errors() -> None:
    """[US-1] Test malformed payload structures (non-dict frame, non-list frames, etc.)."""
    from src.modules.flow_ingestion.domain.exceptions import RateLimitExceededError

    stage = FrameNormalizationStage()

    # Field 'frame' not Mapping
    ctx1 = PipelineContext("P:R:S", {"frame": 123}, "sig", "k1", True)
    with pytest.raises(MalformedPayloadError):
        stage.process(ctx1)

    # Field 'frames' not list
    ctx2 = PipelineContext("P:R:S", {"frames": "not-a-list"}, "sig", "k1", True)
    with pytest.raises(MalformedPayloadError):
        stage.process(ctx2)

    # Item in 'frames' not Mapping
    ctx3 = PipelineContext("P:R:S", {"frames": ["not-a-map"]}, "sig", "k1", True)
    with pytest.raises(MalformedPayloadError):
        stage.process(ctx3)

    # Neither 'frame' nor 'frames'
    ctx4 = PipelineContext("P:R:S", {"other": "value"}, "sig", "k1", True)
    with pytest.raises(MalformedPayloadError):
        stage.process(ctx4)

    # Field boolean validation checks in _parse_record
    valid_base = {
        "plant_id": "P1",
        "regulator_id": "R1",
        "sensor_id": "S1",
        "sequence_number": 1,
        "timestamp_ns": 1000,
        "flow_rate_sccm": 10.0,
        "pressure_bar": 1.0,
        "temperature_celsius": 20.0,
        "status_flags": 0,
    }

    # timestamp_ns as bool
    bad_ts = dict(valid_base, timestamp_ns=True)
    with pytest.raises(MalformedPayloadError):
        stage.process(PipelineContext("P:R:S", {"frame": bad_ts}, "sig", "k1", True))

    # flow_rate_sccm as bool
    bad_flow = dict(valid_base, flow_rate_sccm=True)
    with pytest.raises(MalformedPayloadError):
        stage.process(PipelineContext("P:R:S", {"frame": bad_flow}, "sig", "k1", True))

    # pressure_bar as bool
    bad_press = dict(valid_base, pressure_bar=True)
    with pytest.raises(MalformedPayloadError):
        stage.process(PipelineContext("P:R:S", {"frame": bad_press}, "sig", "k1", True))

    # temperature_celsius as bool
    bad_temp = dict(valid_base, temperature_celsius=True)
    with pytest.raises(MalformedPayloadError):
        stage.process(PipelineContext("P:R:S", {"frame": bad_temp}, "sig", "k1", True))

    # status_flags as bool
    bad_flags = dict(valid_base, status_flags=True)
    with pytest.raises(MalformedPayloadError):
        stage.process(PipelineContext("P:R:S", {"frame": bad_flags}, "sig", "k1", True))

    # Physical range violation: negative flow
    neg_flow = dict(valid_base, flow_rate_sccm=-5.0)
    with pytest.raises(RateLimitExceededError):
        stage.process(PipelineContext("P:R:S", {"frame": neg_flow}, "sig", "k1", True))
