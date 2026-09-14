"""Unit tests for RootCauseSummarizer."""

from __future__ import annotations

from src.modules.observability_dashboard.domain.summarizer import RootCauseSummarizer


def test_summarize_with_existing_summary() -> None:
    """[US-4][AC-4.2] Preserves non-empty root cause summary."""
    summarizer = RootCauseSummarizer()
    res = summarizer.summarize("Overpressure", "Manual analysis: valve stuck")
    assert res == "Manual analysis: valve stuck"


def test_summarize_known_trip_reasons() -> None:
    """[US-4][AC-4.2] Synthesizes deterministic diagnosis from known trip reason patterns."""
    summarizer = RootCauseSummarizer()

    s1 = summarizer.summarize("Pressure-flow divergence detected")
    assert "pressure-flow divergence" in s1.lower()

    s2 = summarizer.summarize("Frozen sensor telemetry variance")
    assert "variance" in s2.lower()

    s3 = summarizer.summarize("Erratic signal noise exceeding safety threshold")
    assert "noise" in s3.lower() or "threshold" in s3.lower()

    s4 = summarizer.summarize("Heartbeat timeout missing frames")
    assert "heartbeat" in s4.lower() or "communication" in s4.lower()

    s5 = summarizer.summarize("Unknown hardware anomaly")
    assert "automated safety trip" in s5.lower()
