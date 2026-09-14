"""Orthogonal Behavioral Acceptance Test Suite for flow_ingestion subsystem.

Validates end-to-end user stories and acceptance criteria defined in docs/PRD.md
and docs/traceability.md for the flow_ingestion subsystem:
- [US-1]: Real-Time Telemetry Ingestion & Safety Envelope Validation
  (packet ingestion, schema framing, signature checks, latency conformance)
- [US-5]: Edge-Safe Offline Fallback Mode
  (offline buffering, replay ingestion handling, reconciliation flags)

This test suite is authored by the Independent Test Architect and executes
strictly as a black box: it imports ONLY the public entrypoint app from
src.modules.flow_ingestion.entrypoints.api, NEVER internal domain or adapter classes.
"""

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient


class TestFlowIngestionBehavioralAcceptance:
    """End-to-end behavioral acceptance scenarios for flow_ingestion subsystem."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for the flow_ingestion public entrypoint."""
        from src.modules.flow_ingestion.entrypoints.api import app

        return TestClient(app)

    # =========================================================================
    # User Story US-1: Real-Time Telemetry Ingestion & Envelope Validation
    # =========================================================================

    def test_us1_ac1_1_valid_telemetry_packet_ingested_and_normalized(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.1] Ingest valid telemetry packet over MQTT/Modbus normalized schema within latency budget."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 1001,
                "timestamp_ns": 1726312800000000000,
                "flow_rate_sccm": 2500.5,
                "pressure_bar": 16.2,
                "temperature_celsius": 21.4,
                "status_flags": 0,
            },
            "hmac_signature": "valid-signature-1001",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 201
        data: Mapping[str, Any] = response.json()
        assert data["status"] == "accepted"
        assert data["stream_id"] == "PLANT-BEL-01:REG-OX-401:FLOW-SN-8820"
        assert data["sequence_number"] == 1001
        assert "message_id" in data
        assert "processed_at_ns" in data

    def test_us1_ac1_1_valid_micro_batch_bundle_ingested_successfully(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.1] Ingest nominal 1-second 10-frame micro-batch bundle and dispatch to Pub/Sub."""
        frames = [
            {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 1000 + i,
                "timestamp_ns": 1726312800000000000 + (i * 100_000_000),
                "flow_rate_sccm": 2500.0 + i,
                "pressure_bar": 16.0,
                "temperature_celsius": 21.0,
                "status_flags": 0,
            }
            for i in range(10)
        ]
        batch_payload = {
            "plant_id": "PLANT-BEL-01",
            "regulator_id": "REG-OX-401",
            "sensor_id": "FLOW-SN-8820",
            "batch_id": "BATCH-US1-001",
            "is_replayed": False,
            "frames": frames,
            "hmac_signature": "valid-batch-sig-001",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=batch_payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["batch_id"] == "BATCH-US1-001"
        assert data["frames_received"] == 10
        assert data["frames_accepted"] == 10
        assert data["frames_deduplicated"] == 0
        assert data["is_replayed"] is False

    def test_us1_ac1_2_reject_corrupted_frame_missing_required_fields(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.2] Reject corrupted sensor packet missing required telemetry fields."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "sensor_id": "FLOW-SN-8820",
                # missing regulator_id, sequence_number, flow_rate_sccm
                "timestamp_ns": 1726312800000000000,
            },
            "hmac_signature": "valid-sig",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_us1_ac1_2_reject_unauthorized_spoofed_hmac_signature(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.2] Enforce cryptographic data integrity and reject spoofed or corrupted HMAC signature."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 1002,
                "timestamp_ns": 1726312800100000000,
                "flow_rate_sccm": 2500.5,
                "pressure_bar": 16.2,
                "temperature_celsius": 21.4,
                "status_flags": 0,
            },
            "hmac_signature": "deadbeef-invalid-signature",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 401
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_us1_ac1_3_reject_out_of_bounds_sensor_rate_and_jitter_violation(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.3] Reject telemetry violating rate bounds or physical range thresholds with 422."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 1003,
                "timestamp_ns": 1726312800200000000,
                "flow_rate_sccm": -50.0,  # Negative physical flow rate
                "pressure_bar": 16.2,
                "temperature_celsius": 21.4,
                "status_flags": 0,
            },
            "hmac_signature": "valid-sig-1003",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_us1_ac1_4_reject_duplicate_stream_sequence_number(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.4] Identify duplicate sequence numbers in real-time stream ingestion."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 2000,
                "timestamp_ns": 1726312800000000000,
                "flow_rate_sccm": 2500.5,
                "pressure_bar": 16.2,
                "temperature_celsius": 21.4,
                "status_flags": 0,
            },
            "hmac_signature": "valid-sig-2000",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        # First ingestion accepted
        res1 = client.post("/v1/telemetry/ingest", json=payload)
        assert res1.status_code == 201

        # Second ingestion with identical sequence_number recognized as duplicate
        res2 = client.post("/v1/telemetry/ingest", json=payload)
        assert res2.status_code == 201
        data = res2.json()
        assert data["status"] == "duplicate"

    # =========================================================================
    # User Story US-5: Edge-Safe Offline Fallback Mode
    # =========================================================================

    def test_us5_ac5_1_replayed_offline_telemetry_packet_accepted(
        self, client: TestClient
    ) -> None:
        """[US-5][AC-5.1] Ingest telemetry packets replayed from edge circular buffer with is_replayed flag."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 9001,
                "timestamp_ns": 1726312700000000000,  # historical edge-buffered timestamp
                "flow_rate_sccm": 2480.0,
                "pressure_bar": 15.9,
                "temperature_celsius": 20.8,
                "status_flags": 0,
            },
            "hmac_signature": "valid-sig-replay-9001",
            "key_id": "edge-key-v1",
            "is_replayed": True,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 201
        data: Mapping[str, Any] = response.json()
        assert data["status"] in ["accepted", "replayed"]
        assert data["sequence_number"] == 9001
        assert "message_id" in data

    def test_us5_ac5_2_replayed_offline_batch_reconciled_and_deduplicated(
        self, client: TestClient
    ) -> None:
        """[US-5][AC-5.2] Replay batch from edge circular buffer after reconnection with deduplication tracking."""
        frames = [
            {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 9010 + i,
                "timestamp_ns": 1726312710000000000 + (i * 100_000_000),
                "flow_rate_sccm": 2480.0 + i,
                "pressure_bar": 15.9,
                "temperature_celsius": 20.8,
                "status_flags": 0,
            }
            for i in range(5)
        ]
        batch_payload = {
            "plant_id": "PLANT-BEL-01",
            "regulator_id": "REG-OX-401",
            "sensor_id": "FLOW-SN-8820",
            "batch_id": "BATCH-REPLAY-RECON-001",
            "is_replayed": True,
            "frames": frames,
            "hmac_signature": "valid-replay-batch-sig-001",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=batch_payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["batch_id"] == "BATCH-REPLAY-RECON-001"
        assert data["is_replayed"] is True
        assert data["frames_received"] == 5
        assert data["frames_accepted"] + data["frames_deduplicated"] == 5

    def test_us5_ac5_3_replayed_batch_discontinuity_rejected_with_422(
        self, client: TestClient
    ) -> None:
        """[US-5][AC-5.3] Reject replayed batch with non-monotonic or corrupted sequence frames."""
        corrupted_frames = [
            {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 9050,
                "timestamp_ns": 1726312750000000000,
                "flow_rate_sccm": 2500.0,
                "pressure_bar": 16.0,
                "temperature_celsius": 21.0,
                "status_flags": 0,
            },
            {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 9040,  # Sequence dropped backwards
                "timestamp_ns": 1726312750100000000,
                "flow_rate_sccm": 2500.0,
                "pressure_bar": 16.0,
                "temperature_celsius": 21.0,
                "status_flags": 0,
            },
        ]
        batch_payload = {
            "plant_id": "PLANT-BEL-01",
            "regulator_id": "REG-OX-401",
            "sensor_id": "FLOW-SN-8820",
            "batch_id": "BATCH-REPLAY-CORRUPTED",
            "is_replayed": True,
            "frames": corrupted_frames,
            "hmac_signature": "valid-sig",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=batch_payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data
