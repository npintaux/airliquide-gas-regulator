"""Unit tests for repository and alert dispatch ports."""

from __future__ import annotations

import pytest

from src.modules.observability_dashboard.domain.alert_dispatcher import (
    AlertDispatchPort,
)
from src.modules.observability_dashboard.domain.models import (
    AlertDispatchCommand,
    AlertDispatchReceipt,
    IncidentRecord,
    RegulatorHealthRecord,
    SeverityLevel,
)
from src.modules.observability_dashboard.domain.repository import DashboardRepository


class DummyDashboardRepository(DashboardRepository):
    """Concrete repository dummy for testing port ABC."""

    def get_regulator_health(self, regulator_id: str) -> RegulatorHealthRecord | None:
        return None

    def list_regulator_health(
        self, zone_id: str | None = None, regulator_id: str | None = None
    ) -> list[RegulatorHealthRecord]:
        return []

    def list_incidents(
        self,
        limit: int = 50,
        severity: SeverityLevel | None = None,
        regulator_id: str | None = None,
    ) -> list[IncidentRecord]:
        return []

    def get_incident_by_id(self, incident_id: str) -> IncidentRecord | None:
        return None

    def check_zone_exists(self, zone_id: str) -> bool:
        return True

    def check_regulator_exists(self, regulator_id: str) -> bool:
        return True


class DummyAlertDispatchPort(AlertDispatchPort):
    """Concrete alert dispatch dummy for testing port ABC."""

    def dispatch_alert(self, command: AlertDispatchCommand) -> AlertDispatchReceipt:
        raise NotImplementedError


def test_repository_ports_abc() -> None:
    """[US-4][AC-4.1][AC-4.2][AC-4.3] Test repository ports cannot be instantiated directly."""
    with pytest.raises(TypeError):
        DashboardRepository()  # type: ignore[abstract]

    with pytest.raises(TypeError):
        AlertDispatchPort()  # type: ignore[abstract]

    repo = DummyDashboardRepository()
    assert repo.get_regulator_health("reg-1") is None
    assert repo.list_regulator_health() == []
    assert repo.list_incidents() == []
    assert repo.get_incident_by_id("inc-1") is None
    assert repo.check_zone_exists("zone-a") is True
    assert repo.check_regulator_exists("reg-1") is True
