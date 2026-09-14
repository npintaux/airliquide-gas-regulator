"""Domain exceptions for the Observability Dashboard subsystem."""

from __future__ import annotations


class DashboardDomainError(Exception):
    """Base exception for all domain errors within observability dashboard."""


class InvalidPayloadError(DashboardDomainError):
    """Raised when request payload is empty, invalid, or malformed."""


class InvalidFilterError(DashboardDomainError):
    """Raised when query parameters or filter criteria are invalid or out of bounds."""


class ResourceNotFoundError(DashboardDomainError):
    """Raised when a queried regulator or zone resource cannot be found."""


class IncidentNotFoundError(DashboardDomainError):
    """Raised when a referenced incident ID is not found in the datastore."""


class AlertDispatchError(DashboardDomainError):
    """Raised when an alert notification dispatch fails downstream."""


class DispatchTimeoutError(DashboardDomainError):
    """Raised when alert dispatch exceeds the allowed SLA latency budget."""


class StorageUnavailableError(DashboardDomainError):
    """Raised when datastore or telemetry storage is unavailable or drops connection."""


class InternalServiceError(DashboardDomainError):
    """Raised when an unexpected internal domain or processing error occurs."""
