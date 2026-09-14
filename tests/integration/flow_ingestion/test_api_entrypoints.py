"""Integration tests for flow ingestion FastAPI entrypoint."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.modules.flow_ingestion.entrypoints.api import (
    DEFAULT_KEY_STORE,
    app,
    get_publisher,
)


def compute_sig(key: str, data: Any) -> str:
    """Helper to calculate valid HMAC signature."""
    serialized = json.dumps(data, sort_keys=True).encode("utf-8")
    return hmac.new(key.encode("utf-8"), serialized, hashlib.sha256).hexdigest()


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client fixture."""
    from src.modules.flow_ingestion.entrypoints.api import reset_subsystem_state

    reset_subsystem_state()
    return TestClient(app)


def test_ingest_telemetry_201_success(client: TestClient) -> None:
    """[US-1][AC-1.1] Verify single telemetry ingestion returns 201 Created and schema."""
    key = DEFAULT_KEY_STORE["edge-key-v1"]
    frame = {
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
    raw_payload = {"frame": frame}
    sig = compute_sig(key, raw_payload)

    body = {
        "frame": frame,
        "hmac_signature": sig,
        "key_id": "edge-key-v1",
        "is_replayed": False,
    }

    response = client.post("/v1/telemetry/ingest", json=body)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "accepted"
    assert data["stream_id"] == "PLANT-BEL-01:REG-OX-401:FLOW-SN-8820"
    assert data["sequence_number"] == 10452
    assert "message_id" in data
    assert "processed_at_ns" in data


def test_ingest_telemetry_400_malformed(client: TestClient) -> None:
    """[US-1][AC-1.1] Verify missing or invalid fields return 400 Bad Request."""
    response = client.post("/v1/telemetry/ingest", json={"invalid": "payload"})
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "MALFORMED_PAYLOAD"
    assert "message" in data


def test_ingest_telemetry_401_invalid_signature(client: TestClient) -> None:
    """[US-1][AC-1.1] Verify invalid signature returns 401 Unauthorized."""
    frame = {
        "plant_id": "PLANT-BEL-01",
        "regulator_id": "REG-OX-401",
        "sensor_id": "FLOW-SN-8820",
        "sequence_number": 10453,
        "timestamp_ns": 1726312800100000000,
        "flow_rate_sccm": 2500.5,
        "pressure_bar": 16.2,
        "temperature_celsius": 21.4,
        "status_flags": 0,
    }
    body = {
        "frame": frame,
        "hmac_signature": "invalid-hmac-signature",
        "key_id": "edge-key-v1",
    }
    response = client.post("/v1/telemetry/ingest", json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_SIGNATURE"


def test_ingest_telemetry_422_sequence_discontinuity(client: TestClient) -> None:
    """[US-1][AC-1.3] Verify sequence out-of-order returns 422 Unprocessable."""
    key = DEFAULT_KEY_STORE["edge-key-v1"]
    # First frame to establish stream sequence state
    frame1 = {
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
    raw1 = {"frame": frame1}
    sig1 = compute_sig(key, raw1)
    client.post(
        "/v1/telemetry/ingest",
        json={"frame": frame1, "hmac_signature": sig1, "key_id": "edge-key-v1"},
    )

    # Second frame with non-monotonic lower sequence number
    frame2 = {
        "plant_id": "PLANT-BEL-01",
        "regulator_id": "REG-OX-401",
        "sensor_id": "FLOW-SN-8820",
        "sequence_number": 10450,  # Lower sequence number
        "timestamp_ns": 1726312800100000000,
        "flow_rate_sccm": 2500.5,
        "pressure_bar": 16.2,
        "temperature_celsius": 21.4,
        "status_flags": 0,
    }
    raw2 = {"frame": frame2}
    sig2 = compute_sig(key, raw2)
    body = {
        "frame": frame2,
        "hmac_signature": sig2,
        "key_id": "edge-key-v1",
    }
    response = client.post("/v1/telemetry/ingest", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "SEQUENCE_DISCONTINUITY"


def test_ingest_telemetry_500_publisher_down(client: TestClient) -> None:
    """[US-1][AC-1.4] Verify publisher disconnection returns 500 Server Error."""
    publisher = get_publisher()
    publisher.set_connected(False)
    try:
        key = DEFAULT_KEY_STORE["edge-key-v1"]
        frame = {
            "plant_id": "PLANT-NEW",
            "regulator_id": "REG-01",
            "sensor_id": "SN-01",
            "sequence_number": 1,
            "timestamp_ns": 1000,
            "flow_rate_sccm": 10.0,
            "pressure_bar": 1.0,
            "temperature_celsius": 20.0,
            "status_flags": 0,
        }
        sig = compute_sig(key, {"frame": frame})
        body = {
            "frame": frame,
            "hmac_signature": sig,
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/ingest", json=body)
        assert response.status_code == 500
        assert response.json()["code"] == "PUBLISHER_UNAVAILABLE"
    finally:
        publisher.set_connected(True)


def test_ingest_batch_200_success(client: TestClient) -> None:
    """[US-1][AC-1.1][US-5] Verify micro-batch ingestion returns 200 OK."""
    key = DEFAULT_KEY_STORE["edge-key-v1"]
    frames = [
        {
            "plant_id": "PLANT-BATCH-01",
            "regulator_id": "REG-B1",
            "sensor_id": "SN-B1",
            "sequence_number": i + 1,
            "timestamp_ns": 1726312800000000000 + i * 100_000_000,
            "flow_rate_sccm": 2500.0 + i,
            "pressure_bar": 15.0,
            "temperature_celsius": 22.0,
            "status_flags": 0,
        }
        for i in range(10)
    ]
    raw_payload = {
        "plant_id": "PLANT-BATCH-01",
        "regulator_id": "REG-B1",
        "sensor_id": "SN-B1",
        "batch_id": "BATCH-20260914-001",
        "is_replayed": False,
        "frames": frames,
    }
    sig = compute_sig(key, raw_payload)
    body = {
        **raw_payload,
        "hmac_signature": sig,
        "key_id": "edge-key-v1",
    }

    response = client.post("/v1/telemetry/batch", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "BATCH-20260914-001"
    assert data["stream_id"] == "PLANT-BATCH-01:REG-B1:SN-B1"
    assert data["frames_received"] == 10
    assert data["frames_accepted"] == 10
    assert data["frames_deduplicated"] == 0
    assert data["is_replayed"] is False


def test_ingest_batch_400_empty_frames(client: TestClient) -> None:
    """[US-1][AC-1.1] Verify batch with empty frames returns 400 Bad Request."""
    body = {
        "plant_id": "PLANT-01",
        "regulator_id": "REG-01",
        "sensor_id": "SN-01",
        "batch_id": "BATCH-01",
        "frames": [],
        "hmac_signature": "sig",
        "key_id": "edge-key-v1",
    }
    response = client.post("/v1/telemetry/batch", json=body)
    assert response.status_code == 400
    assert response.json()["code"] == "MALFORMED_PAYLOAD"


def test_ingest_batch_401_invalid_signature(client: TestClient) -> None:
    """[US-1][AC-1.1] Verify batch with invalid signature returns 401 Unauthorized."""
    frames = [
        {
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
    ]
    body = {
        "plant_id": "P1",
        "regulator_id": "R1",
        "sensor_id": "S1",
        "batch_id": "B1",
        "frames": frames,
        "hmac_signature": "bad-sig",
        "key_id": "edge-key-v1",
    }
    response = client.post("/v1/telemetry/batch", json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_SIGNATURE"


def test_ingest_batch_422_discontinuity(client: TestClient) -> None:
    """[US-1][AC-1.3] Verify discontinuous batch frames return 422 Unprocessable."""
    key = DEFAULT_KEY_STORE["edge-key-v1"]
    frames = [
        {
            "plant_id": "P1",
            "regulator_id": "R1",
            "sensor_id": "S1",
            "sequence_number": 1,
            "timestamp_ns": 1000,
            "flow_rate_sccm": 10.0,
            "pressure_bar": 1.0,
            "temperature_celsius": 20.0,
            "status_flags": 0,
        },
        {
            "plant_id": "P1",
            "regulator_id": "R1",
            "sensor_id": "S1",
            "sequence_number": 5,  # Jump
            "timestamp_ns": 100_001_000,
            "flow_rate_sccm": 10.0,
            "pressure_bar": 1.0,
            "temperature_celsius": 20.0,
            "status_flags": 0,
        },
    ]
    raw_payload = {
        "plant_id": "P1",
        "regulator_id": "R1",
        "sensor_id": "S1",
        "batch_id": "B1",
        "frames": frames,
    }
    sig = compute_sig(key, raw_payload)
    body = {
        **raw_payload,
        "hmac_signature": sig,
        "key_id": "edge-key-v1",
    }
    response = client.post("/v1/telemetry/batch", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "SEQUENCE_DISCONTINUITY"


def test_ingest_batch_500_publisher_down(client: TestClient) -> None:
    """[US-1][AC-1.4] Verify batch failure when publisher disconnected returns 500."""
    publisher = get_publisher()
    publisher.set_connected(False)
    try:
        key = DEFAULT_KEY_STORE["edge-key-v1"]
        frames = [
            {
                "plant_id": "P-DOWN",
                "regulator_id": "R1",
                "sensor_id": "S1",
                "sequence_number": 1,
                "timestamp_ns": 1000,
                "flow_rate_sccm": 10.0,
                "pressure_bar": 1.0,
                "temperature_celsius": 20.0,
                "status_flags": 0,
            }
        ]
        raw_payload = {
            "plant_id": "P-DOWN",
            "regulator_id": "R1",
            "sensor_id": "S1",
            "batch_id": "B-DOWN",
            "frames": frames,
        }
        sig = compute_sig(key, raw_payload)
        body = {
            **raw_payload,
            "hmac_signature": sig,
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=body)
        assert response.status_code == 500
        assert response.json()["code"] == "PUBLISHER_UNAVAILABLE"
    finally:
        publisher.set_connected(True)


def test_health_check_200_healthy(client: TestClient) -> None:
    """[US-1] Verify health check endpoint returns 200 OK and healthy status."""
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["subsystem"] == "flow_ingestion"
    assert data["version"] == "1.0.0"
    assert data["pubsub_connected"] is True
    assert data["key_cache_valid"] is True
    assert "timestamp_ns" in data


def test_health_check_400_invalid_query_params(client: TestClient) -> None:
    """[US-1] Verify health check rejects unexpected query parameters with 400 Bad Request."""
    response = client.get("/v1/health?unknown=bad")
    assert response.status_code == 400
    assert response.json()["code"] == "MALFORMED_PAYLOAD"


def test_health_check_422_degraded(client: TestClient) -> None:
    """[US-1] Verify health check returns 422 when degraded."""
    from src.modules.flow_ingestion.entrypoints.api import set_health_override

    set_health_override("degraded")
    try:
        response = client.get("/v1/health")
        assert response.status_code == 422
        assert response.json()["code"] == "DEGRADED_STATE"
    finally:
        set_health_override(None)


def test_health_check_500_failure(client: TestClient) -> None:
    """[US-1] Verify health check returns 500 when unhealthy or pubsub disconnected."""
    publisher = get_publisher()
    publisher.set_connected(False)
    try:
        response = client.get("/v1/health")
        assert response.status_code == 500
        assert response.json()["code"] == "SUBSYSTEM_FAILURE"
    finally:
        publisher.set_connected(True)


def test_health_check_simulate_params(client: TestClient) -> None:
    """[US-1] Verify health check with simulate_fatal and simulate_degraded params."""
    res_fatal = client.get("/v1/health?simulate_fatal=true")
    assert res_fatal.status_code == 500
    assert res_fatal.json()["code"] == "SUBSYSTEM_FAILURE"

    res_degraded = client.get("/v1/health?simulate_degraded=true")
    assert res_degraded.status_code == 422
    assert res_degraded.json()["code"] == "DEGRADED_STATE"


def test_api_helper_functions_and_fault_injections(client: TestClient) -> None:
    """[US-1] Test fallback buffer getter, state reset, and simulated faults."""
    from src.modules.flow_ingestion.entrypoints.api import (
        get_fallback_buffer,
        reset_subsystem_state,
    )

    buffer = get_fallback_buffer()
    assert buffer is not None

    reset_subsystem_state()

    # Fault injection single telemetry
    frame = {
        "plant_id": "TRIGGER-FAULT",
        "regulator_id": "R1",
        "sensor_id": "S1",
        "sequence_number": 1,
        "timestamp_ns": 1000,
        "flow_rate_sccm": 10.0,
        "pressure_bar": 1.0,
        "temperature_celsius": 20.0,
        "status_flags": 0,
    }
    body = {
        "frame": frame,
        "hmac_signature": "mock",
        "key_id": "edge-key-v1",
    }
    res_single = client.post("/v1/telemetry/ingest", json=body)
    assert res_single.status_code == 500
    assert res_single.json()["code"] == "PUBLISHER_UNAVAILABLE"

    # Fault injection batch telemetry
    batch_body = {
        "plant_id": "TRIGGER-FAULT",
        "regulator_id": "R1",
        "sensor_id": "S1",
        "batch_id": "B1",
        "frames": [frame],
        "hmac_signature": "mock",
        "key_id": "edge-key-v1",
        "is_replayed": True,
    }
    res_batch = client.post("/v1/telemetry/batch", json=batch_body)
    assert res_batch.status_code == 500
    assert res_batch.json()["code"] == "PUBLISHER_UNAVAILABLE"

    # Batch with is_replayed=True (non-fault)
    ok_frame = dict(frame, plant_id="P1")
    ok_batch_body = {
        "plant_id": "P1",
        "regulator_id": "R1",
        "sensor_id": "S1",
        "batch_id": "B-OK-1",
        "frames": [ok_frame],
        "hmac_signature": "valid-sig",
        "key_id": "edge-key-v1",
        "is_replayed": True,
    }
    res_ok_batch = client.post("/v1/telemetry/batch", json=ok_batch_body)
    assert res_ok_batch.status_code == 200
    assert res_ok_batch.json()["is_replayed"] is True
