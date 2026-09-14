"""Unit tests for AlertNotifierAdapter."""

from __future__ import annotations

import pytest

from src.modules.observability_dashboard.adapters.alert_notifier_adapter import (
    AlertNotifierAdapter,
)
from src.modules.observability_dashboard.domain.exceptions import AlertDispatchError
from src.modules.observability_dashboard.domain.models import (
    AlertChannel,
    AlertDispatchCommand,
    AlertStatus,
)


def test_alert_notifier_adapter_success() -> None:
    """[US-4][AC-4.3] Test successful dispatch to PagerDuty and Cloud Monitoring."""
    adapter = AlertNotifierAdapter(simulated_latency_ms=250)

    cmd = AlertDispatchCommand(
        incident_id="inc-123",
        channel=AlertChannel.PAGERDUTY,
        message="Critical safety trip",
    )
    receipt = adapter.dispatch_alert(cmd)

    assert receipt.incident_id == "inc-123"
    assert receipt.channel == AlertChannel.PAGERDUTY
    assert receipt.status == AlertStatus.DELIVERED
    assert receipt.latency_ms == 250
    assert len(receipt.dispatch_id) > 0
    assert len(adapter.dispatched) == 1


def test_alert_notifier_adapter_channel_failure() -> None:
    """[US-4][AC-4.3] Test simulated channel outage triggers AlertDispatchError."""
    adapter = AlertNotifierAdapter()
    adapter.set_channel_outage(AlertChannel.CLOUD_MONITORING, outage=True)

    cmd = AlertDispatchCommand(
        incident_id="inc-456",
        channel=AlertChannel.CLOUD_MONITORING,
        message="Cloud monitoring test",
    )
    with pytest.raises(AlertDispatchError, match="Channel 'CLOUD_MONITORING' outage"):
        adapter.dispatch_alert(cmd)

    # Clear channel outage
    adapter.set_channel_outage(AlertChannel.CLOUD_MONITORING, outage=False)
    receipt = adapter.dispatch_alert(cmd)
    assert receipt.channel == AlertChannel.CLOUD_MONITORING

    # Global outage
    adapter.set_global_outage(True)
    cmd2 = AlertDispatchCommand(
        incident_id="inc-789",
        channel=AlertChannel.PAGERDUTY,
        message="PagerDuty test",
    )
    with pytest.raises(AlertDispatchError, match="Downstream notification gateway outage"):
        adapter.dispatch_alert(cmd2)
