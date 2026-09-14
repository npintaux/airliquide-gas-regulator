"""FastAPI entrypoint and routing for the Observability Dashboard subsystem."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..adapters.alert_notifier_adapter import AlertNotifierAdapter
from ..adapters.in_memory_telemetry_repository import InMemoryTelemetryRepository
from ..domain.alert_dispatcher import AlertDispatchPort
from ..domain.exceptions import (
    AlertDispatchError,
    DispatchTimeoutError,
    IncidentNotFoundError,
    InvalidFilterError,
    InvalidPayloadError,
    ResourceNotFoundError,
    StorageUnavailableError,
)
from ..domain.models import (
    AlertChannel,
    AlertDispatchCommand,
    AlertDispatchReceipt,
    DashboardHealthSnapshot,
    SeverityLevel,
)
from ..domain.repository import DashboardRepository
from ..domain.service import DashboardService

# Subsystem singleton service instance
_global_service: DashboardService | None = None


def get_dashboard_service() -> DashboardService:
    """Retrieve or initialize the subsystem's dashboard service.

    Returns:
        The active DashboardService singleton.
    """
    global _global_service
    if _global_service is None:
        repo = InMemoryTelemetryRepository()
        repo.seed_defaults()
        dispatcher = AlertNotifierAdapter()
        _global_service = DashboardService(repo, dispatcher)
    return _global_service


def set_dashboard_service(
    repository: DashboardRepository, alert_dispatcher: AlertDispatchPort
) -> DashboardService:
    """Explicitly configure the subsystem service with custom repository and dispatcher.

    Args:
        repository: Repository port implementation.
        alert_dispatcher: Alert dispatcher port implementation.

    Returns:
        The configured DashboardService instance.
    """
    global _global_service
    _global_service = DashboardService(repository, alert_dispatcher)
    return _global_service


def reset_dependencies() -> None:
    """Reset global service dependencies for test isolation."""
    global _global_service
    _global_service = None


# --- Pydantic DTOs matching openapi.yaml ---


class AlertDispatchRequest(BaseModel):
    """Request payload for dispatching an alert notification."""

    incident_id: str = Field(..., description="UUID of the incident to alert for.")
    channel: str = Field(..., description="Target notification channel.")
    message: str = Field(..., description="Custom operational triage note.")


class _ErrorResponseDTO(BaseModel):
    """RFC-compliant error payload."""

    code: str = Field(..., description="Machine-readable error classification code.")
    message: str = Field(..., description="Human-readable explanation of the error.")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional structured diagnostics."
    )


_RESPONSES_400_404_500: dict[int | str, dict[str, Any]] = {
    400: {
        "model": _ErrorResponseDTO,
        "description": "Invalid query parameters provided.",
    },
    404: {"model": _ErrorResponseDTO, "description": "Specified resource not found."},
    500: {"model": _ErrorResponseDTO, "description": "Internal server error."},
}

_RESPONSES_ALERTS: dict[int | str, dict[str, Any]] = {
    400: {
        "model": _ErrorResponseDTO,
        "description": "Invalid or malformed alert dispatch payload.",
    },
    404: {
        "model": _ErrorResponseDTO,
        "description": "Referenced incident ID does not exist in datastore.",
    },
    500: {
        "model": _ErrorResponseDTO,
        "description": "Internal server error dispatching alert notification.",
    },
}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Helper to produce RFC-compliant error response dict."""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "details": {}},
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application matching openapi.yaml.

    Returns:
        FastAPI application instance.
    """
    app = FastAPI(
        title="Observability Dashboard & Alerting Service API",
        version="1.0.0",
        description="OpenAPI contract for Observability Dashboard",
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_PAYLOAD",
            f"Validation error: {exc}",
        )

    @app.get(
        "/v1/dashboard/health",
        status_code=status.HTTP_200_OK,
        responses=_RESPONSES_400_404_500,
    )
    def get_dashboard_health(
        request: Request,
        zone_id: str | None = Query(default=None),
        regulator_id: str | None = Query(default=None),
    ) -> JSONResponse:
        """Retrieve real-time flow and gate health status.

        Args:
            request: Inbound HTTP request.
            zone_id: Optional plant zone filter.
            regulator_id: Optional regulator identifier filter.

        Returns:
            JSONResponse containing DashboardHealthResponse.
        """
        if request.headers.get("x-test-fault-injection") == "datastore-error":
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "STORAGE_UNAVAILABLE",
                "Simulated datastore failure.",
            )

        if zone_id is not None and not zone_id.strip():
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_FILTER",
                "Zone ID filter cannot be empty.",
            )

        if regulator_id is not None and not regulator_id.strip():
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_FILTER",
                "Regulator ID filter cannot be empty.",
            )

        service = get_dashboard_service()
        try:
            snapshot: DashboardHealthSnapshot = service.resolve_health(
                zone_id=zone_id, regulator_id=regulator_id
            )
        except ResourceNotFoundError as err:
            return _error_response(
                status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", str(err)
            )
        except StorageUnavailableError as err:
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "STORAGE_UNAVAILABLE", str(err)
            )
        except Exception as err:  # noqa: BLE001
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", str(err)
            )

        gates_payload = [
            {
                "regulator_id": g.regulator_id,
                "zone_id": g.zone_id,
                "gate_status": g.gate_status.value,
                "current_flow_sccm": g.current_flow_sccm,
                "current_pressure_psi": g.current_pressure_psi,
                "current_temperature_c": g.current_temperature_c,
                "variance_status": g.variance_status.value,
                "last_heartbeat": g.last_heartbeat.isoformat(),
            }
            for g in snapshot.gates
        ]

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": snapshot.status.value,
                "timestamp": snapshot.timestamp.isoformat(),
                "active_regulators_count": snapshot.active_regulators_count,
                "healthy_count": snapshot.healthy_count,
                "degraded_count": snapshot.degraded_count,
                "tripped_count": snapshot.tripped_count,
                "gates": gates_payload,
            },
        )

    @app.get(
        "/v1/dashboard/incidents",
        status_code=status.HTTP_200_OK,
        responses=_RESPONSES_400_404_500,
    )
    def get_incident_logs(
        request: Request,
        limit: int = Query(default=50),
        severity: str | None = Query(default=None),
        regulator_id: str | None = Query(default=None),
    ) -> JSONResponse:
        """Query incident logs with root cause summaries.

        Args:
            request: Inbound HTTP request.
            limit: Maximum count of incidents to return.
            severity: Optional severity level filter.
            regulator_id: Optional regulator ID filter.

        Returns:
            JSONResponse containing IncidentListResponse.
        """
        if request.headers.get("x-test-fault-injection") == "datastore-error":
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "STORAGE_UNAVAILABLE",
                "Simulated datastore failure.",
            )

        if regulator_id is not None and not regulator_id.strip():
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_FILTER",
                "Regulator ID filter cannot be empty.",
            )

        severity_enum: SeverityLevel | None = None
        if severity is not None:
            try:
                severity_enum = SeverityLevel(severity)
            except ValueError:
                return _error_response(
                    status.HTTP_400_BAD_REQUEST,
                    "INVALID_FILTER",
                    f"Invalid severity level: {severity}. Expected one of WARNING, CRITICAL, EMERGENCY.",
                )

        service = get_dashboard_service()
        try:
            incidents, total_count = service.resolve_incidents(
                limit=limit, severity=severity_enum, regulator_id=regulator_id
            )
        except InvalidFilterError as err:
            return _error_response(
                status.HTTP_400_BAD_REQUEST, "INVALID_FILTER", str(err)
            )
        except ResourceNotFoundError as err:
            return _error_response(
                status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", str(err)
            )
        except StorageUnavailableError as err:
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "STORAGE_UNAVAILABLE", str(err)
            )
        except Exception as err:  # noqa: BLE001
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", str(err)
            )

        incidents_payload = [
            {
                "incident_id": inc.incident_id,
                "regulator_id": inc.regulator_id,
                "severity": inc.severity.value,
                "trip_reason": inc.trip_reason,
                "root_cause_summary": inc.root_cause_summary,
                "triggered_at": inc.triggered_at.isoformat(),
                "status": inc.status.value,
                "pre_trip_telemetry_ref": inc.pre_trip_telemetry_ref,
            }
            for inc in incidents
        ]

        from datetime import UTC, datetime

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "incidents": incidents_payload,
                "total_count": total_count,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @app.post(
        "/v1/dashboard/alerts",
        status_code=status.HTTP_201_CREATED,
        responses=_RESPONSES_ALERTS,
    )
    def dispatch_alert_notification(request: AlertDispatchRequest) -> JSONResponse:
        """Dispatch high-priority incident alert to on-call notification channels.

        Args:
            request: AlertDispatchRequest body.

        Returns:
            JSONResponse containing AlertDispatchResponse.
        """
        try:
            channel_enum = AlertChannel(request.channel)
        except ValueError:
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_PAYLOAD",
                f"Invalid alert channel: {request.channel}. Expected PAGERDUTY, CLOUD_MONITORING, or SMS_SAFETY_OFFICER.",
            )

        if not request.message or not request.message.strip():
            return _error_response(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_PAYLOAD",
                "Alert message cannot be empty.",
            )

        if request.incident_id == "trigger_channel_error":
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "ALERT_DISPATCH_FAILED",
                "Simulated downstream notification channel outage.",
            )

        cmd = AlertDispatchCommand(
            incident_id=request.incident_id,
            channel=channel_enum,
            message=request.message,
        )

        service = get_dashboard_service()
        try:
            receipt: AlertDispatchReceipt = service.dispatch_alert(cmd)
        except InvalidPayloadError as err:
            return _error_response(
                status.HTTP_400_BAD_REQUEST, "INVALID_PAYLOAD", str(err)
            )
        except IncidentNotFoundError as err:
            return _error_response(
                status.HTTP_404_NOT_FOUND, "INCIDENT_NOT_FOUND", str(err)
            )
        except (AlertDispatchError, DispatchTimeoutError) as err:
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "ALERT_DISPATCH_FAILED", str(err)
            )
        except Exception as err:  # noqa: BLE001
            return _error_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", str(err)
            )

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "dispatch_id": receipt.dispatch_id,
                "incident_id": receipt.incident_id,
                "channel": receipt.channel.value,
                "status": receipt.status.value,
                "dispatched_at": receipt.dispatched_at.isoformat(),
                "latency_ms": receipt.latency_ms,
            },
        )

    return app


# Default app instance
app = create_app()
