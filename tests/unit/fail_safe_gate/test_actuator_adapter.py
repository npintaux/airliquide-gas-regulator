"""Unit tests for ActuatorAdapter."""

import pytest

from src.modules.fail_safe_gate.adapters.actuator_adapter import ActuatorAdapter
from src.modules.fail_safe_gate.domain.exceptions import (
    ActuationInterlockConflict,
    HardwareCommunicationError,
    InvalidPayloadError,
)
from src.modules.fail_safe_gate.domain.models import ActuatorCommand


def test_actuator_adapter_successful_dispatch() -> None:
    """[US-2][AC-2.1] Verify successful close dispatch within sub-50ms latency."""
    adapter = ActuatorAdapter(simulated_latency_ms=10.0)
    cmd = ActuatorCommand(
        command_id="cmd-101",
        regulator_id="reg-alpha",
        target_state="closed",
        reason="Manual test closure",
        initiated_by="operator",
        timeout_ms=50,
    )
    result = adapter.dispatch(cmd)

    assert result.command_id == "cmd-101"
    assert result.regulator_id == "reg-alpha"
    assert result.executed_state == "closed"
    assert result.success is True
    assert result.actuation_latency_ms <= 50.0
    assert adapter.current_state == "closed"


def test_actuator_adapter_emergency_trip() -> None:
    """[US-2][AC-2.1] Verify dispatch_emergency_trip convenience method."""
    adapter = ActuatorAdapter()
    result = adapter.dispatch_emergency_trip(
        regulator_id="reg-beta",
        reason="Overpressure emergency trip",
    )
    assert result.success is True
    assert result.executed_state == "closed"
    assert adapter.current_state == "closed"
    assert adapter.last_trip_reason == "Overpressure emergency trip"


def test_actuator_adapter_interlock_conflict() -> None:
    """[US-2][AC-2.1] Verify interlock conflict error when target state is prohibited."""
    adapter = ActuatorAdapter(locked_states={"physical_bypass"})
    cmd = ActuatorCommand(
        command_id="cmd-102",
        regulator_id="reg-alpha",
        target_state="physical_bypass",
        reason="Attempt bypass while locked",
        initiated_by="test",
    )
    with pytest.raises(ActuationInterlockConflict) as exc_info:
        adapter.dispatch(cmd)
    assert "conflicts with active hardware interlock" in str(exc_info.value)
    assert exc_info.value.code == "INTERLOCK_CONFLICT"
    assert exc_info.value.status_code == 422


def test_actuator_adapter_hardware_comm_error() -> None:
    """[US-2][AC-2.1] Verify hardware communication error upon simulated failure."""
    adapter = ActuatorAdapter(fail_communication=True)
    cmd = ActuatorCommand(
        command_id="cmd-103",
        regulator_id="reg-alpha",
        target_state="closed",
        reason="Test comm failure",
        initiated_by="test",
    )
    with pytest.raises(HardwareCommunicationError) as exc_info:
        adapter.dispatch(cmd)
    assert exc_info.value.code == "ACTUATOR_COMM_ERROR"
    assert exc_info.value.status_code == 500


def test_actuator_adapter_invalid_state() -> None:
    """[US-2][AC-2.1] Verify InvalidPayloadError on unsupported target state."""
    adapter = ActuatorAdapter()
    cmd = ActuatorCommand(
        command_id="cmd-104",
        regulator_id="reg-alpha",
        target_state="invalid_unknown_state",
        reason="Test invalid state",
        initiated_by="test",
    )
    with pytest.raises(InvalidPayloadError) as exc_info:
        adapter.dispatch(cmd)
    assert exc_info.value.code == "INVALID_PAYLOAD"
    assert exc_info.value.status_code == 400


def test_actuator_adapter_status_and_reset() -> None:
    """[US-5][AC-5.2] Verify status properties on ActuatorAdapter."""
    adapter = ActuatorAdapter()
    assert adapter.current_state == "open"
    assert adapter.offline_buffer_used_bytes == 0
    assert adapter.offline_buffer_capacity_bytes == 2147483648
    assert adapter.last_trip_reason is None
    assert adapter.last_trip_timestamp_ns is None

    adapter.set_offline_buffer_usage(1024)
    assert adapter.offline_buffer_used_bytes == 1024

    adapter.reset_valve("open")
    assert adapter.current_state == "open"
