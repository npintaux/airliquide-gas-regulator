"""Abstract port defining alert notification dispatch."""

from __future__ import annotations

import abc

from .models import AlertDispatchCommand, AlertDispatchReceipt


class AlertDispatchPort(abc.ABC):
    """Abstract port for routing high-priority incident alerts to notification channels."""

    @abc.abstractmethod
    def dispatch_alert(self, command: AlertDispatchCommand) -> AlertDispatchReceipt:
        """Route an alert command to an external notification channel (PagerDuty, Cloud Monitoring).

        Args:
            command: High-priority alert dispatch parameters.

        Returns:
            Delivery receipt confirming dispatch and latency.

        Raises:
            AlertDispatchError: If downstream channel communication fails.
            DispatchTimeoutError: If dispatch exceeds SLA latency budget.
        """
        ...
