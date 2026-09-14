"""Unit tests for observability dashboard domain exceptions."""

from __future__ import annotations

import pytest

from src.modules.observability_dashboard.domain.exceptions import (
    AlertDispatchError,
    DashboardDomainError,
    DispatchTimeoutError,
    IncidentNotFoundError,
    InternalServiceError,
    InvalidFilterError,
    InvalidPayloadError,
    ResourceNotFoundError,
    StorageUnavailableError,
)


def test_domain_exceptions_inheritance_and_messages() -> None:
    """[US-4][AC-4.1][AC-4.2][AC-4.3] Verify domain exceptions inherit from DashboardDomainError."""
    exc = InvalidPayloadError("Payload is empty")
    assert isinstance(exc, DashboardDomainError)
    assert str(exc) == "Payload is empty"

    filter_exc = InvalidFilterError("Limit out of bounds")
    assert isinstance(filter_exc, DashboardDomainError)

    res_exc = ResourceNotFoundError("Regulator not found")
    assert isinstance(res_exc, DashboardDomainError)

    inc_exc = IncidentNotFoundError("Incident not found")
    assert isinstance(inc_exc, DashboardDomainError)

    disp_exc = AlertDispatchError("Dispatch failed")
    assert isinstance(disp_exc, DashboardDomainError)

    timeout_exc = DispatchTimeoutError("Timeout exceeded")
    assert isinstance(timeout_exc, DashboardDomainError)

    storage_exc = StorageUnavailableError("Storage timeout")
    assert isinstance(storage_exc, DashboardDomainError)

    internal_exc = InternalServiceError("Unexpected error")
    assert isinstance(internal_exc, DashboardDomainError)
