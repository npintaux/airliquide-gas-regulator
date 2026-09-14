"""Alert notification adapter routing to external alert channels."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from ..domain.alert_dispatcher import AlertDispatchPort
from ..domain.exceptions import AlertDispatchError
from ..domain.models import (
    AlertChannel,
    AlertDispatchCommand,
    AlertDispatchReceipt,
    AlertStatus,
)


class AlertNotifierAdapter(AlertDispatchPort):
    """Adapter for dispatching emergency alert notifications to external sinks."""

    def __init__(self, simulated_latency_ms: int = 120) -> None:
        """Initialize the alert notifier adapter.

        Args:
            simulated_latency_ms: Simulated network dispatch latency in milliseconds.
        """
        self._simulated_latency_ms = simulated_latency_ms
        self._channel_outages: set[AlertChannel] = set()
        self._global_outage: bool = False
        self._dispatched: list[AlertDispatchReceipt] = []

    @property
    def dispatched(self) -> list[AlertDispatchReceipt]:
        """List of all alert receipts dispatched through this adapter."""
        return list(self._dispatched)

    def set_channel_outage(self, channel: AlertChannel, outage: bool = True) -> None:
        """Configure simulated outage for a specific alert channel.

        Args:
            channel: The AlertChannel to affect.
            outage: True to simulate outage, False to clear.
        """
        if outage:
            self._channel_outages.add(channel)
        else:
            self._channel_outages.discard(channel)

    def set_global_outage(self, outage: bool = True) -> None:
        """Configure simulated global notification gateway outage.

        Args:
            outage: True to simulate outage, False for normal operation.
        """
        self._global_outage = outage

    def dispatch_alert(self, command: AlertDispatchCommand) -> AlertDispatchReceipt:
        """Dispatch high-priority alert notification to destination channel.

        Args:
            command: Alert dispatch command payload.

        Returns:
            AlertDispatchReceipt confirming delivery.

        Raises:
            AlertDispatchError: If destination channel or gateway has an outage.
        """
        if self._global_outage:
            raise AlertDispatchError("Downstream notification gateway outage.")

        if command.channel in self._channel_outages:
            raise AlertDispatchError(f"Channel '{command.channel.value}' outage.")

        receipt = AlertDispatchReceipt(
            dispatch_id=str(uuid.uuid4()),
            incident_id=command.incident_id,
            channel=command.channel,
            status=AlertStatus.DELIVERED,
            dispatched_at=datetime.now(UTC),
            latency_ms=self._simulated_latency_ms,
        )
        self._dispatched.append(receipt)
        return receipt
