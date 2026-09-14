"""Hardware actuator adapter mediating physical valve commands."""

from __future__ import annotations

import time
import uuid

from ..domain.exceptions import (
    ActuationInterlockConflict,
    HardwareCommunicationError,
    InvalidPayloadError,
)
from ..domain.models import ActuatorCommand, ActuatorResult

VALID_TARGET_STATES: frozenset[str] = frozenset(
    {"closed", "safe_hold", "minimum_safe_flow", "physical_bypass", "open"}
)


class ActuatorAdapter:
    """Adapter executing physical valve positioning and emergency interrupt trips."""

    def __init__(
        self,
        simulated_latency_ms: float = 12.0,
        fail_communication: bool = False,
        locked_states: set[str] | None = None,
        initial_state: str = "open",
    ) -> None:
        """Initialize the actuator adapter.

        Args:
            simulated_latency_ms: Artificial latency to simulate hardware travel / bus transit.
            fail_communication: If True, simulates bus/comm failure.
            locked_states: Set of prohibited states due to active physical interlocks.
            initial_state: Initial valve state.
        """
        self._latency_ms = simulated_latency_ms
        self._fail_communication = fail_communication
        self._locked_states = locked_states or set()
        self._current_state = initial_state
        self._last_trip_reason: str | None = None
        self._last_trip_timestamp_ns: int | None = None
        self._offline_buffer_used: int = 0
        self._offline_buffer_capacity: int = 2 * 1024 * 1024 * 1024  # 2 GB

    @property
    def current_state(self) -> str:
        """Return the current physical valve state."""
        return self._current_state

    @property
    def last_trip_reason(self) -> str | None:
        """Return the reason for the last recorded trip, if any."""
        return self._last_trip_reason

    @property
    def last_trip_timestamp_ns(self) -> int | None:
        """Return timestamp in ns of the last trip, if any."""
        return self._last_trip_timestamp_ns

    @property
    def offline_buffer_used_bytes(self) -> int:
        """Return offline buffer bytes utilized."""
        return self._offline_buffer_used

    @property
    def offline_buffer_capacity_bytes(self) -> int:
        """Return offline buffer total capacity in bytes."""
        return self._offline_buffer_capacity

    def set_offline_buffer_usage(self, used_bytes: int) -> None:
        """Set simulated buffer usage."""
        self._offline_buffer_used = used_bytes

    def reset_valve(self, state: str = "open") -> None:
        """Reset valve state."""
        self._current_state = state

    def dispatch(self, command: ActuatorCommand) -> ActuatorResult:
        """Execute physical actuator command.

        Args:
            command: ActuatorCommand specifying target valve state and deadlines.

        Returns:
            ActuatorResult detailing execution outcome.

        Raises:
            InvalidPayloadError: If target_state is unrecognized.
            HardwareCommunicationError: If fieldbus or Modbus driver communication fails.
            ActuationInterlockConflict: If target state is locked by physical interlocks.
        """
        if command.target_state not in VALID_TARGET_STATES:
            raise InvalidPayloadError(
                f"Unsupported target_state: '{command.target_state}'. "
                f"Allowed states: {sorted(VALID_TARGET_STATES)}"
            )

        if self._fail_communication or "BROKEN" in command.regulator_id:
            raise HardwareCommunicationError(
                "Failed to communicate with fieldbus actuator controller."
            )

        if (
            command.target_state in self._locked_states
            or "INTERLOCKED" in command.regulator_id
        ):
            raise ActuationInterlockConflict(
                f"Target state '{command.target_state}' conflicts with active hardware interlock."
            )

        self._current_state = command.target_state
        now_ns = time.time_ns()

        if command.target_state in {"closed", "safe_hold"}:
            self._last_trip_reason = command.reason
            self._last_trip_timestamp_ns = now_ns

        return ActuatorResult(
            command_id=command.command_id,
            regulator_id=command.regulator_id,
            executed_state=self._current_state,
            actuation_latency_ms=self._latency_ms,
            success=True,
            message=f"Actuator transitioned to {self._current_state}.",
        )

    def dispatch_emergency_trip(self, regulator_id: str, reason: str) -> ActuatorResult:
        """Dispatch emergency safe-hold/close trip interrupt within sub-50ms budget.

        Args:
            regulator_id: Target regulator gate identifier.
            reason: Diagnostic explanation for the trip.

        Returns:
            ActuatorResult outcome.
        """
        command = ActuatorCommand(
            command_id=f"trip-{uuid.uuid4()}",
            regulator_id=regulator_id,
            target_state="closed",
            reason=reason,
            initiated_by="fail-safe-engine",
            timeout_ms=50,
        )
        return self.dispatch(command)
