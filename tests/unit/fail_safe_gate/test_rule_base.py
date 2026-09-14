"""Unit tests for Rule base ABC."""

import pytest

from src.modules.fail_safe_gate.domain.models import (
    Decision,
    EvaluationRequest,
    TelemetryData,
)
from src.modules.fail_safe_gate.domain.rules.base import Rule


class DummyRule(Rule):
    """Concrete dummy rule for testing the abstract base class."""

    @property
    def rule_id(self) -> str:
        """Return dummy rule identifier."""
        return "R-DUMMY-01"

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate dummy condition."""
        if request.telemetry.flow_rate > 100.0:
            return Decision(
                is_allowed=False,
                status_code=422,
                rule_id=self.rule_id,
                reason="Flow exceeded dummy limit",
                trip_required=True,
                violating_rule_id=self.rule_id,
            )
        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id=self.rule_id,
            reason="Within dummy bounds",
            trip_required=False,
        )


def test_rule_abc_cannot_be_instantiated() -> None:
    """[US-1][AC-1.2] Verify Rule abstract class cannot be directly instantiated."""
    with pytest.raises(TypeError):
        Rule()  # type: ignore[abstract]


def test_concrete_rule_evaluation() -> None:
    """[US-1][AC-1.2] Verify concrete Rule implementation behaves correctly."""
    rule = DummyRule()
    assert rule.rule_id == "R-DUMMY-01"

    req_pass = EvaluationRequest(
        request_id="req-1",
        regulator_id="reg-1",
        telemetry=TelemetryData(
            sensor_id="s1",
            flow_rate=50.0,
            pressure=10.0,
            temperature=290.0,
            timestamp_ns=1_000_000,
        ),
    )
    dec_pass = rule.evaluate(req_pass)
    assert dec_pass.is_allowed is True
    assert dec_pass.status_code == 200

    req_fail = EvaluationRequest(
        request_id="req-2",
        regulator_id="reg-1",
        telemetry=TelemetryData(
            sensor_id="s1",
            flow_rate=150.0,
            pressure=10.0,
            temperature=290.0,
            timestamp_ns=1_000_000,
        ),
    )
    dec_fail = rule.evaluate(req_fail)
    assert dec_fail.is_allowed is False
    assert dec_fail.status_code == 422
    assert dec_fail.trip_required is True
    assert dec_fail.violating_rule_id == "R-DUMMY-01"
