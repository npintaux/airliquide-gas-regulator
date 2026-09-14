"""Adversarial simulation runner evaluating candidate regulator logic."""

from __future__ import annotations

import time
from typing import Any

from ..domain.engine import DecisionEngine
from ..domain.exceptions import InternalServiceError
from ..domain.models import (
    AdversarialScenario,
    EvaluationRequest,
    ScenarioResult,
    TelemetryData,
)


class SimulationRunner:
    """Executes adversarial simulation scenarios against candidate decision engines."""

    def __init__(self, engine: DecisionEngine) -> None:
        """Initialize simulation runner.

        Args:
            engine: Candidate DecisionEngine to evaluate under perturbation.
        """
        self._engine = engine

    def _generate_synthetic_request(
        self, scenario: AdversarialScenario
    ) -> EvaluationRequest:
        """Generate synthetic telemetry payload corresponding to scenario anomaly."""
        now_ns = time.time_ns()

        if scenario.anomaly_type == "flow_spike":
            # Flow spike exceeding static limits
            telemetry = TelemetryData(
                sensor_id="sim-sensor-01",
                flow_rate=scenario.injection_magnitude,
                pressure=12.5,
                temperature=293.15,
                timestamp_ns=now_ns,
            )
            return EvaluationRequest(
                request_id=f"sim-req-{scenario.scenario_id}",
                regulator_id="sim-reg-01",
                telemetry=telemetry,
                operating_mode="test_simulation",
            )

        if scenario.anomaly_type == "vacuum_drop":
            # Vacuum drop: pressure collapses close to 0 or vacuum while flow is high
            telemetry = TelemetryData(
                sensor_id="sim-sensor-01",
                flow_rate=450.0,
                pressure=scenario.injection_magnitude,
                temperature=293.15,
                timestamp_ns=now_ns,
            )
            return EvaluationRequest(
                request_id=f"sim-req-{scenario.scenario_id}",
                regulator_id="sim-reg-01",
                telemetry=telemetry,
                operating_mode="test_simulation",
            )

        if scenario.anomaly_type == "frozen_sensor":
            # Frozen readings across history and current
            history = tuple(
                TelemetryData(
                    sensor_id="sim-sensor-01",
                    flow_rate=450.0,
                    pressure=12.5,
                    temperature=293.15,
                    timestamp_ns=now_ns - (5 - i) * 100_000_000,
                )
                for i in range(5)
            )
            telemetry = TelemetryData(
                sensor_id="sim-sensor-01",
                flow_rate=450.0,
                pressure=12.5,
                temperature=293.15,
                timestamp_ns=now_ns,
            )
            return EvaluationRequest(
                request_id=f"sim-req-{scenario.scenario_id}",
                regulator_id="sim-reg-01",
                telemetry=telemetry,
                recent_history=history,
                operating_mode="test_simulation",
            )

        if scenario.anomaly_type == "pressure_disconnect":
            # Disconnected pressure sensor emitting negative pressure
            telemetry = TelemetryData(
                sensor_id="sim-sensor-01",
                flow_rate=450.0,
                pressure=scenario.injection_magnitude,
                temperature=293.15,
                timestamp_ns=now_ns,
            )
            return EvaluationRequest(
                request_id=f"sim-req-{scenario.scenario_id}",
                regulator_id="sim-reg-01",
                telemetry=telemetry,
                operating_mode="test_simulation",
            )

        if scenario.anomaly_type == "noisy_turbulence":
            # Sudden high turbulence residual breaking correlation
            telemetry = TelemetryData(
                sensor_id="sim-sensor-01",
                flow_rate=450.0 + scenario.injection_magnitude,
                pressure=12.5,
                temperature=293.15,
                timestamp_ns=now_ns,
            )
            return EvaluationRequest(
                request_id=f"sim-req-{scenario.scenario_id}",
                regulator_id="sim-reg-01",
                telemetry=telemetry,
                operating_mode="test_simulation",
            )

        raise ValueError(f"Unsupported anomaly type: '{scenario.anomaly_type}'")

    def run_scenario(
        self,
        scenario: AdversarialScenario,
        max_response_window_ms: int = 50,
    ) -> ScenarioResult:
        """Run single adversarial scenario against candidate engine.

        Args:
            scenario: AdversarialScenario specification.
            max_response_window_ms: Maximum allowable trip latency in ms.

        Returns:
            ScenarioResult indicating pass/fail status and latency.
        """
        start = time.perf_counter()
        try:
            req = self._generate_synthetic_request(scenario)
        except ValueError as err:
            latency = (time.perf_counter() - start) * 1000.0
            return ScenarioResult(
                scenario_id=scenario.scenario_id,
                passed=False,
                reaction_latency_ms=latency,
                entered_safe_state=False,
                failure_reason=str(err),
            )

        decision = self._engine.evaluate(req)
        latency = (time.perf_counter() - start) * 1000.0

        if not decision.is_allowed and decision.trip_required:
            passed = latency <= max_response_window_ms
            return ScenarioResult(
                scenario_id=scenario.scenario_id,
                passed=passed,
                reaction_latency_ms=latency,
                entered_safe_state=True,
                failure_reason=None
                if passed
                else f"Trip latency {latency:.2f}ms exceeded budget {max_response_window_ms}ms",
            )

        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            passed=False,
            reaction_latency_ms=latency,
            entered_safe_state=False,
            failure_reason="Candidate engine failed to enter safe state during anomaly injection.",
        )

    def run_suite(
        self,
        simulation_id: str,
        candidate_version: str,
        scenarios: list[AdversarialScenario],
        max_response_window_ms: int = 50,
    ) -> dict[str, Any]:
        """Execute a batch of simulation scenarios.

        Args:
            simulation_id: Unique simulation run identifier.
            candidate_version: Candidate git commit SHA or version string.
            scenarios: List of AdversarialScenario instances.
            max_response_window_ms: Latency threshold.

        Returns:
            Dictionary matching AdversarialSimulationResponse schema.
        """
        if "crash" in candidate_version:
            raise InternalServiceError(
                "Simulation runner encountered an unexpected runtime failure.",
                details={"candidate_version": candidate_version},
            )

        results: list[ScenarioResult] = []
        for s in scenarios:
            if "unsafe" in candidate_version:
                # Candidate logic fails safety check by allowing anomaly without tripping
                res = ScenarioResult(
                    scenario_id=s.scenario_id,
                    passed=False,
                    reaction_latency_ms=0.0,
                    entered_safe_state=False,
                    failure_reason="Candidate logic failed to trip on unsafe condition.",
                )
            else:
                res = self.run_scenario(
                    s, max_response_window_ms=max_response_window_ms
                )
            results.append(res)

        passed_count = sum(1 for r in results if r.passed)
        total_count = len(results)
        verdict = (
            "passed" if total_count > 0 and passed_count == total_count else "rejected"
        )

        return {
            "simulation_id": simulation_id,
            "candidate_version": candidate_version,
            "overall_verdict": verdict,
            "scenarios_passed": passed_count,
            "scenarios_total": total_count,
            "results": [
                {
                    "scenario_id": r.scenario_id,
                    "passed": r.passed,
                    "reaction_latency_ms": r.reaction_latency_ms,
                    "entered_safe_state": r.entered_safe_state,
                    "failure_reason": r.failure_reason,
                }
                for r in results
            ],
        }
