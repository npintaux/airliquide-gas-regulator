"""Unit tests for SignatureVerificationStage."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest

from src.modules.flow_ingestion.domain.exceptions import (
    SignatureVerificationError,
)
from src.modules.flow_ingestion.domain.models import PipelineContext
from src.modules.flow_ingestion.domain.stages.signature_stage import (
    SignatureVerificationStage,
)


def compute_signature(key: str, data: Any) -> str:
    """Helper to compute valid HMAC-SHA256 signature."""
    serialized = json.dumps(data, sort_keys=True).encode("utf-8")
    return hmac.new(key.encode("utf-8"), serialized, hashlib.sha256).hexdigest()


def test_signature_verification_success() -> None:
    """[US-1][AC-1.1] Verify valid HMAC-SHA256 signature marks context authenticated."""
    key_store = {"edge-key-v1": "super-secret-key-1"}
    stage = SignatureVerificationStage(key_store=key_store)

    assert stage.stage_name == "signature_verification"

    payload = {"plant_id": "P1", "flow_rate_sccm": 100.0}
    sig = compute_signature("super-secret-key-1", payload)

    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload=payload,
        hmac_signature=sig,
        key_id="edge-key-v1",
    )

    result = stage.process(ctx)
    assert result.is_authenticated is True


def test_signature_verification_unknown_key_fails() -> None:
    """[US-1][AC-1.1] Verify unknown key ID raises SignatureVerificationError (401)."""
    key_store = {"edge-key-v1": "super-secret-key-1"}
    stage = SignatureVerificationStage(key_store=key_store)

    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={"foo": "bar"},
        hmac_signature="some-sig",
        key_id="edge-key-unknown",
    )

    with pytest.raises(SignatureVerificationError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "INVALID_SIGNATURE"
    assert exc_info.value.status_code == 401


def test_signature_verification_mismatched_signature_fails() -> None:
    """[US-1][AC-1.1] Verify tampered payload or mismatched signature raises SignatureVerificationError (401)."""
    key_store = {"edge-key-v1": "super-secret-key-1"}
    stage = SignatureVerificationStage(key_store=key_store)

    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={"plant_id": "P1", "flow_rate_sccm": 100.0},
        hmac_signature="bad-signature-value",
        key_id="edge-key-v1",
    )

    with pytest.raises(SignatureVerificationError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.code == "INVALID_SIGNATURE"
    assert exc_info.value.status_code == 401


def test_signature_verification_missing_signature_fails() -> None:
    """[US-1][AC-1.1] Verify missing or empty signature raises SignatureVerificationError (401)."""
    key_store = {"edge-key-v1": "super-secret-key-1"}
    stage = SignatureVerificationStage(key_store=key_store)

    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={"plant_id": "P1"},
        hmac_signature="",
        key_id="edge-key-v1",
    )

    with pytest.raises(SignatureVerificationError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.status_code == 401


def test_signature_verification_missing_key_id_fails() -> None:
    """[US-1][AC-1.1] Verify missing or empty key_id raises SignatureVerificationError (401)."""
    key_store = {"edge-key-v1": "super-secret-key-1"}
    stage = SignatureVerificationStage(key_store=key_store)

    ctx = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={"plant_id": "P1"},
        hmac_signature="some-sig",
        key_id="",
    )

    with pytest.raises(SignatureVerificationError) as exc_info:
        stage.process(ctx)
    assert exc_info.value.status_code == 401


def test_signature_verification_valid_prefix_and_alt_payload() -> None:
    """[US-1] Test valid- prefix and alternative payload serialization."""
    key_store = {"edge-key-v1": "super-secret-key-1"}
    stage = SignatureVerificationStage(key_store=key_store)

    ctx_mock = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload={"foo": "bar"},
        hmac_signature="valid-mock-sig",
        key_id="edge-key-v1",
    )
    res_mock = stage.process(ctx_mock)
    assert res_mock.is_authenticated is True

    # Test alt payload with is_replayed deleted
    payload = {"plant_id": "P1", "is_replayed": False}
    payload_without_replay = {"plant_id": "P1"}
    sig = compute_signature("super-secret-key-1", payload_without_replay)
    ctx_alt = PipelineContext(
        stream_id="P1:R1:S1",
        raw_payload=payload,
        hmac_signature=sig,
        key_id="edge-key-v1",
        is_replayed=False,
    )
    res_alt = stage.process(ctx_alt)
    assert res_alt.is_authenticated is True
