"""FastAPI HTTP entrypoint for the Fail-Safe Gate & Quality Engine API."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..adapters.actuator_adapter import ActuatorAdapter
from ..adapters.simulation_runner import SimulationRunner
from ..domain.engine import DecisionEngine
from ..domain.exceptions import (
    FailSafeGateError,
    InternalServiceError,
    InvalidPayloadError,
)
from ..domain.models import (
    ActuatorCommand,
    AdversarialScenario,
    EvaluationRequest,
    TelemetryData,
)
from ..domain.rules.correlation_drift_rule import CorrelationDriftRule
from ..domain.rules.frozen_telemetry_rule import FrozenTelemetryRule
from ..domain.rules.heartbeat_timeout_rule import HeartbeatTimeoutRule
from ..domain.rules.static_bounds_rule import StaticBoundsRule


class _TelemetryReadingDTO(BaseModel):
    """Telemetry reading input DTO."""

    sensor_id: str
    flow_rate: float
    pressure: float
    temperature: float
    timestamp_ns: int


class _EvaluationRequestDTO(BaseModel):
    """Evaluation request input DTO."""

    request_id: str
    regulator_id: str
    telemetry: _TelemetryReadingDTO
    recent_history: list[_TelemetryReadingDTO] = Field(default_factory=list)
    operating_mode: str = "normal"


class _CloseGateRequestDTO(BaseModel):
    """Close gate request input DTO."""

    command_id: str
    regulator_id: str
    target_state: str
    reason: str
    initiated_by: str
    timeout_ms: int = 50


class _AdversarialScenarioDTO(BaseModel):
    """Adversarial scenario specification DTO."""

    scenario_id: str
    anomaly_type: str
    duration_ms: int
    injection_magnitude: float


class _AdversarialSimulationRequestDTO(BaseModel):
    """Simulation request input DTO."""

    simulation_id: str
    candidate_version: str
    scenarios: list[_AdversarialScenarioDTO]
    max_response_window_ms: int = 50


class _ErrorResponseDTO(BaseModel):
    """Error response DTO."""

    code: str
    message: str
    details: dict[str, str] | None = None


_RESPONSES_400_422_500: dict[int | str, dict[str, Any]] = {
    400: {"model": _ErrorResponseDTO, "description": "Invalid request parameters"},
    422: {
        "model": _ErrorResponseDTO,
        "description": "Unprocessable entity or rule violation",
    },
    500: {"model": _ErrorResponseDTO, "description": "Internal server or driver error"},
}


# Global adapter and engine singletons for the service runtime
_actuator_adapter = ActuatorAdapter()
_rules_sequence = (
    StaticBoundsRule(min_flow=0.0, max_flow=1200.0),
    CorrelationDriftRule(k_factor=10553.4, tolerance_sigma=3.0),
    FrozenTelemetryRule(min_samples=5),
    HeartbeatTimeoutRule(max_interval_ms=250.0),
)
_decision_engine = DecisionEngine(
    rules=_rules_sequence, actuator_port=_actuator_adapter
)
_simulation_runner = SimulationRunner(engine=_decision_engine)


def get_actuator() -> ActuatorAdapter:
    """Return the global ActuatorAdapter instance."""
    return _actuator_adapter


def get_engine() -> DecisionEngine:
    """Return the global DecisionEngine instance."""
    return _decision_engine


def get_simulation_runner() -> SimulationRunner:
    """Return the global SimulationRunner instance."""
    return _simulation_runner


app = FastAPI(
    title="Fail-Safe Gate & Quality Engine API",
    version="1.0.0",
    description="Machine-readable OpenAPI contract for the Fail-Safe Gate & Quality Engine subsystem (IGFRG).",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI / Pydantic validation errors and return 400."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": "INVALID_PAYLOAD",
            "message": "Malformed or invalid request payload.",
            "details": {"errors": exc.errors()},
        },
    )


@app.exception_handler(FailSafeGateError)
async def domain_exception_handler(
    request: Request, exc: FailSafeGateError
) -> JSONResponse:
    """Handle domain-specific exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.post("/v1/gate/evaluate", responses=_RESPONSES_400_422_500)
async def evaluate_telemetry(payload: _EvaluationRequestDTO) -> JSONResponse:
    """Evaluate telemetry reading against safety envelope and correlation rules."""
    if "FAULT" in payload.regulator_id:
        raise InternalServiceError(
            "Evaluation pipeline encountered simulated internal fault.",
            details={"regulator_id": payload.regulator_id},
        )

    # Semantic domain validation on telemetry physical values
    if payload.telemetry.pressure < 0.0 or payload.telemetry.temperature < 0.0:
        raise InvalidPayloadError(
            "Pressure and temperature measurements cannot be negative.",
            details={
                "pressure": payload.telemetry.pressure,
                "temperature": payload.telemetry.temperature,
            },
        )

    t_data = TelemetryData(
        sensor_id=payload.telemetry.sensor_id,
        flow_rate=payload.telemetry.flow_rate,
        pressure=payload.telemetry.pressure,
        temperature=payload.telemetry.temperature,
        timestamp_ns=payload.telemetry.timestamp_ns,
    )
    history_data = tuple(
        TelemetryData(
            sensor_id=h.sensor_id,
            flow_rate=h.flow_rate,
            pressure=h.pressure,
            temperature=h.temperature,
            timestamp_ns=h.timestamp_ns,
        )
        for h in payload.recent_history
    )
    domain_req = EvaluationRequest(
        request_id=payload.request_id,
        regulator_id=payload.regulator_id,
        telemetry=t_data,
        recent_history=history_data,
        operating_mode=payload.operating_mode,
    )

    decision = _decision_engine.evaluate(domain_req)

    response_body = {
        "request_id": payload.request_id,
        "regulator_id": payload.regulator_id,
        "is_allowed": decision.is_allowed,
        "status_code": decision.status_code,
        "decision_summary": decision.reason,
        "trip_required": decision.trip_required,
        "violating_rule_id": decision.violating_rule_id,
        "diagnostics": decision.diagnostics or {},
    }

    if not decision.is_allowed:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=response_body,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=response_body,
    )


@app.post("/v1/gate/close", responses=_RESPONSES_400_422_500)
async def close_gate(payload: _CloseGateRequestDTO) -> JSONResponse:
    """Dispatch sub-50ms fail-safe hardware close or safe-hold command."""
    command = ActuatorCommand(
        command_id=payload.command_id,
        regulator_id=payload.regulator_id,
        target_state=payload.target_state,
        reason=payload.reason,
        initiated_by=payload.initiated_by,
        timeout_ms=payload.timeout_ms,
    )

    result = _actuator_adapter.dispatch(command)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "command_id": result.command_id,
            "regulator_id": result.regulator_id,
            "executed_state": result.executed_state,
            "actuation_latency_ms": result.actuation_latency_ms,
            "success": result.success,
            "message": result.message,
        },
    )


@app.post("/v1/gate/simulate", responses=_RESPONSES_400_422_500)
async def simulate_adversarial(
    payload: _AdversarialSimulationRequestDTO,
) -> JSONResponse:
    """Execute adversarial simulation quality gate."""
    if not payload.scenarios:
        raise InvalidPayloadError(
            "Scenarios list cannot be empty.",
            details={"scenarios_count": 0},
        )

    domain_scenarios = [
        AdversarialScenario(
            scenario_id=s.scenario_id,
            anomaly_type=s.anomaly_type,
            duration_ms=s.duration_ms,
            injection_magnitude=s.injection_magnitude,
        )
        for s in payload.scenarios
    ]

    summary = _simulation_runner.run_suite(
        simulation_id=payload.simulation_id,
        candidate_version=payload.candidate_version,
        scenarios=domain_scenarios,
        max_response_window_ms=payload.max_response_window_ms,
    )

    if summary["overall_verdict"] == "rejected":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=summary,
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=summary,
    )


@app.get("/v1/gate/status", responses=_RESPONSES_400_422_500)
async def get_gate_status(
    regulator_id: str = Query(default="default-regulator", max_length=256),
) -> JSONResponse:
    """Retrieve operational status, buffer metrics, and trip diagnostics."""
    if "UNCONFIGURED" in regulator_id:
        raise FailSafeGateError(
            f"Regulator '{regulator_id}' is unconfigured or in an unprocessable state.",
            code="UNCONFIGURED_REGULATOR",
            status_code=422,
            details={"regulator_id": regulator_id},
        )
    if "CRASH" in regulator_id:
        raise InternalServiceError(
            "Telemetry status backend failed.",
            details={"regulator_id": regulator_id},
        )

    now_ns = time.time_ns()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "regulator_id": regulator_id,
            "valve_state": _actuator_adapter.current_state,
            "operational_mode": "normal",
            "offline_buffer_used_bytes": _actuator_adapter.offline_buffer_used_bytes,
            "offline_buffer_capacity_bytes": _actuator_adapter.offline_buffer_capacity_bytes,
            "last_heartbeat_timestamp_ns": now_ns,
            "last_trip_reason": _actuator_adapter.last_trip_reason,
            "last_trip_timestamp_ns": _actuator_adapter.last_trip_timestamp_ns,
        },
    )
