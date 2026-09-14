"""Unit tests for DecisionEngine orchestrator."""

from unittest.mock import MagicMock

from src.modules.fail_safe_gate.domain.engine import DecisionEngine
from src.modules.fail_safe_gate.domain.models import (
    ActuatorResult,
    Decision,
    EvaluationRequest,
    TelemetryData,
)
from src.modules.fail_safe_gate.domain.rules.base import Rule


class PassingRule(Rule):
    """Rule that always passes."""

    @property
    def rule_id(self) -> str:
        """Return rule id."""
        return "R-TEST-PASS"

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Return pass decision."""
        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id=self.rule_id,
            reason="All test conditions nominal.",
            trip_required=False,
        )


class TrippingRule(Rule):
    """Rule that trips."""

    def __init__(
        self, rule_id: str = "R-TEST-TRIP", trip_required: bool = True
    ) -> None:
        self._id = rule_id
        self._trip = trip_required

    @property
    def rule_id(self) -> str:
        """Return rule id."""
        return self._id

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Return trip decision."""
        return Decision(
            is_allowed=False,
            status_code=422,
            rule_id=self.rule_id,
            reason=f"Violation on rule {self.rule_id}",
            trip_required=self._trip,
            violating_rule_id=self.rule_id,
        )


def _sample_request() -> EvaluationRequest:
    return EvaluationRequest(
        request_id="req-123",
        regulator_id="reg-alpha",
        telemetry=TelemetryData(
            sensor_id="sensor-001",
            flow_rate=450.0,
            pressure=12.5,
            temperature=293.15,
            timestamp_ns=1_700_000_000_000_000_000,
        ),
    )


def test_engine_all_rules_pass() -> None:
    """[US-1][AC-1.2] Verify all rules passing yields an overall pass decision."""
    engine = DecisionEngine(rules=[PassingRule(), PassingRule()])
    req = _sample_request()
    decision = engine.evaluate(req)

    assert decision.is_allowed is True
    assert decision.status_code == 200
    assert decision.rule_id == "PASS"
    assert decision.trip_required is False
    assert decision.violating_rule_id is None


def test_engine_short_circuit_on_first_failure() -> None:
    """[US-1][AC-1.2] Verify engine short-circuits on first rule trip."""
    rule1 = TrippingRule("R-FIRST")
    rule2 = MagicMock(spec=Rule)

    engine = DecisionEngine(rules=[rule1, rule2])
    req = _sample_request()
    decision = engine.evaluate(req)

    assert decision.is_allowed is False
    assert decision.status_code == 422
    assert decision.rule_id == "R-FIRST"
    assert decision.violating_rule_id == "R-FIRST"
    rule2.evaluate.assert_not_called()


def test_engine_dispatches_actuator_when_trip_required() -> None:
    """[US-2][AC-2.1] Verify hardware actuator is called if trip_required is True."""
    mock_actuator = MagicMock()
    mock_actuator.dispatch_emergency_trip.return_value = ActuatorResult(
        command_id="cmd-1",
        regulator_id="reg-alpha",
        executed_state="closed",
        actuation_latency_ms=10.0,
        success=True,
    )

    rule = TrippingRule("R-CRITICAL", trip_required=True)
    engine = DecisionEngine(rules=[rule], actuator_port=mock_actuator)
    req = _sample_request()

    decision = engine.evaluate(req)

    assert decision.is_allowed is False
    assert decision.trip_required is True
    mock_actuator.dispatch_emergency_trip.assert_called_once_with(
        regulator_id="reg-alpha",
        reason="Violation on rule R-CRITICAL",
    )


def test_engine_trip_without_actuator_port() -> None:
    """[US-1][AC-1.2] Verify trip handling gracefully when no actuator port is configured."""
    rule = TrippingRule("R-NO-ACTUATOR", trip_required=True)
    engine = DecisionEngine(rules=[rule], actuator_port=None)
    req = _sample_request()

    decision = engine.evaluate(req)
    assert decision.is_allowed is False
    assert decision.trip_required is True


def test_engine_rules_property() -> None:
    """[US-1][AC-1.2] Verify rules property on engine."""
    r = PassingRule()
    engine = DecisionEngine(rules=[r])
    assert engine.rules == (r,)
