"""Orthogonal Contract Verification Test Suite for flow_ingestion subsystem.

Validates that HTTP entrypoints strictly adhere to the frozen openapi.yaml
interface contract, including HTTP status codes, routing/versioning,
payload schemas, error structures, and fault isolation.

This suite is authored by the Independent Test Architect and executes
strictly as a black box: it imports ONLY the public entrypoint app from
src.modules.flow_ingestion.entrypoints.api, NEVER internal domain or adapter classes.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

FROZEN_CONTRACT = Path("src/modules/flow_ingestion/openapi.yaml")


class TestFlowIngestionContractConformance:
    """Black-box OpenAPI contract compliance test suite for flow_ingestion."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for the flow_ingestion public entrypoint."""
        from src.modules.flow_ingestion.entrypoints.api import app

        return TestClient(app)

    @pytest.fixture
    def frozen_contract(self) -> Mapping[str, Any]:
        """Load the frozen openapi.yaml that the running service must satisfy."""
        return yaml.safe_load(FROZEN_CONTRACT.read_text(encoding="utf-8"))

    def test_live_app_conforms_to_frozen_contract(
        self, client: TestClient, frozen_contract: Mapping[str, Any]
    ) -> None:
        """Verify every path/method/status in the frozen contract is served by the live app."""
        live: Mapping[str, Any] = client.get("/openapi.json").json()
        live_paths: Mapping[str, Any] = live.get("paths", {})

        for path, frozen_ops in frozen_contract.get("paths", {}).items():
            assert path in live_paths, f"Frozen contract path '{path}' is not served by the app."
            for method, frozen_op in frozen_ops.items():
                op = f"{method.upper()} {path}"
                live_op = live_paths[path].get(method)
                assert live_op is not None, f"Frozen operation '{op}' is missing."
                live_codes = {str(c) for c in live_op.get("responses", {})}
                for status_code in frozen_op.get("responses", {}):
                    assert str(status_code) in live_codes, (
                        f"Frozen status '{status_code}' for '{op}' is not served."
                    )

    def test_openapi_spec_route_versioning(self, frozen_contract: Mapping[str, Any]) -> None:
        """Verify that all exposed paths are versioned (e.g., /v1/...)."""
        for path in frozen_contract.get("paths", {}):
            assert path.startswith("/v"), f"Path '{path}' violates /v<N>/ versioning contract."

    # --- /v1/telemetry/ingest Contract Conformance ---

    def test_ingest_telemetry_success_returns_201_and_schema(self, client: TestClient) -> None:
        """Assert status_code 201 on valid single telemetry packet ingestion."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 10452,
                "timestamp_ns": 1726312800000000000,
                "flow_rate_sccm": 2500.5,
                "pressure_bar": 16.2,
                "temperature_celsius": 21.4,
                "status_flags": 0,
            },
            "hmac_signature": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 201
        assert response.headers["content-type"].startswith("application/json")
        data: Mapping[str, Any] = response.json()
        assert data["status"] in ["accepted", "duplicate", "replayed"]
        assert "message_id" in data
        assert "stream_id" in data
        assert "sequence_number" in data
        assert "processed_at_ns" in data

    def test_ingest_telemetry_malformed_payload_returns_400(self, client: TestClient) -> None:
        """Assert status_code 400 on malformed syntax or missing required fields."""
        payload = {"invalid_payload": True}
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_ingest_telemetry_invalid_signature_returns_401(self, client: TestClient) -> None:
        """Assert status_code 401 when HMAC signature fails verification."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 10453,
                "timestamp_ns": 1726312800100000000,
                "flow_rate_sccm": 2500.5,
                "pressure_bar": 16.2,
                "temperature_celsius": 21.4,
                "status_flags": 0,
            },
            "hmac_signature": "0000000000000000000000000000000000000000000000000000000000000000",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 401
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_ingest_telemetry_rate_violation_returns_422(self, client: TestClient) -> None:
        """Assert status_code 422 on domain validation failure or rate/jitter violation."""
        payload = {
            "frame": {
                "plant_id": "PLANT-BEL-01",
                "regulator_id": "REG-OX-401",
                "sensor_id": "FLOW-SN-8820",
                "sequence_number": 10454,
                "timestamp_ns": 1726312800200000000,
                "flow_rate_sccm": -999.0,  # Negative flow rate violation
                "pressure_bar": 16.2,
                "temperature_celsius": 21.4,
                "status_flags": 0,
            },
            "hmac_signature": "valid-sig-mock",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_ingest_telemetry_server_error_returns_500(self, client: TestClient) -> None:
        """Assert status_code 500 when downstream publisher fails or unhandled server error occurs."""
        payload = {
            "frame": {
                "plant_id": "TRIGGER-FAULT",
                "regulator_id": "REG-FAULT",
                "sensor_id": "SN-FAULT",
                "sequence_number": 1,
                "timestamp_ns": 1726312800000000000,
                "flow_rate_sccm": 100.0,
                "pressure_bar": 10.0,
                "temperature_celsius": 20.0,
                "status_flags": 0,
            },
            "hmac_signature": "valid-sig",
            "key_id": "edge-key-v1",
            "is_replayed": False,
        }
        response = client.post("/v1/telemetry/ingest", json=payload)
        assert response.status_code == 500
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data
        assert "Traceback" not in response.text

    # --- /v1/telemetry/batch Contract Conformance ---

    def test_ingest_batch_success_returns_200_and_schema(self, client: TestClient) -> None:
        """Assert status_code 200 on valid batch telemetry ingestion."""
        payload = {
            "plant_id": "PLANT-BEL-01",
            "regulator_id": "REG-OX-401",
            "sensor_id": "FLOW-SN-8820",
            "batch_id": "BATCH-20260914-1018-001",
            "is_replayed": False,
            "frames": [
                {
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
            ],
            "hmac_signature": "a8f5f167f44f4964e6c998dee827110c4d474581f19d29efd3a0c4f87a8a1eb3",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=payload)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data: Mapping[str, Any] = response.json()
        assert data["batch_id"] == "BATCH-20260914-1018-001"
        assert "stream_id" in data
        assert "frames_received" in data
        assert "frames_accepted" in data
        assert "frames_deduplicated" in data
        assert "is_replayed" in data
        assert "processed_at_ns" in data

    def test_ingest_batch_empty_frames_returns_400(self, client: TestClient) -> None:
        """Assert status_code 400 on malformed batch or empty frames array."""
        payload = {
            "plant_id": "PLANT-BEL-01",
            "regulator_id": "REG-OX-401",
            "sensor_id": "FLOW-SN-8820",
            "batch_id": "BATCH-EMPTY",
            "is_replayed": False,
            "frames": [],
            "hmac_signature": "a8f5f167f44f4964e6c998dee827110c4d474581f19d29efd3a0c4f87a8a1eb3",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=payload)
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_ingest_batch_invalid_signature_returns_401(self, client: TestClient) -> None:
        """Assert status_code 401 when batch HMAC signature is invalid."""
        payload = {
            "plant_id": "PLANT-BEL-01",
            "regulator_id": "REG-OX-401",
            "sensor_id": "FLOW-SN-8820",
            "batch_id": "BATCH-BAD-SIG",
            "is_replayed": False,
            "frames": [
                {
                    "plant_id": "PLANT-BEL-01",
                    "regulator_id": "REG-OX-401",
                    "sensor_id": "FLOW-SN-8820",
                    "sequence_number": 1,
                    "timestamp_ns": 1726312800000000000,
                    "flow_rate_sccm": 2500.5,
                    "pressure_bar": 16.2,
                    "temperature_celsius": 21.4,
                    "status_flags": 0,
                }
            ],
            "hmac_signature": "invalid-signature",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=payload)
        assert response.status_code == 401
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_ingest_batch_sequence_discontinuity_returns_422(self, client: TestClient) -> None:
        """Assert status_code 422 on batch sequence discontinuity or out-of-order frames."""
        payload = {
            "plant_id": "PLANT-BEL-01",
            "regulator_id": "REG-OX-401",
            "sensor_id": "FLOW-SN-8820",
            "batch_id": "BATCH-DISCONTINUOUS",
            "is_replayed": False,
            "frames": [
                {
                    "plant_id": "PLANT-BEL-01",
                    "regulator_id": "REG-OX-401",
                    "sensor_id": "FLOW-SN-8820",
                    "sequence_number": 10,
                    "timestamp_ns": 1726312800100000000,
                    "flow_rate_sccm": 2500.5,
                    "pressure_bar": 16.2,
                    "temperature_celsius": 21.4,
                    "status_flags": 0,
                },
                {
                    "plant_id": "PLANT-BEL-01",
                    "regulator_id": "REG-OX-401",
                    "sensor_id": "FLOW-SN-8820",
                    "sequence_number": 5,  # Regression in sequence
                    "timestamp_ns": 1726312800200000000,
                    "flow_rate_sccm": 2500.5,
                    "pressure_bar": 16.2,
                    "temperature_celsius": 21.4,
                    "status_flags": 0,
                },
            ],
            "hmac_signature": "valid-sig",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_ingest_batch_server_error_returns_500(self, client: TestClient) -> None:
        """Assert status_code 500 when batch ingestion encounters internal failure."""
        payload = {
            "plant_id": "TRIGGER-FAULT",
            "regulator_id": "REG-FAULT",
            "sensor_id": "SN-FAULT",
            "batch_id": "BATCH-FAULT",
            "is_replayed": False,
            "frames": [
                {
                    "plant_id": "TRIGGER-FAULT",
                    "regulator_id": "REG-FAULT",
                    "sensor_id": "SN-FAULT",
                    "sequence_number": 1,
                    "timestamp_ns": 1726312800000000000,
                    "flow_rate_sccm": 100.0,
                    "pressure_bar": 10.0,
                    "temperature_celsius": 20.0,
                    "status_flags": 0,
                }
            ],
            "hmac_signature": "valid-sig",
            "key_id": "edge-key-v1",
        }
        response = client.post("/v1/telemetry/batch", json=payload)
        assert response.status_code == 500
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    # --- /v1/health Contract Conformance ---

    def test_health_check_success_returns_200(self, client: TestClient) -> None:
        """Assert status_code 200 when subsystem health check succeeds."""
        response = client.get("/v1/health")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data: Mapping[str, Any] = response.json()
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert data["subsystem"] == "flow_ingestion"
        assert "version" in data
        assert "timestamp_ns" in data
        assert "pubsub_connected" in data
        assert "key_cache_valid" in data

    def test_health_check_invalid_params_returns_400(self, client: TestClient) -> None:
        """Assert status_code 400 when invalid query parameters are supplied to health endpoint."""
        response = client.get("/v1/health?invalid_param=unknown")
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_health_check_degraded_returns_422(self, client: TestClient) -> None:
        """Assert status_code 422 when subsystem is in degraded or unserviceable state."""
        response = client.get("/v1/health?check_strict=true&simulate_degraded=true")
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_health_check_failure_returns_500(self, client: TestClient) -> None:
        """Assert status_code 500 when health probe fails critically."""
        response = client.get("/v1/health?simulate_fatal=true")
        assert response.status_code == 500
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data
