"""Automated root-cause diagnostic summarizer."""

from __future__ import annotations


class RootCauseSummarizer:
    """Synthesizes automated, deterministic root-cause diagnosis from trip reasons."""

    def summarize(self, trip_reason: str, existing_summary: str | None = None) -> str:
        """Diagnose and produce a concise root cause statement.

        Args:
            trip_reason: Trigger reason recorded by the safety trip system.
            existing_summary: Optional already-existing diagnosis.

        Returns:
            Deterministic root-cause summary string.
        """
        if existing_summary and existing_summary.strip():
            return existing_summary.strip()

        reason_lower = trip_reason.lower()
        if "divergence" in reason_lower or "pressure" in reason_lower:
            return (
                f"Automated Diagnosis: Pressure-flow divergence violated physical model "
                f"envelope ({trip_reason})."
            )
        if "frozen" in reason_lower or "variance" in reason_lower:
            return (
                f"Automated Diagnosis: Telemetry signal variance collapsed below minimum "
                f"noise floor; suspect frozen sensor ({trip_reason})."
            )
        if "heartbeat" in reason_lower or "timeout" in reason_lower:
            return (
                f"Automated Diagnosis: Telemetry communication dropout; missing heartbeat "
                f"frames ({trip_reason})."
            )
        if (
            "noise" in reason_lower
            or "threshold" in reason_lower
            or "spike" in reason_lower
        ):
            return (
                f"Automated Diagnosis: Flow rate exceeded critical safety threshold or noise bounds "
                f"({trip_reason})."
            )

        return f"Automated Diagnosis: Automated safety trip invoked ({trip_reason})."
