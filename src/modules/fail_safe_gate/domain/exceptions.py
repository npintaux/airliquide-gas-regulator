"""Domain exception taxonomy for the Fail-Safe Gate subsystem."""

from __future__ import annotations

from typing import Any


class FailSafeGateError(Exception):
    """Base class for all domain exceptions in fail-safe gate."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class InvalidPayloadError(FailSafeGateError):
    """Raised when an incoming request payload is malformed or invalid."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="INVALID_PAYLOAD",
            status_code=400,
            details=details,
        )


class SafetyEnvelopeViolation(FailSafeGateError):
    """Raised when gas flow rate violates static safety envelope bounds."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="ENVELOPE_TRIP",
            status_code=422,
            details=details,
        )


class CorrelationDriftViolation(FailSafeGateError):
    """Raised when dynamic pressure-temperature correlation residual exceeds tolerance."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="CORRELATION_DRIFT",
            status_code=422,
            details=details,
        )


class SensorFreezeDetected(FailSafeGateError):
    """Raised when telemetry signal variance is zero or heartbeat interval is missed."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="SENSOR_FROZEN",
            status_code=422,
            details=details,
        )


class ActuationInterlockConflict(FailSafeGateError):
    """Raised when an actuation command conflicts with current physical interlocks."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="INTERLOCK_CONFLICT",
            status_code=422,
            details=details,
        )


class HardwareCommunicationError(FailSafeGateError):
    """Raised when hardware actuator communication or fieldbus fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="ACTUATOR_COMM_ERROR",
            status_code=500,
            details=details,
        )


class InternalServiceError(FailSafeGateError):
    """Raised on unhandled internal domain failure or execution error."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="INTERNAL_ERROR",
            status_code=500,
            details=details,
        )
