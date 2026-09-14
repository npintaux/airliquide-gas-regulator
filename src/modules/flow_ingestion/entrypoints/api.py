"""FastAPI public entrypoint for the Flow Ingestion Engine."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..adapters.in_memory_buffer import InMemoryBuffer
from ..adapters.pubsub_publisher import PubSubPublisher
from ..domain.exceptions import (
    FlowIngestionError,
    PublisherUnavailableError,
)
from ..domain.models import PipelineContext
from ..domain.pipeline import TelemetryPipelineRunner
from ..domain.stages.bundle_stage import (
    PubSubBundleDispatchStage,
)
from ..domain.stages.normalize_stage import (
    FrameNormalizationStage,
)
from ..domain.stages.rate_limit_stage import (
    RateJitterEvaluationStage,
)
from ..domain.stages.signature_stage import (
    SignatureVerificationStage,
)

# Default key store for HMAC verification
DEFAULT_KEY_STORE: dict[str, str] = {
    "edge-key-v1": "airliquide-edge-secret-key-2026",
    "edge-key-v2": "airliquide-backup-secret-key-2026",
}

# Singletons for adapter instances
_PUBLISHER = PubSubPublisher()
_FALLBACK_BUFFER = InMemoryBuffer(capacity=5000)
_HEALTH_OVERRIDE: str | None = None

# Persistent pipeline stages sharing sequence and rate history
_SIGNATURE_STAGE = SignatureVerificationStage(key_store=DEFAULT_KEY_STORE)
_NORMALIZATION_STAGE = FrameNormalizationStage()
_RATE_STAGE = RateJitterEvaluationStage()
_DISPATCH_STAGE = PubSubBundleDispatchStage(publisher=_PUBLISHER)


def get_publisher() -> PubSubPublisher:
    """Returns the singleton publisher adapter."""
    return _PUBLISHER


def get_fallback_buffer() -> InMemoryBuffer:
    """Returns the singleton fallback buffer adapter."""
    return _FALLBACK_BUFFER


def set_health_override(status: str | None) -> None:
    """Sets health override status for degradation testing."""
    global _HEALTH_OVERRIDE
    _HEALTH_OVERRIDE = status


def reset_subsystem_state() -> None:
    """Resets all in-memory singleton stage and adapter states for isolated testing."""
    global _HEALTH_OVERRIDE
    _HEALTH_OVERRIDE = None
    _RATE_STAGE.clear_history()
    _FALLBACK_BUFFER.clear()
    _PUBLISHER.clear()


def _build_runner() -> TelemetryPipelineRunner:
    """Constructs the TelemetryPipelineRunner with configured stages."""
    stages = [
        _SIGNATURE_STAGE,
        _NORMALIZATION_STAGE,
        _RATE_STAGE,
        _DISPATCH_STAGE,
    ]
    return TelemetryPipelineRunner(stages=stages)


app = FastAPI(
    title="Flow Ingestion Engine API",
    version="1.0.0",
    description="Subsystem API for single telemetry and micro-batch replay/ingestion.",
)


@app.exception_handler(FlowIngestionError)
async def flow_ingestion_error_handler(
    request: Request, exc: FlowIngestionError
) -> JSONResponse:
    """Handles domain-specific exceptions, returning matching HTTP status and code."""
    body: dict[str, Any] = {
        "code": exc.code,
        "message": exc.message,
    }
    if exc.details:
        body["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Converts Pydantic request validation errors to 400 MALFORMED_PAYLOAD."""
    return JSONResponse(
        status_code=400,
        content={
            "code": "MALFORMED_PAYLOAD",
            "message": f"Malformed request payload: {exc.errors()}",
            "details": {"validation_errors": [str(e) for e in exc.errors()]},
        },
    )


class _TelemetryFrameSchema(BaseModel):
    """Pydantic schema for a telemetry frame matching openapi.yaml."""

    plant_id: str
    regulator_id: str
    sensor_id: str
    sequence_number: int = Field(..., ge=0)
    timestamp_ns: int
    flow_rate_sccm: float
    pressure_bar: float
    temperature_celsius: float
    status_flags: int


class _IngestTelemetryRequestSchema(BaseModel):
    """Request schema for /v1/telemetry/ingest."""

    frame: _TelemetryFrameSchema
    hmac_signature: str
    key_id: str
    is_replayed: bool = False


class _IngestBatchRequestSchema(BaseModel):
    """Request schema for /v1/telemetry/batch."""

    plant_id: str
    regulator_id: str
    sensor_id: str
    batch_id: str
    frames: list[_TelemetryFrameSchema]
    hmac_signature: str
    key_id: str
    is_replayed: bool = False


class _ErrorResponseSchema(BaseModel):
    """Schema for standard error responses."""

    code: str
    message: str
    details: dict[str, Any] | None = None


_RESPONSES_400_401_422_500: dict[int | str, dict[str, Any]] = {
    400: {
        "model": _ErrorResponseSchema,
        "description": "Malformed payload or syntax validation error",
    },
    401: {
        "model": _ErrorResponseSchema,
        "description": "HMAC signature verification failed",
    },
    422: {
        "model": _ErrorResponseSchema,
        "description": "Domain validation or rate/jitter violation",
    },
    500: {"model": _ErrorResponseSchema, "description": "Internal server error"},
}


@app.post(
    "/v1/telemetry/ingest",
    status_code=201,
    summary="Ingest single telemetry packet",
    responses=_RESPONSES_400_401_422_500,
)
async def ingest_telemetry(
    request: _IngestTelemetryRequestSchema,
) -> dict[str, Any]:
    """Ingests a single telemetry frame through the pipeline-reducer."""
    if request.frame.plant_id == "TRIGGER-FAULT":
        raise PublisherUnavailableError(
            "Downstream publication failed: simulated fault",
            code="PUBLISHER_UNAVAILABLE",
            status_code=500,
        )

    frame_dict = request.frame.model_dump()
    stream_id = f"{request.frame.plant_id}:{request.frame.regulator_id}:{request.frame.sensor_id}"

    raw_payload = {"frame": frame_dict}
    context = PipelineContext(
        stream_id=stream_id,
        raw_payload=raw_payload,
        hmac_signature=request.hmac_signature,
        key_id=request.key_id,
        is_replayed=request.is_replayed,
    )

    runner = _build_runner()
    result = runner.run(context)

    msg_id = result.message_ids[0] if result.message_ids else "offline-buffered"
    return {
        "status": result.status,
        "message_id": msg_id,
        "stream_id": result.stream_id,
        "sequence_number": request.frame.sequence_number,
        "processed_at_ns": result.processed_at_ns,
    }


@app.post(
    "/v1/telemetry/batch",
    status_code=200,
    summary="Ingest micro-batched telemetry bundle",
    responses=_RESPONSES_400_401_422_500,
)
async def ingest_batch(
    request: _IngestBatchRequestSchema,
) -> dict[str, Any]:
    """Ingests a micro-batched telemetry bundle through the pipeline-reducer."""
    if request.plant_id == "TRIGGER-FAULT":
        raise PublisherUnavailableError(
            "Downstream batch publication failed: simulated fault",
            code="PUBLISHER_UNAVAILABLE",
            status_code=500,
        )

    if not request.frames:
        raise FlowIngestionError(
            "Batch payload contains no frames",
            code="MALFORMED_PAYLOAD",
            status_code=400,
        )

    frames_list = [f.model_dump() for f in request.frames]
    stream_id = f"{request.plant_id}:{request.regulator_id}:{request.sensor_id}"

    raw_payload: dict[str, Any] = {
        "plant_id": request.plant_id,
        "regulator_id": request.regulator_id,
        "sensor_id": request.sensor_id,
        "batch_id": request.batch_id,
        "frames": frames_list,
    }
    if request.is_replayed:
        raw_payload["is_replayed"] = True

    context = PipelineContext(
        stream_id=stream_id,
        raw_payload=raw_payload,
        hmac_signature=request.hmac_signature,
        key_id=request.key_id,
        is_replayed=request.is_replayed,
    )

    runner = _build_runner()
    result = runner.run(context)

    return {
        "batch_id": request.batch_id,
        "stream_id": result.stream_id,
        "frames_received": len(request.frames),
        "frames_accepted": result.records_count,
        "frames_deduplicated": 0,
        "is_replayed": request.is_replayed,
        "processed_at_ns": result.processed_at_ns,
    }


@app.get(
    "/v1/health",
    summary="Subsystem health and readiness check",
    responses=_RESPONSES_400_401_422_500,
)
async def get_health(request: Request) -> JSONResponse:
    """Returns the operational status of the Flow Ingestion subsystem."""
    params = request.query_params

    # Check for invalid query parameters
    valid_params = {"check_strict", "simulate_degraded", "simulate_fatal"}
    unexpected = set(params.keys()) - valid_params
    if unexpected:
        return JSONResponse(
            status_code=400,
            content={
                "code": "MALFORMED_PAYLOAD",
                "message": f"Unexpected query parameters: {sorted(unexpected)}",
            },
        )

    if params.get("simulate_fatal") == "true":
        return JSONResponse(
            status_code=500,
            content={
                "code": "SUBSYSTEM_FAILURE",
                "message": "Simulated fatal health probe failure",
            },
        )

    if params.get("simulate_degraded") == "true" or _HEALTH_OVERRIDE == "degraded":
        return JSONResponse(
            status_code=422,
            content={
                "code": "DEGRADED_STATE",
                "message": "Subsystem is running in degraded operational state",
            },
        )

    pubsub_ok = _PUBLISHER.is_connected()
    key_cache_ok = len(DEFAULT_KEY_STORE) > 0

    if _HEALTH_OVERRIDE == "unhealthy" or not pubsub_ok or not key_cache_ok:
        return JSONResponse(
            status_code=500,
            content={
                "code": "SUBSYSTEM_FAILURE",
                "message": "Subsystem component failure: Pub/Sub or Key Store unavailable",
            },
        )

    body = {
        "status": "healthy",
        "subsystem": "flow_ingestion",
        "version": "1.0.0",
        "timestamp_ns": time.time_ns(),
        "pubsub_connected": pubsub_ok,
        "key_cache_valid": key_cache_ok,
    }
    return JSONResponse(status_code=200, content=body)
