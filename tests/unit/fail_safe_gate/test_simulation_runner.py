"""Unit tests for SimulationRunner."""

from src.modules.fail_safe_gate.adapters.simulation_runner import SimulationRunner
from src.modules.fail_safe_gate.domain.engine import DecisionEngine
from src.modules.fail_safe_gate.domain.models import AdversarialScenario
from src.modules.fail_safe_gate.domain.rules.correlation_drift_rule import (
    CorrelationDriftRule,
)
from src.modules.fail_safe_gate.domain.rules.frozen_telemetry_rule import (
    FrozenTelemetryRule,
)
from src.modules.fail_safe_gate.domain.rules.heartbeat_timeout_rule import (
    HeartbeatTimeoutRule,
)
from src.modules.fail_safe_gate.domain.rules.static_bounds_rule import (
    StaticBoundsRule,
)


def _make_engine() -> DecisionEngine:
    return DecisionEngine(
        rules=[
            StaticBoundsRule(min_flow=0.0, max_flow=1200.0),
            CorrelationDriftRule(k_factor=10553.4, tolerance_sigma=3.0),
            FrozenTelemetryRule(min_samples=5),
            HeartbeatTimeoutRule(max_interval_ms=250.0),
        ]
    )


def test_simulation_runner_flow_spike_passes() -> None:
    """[US-3][AC-3.2] Verify simulation detects flow spike and enters safe state."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)

    scenario = AdversarialScenario(
        scenario_id="scen-spike-1",
        anomaly_type="flow_spike",
        duration_ms=100,
        injection_magnitude=1600.0,
    )
    result = runner.run_scenario(scenario, max_response_window_ms=50)

    assert result.scenario_id == "scen-spike-1"
    assert result.passed is True
    assert result.entered_safe_state is True
    assert result.reaction_latency_ms <= 50.0
    assert result.failure_reason is None


def test_simulation_runner_vacuum_drop() -> None:
    """[US-3][AC-3.2] Verify simulation detects vacuum drop anomaly."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)

    scenario = AdversarialScenario(
        scenario_id="scen-vacuum-1",
        anomaly_type="vacuum_drop",
        duration_ms=50,
        injection_magnitude=0.1,  # pressure drops to near 0, breaking correlation
    )
    result = runner.run_scenario(scenario, max_response_window_ms=50)

    assert result.passed is True
    assert result.entered_safe_state is True


def test_simulation_runner_frozen_sensor() -> None:
    """[US-3][AC-3.2] Verify simulation detects frozen sensor anomaly."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)

    scenario = AdversarialScenario(
        scenario_id="scen-freeze-1",
        anomaly_type="frozen_sensor",
        duration_ms=500,
        injection_magnitude=0.0,
    )
    result = runner.run_scenario(scenario, max_response_window_ms=50)

    assert result.passed is True
    assert result.entered_safe_state is True


def test_simulation_runner_pressure_disconnect() -> None:
    """[US-3][AC-3.2] Verify simulation detects pressure disconnect anomaly."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)

    scenario = AdversarialScenario(
        scenario_id="scen-disconnect-1",
        anomaly_type="pressure_disconnect",
        duration_ms=50,
        injection_magnitude=-1.0,
    )
    result = runner.run_scenario(scenario, max_response_window_ms=50)

    assert result.passed is True
    assert result.entered_safe_state is True


def test_simulation_runner_noisy_turbulence() -> None:
    """[US-3][AC-3.2] Verify simulation handles noisy turbulence."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)

    scenario = AdversarialScenario(
        scenario_id="scen-turb-1",
        anomaly_type="noisy_turbulence",
        duration_ms=50,
        injection_magnitude=500.0,
    )
    result = runner.run_scenario(scenario, max_response_window_ms=50)

    assert result.passed is True
    assert result.entered_safe_state is True


def test_simulation_runner_suite_summary() -> None:
    """[US-3][AC-3.3] Verify batch simulation execution and verdict calculation."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)

    scenarios = [
        AdversarialScenario("s1", "flow_spike", 100, 1500.0),
        AdversarialScenario("s2", "vacuum_drop", 100, 0.05),
    ]
    summary = runner.run_suite(
        simulation_id="sim-run-001",
        candidate_version="sha-abcdef",
        scenarios=scenarios,
        max_response_window_ms=50,
    )

    assert summary["simulation_id"] == "sim-run-001"
    assert summary["candidate_version"] == "sha-abcdef"
    assert summary["overall_verdict"] == "passed"
    assert summary["scenarios_passed"] == 2
    assert summary["scenarios_total"] == 2
    assert len(summary["results"]) == 2


def test_simulation_runner_unsupported_anomaly() -> None:
    """[US-3][AC-3.2] Verify handling of unknown anomaly type."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)

    scenario = AdversarialScenario("s-bad", "unknown_type", 100, 0.0)
    result = runner.run_scenario(scenario)
    assert result.passed is False
    assert result.entered_safe_state is False
    assert "Unsupported anomaly type" in (result.failure_reason or "")


def test_simulation_runner_fails_if_engine_does_not_trip() -> None:
    """[US-3][AC-3.3] Verify scenario fails if candidate engine allows unsafe anomaly."""
    # Engine with empty rules (never trips)
    lenient_engine = DecisionEngine(rules=[])
    runner = SimulationRunner(engine=lenient_engine)

    scenario = AdversarialScenario("s-fail", "flow_spike", 100, 2000.0)
    result = runner.run_scenario(scenario)
    assert result.passed is False
    assert result.entered_safe_state is False
    assert "Candidate engine failed to enter safe state" in (
        result.failure_reason or ""
    )


def test_simulation_runner_candidate_crash_raises() -> None:
    """[US-3][AC-3.3] Verify candidate crash raises InternalServiceError."""
    import pytest

    from src.modules.fail_safe_gate.domain.exceptions import InternalServiceError

    engine = _make_engine()
    runner = SimulationRunner(engine=engine)
    with pytest.raises(InternalServiceError) as exc_info:
        runner.run_suite(
            simulation_id="sim-crash",
            candidate_version="candidate-crash-version",
            scenarios=[AdversarialScenario("s1", "flow_spike", 100, 1500.0)],
        )
    assert "runtime failure" in exc_info.value.message


def test_simulation_runner_candidate_unsafe_fails_scenarios() -> None:
    """[US-3][AC-3.3] Verify candidate with unsafe logic is rejected."""
    engine = _make_engine()
    runner = SimulationRunner(engine=engine)
    summary = runner.run_suite(
        simulation_id="sim-unsafe",
        candidate_version="candidate-unsafe-version",
        scenarios=[AdversarialScenario("s1", "flow_spike", 100, 1500.0)],
    )
    assert summary["overall_verdict"] == "rejected"
    assert summary["scenarios_passed"] == 0
    assert summary["results"][0]["entered_safe_state"] is False
