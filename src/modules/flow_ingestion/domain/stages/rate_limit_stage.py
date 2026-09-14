"""Rate and jitter evaluation stage for telemetry sequence validation."""

from __future__ import annotations

from ..exceptions import (
    JitterThresholdExceededError,
    RateLimitExceededError,
    SequenceDiscontinuityError,
)
from ..models import PipelineContext
from .base import PipelineStage


class RateJitterEvaluationStage(PipelineStage):
    """Evaluates packet arrival rate, interval jitter, and sequence monotonicity."""

    def __init__(
        self,
        nominal_interval_ns: int = 100_000_000,  # 100ms
        jitter_tolerance_ns: int = 50_000_000,  # 50ms tolerance
        max_burst_per_sec: int = 1000,
    ) -> None:
        """Initializes stage with timing and rate parameters.

        Args:
            nominal_interval_ns: Nominal interval between frames in nanoseconds (default 100ms).
            jitter_tolerance_ns: Maximum allowed deviation from nominal interval (default 50ms).
            max_burst_per_sec: Maximum frames allowed in a single evaluation (default 1000).
        """
        self._nominal_interval_ns = nominal_interval_ns
        self._jitter_tolerance_ns = jitter_tolerance_ns
        self._max_burst_per_sec = max_burst_per_sec
        # In-memory tracking per stream_id: (last_sequence_number, last_timestamp_ns)
        self._stream_history: dict[str, tuple[int, int]] = {}

    @property
    def stage_name(self) -> str:
        """Returns the stage identifier."""
        return "rate_jitter_evaluation"

    def clear_history(self) -> None:
        """Clears all in-memory stream sequence and jitter tracking history."""
        self._stream_history.clear()

    def process(self, context: PipelineContext) -> PipelineContext:
        """Evaluates sequence monotonicity and timing jitter across records.

        Args:
            context: Incoming PipelineContext with normalized records.

        Returns:
            Updated PipelineContext with evaluated metrics recorded.

        Raises:
            RateLimitExceededError: If frame count exceeds burst limit.
            SequenceDiscontinuityError: If non-monotonic sequence detected on live stream.
            JitterThresholdExceededError: If timestamp jitter exceeds tolerance.
        """
        records = context.records
        if not records:
            return context

        # 1. Rate burst check
        if len(records) > self._max_burst_per_sec:
            raise RateLimitExceededError(
                f"Ingestion burst size {len(records)} exceeds limit of {self._max_burst_per_sec}",
                code="RATE_LIMIT_EXCEEDED",
                status_code=422,
                details={
                    "frame_count": len(records),
                    "max_burst": self._max_burst_per_sec,
                },
            )

        stream_id = context.stream_id
        is_replayed = context.is_replayed

        # 2. Sequential monotonicity & timing jitter across records in batch
        if len(records) > 1:
            batch_prev_seq: int | None = None
            batch_prev_ts: int | None = None
            max_jitter = 0.0

            for r in records:
                if (
                    batch_prev_seq is not None
                    and r.sequence_number != batch_prev_seq + 1
                ):
                    # In a batch, frames must be strictly sequential (seq_delta == 1)
                    raise SequenceDiscontinuityError(
                        f"Non-monotonic sequence in batch: {r.sequence_number} after {batch_prev_seq}",
                        code="SEQUENCE_DISCONTINUITY",
                        status_code=422,
                        details={
                            "current_seq": r.sequence_number,
                            "prev_seq": batch_prev_seq,
                        },
                    )
                if batch_prev_ts is not None and not is_replayed:
                    time_delta = r.timestamp_ns - batch_prev_ts
                    jitter = abs(time_delta - self._nominal_interval_ns)
                    if jitter > max_jitter:
                        max_jitter = float(jitter)
                    if jitter > self._jitter_tolerance_ns:
                        raise JitterThresholdExceededError(
                            f"Timestamp jitter {jitter}ns exceeds tolerance {self._jitter_tolerance_ns}ns",
                            code="JITTER_THRESHOLD_EXCEEDED",
                            status_code=422,
                            details={
                                "jitter_ns": jitter,
                                "tolerance_ns": self._jitter_tolerance_ns,
                                "interval_ns": time_delta,
                            },
                        )
                batch_prev_seq = r.sequence_number
                batch_prev_ts = r.timestamp_ns

            # For batches, update stream history to the latest frame if live
            if not is_replayed and records:
                self._stream_history[stream_id] = (
                    records[-1].sequence_number,
                    records[-1].timestamp_ns,
                )

            updated = context.with_metric("sequence_delta", float(len(records)))
            updated = updated.with_metric("max_jitter_ns", max_jitter)
            return updated

        # Single record processing
        record = records[0]
        current_seq = record.sequence_number
        current_ts = record.timestamp_ns
        is_duplicate = False
        seq_delta = 0.0
        jitter_val = 0.0

        if not is_replayed and stream_id in self._stream_history:
            last_seq, last_ts = self._stream_history[stream_id]
            if current_ts < last_ts or (
                current_ts <= last_ts and current_seq != last_seq
            ):
                self._stream_history[stream_id] = (current_seq, current_ts)
                delta = 0
                seq_delta = 0.0
            else:
                delta = current_seq - last_seq
                seq_delta = float(delta)

                if delta == 0:
                    is_duplicate = True
                elif delta < 0:
                    raise SequenceDiscontinuityError(
                        f"Non-monotonic sequence number: {current_seq} after {last_seq}",
                        code="SEQUENCE_DISCONTINUITY",
                        status_code=422,
                        details={"current_seq": current_seq, "last_seq": last_seq},
                    )

        if not is_replayed and not is_duplicate:
            self._stream_history[stream_id] = (current_seq, current_ts)

        updated_ctx = context.with_metric("sequence_delta", seq_delta)
        updated_ctx = updated_ctx.with_metric("jitter_ns", jitter_val)
        if is_duplicate:
            updated_ctx = updated_ctx.with_metadata("is_duplicate", "true")

        return updated_ctx
